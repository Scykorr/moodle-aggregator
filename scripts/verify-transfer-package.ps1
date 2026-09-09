# Verify an offline transfer package before copying it to USB / the target PC.

param(
    [string]$PackageDir = ".\transfer-package"
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
. (Join-Path $PSScriptRoot "_transfer-lib.ps1")

if (-not [System.IO.Path]::IsPathRooted($PackageDir)) {
    $PackageDir = Join-Path $Root $PackageDir
}
$PackageDir = [System.IO.Path]::GetFullPath($PackageDir)

function Assert-FileBigEnough([string]$Path, [int]$MinMB) {
    if (-not (Test-Path $Path)) { throw "Missing file: $Path" }
    $len = (Get-Item $Path).Length
    if ($len -lt ($MinMB * 1MB)) {
        throw "File too small (${len} bytes, expected >= $MinMB MB): $Path"
    }
}

Write-Host "==> Checking package at $PackageDir"

$moodleTar = Join-Path $PackageDir "images\moodle-offline-5.2.tar"
$mariaTar = Join-Path $PackageDir "images\mariadb-11.4.tar"
$dbTgz = Join-Path $PackageDir "volumes\moodle_db_data.tgz"
$dataTgz = Join-Path $PackageDir "volumes\moodle_data.tgz"
$envFile = Join-Path $PackageDir "project\.env"
$composeFile = Join-Path $PackageDir "project\docker-compose.yml"
$importScript = Join-Path $PackageDir "project\scripts\import-and-start.ps1"

Assert-FileBigEnough $moodleTar 500
Assert-FileBigEnough $mariaTar 50
Assert-FileBigEnough $dbTgz 1
Assert-FileBigEnough $dataTgz 1

foreach ($p in @($envFile, $composeFile, $importScript)) {
    if (-not (Test-Path $p)) { throw "Missing: $p" }
}

$envText = Get-Content $envFile -Raw
if ($envText -notmatch "MOODLE_DATABASE_PASSWORD=") {
    throw "project\.env does not contain MOODLE_DATABASE_PASSWORD"
}

Assert-DockerReady

Write-Host "==> Listing volume archives..."
$dataList = docker run --rm --entrypoint tar -v "$(Split-Path $dataTgz):/backup:ro" mariadb:11.4 tzf "/backup/$(Split-Path $dataTgz -Leaf)"
if ($LASTEXITCODE -ne 0) { throw "Cannot read moodle_data.tgz" }
if (($dataList | Select-String -Pattern "lang/ru/langconfig.php" -SimpleMatch) -eq $null) {
    throw "moodle_data.tgz does not contain Russian language pack (lang/ru/langconfig.php)"
}

$dbList = docker run --rm --entrypoint tar -v "$(Split-Path $dbTgz):/backup:ro" mariadb:11.4 tzf "/backup/$(Split-Path $dbTgz -Leaf)"
if ($LASTEXITCODE -ne 0) { throw "Cannot read moodle_db_data.tgz" }
if (($dbList | Select-String -Pattern "ibdata1|mysql/" | Select-Object -First 1) -eq $null) {
    throw "moodle_db_data.tgz does not look like a MariaDB datadir"
}

Write-Host "==> Checking image tarballs..."
tar.exe -tf $mariaTar 1>$null
if ($LASTEXITCODE -ne 0) { throw "mariadb-11.4.tar is not a readable tar" }
tar.exe -tf $moodleTar 1>$null
if ($LASTEXITCODE -ne 0) { throw "moodle-offline-5.2.tar is not a readable tar" }

Write-Host "Package OK."
Write-Host ("  moodle image : {0:N1} MB" -f ((Get-Item $moodleTar).Length / 1MB))
Write-Host ("  mariadb image: {0:N1} MB" -f ((Get-Item $mariaTar).Length / 1MB))
Write-Host ("  DB volume    : {0:N1} MB" -f ((Get-Item $dbTgz).Length / 1MB))
Write-Host ("  data volume  : {0:N1} MB" -f ((Get-Item $dataTgz).Length / 1MB))
