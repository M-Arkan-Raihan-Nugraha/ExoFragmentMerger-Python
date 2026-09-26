$ErrorActionPreference = "Stop"

if (-not (Get-Command pyinstaller -ErrorAction SilentlyContinue)) {
    throw "PyInstaller belum tersedia. Install dengan: python -m pip install pyinstaller"
}

pyinstaller --clean --noconfirm exo_merger_gui.spec
Write-Host "Selesai. Aplikasi ada di .\dist\ExoFragmentMerger.exe"
