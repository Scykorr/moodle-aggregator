@echo off
cd /d "%~dp0.."
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0import-and-start.ps1" %*
if errorlevel 1 (
  echo.
  echo IMPORT FAILED.
  pause
  exit /b 1
)
