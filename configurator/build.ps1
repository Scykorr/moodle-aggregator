# Build MoodleConfigurator.exe (one-file, windowed)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not (Test-Path ".\.venv")) {
    python -m venv .venv
}
& .\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

pyinstaller --noconfirm moodle_configurator.spec

$exe = Resolve-Path .\dist\MoodleConfigurator.exe
Write-Host ""
Write-Host "EXE ready: $exe"
Write-Host "Run from project root (docker-compose.yml) or keep under configurator\dist"
