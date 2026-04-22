Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

function Find-UsablePython {
  $candidates = @()
  try {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Path -notlike '*WindowsApps*') {
      $candidates += $cmd.Path
    }
  } catch {}
  $candidates += @(
    'C:\Users\thedo\AppData\Local\Programs\Python\Python312\python.exe',
    'C:\Users\thedo\AppData\Local\Programs\Python\Python311\python.exe',
    'C:\Users\thedo\AppData\Local\Programs\Python\Python310\python.exe',
    'C:\Program Files\Python312\python.exe',
    'C:\Program Files\Python311\python.exe',
    'C:\Program Files\Python310\python.exe'
  )
  foreach ($candidate in ($candidates | Select-Object -Unique)) {
    if (-not (Test-Path $candidate)) { continue }
    try {
      $out = & $candidate --version 2>&1
      if ($LASTEXITCODE -eq 0 -and $out -match 'Python\s+3') {
        return $candidate
      }
    } catch {}
  }
  return $null
}

$pythonExe = Find-UsablePython
if (-not $pythonExe) {
  winget install -e --id Python.Python.3.12 --scope user --accept-source-agreements --accept-package-agreements
  $pythonExe = Find-UsablePython
  if (-not $pythonExe) {
    Write-Host "Python install did not become available in this session yet." -ForegroundColor Yellow
    Write-Host "Close PowerShell, reopen it, and run .\\SETUP_FIRST_TIME.ps1 again."
    exit 1
  }
}

& $pythonExe -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt

if (-not (Test-Path ".env")) {
  Copy-Item ".env.example" ".env"
  Write-Host ".env created from template. Fill in your account values before live use."
}

Write-Host "Setup complete."
