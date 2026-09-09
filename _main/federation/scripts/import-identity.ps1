# Import Keycloak + PostgreSQL on an offline Windows PC (no pull).
# ASCII-only script for Windows PowerShell 5.1.

param(
    [string]$PackageDir = ""
)

$ErrorActionPreference = "Stop"

if ($PackageDir) {
    $PackageDir = [System.IO.Path]::GetFullPath($PackageDir)
}
else {
    $PackageDir = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..\transfer-identity"))
    if (-not (Test-Path (Join-Path $PackageDir "IMPORT-IDENTITY.cmd"))) {
        $PackageDir = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\transfer-identity"))
    }
}

. (Join-Path $PSScriptRoot "_offline-lib.ps1")
Assert-DockerReady

$ImagesDir = Join-Path $PackageDir "images"
$VolumesDir = Join-Path $PackageDir "volumes"
$ProjectDir = Join-Path $PackageDir "project"
$KcTar = Join-Path $ImagesDir "keycloak-26.7.3.tar"
$PgTar = Join-Path $ImagesDir "postgres-17.11.tar"
$VolTar = Join-Path $VolumesDir "identity_db.tgz"

foreach ($need in @($KcTar, $PgTar)) {
    if (-not (Test-Path $need)) { throw "Missing image archive: $need" }
}
foreach ($need in @(
    (Join-Path $ProjectDir "compose.yml"),
    (Join-Path $ProjectDir "generated\.env"),
    (Join-Path $ProjectDir "certs\server.crt"),
    (Join-Path $ProjectDir "certs\server.key")
)) {
    if (-not (Test-Path $need)) { throw "Missing required file: $need" }
}

Load-DockerImageArchive -Archive $PgTar
Load-DockerImageArchive -Archive $KcTar
Assert-ImageExists "postgres:17.11"
Assert-ImageExists "quay.io/keycloak/keycloak:26.7.3"

$Target = Join-Path $PackageDir "runtime"
if (Test-Path $Target) {
    Remove-Item $Target -Recurse -Force
}
New-Item -ItemType Directory -Force -Path $Target | Out-Null
Copy-Item (Join-Path $ProjectDir "compose.yml") (Join-Path $Target "compose.yml") -Force
Copy-Tree -Source (Join-Path $ProjectDir "generated") -Destination (Join-Path $Target "generated")
Copy-Tree -Source (Join-Path $ProjectDir "certs") -Destination (Join-Path $Target "certs")
if (Test-Path (Join-Path $ProjectDir "sites.json")) {
    Copy-Item (Join-Path $ProjectDir "sites.json") (Join-Path $Target "sites.json") -Force
}

Set-Location $Target
$composeArgs = @("compose", "--env-file", "generated/.env", "-f", "compose.yml")

if (Test-Path $VolTar) {
    Write-Host "==> Preparing volume and restoring identity_db BEFORE Keycloak start..."
    $code = Invoke-DockerCli -DockerArgs ($composeArgs + @("up", "-d", "--pull", "never", "db"))
    if ($code -ne 0) { throw "postgres up failed" }
    [void](Invoke-DockerCli -DockerArgs ($composeArgs + @("stop")))
    $volName = Get-ComposeVolumeName -LogicalName "identity_db" -ComposeArgs $composeArgs
    [void](Invoke-DockerCli -DockerArgs @(
        "run", "--rm", "--entrypoint", "sh",
        "-v", "${volName}:/data",
        "postgres:17.11",
        "-c", "find /data -mindepth 1 -maxdepth 1 -exec rm -rf {} +"
    ))
    Invoke-VolumeTar -VolumeName $volName -ArchivePath $VolTar -Mode extract -HelperImage "postgres:17.11"
}

Write-Host "==> Starting Keycloak stack (pull never)..."
$code = Invoke-DockerCli -DockerArgs ($composeArgs + @("up", "-d", "--pull", "never"))
if ($code -ne 0) { throw "compose up failed" }

$port = "8443"
foreach ($line in (Get-Content (Join-Path $Target "generated\.env"))) {
    if ($line -match '^\s*IDP_HTTPS_PORT\s*=\s*(.+)\s*$') { $port = $Matches[1].Trim() }
}
$disc = "https://127.0.0.1:$port/realms/students/.well-known/openid-configuration"
Write-Host "==> Waiting for discovery $disc"
Wait-HttpOk -Url $disc -TimeoutSec 180 -SkipCertCheck

Write-Host "OK: Keycloak is up at https://127.0.0.1:$port"
Write-Host "Admin: https://127.0.0.1:$port/admin  (bootstrap-admin / password in generated\.env)"
Write-Host "Working directory: $Target"
