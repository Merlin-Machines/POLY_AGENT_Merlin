Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
.\.venv\Scripts\Activate.ps1
python dashboard_server.py --mgmt
