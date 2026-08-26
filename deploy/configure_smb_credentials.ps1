# ================================================================
#  Securise l'acces SMB au serveur de backup (ex: \\192.168.0.31\SAUV)
#  pour que la copie fonctionne aussi sous le compte SYSTEM (tache
#  planifiee) et pas seulement dans la session interactive actuelle.
#
#  Usage (PowerShell, dans le dossier du projet) :
#    .\deploy\configure_smb_credentials.ps1 -ShareUser Administrateur
#        -> demande le mot de passe du partage de facon masquee
#
#    .\deploy\configure_smb_credentials.ps1 -ShareUser Administrateur -SkipSystem
#        -> stocke uniquement pour le compte courant (pas d'admin requis)
#
#  Ce que fait le script :
#    1. Stocke les identifiants (cmdkey) pour le compte courant
#    2. Teste l'ecriture sur \\SERVER\SAUV
#    3. [admin] Stocke les identifiants pour le compte SYSTEM
#       (via une tache one-shot executee en tant que SYSTEM)
#    4. [admin] Cree la tache planifiee quotidienne "NexusERP Backup DB" (02h00)
#       executee en tant que SYSTEM -> fonctionne meme personne connecte
# ================================================================
param(
    [string]$Server = '192.168.0.31',
    [string]$RemoteDir = 'SAUV',
    [string]$ShareUser,
    [string]$SharePassword,
    [switch]$SkipSystem,
    [switch]$SkipBackupTask,
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot)
)

$ErrorActionPreference = 'Stop'
$unc = "\\$Server\$RemoteDir"

if (-not $ShareUser) {
    Write-Host "Utilisateur du partage $unc (ex: Administrateur) : " -NoNewline
    $ShareUser = Read-Host
}
if (-not $SharePassword) {
    $sec = Read-Host "Mot de passe de $ShareUser sur $Server" -AsSecureString
    $SharePassword = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($sec))
}

Write-Host ""
Write-Host "=== 1. Stockage des identifiants pour le compte courant ($env:USERNAME) ==="
cmdkey /add:"$Server" /user:"$ShareUser" /pass:"$SharePassword"
if ($LASTEXITCODE -ne 0) { throw "cmdkey a echoue (code $LASTEXITCODE)" }
Write-Host "OK - identifiants memorises pour $env:USERNAME"

Write-Host ""
Write-Host "=== 2. Test d'ecriture sur $unc ==="
$testFile = Join-Path $unc "_test_acces_$(Get-Date -Format 'yyyyMMddHHmmss').tmp"
try {
    Set-Content -Path $testFile -Value 'test' -ErrorAction Stop
    Remove-Item $testFile -Force
    Write-Host "OK - lecture/ecriture/suppression sur $unc"
} catch {
    throw "Acces impossible a ${unc} avec $ShareUser : $($_.Exception.Message)"
}

if (-not $SkipSystem) {
    Write-Host ""
    Write-Host "=== 3. Stockage des identifiants pour le compte SYSTEM ==="
    # cmdkey ne peut pas cibler un autre profil : on passe par une tache
    # one-shot executee EN TANT QUE SYSTEM qui lance cmdkey a notre place.
    $oneShot = 'NexusERP_CmdkeyOneShot'
    $inner = "cmdkey /add:$Server /user:$ShareUser /pass:$SharePassword"
    schtasks /create /tn $oneShot /tr "cmd.exe /c $inner" /sc once /st 23:59 /ru SYSTEM /f | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Impossible de creer la tache SYSTEM (droits admin requis)." }
    schtasks /run /tn $oneShot | Out-Null
    Start-Sleep -Seconds 5
    schtasks /delete /tn $oneShot /f | Out-Null
    Write-Host "OK - identifiants memorises dans le profil SYSTEM"

    if (-not $SkipBackupTask) {
        Write-Host ""
        Write-Host "=== 4. Tache planifiee quotidienne 'NexusERP Backup DB' (02h00, SYSTEM) ==="
        $python = Join-Path $ProjectRoot 'venv\Scripts\python.exe'
        $script = Join-Path $ProjectRoot 'scripts\backup_db.py'
        $logDir = Join-Path $ProjectRoot 'logs'
        if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir | Out-Null }
        $action = "cmd.exe /c cd /d `"$ProjectRoot`" && `"$python`" `"$script`" --quiet >> `"$logDir\backup.log`" 2>&1"
        schtasks /create /tn 'NexusERP Backup DB' /tr "$action" /sc daily /st 02:00 /ru SYSTEM /f | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Creation de la tache planifiee impossible." }
        Write-Host "OK - tache 'NexusERP Backup DB' creee (quotidienne a 02h00, compte SYSTEM)"
        Write-Host "     Pour tester tout de suite :  schtasks /run /tn `"NexusERP Backup DB`""
    }
}

Write-Host ""
Write-Host "=== Termine ==="
Write-Host "La copie de backup vers $unc fonctionne maintenant :"
Write-Host "  - dans la session interactive ($env:USERNAME)"
if (-not $SkipSystem) { Write-Host "  - sous le compte SYSTEM (tache planifiee, meme sans session ouverte)" }
