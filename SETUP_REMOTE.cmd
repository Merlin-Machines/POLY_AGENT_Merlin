@echo off
REM Double-click this once to set up private remote access (Tailscale).
REM It installs Tailscale, logs you in, and prints your permanent URL.
set SCRIPT_DIR=%~dp0
powershell -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%_SCRIPTS\SETUP_REMOTE_TAILSCALE.ps1"
pause
