"""Join numbered ExoPlayer fragments and optionally burn in subtitles."""

from __future__ import annotations

import argparse
from collections import Counter
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Callable, Sequence


SEGMENT_PATTERN = re.compile(r"^(\d+)\.")
SUBTITLE_SUFFIXES = {".ar", ".en", ".es", ".fil", ".in_id", ".pt", ".srt", ".vtt", ".ass", ".ssa"}
LANGUAGE_NAMES = {
    "ar": "Arabic",
    "en": "English",
    "es": "Spanish",
    "fil": "Filipino",
    "in_id": "Indonesian",
    "pt": "Portuguese",
}
LANGUAGE_ALIASES = {
    "arabic": "ar",
    "english": "en",
    "spanish": "es",
    "filipino": "fil",
    "id": "in_id",
    "indonesian": "in_id",
    "portuguese": "pt",
}
ProgressCallback = Callable[[str, float], None]


class MergeCancelled(Exception):
    """Raised when the user cancels an active merge."""


def discover_segments(root: Path) -> list[Path]:
    """Return numbered .exo files under root in numeric order."""
    if not root.is_dir():
        raise ValueError(f"Input folder not found: {root}")

    segments: list[tuple[int, Path]] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() != ".exo":
            continue
        match = SEGMENT_PATTERN.match(path.name)
        if match:
            segments.append((int(match.group(1)), path))

    segments.sort(key=lambda item: (item[0], str(item[1]).casefold()))
    return [path for _, path in segments]


def discover_episode_dirs(root: Path) -> list[Path]:
    """Find episode folders for batch mode.

    Batch mode intentionally groups only direct child folders. This keeps
    numbered shard folders (for example ``downloads/0`` ... ``downloads/9``)
    as one episode when the input directory itself is passed in normal mode.
    """
    if not root.is_dir():
        raise ValueError(f"Input folder not found: {root}")
    episode_dirs = [path for path in root.iterdir() if path.is_dir() and discover_segments(path)]
    if not episode_dirs:
        raise ValueError(
            "Batch mode requires one folder per episode, each containing numbered .exo fragments."
        )
    return sorted(episode_dirs, key=lambda path: path.name.casefold())


def validate_segments(segments: Sequence[Path], allow_gaps: bool = False) -> None:
    if not segments:
        raise ValueError("No numbered .exo fragments were found.")

    indexes = [int(SEGMENT_PATTERN.match(path.name).group(1)) for path in segments]
    duplicates = sorted(index for index, count in Counter(indexes).items() if count > 1)
    if duplicates:
        raise ValueError(f"Duplicate fragment numbers: {', '.join(map(str, duplicates))}")

    if not allow_gaps:
        missing = sorted(set(range(indexes[0], indexes[-1] + 1)) - set(indexes))
        if missing:
            preview = ", ".join(map(str, missing[:20]))
            more = " ..." if len(missing) > 20 else ""
            raise ValueError(f"Missing fragment numbers: {preview}{more}. Use --allow-gaps to continue.")

    empty = [path.name for path in segments if path.stat().st_size == 0]
    if empty:
        raise ValueError(f"Empty fragment files: {', '.join(empty[:5])}")


def inspect_episode(root: Path, allow_gaps: bool = False) -> dict[str, object]:
    """Validate an episode without invoking FFmpeg."""
    segments = discover_segments(root)
    validate_segments(segments, allow_gaps=allow_gaps)
    return {
        "name": root.name,
        "path": root,
        "segments": len(segments),
        "first": segments[0].name,
        "last": segments[-1].name,
        "subtitles": discover_subtitles(root),
    }


def discover_subtitles(root: Path) -> list[Path]:
    """Find subtitle sidecars supported by this project's input files."""
    if not root.is_dir():
        raise ValueError(f"Subtitle folder not found: {root}")
    return sorted(
        (
            path
            for path in root.rglob("*")
            if path.is_file() and path.suffix.lower() in SUBTITLE_SUFFIXES
        ),
        key=lambda path: (path.suffix.casefold(), path.name.casefold(), str(path).casefold()),
    )


def subtitle_language(path: Path) -> str | None:
    suffix = path.suffix.lower().lstrip(".")
    if suffix in LANGUAGE_NAMES:
        return suffix
    if "indo" in path.stem.lower():
        return "in_id"
    return None


def subtitle_label(path: Path) -> str:
    language = subtitle_language(path)
    name = LANGUAGE_NAMES.get(language, "Other")
    return f"{name} ({path.name})"


def resolve_subtitle(candidates: Sequence[Path], selection: str | None) -> Path | None:
    """Resolve a subtitle by language code, alias, filename, or 'none'."""
    normalized = (selection or "auto").strip().casefold()
    if normalized in {"none", "no", "off"}:
        return None
    if not candidates:
        return None

    if normalized == "auto":
        indonesian = [path for path in candidates if path.suffix.lower() == ".in_id"]
        if len(indonesian) == 1:
            return indonesian[0]
        if len(candidates) == 1:
            return candidates[0]
        raise ValueError("No subtitle selected. Use --subtitle CODE, a filename, or --subtitle none.")

    exact = [path for path in candidates if path.name.casefold() == normalized]
    if exact:
        return exact[0]

    language = normalized.lstrip(".")
    language = LANGUAGE_ALIASES.get(language, language)
    matches = [path for path in candidates if subtitle_language(path) == language]
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        canonical = [path for path in matches if path.suffix.lower() == ".in_id"]
        if len(canonical) == 1:
            return canonical[0]
        files = ", ".join(path.name for path in matches)
        raise ValueError(f"Selection '{selection}' matches multiple files: {files}. Use the full filename.")

    options = ", ".join(path.name for path in candidates)
    raise ValueError(f"Subtitle '{selection}' was not found. Available files: {options}")


def escape_filter_path(path: Path) -> str:
    value = str(path.resolve()).replace("\\", "/")
    for character in ("\\", "'", ":", ",", "[", "]"):
        value = value.replace(character, "\\" + character)
    return value


def build_ffmpeg_command(
    ffmpeg: str,
    raw_input: Path,
    output: Path,
    subtitle: Path | None,
    preset: str,
    crf: int,
) -> list[str]:
    command = [
        ffmpeg,
        "-hide_banner",
        "-nostdin",
        "-y",
        "-err_detect",
        "ignore_err",
        "-i",
        str(raw_input),
        "-map",
        "0:v:0",
        "-map",
        "0:a?",
    ]
    if subtitle is None:
        command.extend(["-c", "copy", "-bsf:a", "aac_adtstoasc"])
    else:
        subtitle_filter = f"subtitles='{escape_filter_path(subtitle)}'"
        command.extend(
            [
                "-vf",
                subtitle_filter,
                "-c:v",
                "libx264",
                "-preset",
                preset,
                "-crf",
                str(crf),
                "-c:a",
                "copy",
                "-bsf:a",
                "aac_adtstoasc",
            ]
        )
    command.extend(["-progress", "pipe:1", "-nostats"])
    command.append(str(output))
    return command


def prompt_for_subtitle(candidates: Sequence[Path]) -> Path | None:
    print("Choose a subtitle:")
    print("  0. No subtitles")
    for index, path in enumerate(candidates, start=1):
        print(f"  {index}. {subtitle_label(path)}")

    while True:
        response = input("Selection number [automatic]: ").strip()
        if not response:
            try:
                return resolve_subtitle(candidates, "auto")
            except ValueError as error:
                print(error)
                continue
        if response == "0":
            return None
        if response.isdigit() and 1 <= int(response) <= len(candidates):
            return candidates[int(response) - 1]
        print(f"Enter a number from 0 to {len(candidates)}.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Merge numbered .exo fragments and optionally burn subtitles into an MP4."
    )
    parser.add_argument("-i", "--input-dir", type=Path, default=Path("."), help="Folder containing fragments and subtitles")
    parser.add_argument("-o", "--output", type=Path, default=Path("video_hardsub_final.mp4"), help="Output MP4 path")
    parser.add_argument("-s", "--subtitle", help="Language code (en, es, in_ID), filename, or 'none'")
    parser.add_argument("--list-subtitles", action="store_true", help="List available subtitles and exit")
    parser.add_argument("--allow-gaps", action="store_true", help="Continue when fragment numbers are missing")
    parser.add_argument("--overwrite", action="store_true", help="Allow replacing existing output files")
    parser.add_argument("--skip-existing", action="store_true", help="Skip existing outputs, especially in batch mode")
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Process each direct input subfolder as one episode",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Output folder for --batch; filenames follow episode folder names",
    )
    parser.add_argument("--ffmpeg", default="ffmpeg", help="FFmpeg executable path")
    parser.add_argument(
        "--preset",
        choices=("ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow", "placebo"),
        default="ultrafast",
        help="libx264 encoder preset (default: ultrafast)",
    )
    parser.add_argument("--crf", type=int, default=23, help="libx264 quality, range 0-51 (default: 23)")
    return parser


def _find_executable(executable: str) -> str:
    executable_name = Path(executable).name.casefold()
    if executable_name in {"ffmpeg", "ffmpeg.exe"}:
        search_roots = [
            Path(sys.executable).resolve().parent,
            Path(__file__).resolve().parent.parent,
            Path.cwd(),
        ]
        bundled_root = getattr(sys, "_MEIPASS", None)
        if bundled_root:
            search_roots.insert(0, Path(bundled_root))
        for root in search_roots:
            for candidate in (root / "ffmpeg" / "ffmpeg.exe", root / "ffmpeg.exe"):
                if candidate.is_file():
                    return str(candidate.resolve())
    resolved = shutil.which(executable)
    if resolved:
        return resolved
    candidate = Path(executable)
    if candidate.is_file():
        return str(candidate.resolve())
    raise ValueError(f"FFmpeg executable not found: {executable}")


def _join_segments(segments: Sequence[Path], destination: Path) -> None:
    with destination.open("wb") as output_file:
        for index, path in enumerate(segments, start=1):
            with path.open("rb") as input_file:
                shutil.copyfileobj(input_file, output_file, length=1024 * 1024)


def _safe_output_name(name: str) -> str:
    """Return a filesystem-friendly episode name without changing its meaning."""
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return cleaned or "episode"


def merge_episode(
    input_dir: Path,
    output: Path,
    subtitle_selection: str | Path | None,
    ffmpeg: str,
    allow_gaps: bool,
    preset: str,
    crf: int,
    fallback_subtitle_dir: Path | None = None,
    overwrite: bool = False,
    skip_existing: bool = False,
    progress_callback: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> bool:
    """Merge one episode and atomically publish its output."""
    segments = discover_segments(input_dir)
    validate_segments(segments, allow_gaps=allow_gaps)
    candidates = discover_subtitles(input_dir)
    if not candidates and fallback_subtitle_dir is not None:
        candidates = discover_subtitles(fallback_subtitle_dir)
    subtitle = (
        subtitle_selection
        if isinstance(subtitle_selection, Path)
        else resolve_subtitle(candidates, subtitle_selection)
    )

    if output.exists() and not output.is_file():
        raise ValueError(f"Output is not a file: {output}")
    if output.exists() and skip_existing:
        print(f"[{input_dir.name}] Skipped, output already exists: {output}")
        if progress_callback:
            progress_callback("skipped", 1.0)
        return False
    if output.exists() and not overwrite:
        raise ValueError(f"Output already exists: {output}. Use --overwrite to replace it.")

    output.parent.mkdir(parents=True, exist_ok=True)
    print(f"[{input_dir.name}] Fragments found: {len(segments)} ({segments[0].name} to {segments[-1].name})")
    print(f"[{input_dir.name}] Subtitle: {subtitle_label(subtitle) if subtitle else 'none'}")

    with tempfile.TemporaryDirectory(prefix="exo-merge-", dir=output.parent) as temporary_directory:
        temporary_root = Path(temporary_directory)
        raw_input = temporary_root / "joined.ts"
        temporary_output = temporary_root / "result.mp4"
        with raw_input.open("wb") as output_file:
            for index, path in enumerate(segments, start=1):
                if cancel_event and cancel_event.is_set():
                    raise MergeCancelled("Process cancelled by user.")
                with path.open("rb") as input_file:
                    shutil.copyfileobj(input_file, output_file, length=1024 * 1024)
                if progress_callback:
                    progress_callback("joining fragments", 0.3 * index / len(segments))
        command = build_ffmpeg_command(ffmpeg, raw_input, temporary_output, subtitle, preset, crf)
        if progress_callback:
            progress_callback("running FFmpeg", 0.3)
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert process.stdout is not None
        for line in process.stdout:
            if cancel_event and cancel_event.is_set():
                process.terminate()
                process.wait(timeout=10)
                raise MergeCancelled("Process cancelled by user.")
            if progress_callback and line.startswith("progress="):
                progress_callback("running FFmpeg", 0.3)
        return_code = process.wait()
        if return_code:
            raise subprocess.CalledProcessError(return_code, command)
        if cancel_event and cancel_event.is_set():
            raise MergeCancelled("Process cancelled by user.")
        os.replace(temporary_output, output)
    if progress_callback:
        progress_callback("completed", 1.0)
    print(f"[{input_dir.name}] Video saved: {output}")
    return True


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if not 0 <= args.crf <= 51:
            raise ValueError("Nilai --crf harus berada pada rentang 0 sampai 51.")

        input_dir = args.input_dir.expanduser().resolve()
        output = args.output.expanduser().resolve()
        output_dir = args.output_dir.expanduser().resolve() if args.output_dir else None
        if args.batch and args.output_dir is None:
            output_dir = output if output.suffix.lower() != ".mp4" else output.parent / output.stem
        if not args.batch and output_dir is not None:
            raise ValueError("--output-dir hanya dapat digunakan bersama --batch.")
        if not args.batch and output.suffix.lower() != ".mp4":
            raise ValueError("File output harus berekstensi .mp4.")

        candidates = discover_subtitles(input_dir)
        if args.list_subtitles:
            if candidates:
                for path in candidates:
                    print(f"{subtitle_label(path)}\t{path}")
            else:
                print("No supported subtitles were found.")
            return 0

        if not args.batch and args.subtitle is None and sys.stdin.isatty() and len(candidates) > 1:
            subtitle = prompt_for_subtitle(candidates)
        else:
            subtitle = resolve_subtitle(candidates, args.subtitle)

        ffmpeg = _find_executable(args.ffmpeg)
        if args.batch:
            episode_dirs = discover_episode_dirs(input_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
            for episode_dir in episode_dirs:
                episode_output = output_dir / f"{_safe_output_name(episode_dir.name)}.mp4"
                merge_episode(
                    episode_dir,
                    episode_output,
                    args.subtitle,
                    ffmpeg,
                    args.allow_gaps,
                    args.preset,
                    args.crf,
                    fallback_subtitle_dir=input_dir,
                    overwrite=args.overwrite,
                    skip_existing=args.skip_existing,
                )
            print(f"Completed: {len(episode_dirs)} episode(s) processed to {output_dir}")
        else:
            merge_episode(
                input_dir,
                output,
                subtitle,
                ffmpeg,
                args.allow_gaps,
                args.preset,
                args.crf,
                overwrite=args.overwrite,
                skip_existing=args.skip_existing,
            )
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError, MergeCancelled) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
