# Load Moodle images + volume snapshot and start the stack on an offline PC.

param(
    [string]$PackageDir = ""
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
. (Join-Path $PSScriptRoot "_transfer-lib.ps1")

Assert-DockerReady

$ImagesDir = Find-TransferDir -Name "images" -MarkerFile "moodle-offline-5.2.tar" -PackageDir $PackageDir -ProjectRoot $Root
$VolumesDir = Find-TransferDir -Name "volumes" -MarkerFile "moodle_db_data.tgz" -PackageDir $PackageDir -ProjectRoot $Root

if (-not $ImagesDir) {
    throw "Image archives not found. Expected moodle-offline-5.2.tar and mariadb-11.4.tar"
}
if (-not $VolumesDir) {
    throw "Volume snapshots not found. Expected volumes\moodle_db_data.tgz and volumes\moodle_data.tgz. Without them Moodle would be empty."
}

foreach ($need in @("moodle-offline-5.2.tar", "mariadb-11.4.tar")) {
    if (-not (Test-Path (Join-Path $ImagesDir $need))) {
        throw "Missing image archive: $need"
    }
}
foreach ($need in @("moodle_db_data.tgz", "moodle_data.tgz")) {
    if (-not (Test-Path (Join-Path $VolumesDir $need))) {
        throw "Missing volume archive: $need"
    }
}

Write-Host "==> Loading images from $ImagesDir"
docker load -i (Join-Path $ImagesDir "mariadb-11.4.tar")
if ($LASTEXITCODE -ne 0) { throw "docker load mariadb:11.4 failed" }
docker load -i (Join-Path $ImagesDir "moodle-offline-5.2.tar")
if ($LASTEXITCODE -ne 0) { throw "docker load moodle-offline:5.2 failed" }

if (-not (Test-Path ".\.env")) {
    if (Test-Path ".\.env.example") {
        Copy-Item ".\.env.example" ".\.env"
        Write-Warning "Created .env from .env.example. DB passwords may not match the snapshot."
    }
    else {
        throw ".env is missing."
    }
}

Write-Host "==> Creating containers and empty volumes (not starting yet)..."
docker compose up --no-build --pull never --no-start
if ($LASTEXITCODE -ne 0) { throw "docker compose up --no-start failed" }

$dbVol = Get-ComposeVolumeName "moodle_db_data"
$dataVol = Get-ComposeVolumeName "moodle_data"
Write-Host "    Restoring DB volume:   $dbVol"
Write-Host "    Restoring data volume: $dataVol"

Write-Host "==> Restoring volume snapshots from $VolumesDir"
Invoke-VolumeTar -VolumeName $dbVol -ArchivePath (Join-Path $VolumesDir "moodle_db_data.tgz") -Mode extract
Invoke-VolumeTar -VolumeName $dataVol -ArchivePath (Join-Path $VolumesDir "moodle_data.tgz") -Mode extract

Write-Host "==> Starting Moodle stack (offline, no build/pull)..."
docker compose up -d --no-build --pull never
if ($LASTEXITCODE -ne 0) { throw "docker compose up -d failed" }

Write-Host "==> Waiting for Moodle to accept the restored site..."
$result = Wait-MoodleReady -TimeoutSec 240
if (-not $result.Existing) {
    throw "Restored DB was not detected. Refusing to continue."
}

Write-Host "==> Status:"
docker compose ps
Write-Host ""
Write-Host "Moodle is up with the transferred data."
Write-Host "Open http://localhost/  (admin / Admin123! unless .env was changed)"
Write-Host "If this PC has a different LAN IP, update MOODLE_WWWROOT in .env and recreate the moodle service."
