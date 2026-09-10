# Shared helpers for offline federation transfer.
# ASCII only. CRLF. Safe for Windows PowerShell 5.1 + cmd.exe.

$ErrorActionPreference = "Stop"

function Normalize-DirPath {
    param([Parameter(Mandatory = $true)][string]$PathValue)
    if ([string]::IsNullOrWhiteSpace($PathValue)) {
        throw "Empty path."
    }
    $full = [System.IO.Path]::GetFullPath($PathValue.Trim().Trim('"'))
    return $full.TrimEnd('\', '/')
}

function Invoke-DockerCli {
    param([Parameter(Mandatory = $true)][string[]]$DockerArgs)
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    # Do not let docker stdout become the function return value.
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
    $parent = Split-Path -Parent $OutFile
    if ($parent) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    Write-Host ("==> docker save {0} -> {1}" -f $Image, $OutFile)
    $code = Invoke-DockerCli -DockerArgs @("save", $Image, "-o", $OutFile)
    if ($code -ne 0) { throw ("docker save failed for {0}" -f $Image) }
    if (-not (Test-Path -LiteralPath $OutFile) -or ((Get-Item -LiteralPath $OutFile).Length -lt 1MB)) {
        throw ("Image archive missing or too small: {0}" -f $OutFile)
    }
}

function Load-DockerImageArchive {
    param([Parameter(Mandatory = $true)][string]$Archive)
    if (-not (Test-Path -LiteralPath $Archive)) {
        throw ("Missing image archive: {0}" -f $Archive)
    }
    Write-Host ("==> docker load -i {0}" -f $Archive)
    $code = Invoke-DockerCli -DockerArgs @("load", "-i", $Archive)
    if ($code -ne 0) { throw ("docker load failed: {0}" -f $Archive) }
}

function Get-ComposeVolumeName {
    param(
        [Parameter(Mandatory = $true)][string]$LogicalName,
        [Parameter(Mandatory = $true)][string[]]$ComposeArgs
    )
    $prev = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $raw = & docker @ComposeArgs config --format json 2>$null
    $code = $LASTEXITCODE
    $ErrorActionPreference = $prev
    if ($code -ne 0 -or [string]::IsNullOrWhiteSpace($raw)) {
        throw "docker compose config failed."
    }
    $cfg = $raw | ConvertFrom-Json
    $vol = $cfg.volumes.$LogicalName
    if (-not $vol -or -not $vol.name) {
        throw ("Compose volume '{0}' not found." -f $LogicalName)
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
    $backupDir = Normalize-DirPath (Split-Path -Parent $ArchivePath)
    $archiveFile = Split-Path -Leaf $ArchivePath
    New-Item -ItemType Directory -Force -Path $backupDir | Out-Null
    Assert-ImageExists $HelperImage

    # Do not use $args - it is a reserved automatic variable in PowerShell.
    if ($Mode -eq "create") {
        $runArgs = @(
            "run", "--rm", "--entrypoint", "tar",
            "-v", ($VolumeName + ":/data:ro"),
            "-v", ($backupDir + ":/backup"),
            $HelperImage,
            "czf", ("/backup/" + $archiveFile), "-C", "/data", "."
        )
    }
    else {
        $runArgs = @(
            "run", "--rm", "--entrypoint", "tar",
            "-v", ($VolumeName + ":/data"),
            "-v", ($backupDir + ":/backup:ro"),
            $HelperImage,
            "xzf", ("/backup/" + $archiveFile), "-C", "/data"
        )
    }
    $code = Invoke-DockerCli -DockerArgs $runArgs
    if ($code -ne 0) {
        throw ("Volume tar {0} failed for {1} ({2})." -f $Mode, $VolumeName, $archiveFile)
    }
}

function Copy-Tree {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )
    if (-not (Test-Path -LiteralPath $Source)) {
        throw ("Missing source: {0}" -f $Source)
    }
    $parent = Split-Path -Parent $Destination
    if ($parent) {
        New-Item -ItemType Directory -Force -Path $parent | Out-Null
    }
    Copy-Item -LiteralPath $Source -Destination $Destination -Recurse -Force
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
                $code = & curl.exe -k -s -o NUL -w "%{http_code}" -- $Url
            }
            else {
                $code = & curl.exe -s -o NUL -w "%{http_code}" -- $Url
            }
            if ($code -eq "200") { return }
        }
        catch {
            # retry until timeout
        }
        Start-Sleep -Seconds 3
    }
    throw ("URL did not return HTTP 200 within {0}s: {1}" -f $TimeoutSec, $Url)
}

function Write-ImportCmd {
    param(
        [Parameter(Mandatory = $true)][string]$PackageRoot,
        [Parameter(Mandatory = $true)][string]$ScriptRelativePath,
        [Parameter(Mandatory = $true)][string]$CmdName
    )
    $cmdPath = Join-Path $PackageRoot $CmdName
    # IMPORTANT: use "%~dp0." not "%~dp0"
    # A trailing backslash before the closing quote breaks PowerShell argument parsing.
    $lines = @(
        "@echo off",
        "setlocal EnableExtensions",
        'cd /d "%~dp0"',
        "echo Starting offline import...",
        ('powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0{0}" -PackageDir "%~dp0."' -f $ScriptRelativePath),
        "set ERR=%ERRORLEVEL%",
        "if not %ERR%==0 (",
        "  echo.",
        "  echo IMPORT FAILED with code %ERR%",
        "  pause",
        "  exit /b %ERR%",
        ")",
        "echo.",
        "echo IMPORT OK",
        "pause"
    )
    $content = ($lines -join "`r`n") + "`r`n"
    [System.IO.File]::WriteAllText($cmdPath, $content, [System.Text.Encoding]::ASCII)
}

function Write-Utf8File {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Content
    )
    $utf8NoBom = New-Object System.Text.UTF8Encoding $false
    [System.IO.File]::WriteAllText($Path, $Content, $utf8NoBom)
}
