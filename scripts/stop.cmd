@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop.ps1" %*
set ERR=%ERRORLEVEL%
if not %ERR%==0 (
  echo.
  echo Stop failed with exit code %ERR%.
  pause
)
exit /b %ERR%
