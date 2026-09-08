# Export Moodle Docker stack for offline transfer to another PC.
# Run on a machine WITH internet after a successful `docker compose build`.

param(
    [string]$OutDir = ".\transfer-package"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

Write-Host "==> Preparing transfer package in $OutDir"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
New-Item -ItemType Directory -Force -Path "$OutDir\images" | Out-Null
New-Item -ItemType Directory -Force -Path "$OutDir\project" | Out-Null

Write-Host "==> Ensuring images exist (build if needed)..."
docker compose build
docker compose pull db

Write-Host "==> Saving Docker images..."
docker save moodle-offline:5.2 -o "$OutDir\images\moodle-offline-5.2.tar"
docker save mariadb:11.4 -o "$OutDir\images\mariadb-11.4.tar"

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
        Copy-Item -Path $src -Destination "$OutDir\project\$item" -Recurse -Force
    }
}

# Optional: include built EXE if present
$exe = Join-Path $Root "configurator\dist\MoodleConfigurator.exe"
if (Test-Path $exe) {
    New-Item -ItemType Directory -Force -Path "$OutDir\project\configurator\dist" | Out-Null
    Copy-Item $exe "$OutDir\project\configurator\dist\" -Force
}

Write-Host "==> Writing package info..."
@"
Moodle Offline Transfer Package
Created: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
Images:
  - moodle-offline:5.2
  - mariadb:11.4

On target PC:
  1. Install Docker Desktop
  2. Run scripts\import-and-start.ps1
  3. Run MoodleConfigurator.exe and set LAN IP (wwwroot)
"@ | Set-Content -Encoding UTF8 "$OutDir\PACKAGE_INFO.txt"

Write-Host "==> Done. Copy folder '$OutDir' to USB / network share."
Write-Host "    Size tip: images are large (several GB)."
