# Import Keycloak + PostgreSQL on an offline Windows PC (no pull).
# ASCII only. Safe for cmd.exe double-click and PowerShell 5.1.

param(
    [string]$PackageDir = ""
)

$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "_offline-lib.ps1")

try {
    if ([string]::IsNullOrWhiteSpace($PackageDir)) {
        $candidate = Join-Path $PSScriptRoot ".."
        $PackageDir = Normalize-DirPath $candidate
        if (-not (Test-Path -LiteralPath (Join-Path $PackageDir "images\keycloak-26.7.3.tar"))) {
            $PackageDir = Normalize-DirPath (Join-Path $PSScriptRoot "..\transfer-identity")
        }
    }
    else {
        $PackageDir = Normalize-DirPath $PackageDir
    }

    Write-Host ("PackageDir={0}" -f $PackageDir)
    Assert-DockerReady

    $ImagesDir = Join-Path $PackageDir "images"
    $VolumesDir = Join-Path $PackageDir "volumes"
    $ProjectDir = Join-Path $PackageDir "project"
    $KcTar = Join-Path $ImagesDir "keycloak-26.7.3.tar"
    $PgTar = Join-Path $ImagesDir "postgres-17.11.tar"
    $VolTar = Join-Path $VolumesDir "identity_db.tgz"

    foreach ($need in @($KcTar, $PgTar)) {
        if (-not (Test-Path -LiteralPath $need)) {
            throw ("Missing image archive: {0}" -f $need)
        }
    }
    foreach ($need in @(
        (Join-Path $ProjectDir "compose.yml"),
        (Join-Path $ProjectDir "generated\.env"),
        (Join-Path $ProjectDir "certs\server.crt"),
        (Join-Path $ProjectDir "certs\server.key")
    )) {
        if (-not (Test-Path -LiteralPath $need)) {
            throw ("Missing required file: {0}" -f $need)
        }
    }

    Load-DockerImageArchive -Archive $PgTar
    Load-DockerImageArchive -Archive $KcTar
    Assert-ImageExists "postgres:17.11"
    Assert-ImageExists "quay.io/keycloak/keycloak:26.7.3"

    $Target = Join-Path $PackageDir "runtime"
    if (Test-Path -LiteralPath $Target) {
        Remove-Item -LiteralPath $Target -Recurse -Force
    }
    New-Item -ItemType Directory -Force -Path $Target | Out-Null
    Copy-Item -LiteralPath (Join-Path $ProjectDir "compose.yml") -Destination (Join-Path $Target "compose.yml") -Force
    Copy-Tree -Source (Join-Path $ProjectDir "generated") -Destination (Join-Path $Target "generated")
    Copy-Tree -Source (Join-Path $ProjectDir "certs") -Destination (Join-Path $Target "certs")
    if (Test-Path -LiteralPath (Join-Path $ProjectDir "sites.json")) {
        Copy-Item -LiteralPath (Join-Path $ProjectDir "sites.json") -Destination (Join-Path $Target "sites.json") -Force
    }

    Set-Location -LiteralPath $Target
    $composeArgs = @("compose", "--env-file", "generated/.env", "-f", "compose.yml")

    if (Test-Path -LiteralPath $VolTar) {
        Write-Host "==> Preparing volume and restoring identity_db BEFORE Keycloak start..."
        $code = Invoke-DockerCli -DockerArgs ($composeArgs + @("up", "-d", "--pull", "never", "db"))
        if ($code -ne 0) { throw "postgres up failed" }
        [void](Invoke-DockerCli -DockerArgs ($composeArgs + @("stop")))
        $volName = Get-ComposeVolumeName -LogicalName "identity_db" -ComposeArgs $composeArgs
        [void](Invoke-DockerCli -DockerArgs @(
            "run", "--rm", "--entrypoint", "sh",
            "-v", ($volName + ":/data"),
            "postgres:17.11",
            "-c", "find /data -mindepth 1 -maxdepth 1 -exec rm -rf {} +"
        ))
        Invoke-VolumeTar -VolumeName $volName -ArchivePath $VolTar -Mode extract -HelperImage "postgres:17.11"
    }

    Write-Host "==> Starting Keycloak stack (pull never)..."
    $code = Invoke-DockerCli -DockerArgs ($composeArgs + @("up", "-d", "--pull", "never"))
    if ($code -ne 0) { throw "compose up failed" }

    $port = "8443"
    foreach ($line in (Get-Content -LiteralPath (Join-Path $Target "generated\.env"))) {
        if ($line -match '^\s*IDP_HTTPS_PORT\s*=\s*(.+)\s*$') {
            $port = $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
    $disc = "https://127.0.0.1:{0}/realms/students/.well-known/openid-configuration" -f $port
    Write-Host ("==> Waiting for discovery {0}" -f $disc)
    Wait-HttpOk -Url $disc -TimeoutSec 180 -SkipCertCheck

    Write-Host ("OK: Keycloak is up at https://127.0.0.1:{0}" -f $port)
    Write-Host ("Admin: https://127.0.0.1:{0}/admin  (bootstrap-admin / password in generated\.env)" -f $port)
    Write-Host ("Working directory: {0}" -f $Target)
    exit 0
}
catch {
    Write-Host ""
    Write-Host ("ERROR: {0}" -f $_.Exception.Message)
    exit 1
}
