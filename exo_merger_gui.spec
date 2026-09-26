# Build with: pyinstaller --clean --noconfirm exo_merger_gui.spec
from pathlib import Path
import sys

project_root = Path(SPECPATH)
python_root = Path(sys.base_prefix)
tkinter_root = python_root / "Lib" / "tkinter"
tcl_root = python_root / "tcl"

tk_data = [(str(tkinter_root), "tkinter")]
for directory in ("tcl8.6", "tk8.6"):
    source = tcl_root / directory
    if source.exists():
        tk_data.append((str(source), f"tcl/{directory}"))

tk_binaries = []
for filename in ("_tkinter.pyd", "tk86t.dll", "tcl86t.dll"):
    source = python_root / "DLLs" / filename
    if source.exists():
        tk_binaries.append((str(source), "."))

ffmpeg_source = project_root / "vendor" / "ffmpeg.exe"
if not ffmpeg_source.is_file():
    raise SystemExit(f"Bundled FFmpeg executable is missing: {ffmpeg_source}")
ffmpeg_binaries = [(str(ffmpeg_source), "ffmpeg")]

a = Analysis(
    [str(project_root / "app" / "__main__.py")],
    pathex=[str(project_root), str(python_root / "Lib")],
    binaries=tk_binaries + ffmpeg_binaries,
    datas=tk_data,
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="ExoFragmentMerger",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
