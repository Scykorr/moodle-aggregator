# Export Keycloak + PostgreSQL images, certs, generated env/realm, optional DB volume.
# ASCII only. Safe for Windows PowerShell 5.1.

param(
    [string]$OutDir = ".\transfer-identity"
)

$ErrorActionPreference = "Stop"

$FedRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $FedRoot
. (Join-Path $PSScriptRoot "_offline-lib.ps1")

try {
    Assert-DockerReady

    $OutDir = Normalize-DirPath (Join-Path $FedRoot $OutDir)
    $ImagesDir = Join-Path $OutDir "images"
    $VolumesDir = Join-Path $OutDir "volumes"
    $ProjectDir = Join-Path $OutDir "project"
    $ScriptsDir = Join-Path $OutDir "scripts"

    Write-Host ("==> Package: {0}" -f $OutDir)
    New-Item -ItemType Directory -Force -Path $ImagesDir, $VolumesDir, $ProjectDir, $ScriptsDir | Out-Null

    foreach ($img in @("quay.io/keycloak/keycloak:26.7.3", "postgres:17.11")) {
        Assert-ImageExists $img
    }

    if (-not (Test-Path -LiteralPath (Join-Path $FedRoot "generated\.env"))) {
        throw "Missing generated\.env. Run: python prepare.py first."
    }
    if (-not (Test-Path -LiteralPath (Join-Path $FedRoot "certs\server.crt")) -or -not (Test-Path -LiteralPath (Join-Path $FedRoot "certs\server.key"))) {
        throw "Missing certs\server.crt / server.key."
    }

    Save-DockerImage -Image "quay.io/keycloak/keycloak:26.7.3" -OutFile (Join-Path $ImagesDir "keycloak-26.7.3.tar")
    Save-DockerImage -Image "postgres:17.11" -OutFile (Join-Path $ImagesDir "postgres-17.11.tar")

    Write-Host "==> Copying Keycloak project (CONTAINS SECRETS)..."
    Copy-Item -LiteralPath (Join-Path $FedRoot "compose.yml") -Destination (Join-Path $ProjectDir "compose.yml") -Force
    Copy-Tree -Source (Join-Path $FedRoot "generated") -Destination (Join-Path $ProjectDir "generated")
    Copy-Tree -Source (Join-Path $FedRoot "certs") -Destination (Join-Path $ProjectDir "certs")
    if (Test-Path -LiteralPath (Join-Path $FedRoot "sites.json")) {
        Copy-Item -LiteralPath (Join-Path $FedRoot "sites.json") -Destination (Join-Path $ProjectDir "sites.json") -Force
    }
    foreach ($doc in @("docs\offline-keycloak.md", "docs\deployment.md", "docs\operator-guide.md")) {
        $src = Join-Path $FedRoot $doc
        if (Test-Path -LiteralPath $src) {
            $dest = Join-Path $ProjectDir $doc
            $parent = Split-Path -Parent $dest
            if ($parent) {
                New-Item -ItemType Directory -Force -Path $parent | Out-Null
            }
            Copy-Item -LiteralPath $src -Destination $dest -Force
        }
    }

    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "_offline-lib.ps1") -Destination (Join-Path $ScriptsDir "_offline-lib.ps1") -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "import-identity.ps1") -Destination (Join-Path $ScriptsDir "import-identity.ps1") -Force
    Write-ImportCmd -PackageRoot $OutDir -ScriptRelativePath "scripts\import-identity.ps1" -CmdName "IMPORT-IDENTITY.cmd"

    $composeArgs = @("compose", "--env-file", "generated/.env", "-f", "compose.yml")

    Write-Host "==> Stopping identity stack for DB snapshot..."
    [void](Invoke-DockerCli -DockerArgs ($composeArgs + @("stop")))

    try {
        $volName = Get-ComposeVolumeName -LogicalName "identity_db" -ComposeArgs $composeArgs
        $code = Invoke-DockerCli -DockerArgs @("volume", "inspect", "-f", "{{.Name}}", $volName)
        if ($code -eq 0) {
            Invoke-VolumeTar -VolumeName $volName `
                -ArchivePath (Join-Path $VolumesDir "identity_db.tgz") `
                -Mode create `
                -HelperImage "postgres:17.11"
            Write-Host ("    Saved volume {0}" -f $volName)
        }
        else {
            Write-Warning ("Volume {0} not found yet; package without user DB." -f $volName)
        }
    }
    finally {
        Write-Host "==> Starting identity stack again on export PC..."
        [void](Invoke-DockerCli -DockerArgs ($composeArgs + @("up", "-d", "--pull", "never")))
    }

    $readme = @(
        "Keycloak offline package - CONTAINS SECRETS",
        "1. Start Docker Desktop on the target PC.",
        "2. Copy this whole folder to the target PC.",
        "3. Double-click IMPORT-IDENTITY.cmd",
        "4. Open https://127.0.0.1:8443/admin (bootstrap-admin)",
        "Password: project/generated/.env -> KC_BOOTSTRAP_ADMIN_PASSWORD",
        "See project/docs/offline-keycloak.md"
    ) -join "`r`n"
    Write-Utf8File -Path (Join-Path $OutDir "README.txt") -Content ($readme + "`r`n")

    Write-Host ("==> Done: {0}" -f $OutDir)
    Get-ChildItem -LiteralPath $OutDir -Recurse -File | ForEach-Object {
        Write-Host ("{0}  {1:N2} MB" -f $_.FullName, ($_.Length / 1MB))
    }
    exit 0
}
catch {
    Write-Host ""
    Write-Host ("ERROR: {0}" -f $_.Exception.Message)
    exit 1
}
