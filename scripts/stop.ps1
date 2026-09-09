# Stop stack and optionally remove containers (keeps volumes by default).
# Prefer stop.cmd (bypasses ExecutionPolicy).

param(
    [switch]$RemoveVolumes
)

$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "_common.ps1")

$Root = Get-ComposeRoot -StartDir $PSScriptRoot
Set-Location $Root
Assert-DockerReady

if ($RemoveVolumes) {
    Write-Host "WARNING: removing volumes (all Moodle data will be deleted)..."
    Invoke-Docker -DockerArgs @("compose", "down", "-v")
} else {
    Invoke-Docker -DockerArgs @("compose", "down")
}

Write-Host "Stopped."
