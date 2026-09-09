# Export Moodle aggregator image (+ optional data volume) for offline USB transfer.
# Run on a PC WITH Docker images already built. Does not pull from the internet.

param(
    [string]$OutDir = ".\transfer-aggregator"
)

$ErrorActionPreference = "Stop"
$FedRoot = Split-Path -Parent $PSScriptRoot
Set-Location $FedRoot
. (Join-Path $PSScriptRoot "_offline-lib.ps1")

Assert-DockerReady

$OutDir = [System.IO.Path]::GetFullPath((Join-Path $FedRoot $OutDir))
$ImagesDir = Join-Path $OutDir "images"
$VolumesDir = Join-Path $OutDir "volumes"
$ProjectDir = Join-Path $OutDir "project"
$ScriptsDir = Join-Path $OutDir "scripts"

Write-Host "==> Package: $OutDir"
New-Item -ItemType Directory -Force -Path $ImagesDir, $VolumesDir, $ProjectDir, $ScriptsDir | Out-Null

$code = Invoke-DockerCli -DockerArgs @("image", "inspect", "moodle-aggregator:local")
if ($code -ne 0) {
    Write-Host "==> Building moodle-aggregator:local (export PC only)..."
    $code = Invoke-DockerCli -DockerArgs @("compose", "-f", "compose.aggregator.yml", "build")
    if ($code -ne 0) { throw "build failed" }
}
Assert-ImageExists "moodle-aggregator:local"

Save-DockerImage -Image "moodle-aggregator:local" -OutFile (Join-Path $ImagesDir "moodle-aggregator-local.tar")

Write-Host "==> Copying project files for offline start..."
foreach ($item in @(
    "compose.aggregator.yml",
    ".env.aggregator.example",
    "docs\offline-aggregator.md",
    "docs\web-aggregator.md",
    "docs\operator-guide.md"
)) {
    $src = Join-Path $FedRoot $item
    if (Test-Path $src) {
        $dest = Join-Path $ProjectDir $item
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $dest) | Out-Null
        Copy-Item $src $dest -Force
    }
}
if (Test-Path (Join-Path $FedRoot ".env.aggregator")) {
    Copy-Item (Join-Path $FedRoot ".env.aggregator") (Join-Path $ProjectDir ".env.aggregator") -Force
}
else {
    Copy-Item (Join-Path $FedRoot ".env.aggregator.example") (Join-Path $ProjectDir ".env.aggregator") -Force
}

Copy-Item (Join-Path $PSScriptRoot "_offline-lib.ps1") (Join-Path $ScriptsDir "_offline-lib.ps1") -Force
Copy-Item (Join-Path $PSScriptRoot "import-aggregator.ps1") (Join-Path $ScriptsDir "import-aggregator.ps1") -Force
Write-ImportCmd -PackageRoot $OutDir -ScriptRelativePath "scripts\import-aggregator.ps1" -CmdName "IMPORT-AGGREGATOR.cmd"

$composeArgs = @("compose", "-f", "compose.aggregator.yml")
if (Test-Path (Join-Path $FedRoot ".env.aggregator")) {
    $composeArgs = @("compose", "--env-file", ".env.aggregator", "-f", "compose.aggregator.yml")
}

Write-Host "==> Stopping aggregator for volume snapshot..."
[void](Invoke-DockerCli -DockerArgs ($composeArgs + @("stop")))

try {
    $volName = Get-ComposeVolumeName -LogicalName "aggregator_data" -ComposeArgs $composeArgs
    $code = Invoke-DockerCli -DockerArgs @("volume", "inspect", "-f", "{{.Name}}", $volName)
    if ($code -eq 0) {
        Invoke-VolumeTar -VolumeName $volName `
            -ArchivePath (Join-Path $VolumesDir "aggregator_data.tgz") `
            -Mode create `
            -HelperImage "moodle-aggregator:local"
        Write-Host "    Saved volume $volName"
    }
    else {
        Write-Warning "Volume $volName not found yet; package without server list."
    }
}
finally {
    Write-Host "==> Starting aggregator again on export PC..."
    [void](Invoke-DockerCli -DockerArgs ($composeArgs + @("up", "-d", "--no-build", "--pull", "never")))
}

@(
    "Moodle Aggregator offline package",
    "1. Start Docker Desktop on the target PC.",
    "2. Copy this whole folder to the target PC.",
    "3. Run IMPORT-AGGREGATOR.cmd",
    "4. Open http://127.0.0.1:8090",
    "See project/docs/offline-aggregator.md"
) | Set-Content -Path (Join-Path $OutDir "README.txt") -Encoding UTF8

Write-Host "==> Done: $OutDir"
Get-ChildItem $OutDir -Recurse -File | ForEach-Object {
    Write-Host ("{0}  {1:N2} MB" -f $_.FullName, ($_.Length / 1MB))
}
