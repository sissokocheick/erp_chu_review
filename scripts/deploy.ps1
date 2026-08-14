# ==========================================================================
#  deploy.ps1 - Deployment of NexusERP (Windows PowerShell)
#
#  Pipeline : env validation -> migrate -> collectstatic -> check --deploy -> server
#
#  Usage :
#    .\scripts\deploy.ps1                 # everything + start server
#    .\scripts\deploy.ps1 -Check          # validate env + check --deploy, no server
#    .\scripts\deploy.ps1 -Backup         # PostgreSQL backup before migrate
#    .\scripts\deploy.ps1 -NoMigrate -NoCollectstatic
#    .\scripts\deploy.ps1 -Port 8080 -Workers 4 -Foreground
#
#  A .env file at the project root is loaded automatically (without
#  overriding already-set variables). See .env.example and PRODUCTION.md.
#
#  NOTE : gunicorn is not natively supported on Windows. The script uses
#  gunicorn when available, otherwise it falls back to waitress
#  (pip install waitress), recommended for Windows production.
# ==========================================================================
[CmdletBinding()]
param(
  [switch]$Check,
  [switch]$Backup,
  [switch]$NoMigrate,
  [switch]$NoCollectstatic,
  [switch]$Foreground,
  [int]$Port = 8000,
  [int]$Workers = 3,
  [int]$Timeout = 120
)

$ErrorActionPreference = 'Stop'
$BASE_DIR = Split-Path -Parent $PSScriptRoot
$VENV_PY  = Join-Path $BASE_DIR 'venv\Scripts\python.exe'
$ENV_FILE = Join-Path $BASE_DIR '.env'
$LOG_DIR  = Join-Path $BASE_DIR 'logs'

function Info($m) { Write-Host ">> $m" -ForegroundColor Cyan }
function Ok($m)   { Write-Host "OK $m" -ForegroundColor Green }
function Fail($m) { Write-Host "ERR $m" -ForegroundColor Red; exit 1 }

function Wait-Healthy([int]$Port, [int]$Attempts = 10) {
  for ($i = 1; $i -le $Attempts; $i++) {
    try {
      $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health/" -UseBasicParsing -TimeoutSec 3
      if ($r.StatusCode -eq 200) { return $true }
    } catch { }
    Start-Sleep -Seconds 3
  }
  return $false
}

if (-not (Test-Path $VENV_PY)) { Fail "venv python not found: $VENV_PY" }

# ---- 1. Load .env (without overriding existing variables) ------------------
if (Test-Path $ENV_FILE) {
  Info "Loading $ENV_FILE"
  Get-Content $ENV_FILE | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith('#')) {
      $line = $line -replace '^export\s+', ''
      if ($line -match '^([^=]+)=(.*)$') {
        $k = $Matches[1].Trim()
        $v = $Matches[2].Trim()
        if ($v.Length -ge 2 -and $v[0] -eq '"' -and $v[-1] -eq '"') { $v = $v.Substring(1, $v.Length - 2) }
        if (-not [Environment]::GetEnvironmentVariable($k)) {
          [Environment]::SetEnvironmentVariable($k, $v, 'Process')
        }
      }
    }
  }
} else {
  Info "No $ENV_FILE - using existing environment variables."
}

# ---- 2. Validate required variables ---------------------------------------
$env:DJANGO_DEBUG = 'False'
$missing = @()
if (-not $env:DJANGO_SECRET_KEY) { $missing += 'DJANGO_SECRET_KEY' }
if (-not $env:DATABASE_URL -and -not $env:DB_PASSWORD) { $missing += 'DB_PASSWORD (or DATABASE_URL)' }
if ($missing.Count -gt 0) {
  Fail "Missing required variables: $($missing -join ', ').`nCopy .env.example to .env and fill values (see PRODUCTION.md)."
}
if ($env:DJANGO_SECRET_KEY.Length -lt 50) {
  Fail "DJANGO_SECRET_KEY is shorter than 50 characters - generate a long random key."
}
if (-not $env:DJANGO_ALLOWED_HOSTS) {
  Write-Host "WARN DJANGO_ALLOWED_HOSTS not set (default '*') - restrict it in production." -ForegroundColor Yellow
}
Ok "Environment validated (DEBUG=False)"

# ---- 3. Backup (optional but recommended before migration) ----------------
if ($Backup) {
  Info "PostgreSQL backup before deployment..."
  Push-Location $BASE_DIR
  try { & $VENV_PY scripts\backup_db.py --quiet } finally { Pop-Location }
  if ($LASTEXITCODE -ne 0) { Fail "Backup failed - deployment aborted (see scripts/backup_db.py --help)" }
  Ok "Backup done (backups/)"
}

# ---- 4. Migrations ---------------------------------------------------------
if (-not $NoMigrate) {
  Info "Applying migrations..."
  Push-Location $BASE_DIR
  try { & $VENV_PY manage.py migrate } finally { Pop-Location }
  if ($LASTEXITCODE -ne 0) { Fail "migrate failed (exit code $LASTEXITCODE)" }
  Ok "Migrations applied"
} else { Info "Migration skipped (-NoMigrate)" }

# ---- 5. Static files -------------------------------------------------------
if (-not $NoCollectstatic) {
  Info "Collecting static files..."
  Push-Location $BASE_DIR
  try { & $VENV_PY manage.py collectstatic --noinput } finally { Pop-Location }
  if ($LASTEXITCODE -ne 0) { Fail "collectstatic failed (exit code $LASTEXITCODE)" }
  Ok "Static files collected"
} else { Info "Collectstatic skipped (-NoCollectstatic)" }

# ---- 6. Security checks ----------------------------------------------------
Info "Running check --deploy..."
Push-Location $BASE_DIR
try { & $VENV_PY manage.py check --deploy } finally { Pop-Location }
if ($LASTEXITCODE -ne 0) { Fail "check --deploy reported issues" }
Ok "check --deploy: no warnings"

if ($Check) {
  Write-Host "`nDONE checks - start the server with: .\scripts\deploy.ps1"
  exit 0
}

# ---- 7. Start the server ---------------------------------------------------
New-Item -ItemType Directory -Force -Path $LOG_DIR | Out-Null
$gunicornExe = Join-Path $BASE_DIR 'venv\Scripts\gunicorn.exe'
$useGunicorn = (Test-Path $gunicornExe) -or (Get-Command 'gunicorn' -ErrorAction SilentlyContinue)

if ($useGunicorn) {
  Info "Starting gunicorn on 127.0.0.1:$Port (workers=$Workers)..."
  $gArgs = @('config.wsgi:application',
             "--bind 127.0.0.1:$Port",
             "--workers $Workers",
             "--timeout $Timeout",
             "--access-logfile $LOG_DIR\gunicorn-access.log",
             "--error-logfile $LOG_DIR\gunicorn-error.log")
  if ($Foreground) {
    Push-Location $BASE_DIR
    try { & $VENV_PY -m gunicorn @gArgs } finally { Pop-Location }
  } else {
    $logOut = Join-Path $LOG_DIR 'gunicorn.out'
    $logErr = Join-Path $LOG_DIR 'gunicorn-error.log'
    $p = Start-Process -FilePath $VENV_PY -ArgumentList (@('-m','gunicorn') + $gArgs) `
         -WorkingDirectory $BASE_DIR -WindowStyle Hidden `
         -RedirectStandardOutput $logOut -RedirectStandardError $logErr -PassThru
    Start-Sleep -Seconds 3
    if ($p.HasExited) { Fail "gunicorn exited - see $logErr" }
    Ok "gunicorn started (PID $($p.Id)) - http://127.0.0.1:$Port"
    if (Wait-Healthy -Port $Port) { Ok "Healthy: /health/ responds" }
    else { Fail "/health/ did not respond after 30s - database unreachable?" }
    Write-Host "   Stop: Stop-Process -Id $($p.Id)"
  }
} else {
  Write-Host "WARN gunicorn is not available on Windows." -ForegroundColor Yellow
  if (Get-Command 'waitress-serve' -ErrorAction SilentlyContinue) {
    Info "Starting via waitress (Windows WSGI server)..."
    $wArgs = @("--listen=127.0.0.1:$Port", 'config.wsgi:application')
    if ($Foreground) {
      Push-Location $BASE_DIR
      try { & waitress-serve @wArgs } finally { Pop-Location }
    } else {
      $p = Start-Process -FilePath (Get-Command 'waitress-serve').Source -ArgumentList $wArgs `
           -WorkingDirectory $BASE_DIR -WindowStyle Hidden -PassThru
      Start-Sleep -Seconds 3
      if ($p.HasExited) { Fail "waitress exited" }
      Ok "waitress started (PID $($p.Id)) - http://127.0.0.1:$Port"
      if (Wait-Healthy -Port $Port) { Ok "Healthy: /health/ responds" }
      else { Fail "/health/ did not respond after 30s - database unreachable?" }
      Write-Host "   Stop: Stop-Process -Id $($p.Id)"
    }
  } else {
    Fail "No WSGI server available. On Windows: pip install waitress, or deploy on Linux/WSL with gunicorn (see PRODUCTION.md)."
  }
}
