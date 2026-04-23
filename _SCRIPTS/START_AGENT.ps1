Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
.\.venv\Scripts\Activate.ps1

# Kill any stale instances before starting
Get-WmiObject Win32_Process | Where-Object {
    $_.Name -like "python*" -and $_.CommandLine -like "*agent.main*"
} | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
Start-Sleep -Milliseconds 500

$py = "$root\.venv\Scripts\python.exe"

# Start agent, dashboard, vault
$agent = Start-Process -FilePath $py -ArgumentList "-m","agent.main" -WorkingDirectory $root -WindowStyle Hidden -PassThru
$dash  = Start-Process -FilePath $py -ArgumentList "dashboard_server.py","--mgmt" -WorkingDirectory $root -WindowStyle Hidden -PassThru
$vault = Start-Process -FilePath $py -ArgumentList "-m","uvicorn","vault_mgmt.app:app","--host","127.0.0.1","--port","8010" -WorkingDirectory $root -WindowStyle Hidden -PassThru

# Start Cloudflare tunnel for mobile access
$tunnel = Start-Process -FilePath "cloudflared" `
  -ArgumentList "tunnel","--url","http://localhost:7731","--no-autoupdate" `
  -WorkingDirectory $root -WindowStyle Hidden `
  -RedirectStandardOutput "$root\logs\tunnel.log" `
  -RedirectStandardError "$root\logs\tunnel_err.log" `
  -PassThru

Start-Sleep -Seconds 10
$url = Select-String -Path "$root\logs\tunnel_err.log" -Pattern "https://.*trycloudflare\.com" |
       Select-Object -Last 1 | ForEach-Object { $_.Matches[0].Value }

Write-Host ""
Write-Host "=== POLY AGENT MERLIN STARTED ===" -ForegroundColor Cyan
Write-Host "Agent PID:     $($agent.Id)"
Write-Host "Dashboard PID: $($dash.Id)"
Write-Host "Vault PID:     $($vault.Id)"
Write-Host "Tunnel PID:    $($tunnel.Id)"
Write-Host ""
Write-Host "Local:   http://localhost:7731/mgmt" -ForegroundColor Green
Write-Host "WiFi:    http://192.168.4.106:7731/mgmt" -ForegroundColor Green
if ($url) {
    Write-Host "Mobile:  $url/mgmt" -ForegroundColor Yellow
} else {
    Write-Host "Mobile:  check logs\tunnel_err.log for URL" -ForegroundColor Yellow
}
Write-Host ""
