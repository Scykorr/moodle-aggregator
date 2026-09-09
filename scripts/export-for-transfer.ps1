# Export Moodle Docker stack for offline transfer to another PC.
# Run on a machine WITH internet after a successful `docker compose build`.
# Prefer export-for-transfer.cmd (bypasses ExecutionPolicy).

param(
    [string]$OutDir = ".\transfer-package"
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")

$Root = Get-ComposeRoot -StartDir $PSScriptRoot
Set-Location $Root

if (-not [IO.Path]::IsPathRooted($OutDir)) {
    $OutDir = Join-Path $Root $OutDir
}
$OutDir = [IO.Path]::GetFullPath($OutDir)
$ImagesOut = Join-Path $OutDir "images"
$ProjectOut = Join-Path $OutDir "project"

Write-Host "==> Preparing transfer package in $OutDir"
New-Item -ItemType Directory -Force -Path $ImagesOut | Out-Null
if (Test-Path -LiteralPath $ProjectOut) {
    # Re-export used to Copy-Item into existing folders and nest docker/docker, scripts/scripts.
    Remove-Item -LiteralPath $ProjectOut -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $ProjectOut | Out-Null

Assert-DockerReady

Write-Host "==> Ensuring images exist (build if needed)..."
Invoke-Docker -DockerArgs @("compose", "build")
& docker compose pull db
if ($LASTEXITCODE -ne 0) {
    & docker image inspect "mariadb:11.4" 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "mariadb:11.4 is missing and 'docker compose pull db' failed."
    }
    Write-Warning "docker compose pull db failed; using the existing local mariadb:11.4 image."
}

Ensure-ImageTag -Name "moodle-offline" -Tag "5.2"
Ensure-ImageTag -Name "mariadb" -Tag "11.4"

function Save-DockerImage {
    param(
        [string]$Image,
        [string]$TarPath
    )
    $TarPath = [IO.Path]::GetFullPath($TarPath)
    if (Test-Path -LiteralPath $TarPath) {
        Remove-Item -LiteralPath $TarPath -Force
    }
    Write-Host "    saving $Image"
    Write-Host "    -> $TarPath"
    # Flag -o must come before the image name; path must be absolute (Docker Desktop
    # otherwise may write a tiny/wrong file into the images folder).
    Invoke-Docker -DockerArgs @("save", "-o", $TarPath, $Image)
    $item = Get-Item -LiteralPath $TarPath
    if ($item.Length -lt 10MB) {
        throw "Saved image is too small ($($item.Length) bytes): $TarPath. docker save wrote an invalid archive."
    }
    Write-Host ("    {0:N1} MB" -f ($item.Length / 1MB))
}

Write-Host "==> Saving Docker images..."
Save-DockerImage -Image "moodle-offline:5.2" -TarPath (Join-Path $ImagesOut "moodle-offline-5.2.tar")
Save-DockerImage -Image "mariadb:11.4" -TarPath (Join-Path $ImagesOut "mariadb-11.4.tar")

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
    if (-not (Test-Path -LiteralPath $src)) {
        continue
    }
    $dest = Join-Path $ProjectOut $item
    Copy-Item -LiteralPath $src -Destination $dest -Recurse -Force
}

$junk = @(
    (Join-Path $ProjectOut "configurator\.venv"),
    (Join-Path $ProjectOut "configurator\build"),
    (Join-Path $ProjectOut "configurator\dist")
)
foreach ($path in $junk) {
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Recurse -Force
    }
}
Get-ChildItem -LiteralPath $ProjectOut -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force

$exe = Join-Path $Root "configurator\dist\MoodleConfigurator.exe"
if (Test-Path -LiteralPath $exe) {
    New-Item -ItemType Directory -Force -Path (Join-Path $ProjectOut "configurator\dist") | Out-Null
    Copy-Item -LiteralPath $exe -Destination (Join-Path $ProjectOut "configurator\dist\") -Force
}

Write-Host "==> Writing package info..."
@"
Moodle Offline Transfer Package
Created: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
Images:
  - moodle-offline:5.2
  - mariadb:11.4
  - folder: $ImagesOut

Copy the WHOLE '$OutDir' folder (images + project together).

On target PC:
  1. Install Docker Desktop and wait until it is Running
  2. Open project\scripts\import-and-start.cmd
  3. Run MoodleConfigurator.exe and set LAN IP (wwwroot)
"@ | Set-Content -Encoding ASCII (Join-Path $OutDir "PACKAGE_INFO.txt")

Write-Host "==> Done. Copy folder '$OutDir' to USB / network share."
Write-Host "    Size tip: images are large (several GB)."
