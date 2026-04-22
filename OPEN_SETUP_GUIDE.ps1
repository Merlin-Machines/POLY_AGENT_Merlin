Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
$root = $PSScriptRoot
Set-Location $root

try {
  if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env" -ErrorAction Stop
  }

  $guide = Join-Path $root "_GUIDES\ENV_SETUP_QUICK_GUIDE.txt"
  $auth = Join-Path $root "_GUIDES\Polymarkey Authentication.txt"
  $envf = Join-Path $root ".env"

  foreach ($f in @($guide, $envf, $auth)) {
    if (-not (Test-Path $f)) {
      throw "Missing expected file: $f"
    }
  }

  Start-Process notepad.exe $guide
  Start-Process notepad.exe $envf
  Start-Process notepad.exe $auth
  Write-Host "Opened setup guide + .env + Polymarket auth notes."
}
catch {
  Write-Host "OPEN_SETUP_GUIDE failed: $($_.Exception.Message)" -ForegroundColor Red
  Write-Host "Try running this in PowerShell from the folder:" -ForegroundColor Yellow
  Write-Host ".\OPEN_SETUP_GUIDE.ps1"
  Read-Host "Press Enter to close"
}
