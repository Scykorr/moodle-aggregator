# Export the running Moodle stack (images + volumes + project) for offline transfer.
# Does NOT rebuild or pull: saves the current local images and data snapshot.

param(
    [string]$OutDir = ".\transfer-package"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
. (Join-Path $PSScriptRoot "_transfer-lib.ps1")

Assert-DockerReady

$OutDir = [System.IO.Path]::GetFullPath((Join-Path $Root $OutDir))
$ImagesDir = Join-Path $OutDir "images"
$VolumesDir = Join-Path $OutDir "volumes"
$ProjectDir = Join-Path $OutDir "project"
$ExtrasDir = Join-Path $OutDir "extras"

Write-Host "==> Preparing transfer package in $OutDir"
New-Item -ItemType Directory -Force -Path $ImagesDir, $VolumesDir, $ProjectDir, $ExtrasDir | Out-Null

foreach ($img in @("moodle-offline:5.2", "mariadb:11.4")) {
    docker image inspect $img 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Image $img not found. Build/start the stack on this PC first."
    }
}

Write-Host "==> Copying project files..."
$copyItems = @(
    "docker-compose.yml",
    "Dockerfile",
    ".env",
    ".env.example",
    "docker",
    "configurator",
    "docs",
    "scripts",
    "README.md"
)
foreach ($item in $copyItems) {
    $src = Join-Path $Root $item
    if (Test-Path $src) {
        Copy-Item -Path $src -Destination (Join-Path $ProjectDir $item) -Recurse -Force
    }
}

if (-not (Test-Path (Join-Path $ProjectDir ".env"))) {
    throw ".env is missing. The target PC needs the same DB passwords as this instance."
}

$exe = Join-Path $Root "configurator\dist\MoodleConfigurator.exe"
if (Test-Path $exe) {
    New-Item -ItemType Directory -Force -Path (Join-Path $ProjectDir "configurator\dist") | Out-Null
    Copy-Item $exe (Join-Path $ProjectDir "configurator\dist\") -Force
}

$ruZip = "C:\Users\Tony Fedos\Downloads\ru.zip"
if (Test-Path $ruZip) {
    Copy-Item $ruZip (Join-Path $ExtrasDir "ru.zip") -Force
}

Write-Host "==> Saving Docker images (this can take several minutes)..."
docker save moodle-offline:5.2 -o (Join-Path $ImagesDir "moodle-offline-5.2.tar")
if ($LASTEXITCODE -ne 0) { throw "docker save moodle-offline:5.2 failed" }
docker save mariadb:11.4 -o (Join-Path $ImagesDir "mariadb-11.4.tar")
if ($LASTEXITCODE -ne 0) { throw "docker save mariadb:11.4 failed" }

Write-Host "==> Stopping stack for a consistent volume snapshot..."
docker compose stop
if ($LASTEXITCODE -ne 0) { throw "docker compose stop failed" }

try {
    $dbVol = Get-ComposeVolumeName "moodle_db_data"
    $dataVol = Get-ComposeVolumeName "moodle_data"
    Write-Host "    DB volume:   $dbVol"
    Write-Host "    Data volume: $dataVol"

    Write-Host "==> Archiving volumes..."
    Invoke-VolumeTar -VolumeName $dbVol -ArchivePath (Join-Path $VolumesDir "moodle_db_data.tgz") -Mode create
    Invoke-VolumeTar -VolumeName $dataVol -ArchivePath (Join-Path $VolumesDir "moodle_data.tgz") -Mode create
}
finally {
    Write-Host "==> Starting stack again on this PC..."
    docker compose start
}

Write-Host "==> Writing launcher and package info..."
$importCmd = @"
@echo off
cd /d "%~dp0project"
echo Importing Moodle images and data. Keep this window open.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0project\scripts\import-and-start.ps1"
if errorlevel 1 (
  echo.
  echo IMPORT FAILED. Do not close this window; copy the error text.
  pause
  exit /b 1
)
echo.
echo Moodle should be at http://localhost/
pause
"@
Set-Content -Path (Join-Path $OutDir "IMPORT-AND-START.cmd") -Value $importCmd -Encoding ASCII

$info = @"
Moodle Offline Transfer Package
Created: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
Source volumes:
  - moodle_db_data (MariaDB)
  - moodle_data (moodledata, including language packs)

Images:
  - moodle-offline:5.2
  - mariadb:11.4

ON TARGET PC (Docker Desktop already installed and RUNNING):
  1. Copy this whole folder (transfer-package) onto the disk.
  2. Double-click IMPORT-AND-START.cmd
     or in PowerShell from this folder:
        powershell -NoProfile -ExecutionPolicy Bypass -File .\project\scripts\import-and-start.ps1
  3. Open http://localhost/
     Login: admin / Admin123!  (unless you changed .env)
  4. If users will open Moodle by LAN IP, set MOODLE_WWWROOT to http://<that-IP>
     then: docker compose -f project\docker-compose.yml up -d --no-build --pull never --force-recreate moodle

Do NOT run docker compose build or docker compose pull on the target PC.
"@
Set-Content -Encoding ASCII -Path (Join-Path $OutDir "PACKAGE_INFO.txt") -Value $info

Write-Host "==> Verifying package..."
& (Join-Path $PSScriptRoot "verify-transfer-package.ps1") -PackageDir $OutDir

Write-Host "==> Done. Copy folder '$OutDir' to USB / external disk."
Get-ChildItem -Recurse $OutDir -File | ForEach-Object {
    "{0,10:N1} MB  {1}" -f ($_.Length / 1MB), $_.FullName.Substring($OutDir.Length + 1)
} | Write-Host
