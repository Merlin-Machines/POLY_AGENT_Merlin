Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

if (-not (Test-Path ".\.venv\Scripts\Activate.ps1")) {
  Write-Host "Missing virtual environment. Run .\SETUP_FIRST_TIME.ps1 first."
  exit 1
}

.\.venv\Scripts\Activate.ps1
python .\_TOOLS\verify_env_link.py
