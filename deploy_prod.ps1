$serverIP = "192.168.0.29"
$serverUser = "chuangre"
$deployDir = "/opt/erp_chu_review"

Write-Host "=========================================" -ForegroundColor Cyan
Write-Host "🚀 DEPLOIEMENT VERS PRODUCTION ()" -ForegroundColor Cyan
Write-Host "=========================================" -ForegroundColor Cyan

Write-Host "
[1/3] Copie des fichiers vers le serveur..." -ForegroundColor Yellow
git archive -o deploy_temp.tar HEAD
scp deploy_temp.tar ${serverUser}@${serverIP}:/tmp/deploy_temp.tar
if ($LASTEXITCODE -ne 0) {
    Write-Host "❌ ERREUR LORS DU TRANSFERT SCP !" -ForegroundColor Red
    exit 1
}

Write-Host "
[2/3] Extraction et mise à jour sur le serveur..." -ForegroundColor Yellow
$sshCommand = "
    sudo tar -xf /tmp/deploy_temp.tar -C $deployDir &&
    rm /tmp/deploy_temp.tar &&
    sudo chown -R nexuserp:nexuserp $deployDir &&
    cd $deployDir &&
    sudo -u nexuserp bash -c 'set -a; source .env; set +a; venv/bin/python manage.py migrate --noinput' &&
    sudo -u nexuserp bash -c 'set -a; source .env; set +a; venv/bin/python manage.py collectstatic --noinput' &&
    sudo systemctl restart nexuserp
"
ssh -t ${serverUser}@${serverIP} $sshCommand
if ($LASTEXITCODE -ne 0) {
    Write-Host "
❌ ERREUR SUR LE SERVEUR (Mauvais mot de passe ou permissions) !" -ForegroundColor Red
    exit 1
}

Write-Host "
✅ DEPLOIEMENT REUSSI A 100% !" -ForegroundColor Green
