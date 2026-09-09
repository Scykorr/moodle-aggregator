# Import Moodle aggregator on an offline Windows PC (no pull / no build).
# ASCII-only script for Windows PowerShell 5.1.

param(
    [string]$PackageDir = ""
)

$ErrorActionPreference = "Stop"

if ($PackageDir) {
    $PackageDir = [System.IO.Path]::GetFullPath($PackageDir)
}
else {
    $PackageDir = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\..\transfer-aggregator"))
    if (-not (Test-Path (Join-Path $PackageDir "IMPORT-AGGREGATOR.cmd"))) {
        $PackageDir = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "..\transfer-aggregator"))
    }
}

. (Join-Path $PSScriptRoot "_offline-lib.ps1")
Assert-DockerReady

$ImagesDir = Join-Path $PackageDir "images"
$VolumesDir = Join-Path $PackageDir "volumes"
$ProjectDir = Join-Path $PackageDir "project"
$ImageTar = Join-Path $ImagesDir "moodle-aggregator-local.tar"
$VolTar = Join-Path $VolumesDir "aggregator_data.tgz"

if (-not (Test-Path $ImageTar)) {
    throw "Missing $ImageTar. Copy the full transfer-aggregator package."
}
if (-not (Test-Path (Join-Path $ProjectDir "compose.aggregator.yml"))) {
    throw "Missing project\compose.aggregator.yml"
}

Load-DockerImageArchive -Archive $ImageTar
Assert-ImageExists "moodle-aggregator:local"

$Target = Join-Path $PackageDir "runtime"
New-Item -ItemType Directory -Force -Path $Target | Out-Null
Copy-Item (Join-Path $ProjectDir "compose.aggregator.yml") (Join-Path $Target "compose.aggregator.yml") -Force
if (Test-Path (Join-Path $ProjectDir ".env.aggregator")) {
    Copy-Item (Join-Path $ProjectDir ".env.aggregator") (Join-Path $Target ".env.aggregator") -Force
}
else {
    Copy-Item (Join-Path $ProjectDir ".env.aggregator.example") (Join-Path $Target ".env.aggregator") -Force
}

Set-Location $Target
$composeArgs = @("compose", "--env-file", ".env.aggregator", "-f", "compose.aggregator.yml")

Write-Host "==> Creating containers (pull never, no build)..."
$code = Invoke-DockerCli -DockerArgs ($composeArgs + @("up", "-d", "--no-build", "--pull", "never"))
if ($code -ne 0) { throw "compose up failed" }

if (Test-Path $VolTar) {
    Write-Host "==> Restoring aggregator_data volume..."
    [void](Invoke-DockerCli -DockerArgs ($composeArgs + @("stop")))
    $volName = Get-ComposeVolumeName -LogicalName "aggregator_data" -ComposeArgs $composeArgs
    Invoke-VolumeTar -VolumeName $volName -ArchivePath $VolTar -Mode extract -HelperImage "moodle-aggregator:local"
    $code = Invoke-DockerCli -DockerArgs ($composeArgs + @("up", "-d", "--no-build", "--pull", "never"))
    if ($code -ne 0) { throw "compose up after volume restore failed" }
}

$port = "8090"
$envFile = Get-Content (Join-Path $Target ".env.aggregator") -ErrorAction SilentlyContinue
foreach ($line in $envFile) {
    if ($line -match '^\s*AGGREGATOR_PORT\s*=\s*(.+)\s*$') { $port = $Matches[1].Trim() }
}
$health = "http://127.0.0.1:$port/healthz"
Write-Host "==> Waiting for $health"
Wait-HttpOk -Url $health -TimeoutSec 90

Write-Host "OK: aggregator is up at http://127.0.0.1:$port"
Write-Host "Working directory: $Target"
