# Import Moodle images and start stack on an offline target PC.
# Prefer import-and-start.cmd (bypasses ExecutionPolicy).

param(
    [string]$PackageDir = ""
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")

$Root = Get-ComposeRoot -StartDir $PSScriptRoot
Set-Location $Root

Assert-DockerReady

function Find-ImagesDir {
    param(
        [string]$Root,
        [string]$PackageDir
    )
    $need = @("moodle-offline-5.2.tar", "mariadb-11.4.tar")
    $candidates = New-Object System.Collections.Generic.List[string]

    if ($PackageDir) {
        $PackageDir = $PackageDir.Trim().Trim('"')
        if (-not [IO.Path]::IsPathRooted($PackageDir)) {
            $PackageDir = [IO.Path]::GetFullPath((Join-Path (Get-Location) $PackageDir))
        }
        $candidates.Add($PackageDir)
        $candidates.Add((Join-Path $PackageDir "images"))
        $candidates.Add((Join-Path $PackageDir "transfer-package"))
        $candidates.Add((Join-Path $PackageDir "transfer-package\images"))
        $candidates.Add((Join-Path $PackageDir "project\..\images"))
    }

    $walk = $Root
    for ($i = 0; $i -lt 4; $i++) {
        $candidates.Add((Join-Path $walk "images"))
        $candidates.Add((Join-Path $walk "transfer-package\images"))
        $parent = Split-Path $walk
        if (-not $parent -or $parent -eq $walk) {
            break
        }
        $walk = $parent
        $candidates.Add((Join-Path $walk "images"))
    }

    $seen = @{}
    foreach ($c in $candidates) {
        if (-not $c) { continue }
        try {
            $full = [IO.Path]::GetFullPath($c)
        } catch {
            continue
        }
        if ($seen.ContainsKey($full)) { continue }
        $seen[$full] = $true
        $ok = $true
        foreach ($name in $need) {
            if (-not (Test-NonEmptyImageTar (Join-Path $full $name))) {
                $ok = $false
                break
            }
        }
        if ($ok) {
            return $full
        }
    }
    return $null
}

$ImagesDir = Find-ImagesDir -Root $Root -PackageDir $PackageDir
if (-not $ImagesDir) {
    throw @"
Image archives not found or too small (empty/corrupt tar).
Need both:
  moodle-offline-5.2.tar
  mariadb-11.4.tar
Place them in transfer-package\images next to the project folder, or pass -PackageDir.
"@
}

Write-Host "==> Loading images from $ImagesDir"
$mariadbTar = [IO.Path]::GetFullPath((Join-Path $ImagesDir "mariadb-11.4.tar"))
$moodleTar = [IO.Path]::GetFullPath((Join-Path $ImagesDir "moodle-offline-5.2.tar"))
Import-DockerImageTar -TarPath $mariadbTar -Name "mariadb" -Tag "11.4"
Import-DockerImageTar -TarPath $moodleTar -Name "moodle-offline" -Tag "5.2"

$envFile = Join-Path $Root ".env"
$example = Join-Path $Root ".env.example"
if (-not (Test-Path -LiteralPath $envFile)) {
    if (-not (Test-Path -LiteralPath $example)) {
        throw "Missing .env and .env.example in $Root"
    }
    Copy-Item -LiteralPath $example -Destination $envFile
    Write-Host "Created .env from .env.example -- set MOODLE_WWWROOT before first use."
}

$env:COMPOSE_BAKE = "false"
$upArgs = @("compose", "up", "-d", "--no-build")
$composeHelp = & docker compose up --help 2>&1 | Out-String
if ($composeHelp -match "--pull") {
    $upArgs += @("--pull", "never")
}

Write-Host "==> Starting Moodle stack (loaded images, no rebuild)..."
Invoke-Docker -DockerArgs $upArgs

Write-Host "==> Status:"
Invoke-Docker -DockerArgs @("compose", "ps")
Write-Host ""
Write-Host "Open MoodleConfigurator.exe to set LAN IP (wwwroot), then open http://<IP>/ in browsers on the LAN."
