# Exo Fragment Merger

Windows desktop and CLI utility for joining numbered ExoPlayer `.exo` fragments into MP4 videos, with optional burned-in subtitles and batch episode processing.

## Requirements

- Python 3.10 or newer
- FFmpeg on `PATH` for source/CLI use
- For burned-in subtitles, FFmpeg must include `libass` and `libx264`

No additional Python packages are required for normal source usage.

## Usage

For regular users, run the packaged `ExoFragmentMerger.exe` and double-click it. FFmpeg is bundled inside the executable.

```powershell
python -m app
```

The GUI supports single-video and batch episode processing, subtitle selection, pre-flight validation, progress reporting, cancellation, resume/skip, and an About dialog.

Fragments and subtitles are discovered recursively under `--input-dir`. The leading number in each `.exo` filename determines merge order.

```powershell
# List available subtitles
python -m app.exo_merger --input-dir .\data\input\episode_01 --list-subtitles

# Select a language by code
python -m app.exo_merger --input-dir .\data\input\episode_01 --subtitle en --output .\data\output\video_english.mp4

# Select a specific subtitle filename
python -m app.exo_merger --input-dir .\data\input\episode_01 --subtitle subtitle_indo.vtt --output .\data\output\video_indonesia.mp4

# Create a video without subtitles
python -m app.exo_merger --input-dir .\data\input\episode_01 --subtitle none --output .\data\output\video_no_subtitle.mp4

# Explicitly replace an existing output
python -m app.exo_merger --input-dir .\data\input\episode_01 --subtitle in_ID --output .\data\output\video_hardsub_final.mp4 --overwrite
```

In an interactive terminal with multiple subtitles, the program displays a selection menu. Automatic selection prefers `.in_ID` when available; use `--subtitle` for non-interactive runs.

## Multiple episodes

Use one direct subfolder for each episode:

```text
series/
├── Episode 01/
│   └── downloads/0/*.exo ...
├── Episode 02/
│   └── downloads/0/*.exo ...
└── Episode 03/
    └── downloads/0/*.exo ...
```

Process all episodes:

```powershell
python -m app.exo_merger --input-dir .\series --batch --subtitle in_ID --output-dir .\hasil
```

The output becomes `hasil/Episode_01.mp4`, `hasil/Episode_02.mp4`, and so on. Fragments may be nested deeper; episode folders must be direct children of `--input-dir`.

## Project structure

```text
app/                       application package
tests/                     unit tests
data/input/episode_01/     local source media
data/output/               generated videos
vendor/                    local FFmpeg binary
build_windows.ps1          Windows build script
exo_merger_gui.spec        PyInstaller configuration
pyproject.toml             package metadata and entry points
```

The production entry point is `python -m app`. After editable installation, use `exo-merger-gui` for the GUI and `exo-merger` for the CLI. Add new episodes as subfolders under `data/input/`.

## Build the Windows executable

The build requires a local `vendor/ffmpeg.exe`. It is excluded from Git because it is large.

```powershell
python -m pip install pyinstaller
powershell -ExecutionPolicy Bypass -File .\build_windows.ps1
```

The final portable application is one file: `dist/ExoFragmentMerger.exe`. FFmpeg is bundled inside it.

## CLI options

- `-i, --input-dir`: fragment and subtitle folder; default `.`.
- `-s, --subtitle`: language code, subtitle filename, or `none`.
- `--list-subtitles`: list subtitles without processing video.
- `-o, --output`: MP4 output path.
- `--overwrite`: replace an existing output.
- `--skip-existing`: skip existing outputs for resumable batch jobs.
- `--allow-gaps`: continue when fragment numbers are missing.
- `--batch`: process each direct subfolder as one episode.
- `--output-dir`: output folder for batch mode.
- `--preset`: `libx264` preset; default `ultrafast`.
- `--crf`: `libx264` quality from 0 to 51; default `23`.
- `--ffmpeg`: FFmpeg executable path; default `ffmpeg`.

Videos with subtitles are re-encoded so the text becomes permanent. Audio is copied. Without subtitles, audio and video streams are copied without re-encoding.

Processing uses a temporary folder beside the output and replaces the final output only after FFmpeg succeeds. Temporary files are cleaned automatically.

## Test

```powershell
python -m unittest discover -s tests -p "test_*.py" -v
```
