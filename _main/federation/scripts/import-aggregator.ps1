# Import Moodle aggregator on an offline Windows PC (no pull / no build).
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
        if (-not (Test-Path -LiteralPath (Join-Path $PackageDir "images\moodle-aggregator-local.tar"))) {
            $PackageDir = Normalize-DirPath (Join-Path $PSScriptRoot "..\transfer-aggregator")
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
    $ImageTar = Join-Path $ImagesDir "moodle-aggregator-local.tar"
    $VolTar = Join-Path $VolumesDir "aggregator_data.tgz"

    if (-not (Test-Path -LiteralPath $ImageTar)) {
        throw ("Missing image file:{0}{1}{0}Copy the full transfer-aggregator folder." -f [Environment]::NewLine, $ImageTar)
    }
    if (-not (Test-Path -LiteralPath (Join-Path $ProjectDir "compose.aggregator.yml"))) {
        throw "Missing project\compose.aggregator.yml"
    }

    Load-DockerImageArchive -Archive $ImageTar
    Assert-ImageExists "moodle-aggregator:local"

    $Target = Join-Path $PackageDir "runtime"
    New-Item -ItemType Directory -Force -Path $Target | Out-Null
    Copy-Item -LiteralPath (Join-Path $ProjectDir "compose.aggregator.yml") -Destination (Join-Path $Target "compose.aggregator.yml") -Force

    $envSrc = Join-Path $ProjectDir ".env.aggregator"
    if (-not (Test-Path -LiteralPath $envSrc)) {
        $envSrc = Join-Path $ProjectDir ".env.aggregator.example"
    }
    if (-not (Test-Path -LiteralPath $envSrc)) {
        throw "Missing project\.env.aggregator and .env.aggregator.example"
    }
    Copy-Item -LiteralPath $envSrc -Destination (Join-Path $Target ".env.aggregator") -Force

    Set-Location -LiteralPath $Target
    $composeArgs = @("compose", "--env-file", ".env.aggregator", "-f", "compose.aggregator.yml")

    Write-Host "==> Creating containers (pull never, no build)..."
    $code = Invoke-DockerCli -DockerArgs ($composeArgs + @("up", "-d", "--no-build", "--pull", "never"))
    if ($code -ne 0) { throw "compose up failed" }

    if (Test-Path -LiteralPath $VolTar) {
        Write-Host "==> Restoring aggregator_data volume..."
        [void](Invoke-DockerCli -DockerArgs ($composeArgs + @("stop")))
        $volName = Get-ComposeVolumeName -LogicalName "aggregator_data" -ComposeArgs $composeArgs
        Invoke-VolumeTar -VolumeName $volName -ArchivePath $VolTar -Mode extract -HelperImage "moodle-aggregator:local"
        $code = Invoke-DockerCli -DockerArgs ($composeArgs + @("up", "-d", "--no-build", "--pull", "never"))
        if ($code -ne 0) { throw "compose up after volume restore failed" }
    }

    $port = "8090"
    foreach ($line in (Get-Content -LiteralPath (Join-Path $Target ".env.aggregator") -ErrorAction SilentlyContinue)) {
        if ($line -match '^\s*AGGREGATOR_PORT\s*=\s*(.+)\s*$') {
            $port = $Matches[1].Trim().Trim('"').Trim("'")
        }
    }
    $health = "http://127.0.0.1:{0}/healthz" -f $port
    Write-Host ("==> Waiting for {0}" -f $health)
    Wait-HttpOk -Url $health -TimeoutSec 90

    Write-Host ("OK: catalog  http://127.0.0.1:{0}/" -f $port)
    Write-Host ("OK: admin    http://127.0.0.1:{0}/admin" -f $port)
    Write-Host ("Working directory: {0}" -f $Target)
    exit 0
}
catch {
    Write-Host ""
    Write-Host ("ERROR: {0}" -f $_.Exception.Message)
    exit 1
}
