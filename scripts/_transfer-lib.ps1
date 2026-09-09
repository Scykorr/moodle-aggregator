# Shared helpers for offline Moodle transfer. Dot-source from other scripts.

$ErrorActionPreference = "Stop"

function Assert-DockerReady {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker not found in PATH. Start Docker Desktop and retry."
    }
    docker info 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Desktop is not running (docker info failed)."
    }
}

function Get-ComposeVolumeName {
    param([Parameter(Mandatory = $true)][string]$LogicalName)
    $raw = docker compose config --format json
    if ($LASTEXITCODE -ne 0 -or -not $raw) {
        throw "docker compose config failed. Run this from the project directory."
    }
    $cfg = $raw | ConvertFrom-Json
    $vol = $cfg.volumes.$LogicalName
    if (-not $vol -or -not $vol.name) {
        throw "Compose volume '$LogicalName' not found."
    }
    return [string]$vol.name
}

function Invoke-VolumeTar {
    param(
        [Parameter(Mandatory = $true)][string]$VolumeName,
        [Parameter(Mandatory = $true)][string]$ArchivePath,
        [Parameter(Mandatory = $true)][ValidateSet("create", "extract")][string]$Mode
    )
    $backupDir = [System.IO.Path]::GetFullPath((Split-Path -Parent $ArchivePath))
    $archiveFile = Split-Path -Leaf $ArchivePath
    New-Item -ItemType Directory -Force -Path $backupDir | Out-Null

    if ($Mode -eq "create") {
        docker run --rm --entrypoint tar `
            -v "${VolumeName}:/data:ro" `
            -v "${backupDir}:/backup" `
            mariadb:11.4 `
            czf "/backup/$archiveFile" -C /data .
    }
    else {
        docker run --rm --entrypoint tar `
            -v "${VolumeName}:/data" `
            -v "${backupDir}:/backup:ro" `
            mariadb:11.4 `
            xzf "/backup/$archiveFile" -C /data
    }
    if ($LASTEXITCODE -ne 0) {
        throw "Volume tar $Mode failed for $VolumeName ($archiveFile)."
    }
}

function Find-TransferDir {
    param(
        [string]$Name,
        [string]$MarkerFile,
        [string]$PackageDir = "",
        [string]$ProjectRoot
    )
    $candidates = @()
    if ($PackageDir) {
        $candidates += (Join-Path $PackageDir $Name)
    }
    $parent = Split-Path $ProjectRoot
    $candidates += (Join-Path $parent $Name)
    $candidates += (Join-Path $ProjectRoot "transfer-package\$Name")
    $candidates += (Join-Path $ProjectRoot $Name)

    foreach ($c in $candidates) {
        if ($c -and (Test-Path (Join-Path $c $MarkerFile))) {
            return (Resolve-Path $c).Path
        }
    }
    return $null
}

function Wait-MoodleReady {
    param([int]$TimeoutSec = 240)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    $sawExisting = $false
    $sawFresh = $false
    while ((Get-Date) -lt $deadline) {
        $logs = docker compose logs moodle 2>$null | Out-String
        if ($logs -match "Existing installation detected") { $sawExisting = $true }
        if ($logs -match "First-time CLI install") { $sawFresh = $true }
        if ($logs -match "Starting Apache") {
            if ($sawFresh -and -not $sawExisting) {
                throw "Moodle started a fresh install. Volume snapshot was not applied. Do not use this instance."
            }
            return @{ Existing = $sawExisting; Fresh = $sawFresh }
        }
        Start-Sleep -Seconds 3
    }
    throw "Moodle did not become ready within ${TimeoutSec}s. See: docker compose logs moodle"
}
