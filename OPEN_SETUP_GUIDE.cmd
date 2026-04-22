@echo off
set SCRIPT_DIR=%~dp0
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%OPEN_SETUP_GUIDE.ps1"
if errorlevel 1 (
  echo.
  echo Launcher reported an error. Run manually in PowerShell:
  echo   cd /d "%SCRIPT_DIR%"
  echo   .\OPEN_SETUP_GUIDE.ps1
  pause
)
