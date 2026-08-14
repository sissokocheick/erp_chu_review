# ═══════════════════════════════════════════════════════════════════════════
#  install_windows_service.ps1 — Service Windows NexusERP
#
#  Deux modes :
#    - NSSM (par défaut) : vrai service Windows, démarrage au boot, arrêt du
#      système géré, redémarrage automatique en cas de crash. Nécessite NSSM :
#        winget install NSSM  (ou https://nssm.cc)
#    - Tâche planifiée (-UseTaskScheduler) : sans dépendance externe, tâche
#      au démarrage de la machine. Le redémarrage en cas de crash est assuré
#      par la boucle interne de run_windows_service.ps1.
#
#  Usage (PowerShell en administrateur) :
#    .\deploy\install_windows_service.ps1                  # installer (NSSM)
#    .\deploy\install_windows_service.ps1 -UseTaskScheduler
#    .\deploy\install_windows_service.ps1 -Uninstall       # désinstaller
#    .\deploy\install_windows_service.ps1 -Port 8080
#
#  Prérequis : venv créé, waitress installé (pip install waitress), .env
#  renseigné à la racine du projet.
# ═══════════════════════════════════════════════════════════════════════════
[CmdletBinding()]
param(
  [switch]$UseTaskScheduler,
  [switch]$Uninstall,
  [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'
$BASE_DIR = Split-Path -Parent $PSScriptRoot
$RUNNER   = Join-Path $PSScriptRoot 'run_windows_service.ps1'
$LOG_DIR  = Join-Path $BASE_DIR 'logs'
New-Item -ItemType Directory -Force -Path $LOG_DIR | Out-Null

# ── Vérifications préalables ───────────────────────────────────────────────
if (-not (Test-Path (Join-Path $BASE_DIR '.env'))) {
  Write-Host "ERR fichier .env introuvable a la racine - copier .env.example vers .env" -ForegroundColor Red
  exit 1
}
if (-not (Test-Path (Join-Path $BASE_DIR 'venv\Scripts\waitress-serve.exe'))) {
  Write-Host "ERR waitress non installe dans le venv. Lancer : $BASE_DIR\venv\Scripts\pip install waitress" -ForegroundColor Red
  exit 1
}

$powershell = (Get-Command powershell.exe).Source

# ═══════════════════════════════════════════════════════════════════════════
#  Mode 1 : Tâche planifiée (schtasks)
# ═══════════════════════════════════════════════════════════════════════════
if ($UseTaskScheduler) {
  if ($Uninstall) {
    schtasks /Delete /TN "NexusERP" /F | Out-Null
    Write-Host "OK tache planifiee NexusERP supprimee."
    exit 0
  }
  $cmd = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$RUNNER`" -Port $Port"
  schtasks /Create /TN "NexusERP" /TR $cmd /SC ONSTART /RL HIGHEST /F | Out-Null
  if ($LASTEXITCODE -ne 0) { Write-Host "ERR schtasks a echoue" -ForegroundColor Red; exit 1 }
  Write-Host "OK tache planifiee NexusERP creee (demarrage de la machine, port $Port)."
  Write-Host "   Lancer maintenant : schtasks /Run /TN NexusERP"
  Write-Host "   Logs : $LOG_DIR"
  exit 0
}

# ═══════════════════════════════════════════════════════════════════════════
#  Mode 2 : NSSM (vrai service Windows)
# ═══════════════════════════════════════════════════════════════════════════
$nssm = Get-Command 'nssm' -ErrorAction SilentlyContinue
if (-not $nssm) {
  $nssm = Get-Command 'nssm.exe' -ErrorAction SilentlyContinue
}
if (-not $nssm) {
  Write-Host "ERR NSSM introuvable. Installer : winget install NSSM (https://nssm.cc)" -ForegroundColor Red
  Write-Host "   Ou utiliser la tache planifiee : .\deploy\install_windows_service.ps1 -UseTaskScheduler"
  exit 1
}
$nssm = $nssm.Source

if ($Uninstall) {
  & $nssm stop NexusERP 2>$null | Out-Null
  Start-Sleep -Seconds 2
  & $nssm remove NexusERP confirm | Out-Null
  Write-Host "OK service NexusERP supprime."
  exit 0
}

# Création du service : powershell -File run_windows_service.ps1
& $nssm install NexusERP $powershell "-NoProfile -ExecutionPolicy Bypass -File `"$RUNNER`" -Port $Port" | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Host "ERR nssm install a echoue" -ForegroundColor Red; exit 1 }

& $nssm set NexusERP AppDirectory "$BASE_DIR" | Out-Null
& $nssm set NexusERP Description "NexusERP - ERP de gestion de stock (waitress)" | Out-Null
& $nssm set NexusERP Start SERVICE_AUTO_START | Out-Null
# Redémarrage automatique en cas de crash
& $nssm set NexusERP AppExit Default Restart | Out-Null
& $nssm set NexusERP AppRestartDelay 5000 | Out-Null
# Logs du service
& $nssm set NexusERP AppStdout (Join-Path $LOG_DIR 'nssm-out.log') | Out-Null
& $nssm set NexusERP AppStderr (Join-Path $LOG_DIR 'nssm-error.log') | Out-Null
& $nssm set NexusERP AppRotateFiles 1 | Out-Null
& $nssm set NexusERP AppRotateBytes 10485760 | Out-Null

Write-Host "OK service NexusERP installe (demarrage auto au boot, port $Port)."
Write-Host "   Demarrer : nssm start NexusERP   |   Statut : nssm status NexusERP"
Write-Host "   Logs     : $LOG_DIR"
