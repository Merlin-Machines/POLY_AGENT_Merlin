@echo off
set SCRIPT_DIR=%~dp0
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%SETUP_FIRST_TIME.ps1"
pause
