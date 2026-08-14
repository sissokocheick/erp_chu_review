# ═══════════════════════════════════════════════════════════════════════════
#  run_windows_service.ps1 — Launcher du serveur Windows (waitress)
#
#  Chargé par le service NSSM « NexusERP » ou par une tâche planifiée au
#  démarrage. Comportement :
#   1. charge le .env de la racine du projet dans l'environnement ;
#   2. vérifie que waitress est installé (pip install waitress sinon) ;
#   3. lance waitress en boucle : en cas de crash, redémarre après 5 s
#      (équivalent Windows de Restart=always de systemd) ;
#   4. journalise dans logs/waitress.log et logs/waitress-error.log.
#
#  Usage direct (test) :
#    .\deploy\run_windows_service.ps1 -Port 8000 -NoLoop
# ═══════════════════════════════════════════════════════════════════════════
[CmdletBinding()]
param(
  [int]$Port = 8000,
  [switch]$NoLoop
)

$ErrorActionPreference = 'Stop'
$BASE_DIR = Split-Path -Parent $PSScriptRoot
$LOG_DIR  = Join-Path $BASE_DIR 'logs'
New-Item -ItemType Directory -Force -Path $LOG_DIR | Out-Null

# ── 1. Chargement du .env ──────────────────────────────────────────────────
$ENV_FILE = Join-Path $BASE_DIR '.env'
if (Test-Path $ENV_FILE) {
  Get-Content $ENV_FILE | ForEach-Object {
    $line = $_.Trim()
    if ($line -and -not $line.StartsWith('#') -and $line.Contains('=')) {
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
  Write-Host "WARN pas de $ENV_FILE - utiliser les variables deja definies."
}

# ── 2. Vérification waitress ───────────────────────────────────────────────
$waitress = Join-Path $BASE_DIR 'venv\Scripts\waitress-serve.exe'
if (-not (Test-Path $waitress)) {
  Write-Host "ERR waitress n'est pas installe. Lancer : pip install waitress" -ForegroundColor Red
  exit 1
}

$wArgs = @("--listen=127.0.0.1:$Port", 'config.wsgi:application')
$logOut = Join-Path $LOG_DIR 'waitress.log'
$logErr = Join-Path $LOG_DIR 'waitress-error.log'

Write-Host ">> NexusERP : waitress sur 127.0.0.1:$Port (logs : $LOG_DIR)"

# ── 3. Boucle avec redémarrage automatique ─────────────────────────────────
while ($true) {
  $p = Start-Process -FilePath $waitress -ArgumentList $wArgs `
       -WorkingDirectory $BASE_DIR -WindowStyle Hidden `
       -RedirectStandardOutput $logOut -RedirectStandardError $logErr -PassThru
  Write-Host ">> serveur demarre (PID $($p.Id))"
  $p.WaitForExit()
  $code = $p.ExitCode
  Write-Host ">> serveur arrete (code $code) - $(Get-Date -Format 'HH:mm:ss')"
  if ($NoLoop) { exit $code }
  Start-Sleep -Seconds 5
}
