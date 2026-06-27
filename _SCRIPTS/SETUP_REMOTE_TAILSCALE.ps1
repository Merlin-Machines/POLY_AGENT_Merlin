Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host ""
Write-Host "=== ONE-TIME REMOTE SETUP (Tailscale Funnel) ===" -ForegroundColor Cyan
Write-Host "This gives you a permanent https URL for desktop + phone." -ForegroundColor Cyan
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
# 3. Turn on Funnel for the dashboard port (7731).
#    The first run prints a link if Funnel/HTTPS isn't enabled for the tailnet.
# ---------------------------------------------------------------------------
Write-Host "[3/4] Enabling Funnel for port 7731..." -ForegroundColor Yellow
Write-Host "      If you see a 'Funnel is not enabled' link, open it, click through" -ForegroundColor Yellow
Write-Host "      to enable Funnel + HTTPS for your tailnet, then re-run this script." -ForegroundColor Yellow
tailscale funnel --bg 7731

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
    Write-Host "[4/4] DONE. Your permanent remote URL is:" -ForegroundColor Green
    Write-Host "      $url/mgmt" -ForegroundColor Green
    Write-Host ""
    Write-Host "      Bookmark it on your phone and desktop. It will not change." -ForegroundColor Green
    New-Item -ItemType Directory -Force -Path "$root\logs" | Out-Null
    Set-Content -Path "$root\logs\remote_url.txt" -Value $url -NoNewline -Encoding ASCII
} else {
    Write-Host "[4/4] Funnel set, but the URL didn't resolve yet." -ForegroundColor Yellow
    Write-Host "      Run 'tailscale funnel status' to see it." -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# Reminder: protect the live trading controls with a password.
# ---------------------------------------------------------------------------
$hasPassword = $false
if (Test-Path "$root\.env") {
    $hasPassword = (Select-String -Path "$root\.env" -Pattern "^\s*MGMT_PASSWORD\s*=\s*\S" -Quiet)
}
Write-Host ""
if (-not $hasPassword) {
    Write-Host "IMPORTANT: Funnel is public. Set MGMT_PASSWORD=yourpassword in .env" -ForegroundColor Red
    Write-Host "           before exposing the live trading controls." -ForegroundColor Red
} else {
    Write-Host "Password protection: ENABLED (log in with any username + MGMT_PASSWORD)." -ForegroundColor Green
}
Write-Host ""
