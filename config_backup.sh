#!/bin/bash
# ================================================================
#  Configurer le serveur de backup distant
#  Usage: bash config_backup.sh <IP_SERVEUR> <USER_SSH>
#  Exemple: bash config_backup.sh 192.168.0.30 backup
# ================================================================
set -e

if [ -z "$1" ]; then
    echo "Usage: $0 <IP_SERVEUR> [USER_SSH]"
    echo "Exemple: $0 192.168.0.30 backup"
    exit 1
fi

REMOTE_HOST="$1"
REMOTE_USER="${2:-backup}"
REMOTE_DIR="/home/${REMOTE_USER}/backups"

# Detection QNAP (SSHD sur port 22, dossier /home/${REMOTE_USER})
if ssh -i ~/.ssh/id_rsa_backup -o StrictHostKeyChecking=no -o ConnectTimeout=3 "${REMOTE_USER}@${REMOTE_HOST}" "uname -a" 2>/dev/null | grep -qi "qnap\|QNAP"; then
    QNAP=true
    echo ">> QNAP detecte"
else
    QNAP=false
fi

echo "=== Configuration du backup distant ==="
echo "  Serveur: ${REMOTE_HOST}"
echo "  User:    ${REMOTE_USER}"
echo "  Dossier: ${REMOTE_DIR}"
echo ""

# 1. Mettre a jour le .env
echo ">> Mise a jour du .env ..."
cd /home/chuangre/erp_chu_review

# Supprimer les anciennes lignes backup
sed -i '/^# Backup distant/d' .env
sed -i '/^BACKUP_REMOTE_HOST=/d' .env
sed -i '/^BACKUP_REMOTE_USER=/d' .env
sed -i '/^BACKUP_REMOTE_DIR=/d' .env

# Ajouter les nouvelles
cat >> .env << EOF
# Backup distant
BACKUP_REMOTE_HOST=${REMOTE_HOST}
BACKUP_REMOTE_USER=${REMOTE_USER}
BACKUP_REMOTE_DIR=${REMOTE_DIR}
EOF

echo "OK : .env mis a jour"

# 2. Generer la cle SSH si elle n'existe pas
if [ ! -f ~/.ssh/id_rsa_backup ]; then
    echo ">> Generation de la cle SSH ..."
    ssh-keygen -t rsa -b 4096 -f ~/.ssh/id_rsa_backup -N "" -q
    echo "OK : Cle generee"
else
    echo ">> Cle SSH deja existante"
fi

# 3. Copier la cle vers le serveur distant
echo ">> Copie de la cle vers ${REMOTE_USER}@${REMOTE_HOST} ..."
echo "   (entrez le mot de passe du serveur distant une fois)"
ssh-copy-id -i ~/.ssh/id_rsa_backup "${REMOTE_USER}@${REMOTE_HOST}" 2>/dev/null || \
    cat ~/.ssh/id_rsa_backup.pub | ssh "${REMOTE_USER}@${REMOTE_HOST}" "mkdir -p ~/.ssh && cat >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys"

echo "OK : Cle copiee"

# 4. Tester la connexion
echo ">> Test de connexion SSH ..."
ssh -i ~/.ssh/id_rsa_backup -o StrictHostKeyChecking=no "${REMOTE_USER}@${REMOTE_HOST}" "echo 'Connexion OK'" 2>/dev/null

# 5. Tester le backup
echo ">> Test de sauvegarde complete ..."
source venv/bin/activate
python scripts/backup_db.py --dir backups --quiet

# 6. Copier vers le serveur distant
LATEST=$(ls -t backups/*.backup 2>/dev/null | head -1)
if [ -n "$LATEST" ]; then
    echo ">> Copie de $(basename $LATEST) vers le serveur distant ..."
    scp -i ~/.ssh/id_rsa_backup -o StrictHostKeyChecking=no "$LATEST" "${REMOTE_USER}@${REMOTE_HOST}:${REMOTE_DIR}/"
    echo "OK : Backup copie avec succes"
else
    echo "WARN : Aucun backup local a copier"
fi

# 7. Activer le cron automatique
CRON_LINE="0 2 * * * cd /home/chuangre/erp_chu_review && source venv/bin/activate && python scripts/backup_db.py --dir backups --quiet >> logs/backup.log 2>&1"

# Verifier si le cron est deja active
crontab -l 2>/dev/null | grep -q "backup_db.py"
if [ $? -eq 0 ]; then
    echo ">> Cron deja actif"
else
    echo ">> Activation du backup automatique (cron a 2h du matin) ..."
    (crontab -l 2>/dev/null; echo "${CRON_LINE}") | crontab -
    echo "OK : Cron active"
fi

echo ""
echo "=== Configuration terminee ==="
echo "  Serveur: ${REMOTE_HOST}"
echo "  Backup:  $(ls -t backups/*.backup 2>/dev/null | head -1)"
echo "  Cron:    0 2 * * * (quotidien a 2h du matin)"
echo ""
echo "Pour modifier : crontab -e"
echo "Pour desactiver : crontab -e puis supprimer la ligne backup_db.py"
