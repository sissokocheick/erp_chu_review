#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
#  setup-ubuntu.sh — Installation NexusERP sur Ubuntu 26.04 LTS
#
#  Installe : Python 3.14, PostgreSQL 17, Nginx, Certbot (Let's Encrypt),
#  crée la base de données, les dépendances, les migrations, et configure
#  le service systemd + reverse proxy nginx.
#
#  Usage :
#    sudo bash scripts/setup-ubuntu.sh                    # domaine par défaut
#    sudo bash scripts/setup-ubuntu.sh erp.chu.example    # avec domaine
#    sudo bash scripts/setup-ubuntu.sh erp.chu.example --dev   # mode dev (pas SSL)
#
#  Prérequis :
#    - Ubuntu 26.04 LTS (minimal ou serveur)
#    - Accès root ou sudo
#    - Un nom de domaine pointant vers le serveur (pour SSL)
# ═══════════════════════════════════════════════════════════════════════════
set -euo pipefail

# ── Paramètres ────────────────────────────────────────────────────────────
DOMAIN="${1:-erp.chu.example}"
# IPs supplémentaires pour le réseau interne (ex: --ip 192.168.0.27,192.168.35.27)
EXTRA_IPS=""
DEV_MODE=0
for arg in "$@"; do
  case "$arg" in
    --dev) DEV_MODE=1 ;;
    --ip) shift_next=1 ;;
    *) if [ -n "${shift_next:-}" ]; then EXTRA_IPS="$arg"; shift_next=; fi ;;
  esac
done

APP_DIR="/opt/erp_chu_review"
APP_USER="nexuserp"
APP_PORT=8000
DB_NAME="chu_angre_db"
DB_USER="nexuserp_db"
DB_PASSWORD="$(openssl rand -hex 16)"
SECRET_KEY="$(openssl rand -hex 50)"

# ── Couleurs ──────────────────────────────────────────────────────────────
info()  { echo -e "\033[1;34m▶\033[0m $*"; }
ok()    { echo -e "\033[1;32m✔\033[0m $*"; }
warn()  { echo -e "\033[1;33m⚠\033[0m $*"; }
fail()  { echo -e "\033[1;31m✘\033[0m $*" >&2; exit 1; }

# ── Vérification root ─────────────────────────────────────────────────────
if [ "$(id -u)" -ne 0 ]; then
  fail "Ce script doit être lancé en root (sudo bash scripts/setup-ubuntu.sh)"
fi

echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║       NexusERP — Installation Ubuntu 26.04 LTS         ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
info "Domaine : $DOMAIN"
info "Dossier : $APP_DIR"
info "Base    : $DB_NAME"
echo ""

# ═══════════════════════════════════════════════════════════════════════════
# ÉTAPE 1 — Mise à jour système + paquets de base
# ═══════════════════════════════════════════════════════════════════════════
info "ÉTAPE 1/10 — Mise à jour système..."
apt-get update -qq
apt-get upgrade -y -qq

apt-get install -y -qq \
  git curl wget build-essential \
  libpq-dev libjpeg-dev zlib1g-dev libfreetype6-dev \
  libffi-dev libssl-dev libxml2-dev libxslt1-dev \
  ufw fail2ban

ok "Paquets système installés"

# ═══════════════════════════════════════════════════════════════════════════
# ÉTAPE 2 — Python 3.14
# ═══════════════════════════════════════════════════════════════════════════
info "ÉTAPE 2/10 — Python 3.14..."

# Sur Ubuntu 26.04, Python 3.14 est dans les dépôts officiels
if ! command -v python3.14 &>/dev/null; then
  apt-get install -y -qq software-properties-common
  add-apt-repository -y ppa:deadsnakes/ppa
  apt-get update -qq
  apt-get install -y -qq python3.14 python3.14-venv python3.14-dev python3-pip
fi

PYTHON=$(command -v python3.14 || command -v python3)
info "Python : $($PYTHON --version)"
ok "Python installé"

# ═══════════════════════════════════════════════════════════════════════════
# ÉTAPE 3 — PostgreSQL 17
# ═══════════════════════════════════════════════════════════════════════════
info "ÉTAPE 3/10 — PostgreSQL 17..."

if ! command -v psql &>/dev/null; then
  # Ajouter le dépôt officiel PostgreSQL pour avoir PG 17
  apt-get install -y -qq postgresql-common
  /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh -y
  apt-get install -y -qq postgresql-17 postgresql-client-17
fi

PG_VERSION=$(psql --version | grep -oP '\d+\.\d+' | head -1)
info "PostgreSQL : $PG_VERSION"

# Créer la base et l'utilisateur
sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='$DB_USER'" | grep -q 1 || \
  sudo -u postgres psql -c "CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD' CREATEDB;"

sudo -u postgres psql -tc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1 || \
  sudo -u postgres psql -c "CREATE DATABASE $DB_NAME OWNER $DB_USER;"

# Accorder les privilèges
sudo -u postgres psql -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;"
sudo -u postgres psql -d $DB_NAME -c "GRANT ALL ON SCHEMA public TO $DB_USER;"

ok "PostgreSQL configuré (base=$DB_NAME, user=$DB_USER)"

# ═══════════════════════════════════════════════════════════════════════════
# ÉTAPE 4 — Utilisateur système + clonage du code
# ═══════════════════════════════════════════════════════════════════════════
info "ÉTAPE 4/10 — Utilisateur et code source..."

# Créer l'utilisateur système
id "$APP_USER" &>/dev/null || useradd -r -s /usr/sbin/nologin -m "$APP_USER"

# Cloner ou copier l'app
if [ ! -d "$APP_DIR" ]; then
  mkdir -p "$APP_DIR"
fi

# Si on a le code source dans le répertoire courant, le copier
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if [ -f "$SCRIPT_DIR/manage.py" ]; then
  info "Copie du code source depuis $SCRIPT_DIR..."
  rsync -a --exclude='venv' --exclude='__pycache__' --exclude='*.pyc' \
    --exclude='.git' --exclude='staticfiles' --exclude='media' \
    --exclude='logs' --exclude='backups' \
    "$SCRIPT_DIR/" "$APP_DIR/"
else
  fail "Lancez ce script depuis le répertoire du projet (scripts/setup-ubuntu.sh)"
fi

# Permissions
chown -R "$APP_USER":"$APP_USER" "$APP_DIR"
ok "Code source déployé dans $APP_DIR"

# ═══════════════════════════════════════════════════════════════════════════
# ÉTAPE 5 — Virtual environment + dépendances
# ═══════════════════════════════════════════════════════════════════════════
info "ÉTAPE 5/10 — Environnement Python..."

cd "$APP_DIR"
sudo -u "$APP_USER" $PYTHON -m venv venv
sudo -u "$APP_USER" venv/bin/pip install --upgrade pip -q
sudo -u "$APP_USER" venv/bin/pip install -r requirements.txt -q
sudo -u "$APP_USER" venv/bin/pip install gunicorn -q

ok "Dépendances installées ($(wc -l < requirements.txt) paquets)"

# ═══════════════════════════════════════════════════════════════════════════
# ÉTAPE 6 — Fichier .env de production
# ═══════════════════════════════════════════════════════════════════════════
info "ÉTAPE 6/10 — Configuration .env..."

if [ ! -f "$APP_DIR/.env" ]; then
  cat > "$APP_DIR/.env" <<ENVEOF
# ── NexusERP Production ── Généré par setup-ubuntu.sh le $(date +%Y-%m-%d)
DJANGO_DEBUG=False
DJANGO_SECRET_KEY=$SECRET_KEY
DJANGO_ALLOWED_HOSTS=$DOMAIN,www.$DOMAIN${EXTRA_IPS:+,$EXTRA_IPS}
CSRF_TRUSTED_ORIGINS=https://$DOMAIN,https://www.$DOMAIN${EXTRA_IPS:+,http://$EXTRA_IPS}
TRUSTED_INTERNAL=1

DB_NAME=$DB_NAME
DB_USER=$DB_USER
DB_PASSWORD=$DB_PASSWORD
DB_HOST=localhost
DB_PORT=5432

# Notifications (à remplir manuellement)
# EMAIL_HOST=smtp.gmail.com
# EMAIL_PORT=587
# EMAIL_HOST_USER=
# EMAIL_HOST_PASSWORD=
# EMAIL_USE_TLS=True
# TWILIO_ACCOUNT_SID=
# TWILIO_AUTH_TOKEN=
# TWILIO_FROM_NUMBER=
# ALERT_EMAILS=
# ALERT_PHONES=
ENVEOF
  chown "$APP_USER":"$APP_USER" "$APP_DIR/.env"
  chmod 600 "$APP_DIR/.env"
  ok "Fichier .env créé (mots de passe générés aléatoirement)"
else
  warn "Fichier .env existant — non écrasé"
fi

# ═══════════════════════════════════════════════════════════════════════════
# ÉTAPE 7 — Migrations + données initiales
# ═══════════════════════════════════════════════════════════════════════════
info "ÉTAPE 7/10 — Base de données..."

cd "$APP_DIR"
sudo -u "$APP_USER" venv/bin/python manage.py migrate --noinput
sudo -u "$APP_USER" venv/bin/python manage.py collectstatic --noinput

# Import des données SAGE (idempotent — get_or_create)
info "Import des données initiales (familles, fournisseurs, services, articles)..."
sudo -u "$APP_USER" venv/bin/python manage.py import_sage_data --quiet 2>/dev/null || \
  warn "Import SAGE échoué (à relancer manuellement : python manage.py import_sage_data)"

# Rôles et permissions
info "Création des rôles et permissions..."
sudo -u "$APP_USER" venv/bin/python manage.py init_roles 2>/dev/null || true

# Superutilisateur
if [ -n "${DJANGO_ADMIN_USERNAME:-}" ]; then
  sudo -u "$APP_USER" venv/bin/python manage.py shell -c "
from django.contrib.auth.models import User
if not User.objects.filter(username='$DJANGO_ADMIN_USERNAME').exists():
    User.objects.create_superuser('$DJANGO_ADMIN_USERNAME', '${DJANGO_ADMIN_EMAIL:-admin@$DOMAIN}', '${DJANGO_ADMIN_PASSWORD:-admin}')
    print('Superutilisateur créé : $DJANGO_ADMIN_USERNAME')
else:
    print('Superutilisateur $DJANGO_ADMIN_USERNAME existe déjà')
" 2>/dev/null
fi

# Répertoires
mkdir -p "$APP_DIR/logs" "$APP_DIR/media" "$APP_DIR/backups"
chown -R "$APP_USER":"$APP_USER" "$APP_DIR/logs" "$APP_DIR/media" "$APP_DIR/backups"

ok "Base de données initialisée"

# ═══════════════════════════════════════════════════════════════════════════
# ÉTAPE 8 — Service systemd
# ═══════════════════════════════════════════════════════════════════════════
info "ÉTAPE 8/10 — Service systemd..."

# Adapter le fichier service
sed -i "s|/opt/erp_chu_review|$APP_DIR|g" "$APP_DIR/deploy/nexuserp.service"
sed -i "s|User=www-data|User=$APP_USER|g" "$APP_DIR/deploy/nexuserp.service"
sed -i "s|Group=www-data|Group=$APP_USER|g" "$APP_DIR/deploy/nexuserp.service"

cp "$APP_DIR/deploy/nexuserp.service" /etc/systemd/system/
systemctl daemon-reload
systemctl enable nexuserp

ok "Service systemd configuré (nexuserp.service)"

# ═══════════════════════════════════════════════════════════════════════════
# ÉTAPE 9 — Nginx reverse proxy
# ═══════════════════════════════════════════════════════════════════════════
info "ÉTAPE 9/10 — Nginx..."

apt-get install -y -qq nginx

if [ "$DEV_MODE" -eq 1 ]; then
  # Mode dev : pas de SSL, juste reverse proxy
  # Construire la liste des server_name (domaine + IPs)
  NGINX_NAMES="$DOMAIN"
  [ -n "$EXTRA_IPS" ] && NGINX_NAMES="$NGINX_NAMES $EXTRA_IPS"

  cat > /etc/nginx/sites-available/nexuserp <<NGINXEOF
server {
    listen 80;
    listen 8080;
    server_name $NGINX_NAMES;

    client_max_body_size 20M;

    location /static/ {
        alias $APP_DIR/staticfiles/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    location /media/ {
        alias $APP_DIR/media/;
        expires 7d;
    }

    location / {
        proxy_pass http://127.0.0.1:$APP_PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }
}
NGINXEOF
  ok "Nginx configuré (mode dev, pas de SSL)"
else
  # Mode prod : HTTP → HTTPS
  NGINX_NAMES="$DOMAIN www.$DOMAIN"
  [ -n "$EXTRA_IPS" ] && NGINX_NAMES="$NGINX_NAMES $EXTRA_IPS"

  cat > /etc/nginx/sites-available/nexuserp <<NGINXEOF
server {
    listen 80;
    server_name $NGINX_NAMES;
    return 301 https://\$host\$request_uri;
}

server {
    listen 443 ssl http2;
    listen 8443 ssl;
    server_name $NGINX_NAMES;

    # SSL — Certbot créera les certificats ci-dessous
    ssl_certificate     /etc/letsencrypt/live/$DOMAIN/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/$DOMAIN/privkey.pem;

    # Protocoles SSL sécurisés
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384;
    ssl_prefer_server_ciphers off;

    # En-têtes de sécurité
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;
    add_header X-Content-Type-Options nosniff always;
    add_header Referrer-Policy strict-origin-when-cross-origin always;
    add_header X-Frame-Options SAMEORIGIN always;

    client_max_body_size 20M;

    # Fichiers statiques (servis directement par Nginx)
    location /static/ {
        alias $APP_DIR/staticfiles/;
        expires 30d;
        add_header Cache-Control "public, immutable";
    }

    location /media/ {
        alias $APP_DIR/media/;
        expires 7d;
    }

    # Proxy vers Gunicorn
    location / {
        proxy_pass http://127.0.0.1:$APP_PORT;
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_read_timeout 120s;
    }
}
NGINXEOF
  ok "Nginx configuré (HTTP → HTTPS)"
fi

# Activer le site
ln -sf /etc/nginx/sites-available/nexuserp /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

# Test de la config
nginx -t 2>/dev/null || fail "Config nginx invalide"

# ═══════════════════════════════════════════════════════════════════════════
# ÉTAPE 10 — SSL Let's Encrypt + démarrage
# ═══════════════════════════════════════════════════════════════════════════
if [ "$DEV_MODE" -eq 0 ]; then
  info "ÉTAPE 10/10 — SSL Let's Encrypt..."

  apt-get install -y -qq certbot python3-certbot-nginx

  # Démarrer nginx temporairement pour la validation HTTP
  systemctl restart nginx

  # Demander le certificat
  certbot certonly --webroot -w /var/www/html \
    -d "$DOMAIN" -d "www.$DOMAIN" \
    --non-interactive --agree-tos --email "admin@$DOMAIN" \
    || warn "Certbot échoué — configurez le certificat manuellement"

  # Configurer le renouvellement automatique
  systemctl enable certbot.timer 2>/dev/null || true

  ok "SSL Let's Encrypt configuré"
else
  info "ÉTAPE 10/10 — Mode dev, pas de SSL"
fi

# ── Firewall ──────────────────────────────────────────────────────────────
info "Configuration du firewall..."
ufw allow 22/tcp   >/dev/null 2>&1  # SSH
ufw allow 80/tcp   >/dev/null 2>&1  # HTTP
ufw allow 443/tcp  >/dev/null 2>&1  # HTTPS
ufw allow 8080/tcp  >/dev/null 2>&1  # HTTP alternatif (réseau interne)
ufw --force enable >/dev/null 2>&1

# ── Fail2ban ──────────────────────────────────────────────────────────────
info "Configuration de Fail2ban..."
systemctl enable fail2ban >/dev/null 2>&1
systemctl start fail2ban  >/dev/null 2>&1

# ── Démarrage ─────────────────────────────────────────────────────────────
info "Démarrage de l'application..."
systemctl start nexuserp
systemctl restart nginx

# Vérification
sleep 3
if systemctl is-active --quiet nexuserp; then
  ok "NexusERP démarré avec succès !"
else
  warn "Le service nexuserp n'a pas démarré — vérifiez : journalctl -u nexuserp -n 20"
fi

if curl -fsS http://127.0.0.1:8000/health/ >/dev/null 2>&1; then
  ok "Healthcheck : OK"
else
  warn "Healthcheck : échoué (le service démarre peut-être encore)"
fi

# ═══════════════════════════════════════════════════════════════════════════
# RÉSUMÉ
# ═══════════════════════════════════════════════════════════════════════════
echo ""
echo "╔══════════════════════════════════════════════════════════╗"
echo "║              ✅ Installation terminée !                 ║"
echo "╚══════════════════════════════════════════════════════════╝"
echo ""
echo "  URL        : https://$DOMAIN"
[ -n "$EXTRA_IPS" ] && echo "  Réseau     : http://$(echo $EXTRA_IPS | cut -d, -f1)"
echo "  Dossier    : $APP_DIR"
echo "  Base       : $DB_NAME (user: $DB_USER)"
echo "  Secret     : $DB_PASSWORD (dans $APP_DIR/.env)"
echo "  Service    : systemctl status nexuserp"
echo "  Logs       : journalctl -u nexuserp -f"
echo "  Nginx      : journalctl -u nginx -f"
echo ""
echo "  Commandes utiles :"
echo "    sudo systemctl restart nexuserp    # redémarrer l'app"
echo "    sudo systemctl restart nginx       # redémarrer nginx"
echo "    cd $APP_DIR && sudo -u $APP_USER venv/bin/python manage.py createsuperuser"
echo "    cd $APP_DIR && sudo -u $APP_USER venv/bin/python manage.py import_sage_data"
echo ""
