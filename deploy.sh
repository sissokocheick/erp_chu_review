#!/bin/bash
set -e

echo "╔══════════════════════════════════════════════════╗"
echo "║  DEPLOIEMENT ERP CHU - PRODUCTION                ║"
echo "╚══════════════════════════════════════════════════╝"

# 1. Creer le dossier et cloner
echo ""
echo "=== 1/7 Clone du code ==="
cd /home/chuangre
if [ -d "erp_chu_review" ]; then
    cd erp_chu_review
    git pull origin main
else
    git clone https://github.com/sissokocheick/erp_chu_review.git
    cd erp_chu_review
fi

# 2. Environnement virtuel
echo ""
echo "=== 2/7 Environnement virtuel ==="
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt --quiet

# 3. Fichier .env
echo ""
echo "=== 3/7 Configuration .env ==="
if [ ! -f ".env" ]; then
    SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")
    cat > .env << EOF
DJANGO_DEBUG=False
DJANGO_SECRET_KEY=${SECRET}
DJANGO_ALLOWED_HOSTS=192.168.0.29,localhost,127.0.0.1
TRUSTED_INTERNAL=1
DB_NAME=erp_chu_prod
DB_USER=postgres
DB_PASSWORD=Chu@angre2026
DB_HOST=localhost
DB_PORT=5432
EOF
    echo "Fichier .env cree"
else
    echo "Fichier .env existe deja"
fi

# 4. Base PostgreSQL
echo ""
echo "=== 4/7 Base PostgreSQL ==="
sudo -u postgres psql -c "SELECT 1 FROM pg_database WHERE datname='erp_chu_prod'" | grep -q 1 || \
    sudo -u postgres psql -c "CREATE DATABASE erp_chu_prod;"
echo "Base erp_chu_prod prete"

# 5. Migrations
echo ""
echo "=== 5/7 Migrations ==="
python manage.py migrate --noinput

# 6. Fichiers statiques + superuser
echo ""
echo "=== 6/7 Statiques + Superuser ==="
python manage.py collectstatic --noinput
python manage.py shell -c "
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@chu-ancre.ci', 'admin123')
    print('Superuser admin cree')
else:
    print('Superuser admin existe deja')
"

# 7. Lancer le serveur
echo ""
echo "=== 7/7 Lancement du serveur ==="
pkill -f "runserver.*8000" 2>/dev/null || true
sleep 1
nohup python manage.py runserver 0.0.0.0:8000 > server.log 2>&1 &
echo "Serveur lance (PID: $!)"

sleep 3
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/ 2>/dev/null)
if [ "$HTTP_CODE" = "302" ] || [ "$HTTP_CODE" = "200" ]; then
    echo ""
    echo "╔══════════════════════════════════════════════════╗"
    echo "║  ✅ DEPLOIEMENT REUSSI !                         ║"
    echo "║                                                  ║"
    echo "║  URL:    http://192.168.0.29:8000/              ║"
    echo "║  Login:  admin / admin123                        ║"
    echo "║                                                  ║"
    echo "║  Logs:   tail -f /home/chuangre/erp_chu_review/server.log ║"
    echo "╚══════════════════════════════════════════════════╝"
else
    echo "❌ Erreur HTTP $HTTP_CODE - verifiez server.log"
    tail -20 server.log
fi
