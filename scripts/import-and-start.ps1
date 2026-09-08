# Import Moodle images and start stack on offline target PC.

param(
    [string]$PackageDir = ""
)

$ErrorActionPreference = "Stop"

# If launched from transfer-package\project\scripts, go up to project root
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Error "Docker not found. Install Docker Desktop first."
}

# Locate images: sibling ../images (transfer layout) or ./transfer-package/images
$candidates = @(
    (Join-Path (Split-Path $Root) "images"),
    (Join-Path $Root "transfer-package\images"),
    (Join-Path $Root "images")
)
if ($PackageDir) {
    $candidates = @((Join-Path $PackageDir "images")) + $candidates
}

$ImagesDir = $null
foreach ($c in $candidates) {
    if (Test-Path (Join-Path $c "moodle-offline-5.2.tar")) {
        $ImagesDir = $c
        break
    }
}

if (-not $ImagesDir) {
    Write-Error "Image archives not found. Expected moodle-offline-5.2.tar and mariadb-11.4.tar"
}

Write-Host "==> Loading images from $ImagesDir"
docker load -i (Join-Path $ImagesDir "mariadb-11.4.tar")
docker load -i (Join-Path $ImagesDir "moodle-offline-5.2.tar")

if (-not (Test-Path ".\.env")) {
    Copy-Item ".\.env.example" ".\.env"
    Write-Host "Created .env from .env.example — set MOODLE_WWWROOT before first use."
}

Write-Host "==> Starting Moodle stack..."
docker compose up -d

Write-Host "==> Status:"
docker compose ps
Write-Host ""
Write-Host "Open MoodleConfigurator.exe to set LAN IP (wwwroot), then open http://<IP>/ in browsers on the LAN."
