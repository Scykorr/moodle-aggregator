# Shared helpers for Moodle offline transfer scripts (Windows PowerShell 5.1+).
$ErrorActionPreference = "Stop"
if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
    $PSNativeCommandUseErrorActionPreference = $false
}

function Add-DockerToPath {
    if (Get-Command docker -ErrorAction SilentlyContinue) {
        return
    }
    $candidates = @(
        (Join-Path $env:ProgramFiles "Docker\Docker\resources\bin")
    )
    if (${env:ProgramFiles(x86)}) {
        $candidates += (Join-Path ${env:ProgramFiles(x86)} "Docker\Docker\resources\bin")
    }
    foreach ($dir in $candidates) {
        if ($dir -and (Test-Path -LiteralPath (Join-Path $dir "docker.exe"))) {
            $env:Path = "$dir;$env:Path"
            return
        }
    }
}

function Invoke-Docker {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$DockerArgs
    )
    & docker @DockerArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed (exit $LASTEXITCODE): docker $($DockerArgs -join ' ')"
    }
}

function Assert-DockerReady {
    Add-DockerToPath
    if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
        throw "Docker not found. Install Docker Desktop and reopen the terminal."
    }
    & docker info --format "{{.ServerVersion}}" 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker daemon is not running. Start Docker Desktop and wait until it is ready."
    }
    & docker compose version 1>$null 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Docker Compose v2 is not available. Update Docker Desktop so that 'docker compose' works."
    }
}

function Get-ComposeRoot {
    param([string]$StartDir = $PSScriptRoot)
    $walk = $StartDir
    for ($i = 0; $i -lt 6; $i++) {
        if ($walk -and (Test-Path -LiteralPath (Join-Path $walk "docker-compose.yml"))) {
            return $walk
        }
        $parent = Split-Path $walk
        if (-not $parent -or $parent -eq $walk) {
            break
        }
        $walk = $parent
    }
    throw "docker-compose.yml not found near $StartDir. Run the script from transfer-package\project\scripts."
}

function Test-NonEmptyImageTar {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        return $false
    }
    return ((Get-Item -LiteralPath $Path).Length -gt 1MB)
}

function Ensure-ImageTag {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$Tag
    )
    $want = "${Name}:${Tag}"
    & docker image inspect $want 1>$null 2>$null
    if ($LASTEXITCODE -eq 0) {
        return
    }

    $listed = & docker images --format "{{.Repository}}:{{.Tag}}"
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to list Docker images while looking for $want."
    }

    $match = $listed | Where-Object {
        $_ -eq $want -or
        $_ -eq "docker.io/library/${want}" -or
        $_ -eq "docker.io/${want}" -or
        $_ -like "*/${Name}:${Tag}"
    } | Select-Object -First 1

    if ($match) {
        Write-Host "    tagging $match -> $want"
        Invoke-Docker -DockerArgs @("tag", $match, $want)
        return
    }

    throw "Required image '$want' is missing (wrong name/tag after docker load). Run 'docker images'."
}

function Import-DockerImageTar {
    param(
        [Parameter(Mandatory = $true)]
        [string]$TarPath,
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [Parameter(Mandatory = $true)]
        [string]$Tag
    )
    $want = "${Name}:${Tag}"
    $TarPath = [IO.Path]::GetFullPath($TarPath)
    Write-Host "    docker load -i $TarPath"
    $raw = & docker load -i $TarPath 2>&1
    $code = $LASTEXITCODE
    $output = @($raw | ForEach-Object { "$_" })
    foreach ($line in $output) {
        Write-Host "    $line"
    }
    if ($code -ne 0) {
        throw "docker load failed (exit $code): $TarPath"
    }
    $loaded = @()
    foreach ($line in $output) {
        $text = "$line"
        if ($text -match "Loaded image:\s*(.+?)\s*$") {
            $loaded += $Matches[1].Trim()
        }
    }
    foreach ($img in $loaded) {
        if ($img -and $img -ne $want) {
            Write-Host "    tagging $img -> $want"
            Invoke-Docker -DockerArgs @("tag", $img, $want)
        }
    }
    Ensure-ImageTag -Name $Name -Tag $Tag
}

