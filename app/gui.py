"""Friendly desktop interface for the Exo fragment merger."""

from __future__ import annotations

import queue
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __author__, __version__
from .exo_merger import (
    _find_executable,
    discover_episode_dirs,
    discover_subtitles,
    inspect_episode,
    MergeCancelled,
    merge_episode,
    _safe_output_name,
    subtitle_label,
)


class QueueWriter:
    def __init__(self, messages: queue.Queue[str]) -> None:
        self.messages = messages

    def write(self, value: str) -> int:
        if value.strip():
            self.messages.put(value.rstrip())
        return len(value)

    def flush(self) -> None:
        pass


class MergerApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Exo Fragment Merger")
        self.geometry("760x560")
        self.minsize(680, 480)

        self.messages: queue.Queue[str] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.cancel_event = threading.Event()
        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar()
        self.subtitle_var = tk.StringVar(value="Automatic")
        self.mode_var = tk.StringVar(value="single")
        self.overwrite_var = tk.BooleanVar(value=False)
        self.allow_gaps_var = tk.BooleanVar(value=False)
        self.skip_existing_var = tk.BooleanVar(value=True)
        self.status_var = tk.StringVar(value="Choose a fragment folder to begin.")

        self._build_ui()
        self.after(100, self._drain_messages)

    def _show_about(self) -> None:
        messagebox.showinfo(
            "About Exo Fragment Merger",
            f"Exo Fragment Merger\n\n"
            f"Version: {__version__}\n"
            f"Created by: {__author__}\n\n"
            "A desktop utility for merging ExoPlayer fragments and subtitles.\n"
            "Powered by Python, Tkinter, and FFmpeg.",
            parent=self,
        )

    def _build_ui(self) -> None:
        root = ttk.Frame(self, padding=18)
        root.pack(fill="both", expand=True)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(7, weight=1)

        ttk.Label(root, text="Exo Fragment Merger", font=("Segoe UI", 18, "bold")).grid(
            row=0, column=0, columnspan=3, sticky="w", pady=(0, 14)
        )
        ttk.Label(root, text="Source folder").grid(row=1, column=0, sticky="w", pady=5)
        ttk.Entry(root, textvariable=self.input_var).grid(row=1, column=1, sticky="ew", padx=8, pady=5)
        ttk.Button(root, text="Browse...", command=self._choose_input).grid(row=1, column=2, pady=5)

        ttk.Label(root, text="Mode").grid(row=2, column=0, sticky="w", pady=5)
        modes = ttk.Frame(root)
        modes.grid(row=2, column=1, columnspan=2, sticky="w", padx=8, pady=5)
        ttk.Radiobutton(modes, text="Single video", variable=self.mode_var, value="single", command=self._mode_changed).pack(side="left")
        ttk.Radiobutton(modes, text="Multiple episodes", variable=self.mode_var, value="batch", command=self._mode_changed).pack(side="left", padx=18)

        ttk.Label(root, text="Subtitle").grid(row=3, column=0, sticky="w", pady=5)
        self.subtitle_combo = ttk.Combobox(root, textvariable=self.subtitle_var, state="readonly")
        self.subtitle_combo.grid(row=3, column=1, sticky="ew", padx=8, pady=5)
        ttk.Button(root, text="Refresh", command=self._refresh_subtitles).grid(row=3, column=2, pady=5)

        self.output_label = ttk.Label(root, text="Output file")
        self.output_label.grid(row=4, column=0, sticky="w", pady=5)
        ttk.Entry(root, textvariable=self.output_var).grid(row=4, column=1, sticky="ew", padx=8, pady=5)
        ttk.Button(root, text="Browse...", command=self._choose_output).grid(row=4, column=2, pady=5)

        options = ttk.Frame(root)
        options.grid(row=5, column=0, columnspan=3, sticky="w", pady=(4, 10))
        ttk.Checkbutton(options, text="Allow overwriting existing files", variable=self.overwrite_var).pack(side="left")
        ttk.Checkbutton(options, text="Continue when fragment numbers are missing", variable=self.allow_gaps_var).pack(side="left", padx=18)
        ttk.Checkbutton(options, text="Skip existing output files", variable=self.skip_existing_var).pack(side="left")

        scan_frame = ttk.Frame(root)
        scan_frame.grid(row=6, column=0, columnspan=3, sticky="ew", pady=(0, 8))
        ttk.Button(scan_frame, text="Scan & validate", command=self._scan).pack(side="left")
        self.progress = ttk.Progressbar(scan_frame, mode="determinate", maximum=100)
        self.progress.pack(side="left", fill="x", expand=True, padx=(12, 0))

        ttk.Label(root, text="Process log").grid(row=7, column=0, sticky="nw")
        self.log = tk.Text(root, height=10, state="disabled", wrap="word", background="#f5f5f5")
        self.log.grid(row=7, column=1, columnspan=2, sticky="nsew", padx=8)

        footer = ttk.Frame(root)
        footer.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(12, 0))
        footer.columnconfigure(0, weight=1)
        ttk.Label(footer, textvariable=self.status_var).grid(row=0, column=0, sticky="w")
        self.start_button = ttk.Button(footer, text="Start", command=self._start)
        self.start_button.grid(row=0, column=1, padx=6)
        self.cancel_button = ttk.Button(footer, text="Cancel", command=self._cancel, state="disabled")
        self.cancel_button.grid(row=0, column=2, padx=6)
        ttk.Button(footer, text="ⓘ", width=3, command=self._show_about).grid(row=0, column=3, padx=6)
        ttk.Button(footer, text="Close", command=self.destroy).grid(row=0, column=4)

    def _mode_changed(self) -> None:
        batch = self.mode_var.get() == "batch"
        self.output_label.configure(text="Output folder" if batch else "Output file")
        self.output_var.set("")

    def _choose_input(self) -> None:
        selected = filedialog.askdirectory(title="Choose source folder")
        if selected:
            self.input_var.set(selected)
            self._refresh_subtitles()

    def _choose_output(self) -> None:
        if self.mode_var.get() == "batch":
            selected = filedialog.askdirectory(title="Choose output folder")
        else:
            selected = filedialog.asksaveasfilename(
                title="Save video as",
                defaultextension=".mp4",
                filetypes=(("MP4 video", "*.mp4"), ("Semua file", "*.*")),
            )
        if selected:
            self.output_var.set(selected)

    def _refresh_subtitles(self) -> None:
        try:
            root = Path(self.input_var.get()).expanduser().resolve()
            subtitles = discover_subtitles(root)
            values = ["Automatic", "No subtitles"] + [subtitle_label(path) for path in subtitles]
            self.subtitle_combo["values"] = values
            self.subtitle_var.set(values[0])
            self.status_var.set(f"Found {len(subtitles)} subtitle file(s).")
        except (OSError, ValueError) as error:
            self.subtitle_combo["values"] = ("Automatic", "No subtitles")
            self.subtitle_var.set("Automatic")
            self.status_var.set(str(error))

    def _scan(self) -> None:
        try:
            root = Path(self.input_var.get()).expanduser().resolve()
            if self.mode_var.get() == "batch":
                episodes = discover_episode_dirs(root)
                rows = [inspect_episode(path, self.allow_gaps_var.get()) for path in episodes]
            else:
                rows = [inspect_episode(root, self.allow_gaps_var.get())]
            self._append_log("Validation successful:")
            for row in rows:
                self._append_log(f"- {row['name']}: {row['segments']} fragments ({row['first']} to {row['last']})")
            total = sum(int(row["segments"]) for row in rows)
            self.status_var.set(f"Valid: {len(rows)} episode(s), {total} fragment(s).")
            self.progress["value"] = 0
        except (OSError, ValueError) as error:
            self.status_var.set("Validation failed.")
            messagebox.showerror("Validation failed", str(error))

    def _subtitle_selection(self, input_dir: Path) -> str | None:
        selected = self.subtitle_var.get()
        if selected == "Automatic":
            return None
        if selected == "No subtitles":
            return "none"
        for path in discover_subtitles(input_dir):
            if subtitle_label(path) == selected:
                return path.name
        return selected

    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        input_dir = Path(self.input_var.get()).expanduser().resolve()
        output = Path(self.output_var.get()).expanduser().resolve()
        if not input_dir.is_dir():
            messagebox.showerror("Folder not found", "Choose a valid source folder.")
            return
        if self.mode_var.get() == "single" and output.suffix.lower() != ".mp4":
            messagebox.showerror("Invalid output", "For single-video mode, choose an .mp4 file.")
            return
        if self.mode_var.get() == "batch" and output.suffix.lower() == ".mp4":
            messagebox.showerror("Invalid output", "For multiple-episode mode, choose an output folder.")
            return

        self._set_running(True)
        self.cancel_event.clear()
        self.progress["value"] = 0
        self._append_log("Starting...")
        settings = (
            self.mode_var.get(),
            self._subtitle_selection(input_dir),
            self.allow_gaps_var.get(),
            self.overwrite_var.get(),
            self.skip_existing_var.get(),
        )
        self.worker = threading.Thread(target=self._run_worker, args=(input_dir, output, settings), daemon=True)
        self.worker.start()

    def _run_worker(self, input_dir: Path, output: Path, settings: tuple[str, str | None, bool, bool, bool]) -> None:
        old_stdout = sys.stdout
        sys.stdout = QueueWriter(self.messages)  # type: ignore[assignment]
        try:
            ffmpeg = _find_executable("ffmpeg")
            mode, selection, allow_gaps, overwrite, skip_existing = settings
            if mode == "batch":
                episodes = discover_episode_dirs(input_dir)
                output.mkdir(parents=True, exist_ok=True)
                for episode_index, episode in enumerate(episodes, start=1):
                    self.messages.put(f"Episode {episode_index}/{len(episodes)}: {episode.name}")

                    def update(_phase: str, fraction: float, index: int = episode_index) -> None:
                        self.messages.put(("progress", ((index - 1) + fraction) / len(episodes) * 100))

                    merge_episode(
                        episode,
                        output / f"{_safe_output_name(episode.name)}.mp4",
                        selection,
                        ffmpeg,
                        allow_gaps,
                        "ultrafast",
                        23,
                        fallback_subtitle_dir=input_dir,
                        overwrite=overwrite,
                        skip_existing=skip_existing,
                        progress_callback=update,
                        cancel_event=self.cancel_event,
                    )
                print(f"Completed: {len(episodes)} episode(s) processed.")
            else:
                merge_episode(
                    input_dir,
                    output,
                    selection,
                    ffmpeg,
                    allow_gaps,
                    "ultrafast",
                    23,
                    overwrite=overwrite,
                    skip_existing=skip_existing,
                    progress_callback=lambda _phase, fraction: self.messages.put(("progress", fraction * 100)),
                    cancel_event=self.cancel_event,
                )
        except MergeCancelled:
            self.messages.put("Process cancelled.")
        except Exception as error:  # GUI must report errors without crashing.
            self.messages.put(f"ERROR: {error}")
        finally:
            sys.stdout = old_stdout
            self.messages.put("__DONE__")

    def _set_running(self, running: bool) -> None:
        self.start_button.configure(state="disabled" if running else "normal")
        self.cancel_button.configure(state="normal" if running else "disabled")
        self.status_var.set("Processing..." if running else "Ready.")

    def _cancel(self) -> None:
        if self.worker and self.worker.is_alive():
            self.cancel_event.set()
            self.status_var.set("Cancelling...")

    def _append_log(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _drain_messages(self) -> None:
        try:
            while True:
                message = self.messages.get_nowait()
                if message == "__DONE__":
                    self._set_running(False)
                    self.status_var.set("Process finished or failed. Check the log.")
                elif isinstance(message, tuple) and message[0] == "progress":
                    self.progress["value"] = message[1]
                else:
                    self._append_log(message)
        except queue.Empty:
            pass
        self.after(100, self._drain_messages)


def main() -> None:
    MergerApp().mainloop()


if __name__ == "__main__":
    main()
