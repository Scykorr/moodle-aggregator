# Stop stack and optionally remove containers (keeps volumes by default).

param(
    [switch]$RemoveVolumes
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

if ($RemoveVolumes) {
    Write-Host "WARNING: removing volumes (all Moodle data will be deleted)..."
    docker compose down -v
} else {
    docker compose down
}

Write-Host "Stopped."
