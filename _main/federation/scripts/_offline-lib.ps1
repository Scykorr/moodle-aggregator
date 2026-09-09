# Shared helpers for offline federation (aggregator / Keycloak) transfer.
# Keep this file ASCII-only (Windows PowerShell 5.1 encoding).

$ErrorActionPreference = "Stop"

function Invoke-DockerCli {
    param([Parameter(Mandatory = $true)][string[]]$DockerArgs)
    # Docker progress goes to stderr; with $ErrorActionPreference=Stop that becomes terminating.
    # Pipe through Out-Host so stdout does not become the function return value.
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    & docker @DockerArgs 2>&1 | ForEach-Object { Write-Host $_ }
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prev
    return [int]$code
}

function Assert-DockerReady {
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker not found in PATH. Start Docker Desktop."
    }
    $code = Invoke-DockerCli -DockerArgs @("info", "-f", "{{.ServerVersion}}")
    if ($code -ne 0) {
        throw "Docker Desktop is not running (docker info failed)."
    }
}

function Assert-ImageExists {
    param([Parameter(Mandatory = $true)][string]$Image)
    $code = Invoke-DockerCli -DockerArgs @("image", "inspect", "-f", "{{.Id}}", $Image)
    if ($code -ne 0) {
        throw "Image $Image not found. Build/start the stack on a networked PC first."
    }
}

function Save-DockerImage {
    param(
        [Parameter(Mandatory = $true)][string]$Image,
        [Parameter(Mandatory = $true)][string]$OutFile
    )
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $OutFile) | Out-Null
    Write-Host "==> docker save $Image -> $OutFile"
    $code = Invoke-DockerCli -DockerArgs @("save", $Image, "-o", $OutFile)
    if ($code -ne 0) { throw "docker save failed for $Image" }
    if (-not (Test-Path $OutFile) -or (Get-Item $OutFile).Length -lt 1MB) {
        throw "Image archive missing or too small: $OutFile"
    }
}

function Load-DockerImageArchive {
    param([Parameter(Mandatory = $true)][string]$Archive)
    if (-not (Test-Path $Archive)) { throw "Missing image archive: $Archive" }
    Write-Host "==> docker load -i $Archive"
    $code = Invoke-DockerCli -DockerArgs @("load", "-i", $Archive)
    if ($code -ne 0) { throw "docker load failed: $Archive" }
}

function Get-ComposeVolumeName {
    param(
        [Parameter(Mandatory = $true)][string]$LogicalName,
        [Parameter(Mandatory = $true)][string[]]$ComposeArgs
    )
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $raw = & docker @ComposeArgs config --format json
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prev
    if ($code -ne 0 -or -not $raw) {
        throw "docker compose config failed."
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
        [Parameter(Mandatory = $true)][ValidateSet("create", "extract")][string]$Mode,
        [Parameter(Mandatory = $true)][string]$HelperImage
    )
    $backupDir = [System.IO.Path]::GetFullPath((Split-Path -Parent $ArchivePath))
    $archiveFile = Split-Path -Leaf $ArchivePath
    New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
    Assert-ImageExists $HelperImage

    if ($Mode -eq "create") {
        $args = @(
            "run", "--rm", "--entrypoint", "tar",
            "-v", "${VolumeName}:/data:ro",
            "-v", "${backupDir}:/backup",
            $HelperImage,
            "czf", "/backup/$archiveFile", "-C", "/data", "."
        )
    }
    else {
        $args = @(
            "run", "--rm", "--entrypoint", "tar",
            "-v", "${VolumeName}:/data",
            "-v", "${backupDir}:/backup:ro",
            $HelperImage,
            "xzf", "/backup/$archiveFile", "-C", "/data"
        )
    }
    $code = Invoke-DockerCli -DockerArgs $args
    if ($code -ne 0) {
        throw "Volume tar $Mode failed for $VolumeName ($archiveFile)."
    }
}

function Copy-Tree {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )
    if (-not (Test-Path $Source)) { throw "Missing source: $Source" }
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $Destination) | Out-Null
    Copy-Item -Path $Source -Destination $Destination -Recurse -Force
}

function Wait-HttpOk {
    param(
        [Parameter(Mandatory = $true)][string]$Url,
        [int]$TimeoutSec = 120,
        [switch]$SkipCertCheck
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        try {
            if ($SkipCertCheck) {
                $code = & curl.exe -k -s -o NUL -w "%{http_code}" $Url
                if ($code -eq "200") { return }
            }
            else {
                $code = & curl.exe -s -o NUL -w "%{http_code}" $Url
                if ($code -eq "200") { return }
            }
        }
        catch { }
        Start-Sleep -Seconds 3
    }
    throw "URL did not return HTTP 200 within ${TimeoutSec}s: $Url"
}

function Write-ImportCmd {
    param(
        [Parameter(Mandatory = $true)][string]$PackageRoot,
        [Parameter(Mandatory = $true)][string]$ScriptRelativePath,
        [Parameter(Mandatory = $true)][string]$CmdName
    )
    $cmdPath = Join-Path $PackageRoot $CmdName
    @(
        "@echo off",
        "setlocal",
        'cd /d "%~dp0"',
        ("powershell -NoProfile -ExecutionPolicy Bypass -File `"%~dp0{0}`" -PackageDir `"%~dp0`"" -f $ScriptRelativePath),
        "if errorlevel 1 pause"
    ) | Set-Content -Path $cmdPath -Encoding ASCII
}
