#!/bin/bash
# Script de mise à jour automatique de l'application NexusERP sur le serveur de production.
# Exécution : sudo ./scripts/update.sh

# Couleurs pour l'affichage
GREEN='\033[0;32m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "=== Début de la mise à jour de NexusERP ==="

# 1. Vérification de l'utilisateur (on recommande de le lancer en tant qu'utilisateur de l'app ou root)
APP_DIR="/opt/erp_chu_review"
APP_USER="nexuserp"

cd \ || { echo -e "Erreur: Le dossier \ n'existe pas."; exit 1; }

# 2. Récupération du nouveau code depuis GitHub
echo -e "\n[1/4] Récupération des dernières modifications (git pull)..."
sudo -u \ git pull origin main || { echo -e "Erreur lors du git pull."; exit 1; }

# 3. Application des migrations et fichiers statiques
echo -e "\n[2/4] Application des migrations base de données..."
sudo -u \ bash -c 'set -a; source .env; set +a; venv/bin/python manage.py migrate --noinput' || { echo -e "Erreur lors des migrations."; exit 1; }

echo -e "\n[3/4] Collecte des fichiers statiques..."
sudo -u \ bash -c 'set -a; source .env; set +a; venv/bin/python manage.py collectstatic --noinput' || { echo -e "Erreur lors du collectstatic."; exit 1; }

# 4. Redémarrage du service
echo -e "\n[4/4] Redémarrage du service gunicorn (nexuserp)..."
sudo systemctl restart nexuserp || { echo -e "Erreur lors du redémarrage du service."; exit 1; }

echo -e "\n=== Mise à jour terminée avec succès ! ==="
