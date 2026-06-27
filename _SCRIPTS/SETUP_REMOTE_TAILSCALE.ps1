Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host ""
Write-Host "=== ONE-TIME REMOTE SETUP (Tailscale - private) ===" -ForegroundColor Cyan
Write-Host "Gives you a permanent https URL reachable ONLY by your own devices." -ForegroundColor Cyan
Write-Host "No public internet exposure. Install the Tailscale app on your phone too." -ForegroundColor Cyan
Write-Host ""

# ---------------------------------------------------------------------------
# 1. Install Tailscale if it isn't already on PATH.
# ---------------------------------------------------------------------------
$ts = Get-Command tailscale -ErrorAction SilentlyContinue
if (-not $ts) {
    Write-Host "[1/4] Tailscale not found - installing via winget..." -ForegroundColor Yellow
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        winget install --id Tailscale.Tailscale -e --accept-source-agreements --accept-package-agreements
    } else {
        Write-Host "      winget is not available. Install Tailscale manually:" -ForegroundColor Red
        Write-Host "      https://tailscale.com/download/windows" -ForegroundColor Red
        Write-Host "      Then re-run this script." -ForegroundColor Red
        return
    }
    # winget puts tailscale in Program Files; refresh this session's PATH.
    $env:Path += ";$env:ProgramFiles\Tailscale"
    $ts = Get-Command tailscale -ErrorAction SilentlyContinue
    if (-not $ts) {
        Write-Host "      Installed, but 'tailscale' still not on PATH." -ForegroundColor Red
        Write-Host "      Close and reopen PowerShell, then re-run this script." -ForegroundColor Red
        return
    }
} else {
    Write-Host "[1/4] Tailscale already installed." -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# 2. Log in / bring the node up (opens a browser the first time).
# ---------------------------------------------------------------------------
Write-Host "[2/4] Logging in to Tailscale (a browser window may open)..." -ForegroundColor Yellow
tailscale up

# ---------------------------------------------------------------------------
# 3. Serve the dashboard port (7731) privately inside your tailnet.
#    No public exposure; only devices logged into your account can reach it.
# ---------------------------------------------------------------------------
Write-Host "[3/4] Serving port 7731 privately (tailnet only)..." -ForegroundColor Yellow
Write-Host "      If you see an 'HTTPS is not enabled' link, open it and enable" -ForegroundColor Yellow
Write-Host "      MagicDNS + HTTPS for your tailnet, then re-run this script." -ForegroundColor Yellow
tailscale serve --bg 7731

# ---------------------------------------------------------------------------
# 4. Show the permanent URL.
# ---------------------------------------------------------------------------
$url = $null
try {
    $dns = (& tailscale status --json 2>$null | ConvertFrom-Json).Self.DNSName
    if ($dns) { $url = "https://" + $dns.TrimEnd('.') }
} catch { $url = $null }

Write-Host ""
if ($url) {
    Write-Host "[4/4] DONE. Your permanent private URL is:" -ForegroundColor Green
    Write-Host "      $url/mgmt" -ForegroundColor Green
    Write-Host ""
    Write-Host "      Bookmark it on your phone and desktop. It will not change." -ForegroundColor Green
    Write-Host "      The phone must have the Tailscale app installed and logged in" -ForegroundColor Green
    Write-Host "      to the same account, and be connected." -ForegroundColor Green
    New-Item -ItemType Directory -Force -Path "$root\logs" | Out-Null
    Set-Content -Path "$root\logs\remote_url.txt" -Value $url -NoNewline -Encoding ASCII
} else {
    Write-Host "[4/4] Serve set, but the URL didn't resolve yet." -ForegroundColor Yellow
    Write-Host "      Run 'tailscale serve status' to see it." -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# Note: private serve is reachable only by your own tailnet devices, so a
# password is optional here. It is still supported as defense-in-depth.
# ---------------------------------------------------------------------------
$hasPassword = $false
if (Test-Path "$root\.env") {
    $hasPassword = (Select-String -Path "$root\.env" -Pattern "^\s*MGMT_PASSWORD\s*=\s*\S" -Quiet)
}
Write-Host ""
if ($hasPassword) {
    Write-Host "Password protection: ENABLED (log in with any username + MGMT_PASSWORD)." -ForegroundColor Green
} else {
    Write-Host "Password protection: off. Fine for private mode - only your own" -ForegroundColor Green
    Write-Host "devices on the tailnet can reach the URL. Set MGMT_PASSWORD in .env" -ForegroundColor Green
    Write-Host "if you want an extra login on top." -ForegroundColor Green
}
Write-Host ""
