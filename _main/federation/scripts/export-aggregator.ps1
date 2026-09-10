# Export Moodle aggregator image (+ optional data volume) for offline USB transfer.
# ASCII only. Safe for Windows PowerShell 5.1.

param(
    [string]$OutDir = ".\transfer-aggregator"
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

    $code = Invoke-DockerCli -DockerArgs @("image", "inspect", "-f", "{{.Id}}", "moodle-aggregator:local")
    if ($code -ne 0) {
        Write-Host "==> Building moodle-aggregator:local (export PC only)..."
        $code = Invoke-DockerCli -DockerArgs @("compose", "-f", "compose.aggregator.yml", "build")
        if ($code -ne 0) { throw "build failed" }
    }
    Assert-ImageExists "moodle-aggregator:local"

    Save-DockerImage -Image "moodle-aggregator:local" -OutFile (Join-Path $ImagesDir "moodle-aggregator-local.tar")

    Write-Host "==> Copying project files for offline start..."
    $copyList = @(
        "compose.aggregator.yml",
        ".env.aggregator.example",
        "docs\offline-aggregator.md",
        "docs\web-aggregator.md",
        "docs\operator-guide.md",
        "docs\multi-moodle-accounts.md"
    )
    foreach ($item in $copyList) {
        $src = Join-Path $FedRoot $item
        if (Test-Path -LiteralPath $src) {
            $dest = Join-Path $ProjectDir $item
            $parent = Split-Path -Parent $dest
            if ($parent) {
                New-Item -ItemType Directory -Force -Path $parent | Out-Null
            }
            Copy-Item -LiteralPath $src -Destination $dest -Force
        }
    }

    if (Test-Path -LiteralPath (Join-Path $FedRoot ".env.aggregator")) {
        Copy-Item -LiteralPath (Join-Path $FedRoot ".env.aggregator") -Destination (Join-Path $ProjectDir ".env.aggregator") -Force
    }
    else {
        Copy-Item -LiteralPath (Join-Path $FedRoot ".env.aggregator.example") -Destination (Join-Path $ProjectDir ".env.aggregator") -Force
    }

    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "_offline-lib.ps1") -Destination (Join-Path $ScriptsDir "_offline-lib.ps1") -Force
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot "import-aggregator.ps1") -Destination (Join-Path $ScriptsDir "import-aggregator.ps1") -Force
    Write-ImportCmd -PackageRoot $OutDir -ScriptRelativePath "scripts\import-aggregator.ps1" -CmdName "IMPORT-AGGREGATOR.cmd"

    $composeArgs = @("compose", "-f", "compose.aggregator.yml")
    if (Test-Path -LiteralPath (Join-Path $FedRoot ".env.aggregator")) {
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
            Write-Host ("    Saved volume {0}" -f $volName)
        }
        else {
            Write-Warning ("Volume {0} not found yet; package without catalog data." -f $volName)
        }
    }
    finally {
        Write-Host "==> Starting aggregator again on export PC..."
        [void](Invoke-DockerCli -DockerArgs ($composeArgs + @("up", "-d", "--no-build", "--pull", "never")))
    }

    $readme = @(
        "Moodle Aggregator offline package",
        "1. Start Docker Desktop on the target PC.",
        "2. Copy this whole folder to the target PC.",
        "3. Double-click IMPORT-AGGREGATOR.cmd",
        "4. Catalog (students): http://127.0.0.1:8090/",
        "5. Admin (edit + checks): http://127.0.0.1:8090/admin",
        "See project/docs/offline-aggregator.md"
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
