# Media3 ExoPlayer Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Menambah dukungan format cache Google Media3 ExoPlayer (v3) agar tool bisa auto-detect dan merge fragment dari YouTube offline download maupun legacy ExoPlayer (anime apps).

**Architecture:** Tambah layer deteksi format yang memilah `.exo` files ke dalam dua kategori: legacy (numbered sequential segments) dan Media3 v3 (content_id.position.timestamp.v3.exo). Untuk Media3, fragments dikelompokkan per content_id dan diurutkan by byte offset (position). Jika ada multiple content_ids (video + audio terpisah ala DASH), merge masing-masing lalu gabung via FFmpeg multi-input. Semua perubahan backward-compatible — flow legacy tetap berjalan identik.

**Tech Stack:** Python 3.10+ stdlib, FFmpeg, unittest

## Global Constraints

- Python >= 3.10, zero pip dependencies
- Semua perubahan backward-compatible — flow legacy tidak boleh berubah perilaku
- Naming convention dan code style mengikuti existing codebase (snake_case, docstrings, type hints)
- Semua fitur baru harus punya unit test
- CLI flags baru harus terdokumentasi di README

---

## Background: Mengapa YouTube Gagal

### Format Naming

| Format | Contoh Filename | Arti |
|--------|----------------|------|
| **Legacy ExoPlayer** | `0.0.segment.exo`, `1.0.segment.exo` | Angka pertama = **segment order** |
| **Media3 v3** | `0.0.1697456789123.v3.exo`, `0.1048576.1697456789456.v3.exo` | Angka pertama = **content_id**, kedua = **byte offset**, ketiga = **timestamp** |

Current regex `^(\d+)\.` pada `SEGMENT_PATTERN` menangkap angka pertama sebagai segment number. Ini benar untuk legacy (segment 0, 1, 2...) tapi **salah untuk Media3** karena:
1. Angka pertama = content_id (biasanya 0, 1, 2 untuk video, audio, subtitle) — dikira duplikat
2. Urutan merge ditentukan oleh byte offset (field kedua), bukan field pertama
3. YouTube memisahkan audio dan video ke content_id berbeda (DASH)

### Perbedaan Struktural

| Aspek | Legacy (Anime) | Media3 (YouTube) |
|-------|----------------|------------------|
| Segment naming | `N.*.exo` (N = sequence) | `ID.OFFSET.TIMESTAMP.v3.exo` |
| Stream separation | Single combined stream | Audio + Video terpisah (DASH) |
| Merge strategy | Concat all -> single FFmpeg | Group by content_id -> concat per group -> FFmpeg multi-input |
| Index file | Tidak ada / tidak perlu | `cached_content_index.exi` (opsional, untuk metadata) |

---

## File Structure

| File | Responsibility | Action |
|------|---------------|--------|
| `app/cache_format.py` | Format detection, Media3 parsing, content grouping | **Create** |
| `app/exo_merger.py` | Integrate new format detection into merge pipeline | **Modify** |
| `app/gui.py` | Show detected format info, multi-track UI | **Modify** |
| `tests/test_cache_format.py` | Tests for format detection & Media3 parsing | **Create** |
| `tests/test_gabung_ffmpeg.py` | Update existing tests, add integration tests | **Modify** |
| `README.md` | Document new capabilities | **Modify** |

---

### Task 1: Format Detection & Media3 Parser (`app/cache_format.py`)

**Files:**
- Create: `app/cache_format.py`
- Test: `tests/test_cache_format.py`

**Interfaces:**
- Consumes: nothing (standalone module)
- Produces:
  - `CacheFormat` enum: `LEGACY`, `MEDIA3_V3`
  - `ContentGroup` dataclass: `content_id: int`, `segments: list[Path]`, `total_bytes: int`
  - `detect_cache_format(root: Path) -> CacheFormat`
  - `MEDIA3_PATTERN: re.Pattern` matching `[id].[offset].[timestamp].v3.exo`
  - `parse_media3_filename(name: str) -> tuple[int, int, int] | None` returns `(content_id, position, timestamp)`
  - `group_media3_segments(root: Path) -> list[ContentGroup]`

- [ ] **Step 1: Write the failing tests for format detection**

```python
# tests/test_cache_format.py
import tempfile
import unittest
from pathlib import Path

from app.cache_format import (
    CacheFormat,
    ContentGroup,
    detect_cache_format,
    parse_media3_filename,
    group_media3_segments,
)


class FormatDetectionTests(unittest.TestCase):
    def test_detect_legacy_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "0.0.segment.exo").write_bytes(b"data")
            (root / "1.0.segment.exo").write_bytes(b"data")
            self.assertEqual(detect_cache_format(root), CacheFormat.LEGACY)

    def test_detect_media3_v3_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "0.0.1697456789123.v3.exo").write_bytes(b"data")
            (root / "0.1048576.1697456789456.v3.exo").write_bytes(b"data")
            self.assertEqual(detect_cache_format(root), CacheFormat.MEDIA3_V3)

    def test_detect_empty_folder_returns_legacy(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(detect_cache_format(Path(tmp)), CacheFormat.LEGACY)

    def test_detect_mixed_prefers_media3(self):
        """When both formats exist, Media3 v3 files take priority."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "0.0.segment.exo").write_bytes(b"data")
            (root / "0.0.1697456789123.v3.exo").write_bytes(b"data")
            self.assertEqual(detect_cache_format(root), CacheFormat.MEDIA3_V3)


class Media3ParsingTests(unittest.TestCase):
    def test_parse_valid_v3_filename(self):
        result = parse_media3_filename("0.0.1697456789123.v3.exo")
        self.assertEqual(result, (0, 0, 1697456789123))

    def test_parse_v3_with_large_offset(self):
        result = parse_media3_filename("1.5242880.1697456790000.v3.exo")
        self.assertEqual(result, (1, 5242880, 1697456790000))

    def test_parse_legacy_filename_returns_none(self):
        self.assertIsNone(parse_media3_filename("0.0.segment.exo"))

    def test_parse_non_exo_returns_none(self):
        self.assertIsNone(parse_media3_filename("readme.txt"))


class ContentGroupingTests(unittest.TestCase):
    def test_groups_by_content_id_sorted_by_offset(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            # Content 0 (video): two chunks
            (root / "0.1048576.1697456789456.v3.exo").write_bytes(b"chunk2")
            (root / "0.0.1697456789123.v3.exo").write_bytes(b"chunk1")
            # Content 1 (audio): one chunk
            (root / "1.0.1697456789789.v3.exo").write_bytes(b"audio1")

            groups = group_media3_segments(root)

            self.assertEqual(len(groups), 2)
            # Group 0: video, sorted by offset
            self.assertEqual(groups[0].content_id, 0)
            self.assertEqual(len(groups[0].segments), 2)
            self.assertEqual(groups[0].segments[0].name, "0.0.1697456789123.v3.exo")
            self.assertEqual(groups[0].segments[1].name, "0.1048576.1697456789456.v3.exo")
            # Group 1: audio
            self.assertEqual(groups[1].content_id, 1)
            self.assertEqual(len(groups[1].segments), 1)

    def test_recursive_discovery_in_numbered_subdirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sub = root / "0"
            sub.mkdir()
            (sub / "0.0.1697456789123.v3.exo").write_bytes(b"data")
            (sub / "0.1048576.1697456789456.v3.exo").write_bytes(b"data")

            groups = group_media3_segments(root)

            self.assertEqual(len(groups), 1)
            self.assertEqual(len(groups[0].segments), 2)

    def test_empty_files_are_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "0.0.1697456789123.v3.exo").write_bytes(b"data")
            (root / "0.1048576.1697456789456.v3.exo").write_bytes(b"")  # empty

            groups = group_media3_segments(root)

            self.assertEqual(len(groups[0].segments), 1)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_cache_format -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.cache_format'`

- [ ] **Step 3: Implement `app/cache_format.py`**

```python
"""Detect and parse ExoPlayer cache formats (legacy and Media3 v3)."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class CacheFormat(Enum):
    """Supported ExoPlayer cache naming conventions."""

    LEGACY = "legacy"
    MEDIA3_V3 = "media3_v3"


LEGACY_PATTERN = re.compile(r"^(\d+)\.")
MEDIA3_V3_PATTERN = re.compile(
    r"^(\d+)\.(\d+)\.(\d+)\.v3\.exo$"
)


@dataclass
class ContentGroup:
    """A set of cache spans belonging to the same content stream."""

    content_id: int
    segments: list[Path] = field(default_factory=list)

    @property
    def total_bytes(self) -> int:
        return sum(p.stat().st_size for p in self.segments)


def parse_media3_filename(name: str) -> tuple[int, int, int] | None:
    """Parse a Media3 v3 filename into (content_id, position, timestamp).

    Returns None if the filename does not match the v3 pattern.
    """
    match = MEDIA3_V3_PATTERN.match(name)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def detect_cache_format(root: Path) -> CacheFormat:
    """Auto-detect whether a folder uses legacy or Media3 v3 naming.

    If any `.v3.exo` file is found, the folder is treated as Media3.
    Falls back to LEGACY when no v3 files are present.
    """
    for path in root.rglob("*.exo"):
        if path.is_file() and MEDIA3_V3_PATTERN.match(path.name):
            return CacheFormat.MEDIA3_V3
    return CacheFormat.LEGACY


def group_media3_segments(root: Path) -> list[ContentGroup]:
    """Group Media3 v3 .exo files by content_id, sorted by byte offset.

    Empty files are silently excluded. Groups are returned in content_id
    order so that callers can treat group 0 as the primary (usually video)
    stream and subsequent groups as secondary (audio, etc.) streams.
    """
    if not root.is_dir():
        raise ValueError(f"Input folder not found: {root}")

    buckets: dict[int, list[tuple[int, Path]]] = {}
    for path in root.rglob("*.exo"):
        if not path.is_file() or path.stat().st_size == 0:
            continue
        parsed = parse_media3_filename(path.name)
        if parsed is None:
            continue
        content_id, position, _timestamp = parsed
        buckets.setdefault(content_id, []).append((position, path))

    groups: list[ContentGroup] = []
    for content_id in sorted(buckets):
        entries = sorted(buckets[content_id], key=lambda item: item[0])
        group = ContentGroup(
            content_id=content_id,
            segments=[path for _, path in entries],
        )
        groups.append(group)
    return groups
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m unittest tests.test_cache_format -v`
Expected: All 10 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app/cache_format.py tests/test_cache_format.py
git commit -m "feat: add Media3 v3 cache format detection and parsing"
```

---

### Task 2: Multi-Track Merge Pipeline in `exo_merger.py`

**Files:**
- Modify: `app/exo_merger.py`
- Test: `tests/test_gabung_ffmpeg.py` (add new tests)

**Interfaces:**
- Consumes:
  - `app.cache_format.CacheFormat` enum
  - `app.cache_format.ContentGroup` dataclass
  - `app.cache_format.detect_cache_format(root: Path) -> CacheFormat`
  - `app.cache_format.group_media3_segments(root: Path) -> list[ContentGroup]`
- Produces:
  - `build_ffmpeg_multitrack_command(ffmpeg: str, inputs: Sequence[Path], output: Path, subtitle: Path | None, preset: str, crf: int) -> list[str]`
  - Modified `merge_episode()` that auto-detects format and handles both legacy and Media3

- [ ] **Step 1: Write the failing tests for multi-track FFmpeg command and Media3 discovery**

Tambahkan ke `tests/test_gabung_ffmpeg.py`:

```python
# Add these imports at the top of tests/test_gabung_ffmpeg.py
from app.exo_merger import build_ffmpeg_multitrack_command
from app.cache_format import CacheFormat, detect_cache_format

# Add these test classes
class Media3DiscoveryTests(unittest.TestCase):
    def test_media3_segments_discovered_and_grouped(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            sub = root / "0"
            sub.mkdir()
            (sub / "0.0.100000.v3.exo").write_bytes(b"video1")
            (sub / "0.1048576.100001.v3.exo").write_bytes(b"video2")
            (sub / "1.0.100002.v3.exo").write_bytes(b"audio1")

            from app.cache_format import group_media3_segments
            groups = group_media3_segments(root)

            self.assertEqual(len(groups), 2)
            self.assertEqual(groups[0].content_id, 0)
            self.assertEqual(groups[1].content_id, 1)

    def test_legacy_segments_still_work_after_format_detection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "0.0.segment.exo").write_bytes(b"seg0")
            (root / "1.0.segment.exo").write_bytes(b"seg1")

            fmt = detect_cache_format(root)
            self.assertEqual(fmt, CacheFormat.LEGACY)

            segments = discover_segments(root)
            self.assertEqual(len(segments), 2)


class MultiTrackCommandTests(unittest.TestCase):
    def test_multitrack_command_includes_all_inputs(self):
        inputs = [Path("video.ts"), Path("audio.ts")]
        command = build_ffmpeg_multitrack_command(
            "ffmpeg", inputs, Path("output.mp4"), None, "ultrafast", 23
        )

        input_flags = [i for i, arg in enumerate(command) if arg == "-i"]
        self.assertEqual(len(input_flags), 2)
        self.assertIn("video.ts", command)
        self.assertIn("audio.ts", command)
        self.assertIn("-c", command)
        self.assertIn("copy", command)

    def test_multitrack_command_with_subtitle(self):
        inputs = [Path("video.ts"), Path("audio.ts")]
        subtitle = Path("subs.vtt")
        command = build_ffmpeg_multitrack_command(
            "ffmpeg", inputs, Path("output.mp4"), subtitle, "ultrafast", 23
        )

        self.assertIn("-vf", command)
        self.assertIn("-c:v", command)
        self.assertIn("libx264", command)
        self.assertIn("-c:a", command)
        self.assertIn("copy", command)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m unittest tests.test_gabung_ffmpeg -v`
Expected: FAIL with `ImportError: cannot import name 'build_ffmpeg_multitrack_command'`

- [ ] **Step 3: Add `build_ffmpeg_multitrack_command` to `exo_merger.py`**

Add after `build_ffmpeg_command()` (after line 229):

```python
def build_ffmpeg_multitrack_command(
    ffmpeg: str,
    inputs: Sequence[Path],
    output: Path,
    subtitle: Path | None,
    preset: str,
    crf: int,
) -> list[str]:
    """Build an FFmpeg command that muxes multiple input streams (e.g. video + audio)."""
    command = [ffmpeg, "-hide_banner", "-nostdin", "-y", "-err_detect", "ignore_err"]
    for input_path in inputs:
        command.extend(["-i", str(input_path)])
    # Map all video streams from first input, all audio from all inputs
    command.extend(["-map", "0:v:0"])
    for index in range(len(inputs)):
        command.extend(["-map", f"{index}:a?"])
    if subtitle is None:
        command.extend(["-c", "copy", "-bsf:a", "aac_adtstoasc"])
    else:
        subtitle_filter = f"subtitles='{escape_filter_path(subtitle)}'"
        command.extend([
            "-vf", subtitle_filter,
            "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
            "-c:a", "copy", "-bsf:a", "aac_adtstoasc",
        ])
    command.extend(["-progress", "pipe:1", "-nostats"])
    command.append(str(output))
    return command
```

- [ ] **Step 4: Modify `merge_episode()` to support Media3 format**

At the top of `exo_merger.py`, add the import:

```python
from .cache_format import CacheFormat, detect_cache_format, group_media3_segments
```

In `merge_episode()`, add the Media3 branch **before** the existing legacy code (at the start of the function body, line 337). The existing legacy code stays untouched as the else branch:

```python
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
    cache_format = detect_cache_format(input_dir)

    if cache_format == CacheFormat.MEDIA3_V3:
        return _merge_media3_episode(
            input_dir, output, subtitle_selection, ffmpeg, preset, crf,
            fallback_subtitle_dir, overwrite, skip_existing,
            progress_callback, cancel_event,
        )

    # --- Legacy format (original flow, unchanged) ---
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
    # ... rest of existing legacy code stays exactly the same from here ...
```

Add the new `_merge_media3_episode` private function:

```python
def _merge_media3_episode(
    input_dir: Path,
    output: Path,
    subtitle_selection: str | Path | None,
    ffmpeg: str,
    preset: str,
    crf: int,
    fallback_subtitle_dir: Path | None = None,
    overwrite: bool = False,
    skip_existing: bool = False,
    progress_callback: ProgressCallback | None = None,
    cancel_event: threading.Event | None = None,
) -> bool:
    """Merge one episode using Media3 v3 format (multi-track aware)."""
    groups = group_media3_segments(input_dir)
    if not groups:
        raise ValueError("No Media3 v3 .exo fragments were found.")

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
    total_segments = sum(len(g.segments) for g in groups)
    print(f"[{input_dir.name}] Media3 format: {len(groups)} track(s), {total_segments} fragment(s)")
    print(f"[{input_dir.name}] Subtitle: {subtitle_label(subtitle) if subtitle else 'none'}")

    with tempfile.TemporaryDirectory(prefix="exo-merge-", dir=output.parent) as temporary_directory:
        temporary_root = Path(temporary_directory)
        joined_paths: list[Path] = []
        segments_done = 0
        for group in groups:
            if cancel_event and cancel_event.is_set():
                raise MergeCancelled("Process cancelled by user.")
            track_file = temporary_root / f"track_{group.content_id}.ts"
            with track_file.open("wb") as out_file:
                for path in group.segments:
                    if cancel_event and cancel_event.is_set():
                        raise MergeCancelled("Process cancelled by user.")
                    with path.open("rb") as in_file:
                        shutil.copyfileobj(in_file, out_file, length=1024 * 1024)
                    segments_done += 1
                    if progress_callback:
                        progress_callback("joining fragments", 0.3 * segments_done / total_segments)
            joined_paths.append(track_file)

        temporary_output = temporary_root / "result.mp4"
        if len(joined_paths) == 1:
            command = build_ffmpeg_command(ffmpeg, joined_paths[0], temporary_output, subtitle, preset, crf)
        else:
            command = build_ffmpeg_multitrack_command(ffmpeg, joined_paths, temporary_output, subtitle, preset, crf)

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
```

- [ ] **Step 5: Run all tests to verify they pass**

Run: `python -m unittest discover -s tests -p "test_*.py" -v`
Expected: All tests PASS (existing + new)

- [ ] **Step 6: Commit**

```bash
git add app/exo_merger.py tests/test_gabung_ffmpeg.py
git commit -m "feat: support Media3 v3 multi-track merge pipeline"
```

---

### Task 3: GUI Updates for Media3 Format

**Files:**
- Modify: `app/gui.py`

**Interfaces:**
- Consumes:
  - `app.cache_format.detect_cache_format(root: Path) -> CacheFormat`
  - `app.cache_format.group_media3_segments(root: Path) -> list[ContentGroup]`
  - `app.cache_format.CacheFormat` enum
  - Modified `merge_episode()` (auto-detects format internally)
- Produces: Updated GUI that shows detected format in scan results

- [ ] **Step 1: Add format detection info to `_scan()` method**

Di `gui.py`, add imports at the top:

```python
from .cache_format import CacheFormat, detect_cache_format, group_media3_segments
```

Replace `_scan()` method (lines 163-179) with:

```python
    def _scan(self) -> None:
        try:
            root = Path(self.input_var.get()).expanduser().resolve()
            cache_format = detect_cache_format(root)

            if self.mode_var.get() == "batch":
                episodes = discover_episode_dirs(root)
                rows = [inspect_episode(path, self.allow_gaps_var.get()) for path in episodes]
            else:
                if cache_format == CacheFormat.MEDIA3_V3:
                    groups = group_media3_segments(root)
                    if not groups:
                        raise ValueError("No Media3 v3 .exo fragments were found.")
                    total_segments = sum(len(g.segments) for g in groups)
                    self._append_log(f"Format: Media3 v3 ({len(groups)} track(s))")
                    for group in groups:
                        self._append_log(
                            f"  Track {group.content_id}: {len(group.segments)} fragments, "
                            f"{group.total_bytes / 1024 / 1024:.1f} MB"
                        )
                    self.status_var.set(
                        f"Valid: Media3 format, {len(groups)} track(s), {total_segments} fragment(s)."
                    )
                    self.progress["value"] = 0
                    return
                rows = [inspect_episode(root, self.allow_gaps_var.get())]

            format_label = "Media3 v3" if cache_format == CacheFormat.MEDIA3_V3 else "Legacy"
            self._append_log(f"Format: {format_label}")
            self._append_log("Validation successful:")
            for row in rows:
                self._append_log(f"- {row['name']}: {row['segments']} fragments ({row['first']} to {row['last']})")
            total = sum(int(row["segments"]) for row in rows)
            self.status_var.set(f"Valid: {len(rows)} episode(s), {total} fragment(s).")
            self.progress["value"] = 0
        except (OSError, ValueError) as error:
            self.status_var.set("Validation failed.")
            messagebox.showerror("Validation failed", str(error))
```

- [ ] **Step 2: Test GUI manually**

Run: `python -m app`
Verify:
1. Pilih folder anime -> Scan shows "Format: Legacy"
2. Pilih folder YouTube download -> Scan shows "Format: Media3 v3 (N track(s))"
3. Merge berfungsi untuk kedua format

- [ ] **Step 3: Commit**

```bash
git add app/gui.py
git commit -m "feat: show detected cache format in GUI scan results"
```

---

### Task 4: CLI Flag & `inspect_episode` Update

**Files:**
- Modify: `app/exo_merger.py` (CLI `main()` and `inspect_episode()`)
- Test: `tests/test_gabung_ffmpeg.py`

**Interfaces:**
- Consumes:
  - `app.cache_format.CacheFormat`, `detect_cache_format()`, `group_media3_segments()`
- Produces:
  - Updated `inspect_episode()` that works with both formats
  - New CLI flag `--format` with choices `auto`, `legacy`, `media3` for manual override

- [ ] **Step 1: Write tests for updated inspect_episode**

Add to `tests/test_gabung_ffmpeg.py`:

```python
class InspectMedia3Tests(unittest.TestCase):
    def test_inspect_episode_with_media3_fragments(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "0.0.100000.v3.exo").write_bytes(b"video1")
            (root / "0.1048576.100001.v3.exo").write_bytes(b"video2")
            (root / "1.0.100002.v3.exo").write_bytes(b"audio1")

            from app.exo_merger import inspect_episode
            info = inspect_episode(root)

            self.assertEqual(info["format"], "media3_v3")
            self.assertEqual(info["tracks"], 2)
            self.assertEqual(info["segments"], 3)

    def test_inspect_episode_legacy_includes_format_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "0.0.segment.exo").write_bytes(b"seg0")
            (root / "1.0.segment.exo").write_bytes(b"seg1")

            from app.exo_merger import inspect_episode
            info = inspect_episode(root)

            self.assertEqual(info["format"], "legacy")
            self.assertEqual(info["segments"], 2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m unittest tests.test_gabung_ffmpeg.InspectMedia3Tests -v`
Expected: FAIL (`KeyError: 'format'`)

- [ ] **Step 3: Update `inspect_episode()` in `exo_merger.py`**

Replace `inspect_episode()` (lines 99-110):

```python
def inspect_episode(root: Path, allow_gaps: bool = False) -> dict[str, object]:
    """Validate an episode without invoking FFmpeg."""
    cache_format = detect_cache_format(root)

    if cache_format == CacheFormat.MEDIA3_V3:
        groups = group_media3_segments(root)
        if not groups:
            raise ValueError("No Media3 v3 .exo fragments were found.")
        total_segments = sum(len(g.segments) for g in groups)
        return {
            "name": root.name,
            "path": root,
            "format": "media3_v3",
            "tracks": len(groups),
            "segments": total_segments,
            "first": groups[0].segments[0].name,
            "last": groups[-1].segments[-1].name,
            "subtitles": discover_subtitles(root),
        }

    # Legacy format
    segments = discover_segments(root)
    validate_segments(segments, allow_gaps=allow_gaps)
    return {
        "name": root.name,
        "path": root,
        "format": "legacy",
        "segments": len(segments),
        "first": segments[0].name,
        "last": segments[-1].name,
        "subtitles": discover_subtitles(root),
    }
```

- [ ] **Step 4: Add `--format` CLI flag to `build_parser()`**

Add to `build_parser()` (after line 281):

```python
    parser.add_argument(
        "--format",
        choices=("auto", "legacy", "media3"),
        default="auto",
        help="Cache format: auto-detect (default), force legacy, or force media3",
    )
```

- [ ] **Step 5: Run all tests**

Run: `python -m unittest discover -s tests -p "test_*.py" -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add app/exo_merger.py tests/test_gabung_ffmpeg.py
git commit -m "feat: add --format flag and Media3-aware inspect_episode"
```

---

### Task 5: Update README Documentation

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: all previous tasks
- Produces: updated documentation

- [ ] **Step 1: Add Media3 section to README.md**

Add after the "Multiple episodes" section (after line 64):

```markdown
## Supported formats

ExoFragmentMerger auto-detects the cache format:

| Format | Used By | Example Filename |
|--------|---------|-----------------|
| Legacy ExoPlayer | Anime apps, older players | `0.0.segment.exo` |
| Media3 v3 | YouTube, modern apps | `0.0.1697456789123.v3.exo` |

YouTube and other DASH-based apps store video and audio as separate tracks. The merger automatically detects multiple tracks, concatenates each one, and muxes them together via FFmpeg.

To force a specific format:

    ```powershell
    # Force legacy format
    python -m app.exo_merger --input-dir .\data\input\episode_01 --format legacy --output .\video.mp4

    # Force Media3 format
    python -m app.exo_merger --input-dir .\data\input\youtube_video --format media3 --output .\video.mp4
    ```
```

- [ ] **Step 2: Add `--format` to CLI options section**

Add to the CLI options list (around line 105):

```markdown
- `--format`: cache format — `auto` (default), `legacy`, or `media3`.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document Media3 format support and --format flag"
```

---

## Summary of Changes

| Task | Deliverable | Tests |
|------|------------|-------|
| 1 | `cache_format.py` — Format detection & Media3 parser | 10 unit tests |
| 2 | Multi-track merge pipeline in `exo_merger.py` | 3 new tests |
| 3 | GUI format info display | Manual verification |
| 4 | `inspect_episode()` + `--format` CLI flag | 2 new tests |
| 5 | README documentation | N/A |
