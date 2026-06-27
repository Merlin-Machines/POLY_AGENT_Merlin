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

# Make sure logs\ exists before Start-Process tries to redirect into it.
New-Item -ItemType Directory -Force -Path "$root\logs" | Out-Null

# Warn loudly if the remote control surface has no password. The tunnel below
# publishes the LIVE trading controls to the public internet.
$hasPassword = $false
if (Test-Path "$root\.env") {
    $hasPassword = (Select-String -Path "$root\.env" -Pattern "^\s*MGMT_PASSWORD\s*=\s*\S" -Quiet)
}
if (-not $hasPassword) {
    Write-Host "WARNING: MGMT_PASSWORD is not set in .env." -ForegroundColor Red
    Write-Host "         The public tunnel will expose the live trading controls with NO password." -ForegroundColor Red
    Write-Host "         Add MGMT_PASSWORD=yourpassword to .env and re-run to protect it." -ForegroundColor Red
    Write-Host ""
}

# Start agent, dashboard, vault
$agent = Start-Process -FilePath $py -ArgumentList "-m","agent.main" -WorkingDirectory $root -WindowStyle Hidden -PassThru
$dash  = Start-Process -FilePath $py -ArgumentList "dashboard_server.py","--mgmt" -WorkingDirectory $root -WindowStyle Hidden -PassThru
$vault = Start-Process -FilePath $py -ArgumentList "-m","uvicorn","vault_mgmt.app:app","--host","127.0.0.1","--port","8010" -WorkingDirectory $root -WindowStyle Hidden -PassThru

# Start Cloudflare tunnel for remote (desktop + mobile, anywhere) access
$tunnel = Start-Process -FilePath "cloudflared" `
  -ArgumentList "tunnel","--url","http://localhost:7731","--no-autoupdate" `
  -WorkingDirectory $root -WindowStyle Hidden `
  -RedirectStandardOutput "$root\logs\tunnel.log" `
  -RedirectStandardError "$root\logs\tunnel_err.log" `
  -PassThru

# The tunnel URL can take several seconds to appear; poll instead of a fixed wait.
$url = $null
for ($i = 0; $i -lt 30; $i++) {
    Start-Sleep -Seconds 1
    if (Test-Path "$root\logs\tunnel_err.log") {
        $m = Select-String -Path "$root\logs\tunnel_err.log" -Pattern "https://[a-z0-9-]+\.trycloudflare\.com" -ErrorAction SilentlyContinue |
             Select-Object -Last 1
        if ($m) { $url = $m.Matches[0].Value; break }
    }
}

# Persist the public URL so the dashboard can surface it too.
if ($url) {
    Set-Content -Path "$root\logs\remote_url.txt" -Value $url -NoNewline -Encoding ASCII
} elseif (Test-Path "$root\logs\remote_url.txt") {
    Remove-Item "$root\logs\remote_url.txt" -ErrorAction SilentlyContinue
}

# Auto-detect the LAN IP for the "same WiFi" URL (no hard-coded address).
$wifiIp = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -ne "127.0.0.1" -and $_.IPAddress -notlike "169.254.*" -and $_.PrefixOrigin -eq "Dhcp" } |
    Select-Object -First 1 -ExpandProperty IPAddress)
if (-not $wifiIp) {
    $wifiIp = (Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
        Where-Object { $_.IPAddress -ne "127.0.0.1" -and $_.IPAddress -notlike "169.254.*" } |
        Select-Object -First 1 -ExpandProperty IPAddress)
}
if (-not $wifiIp) { $wifiIp = "localhost" }

Write-Host ""
Write-Host "=== POLY AGENT MERLIN STARTED ===" -ForegroundColor Cyan
Write-Host "Agent PID:     $($agent.Id)"
Write-Host "Dashboard PID: $($dash.Id)"
Write-Host "Vault PID:     $($vault.Id)"
Write-Host "Tunnel PID:    $($tunnel.Id)"
Write-Host ""
Write-Host "Local:   http://localhost:7731/mgmt" -ForegroundColor Green
Write-Host "WiFi:    http://${wifiIp}:7731/mgmt" -ForegroundColor Green
if ($url) {
    Write-Host "Remote:  $url/mgmt" -ForegroundColor Yellow
    Write-Host "         ^ open this on your phone AND desktop to connect from anywhere" -ForegroundColor Yellow
} else {
    Write-Host "Remote:  tunnel URL not ready yet - check logs\tunnel_err.log" -ForegroundColor Yellow
}
if ($hasPassword) {
    Write-Host "Login:   any username + your MGMT_PASSWORD from .env" -ForegroundColor Green
} else {
    Write-Host "Login:   NONE - remote controls are UNPROTECTED (set MGMT_PASSWORD)" -ForegroundColor Red
}
Write-Host ""
