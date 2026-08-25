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

# 3. Fichier .env + export variables
echo ""
echo "=== 3/7 Configuration .env ==="
SECRET=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))" 2>/dev/null || echo 'production-secret-change-me')
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

# Exporter les variables dans l'environnement actuel
set -a
source .env
set +a
echo "Fichier .env cree et variables exportees"

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

# 7. Lancer Gunicorn (production)
echo ""
echo "=== 7/7 Lancement Gunicorn ==="
pkill -9 -f 'gunicorn.*config.wsgi' 2>/dev/null || true
pkill -9 -f 'manage.py runserver' 2>/dev/null || true
sleep 1
nohup gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 3 \
    --threads 2 \
    --timeout 120 \
    --max-requests 1000 \
    --max-requests-jitter 50 \
    --access-logfile server-access.log \
    --error-logfile server-error.log \
    --log-level info \
    --pid gunicorn.pid > /dev/null 2>&1 &
echo "Gunicorn lance (PID: $!)"

sleep 3
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/ 2>/dev/null)
if [ "$HTTP_CODE" = "302" ] || [ "$HTTP_CODE" = "200" ]; then
    echo ""
    echo "╔══════════════════════════════════════════════════╗"
    echo "║  ✅ DEPLOIEMENT REUSSI ! (Gunicorn)              ║"
    echo "║                                                  ║"
    echo "║  URL:    http://192.168.0.29:8000/              ║"
    echo "║  Login:  admin / admin123                        ║"
    echo "║  Workers: 3 | Threads: 2                        ║"
    echo "║                                                  ║"
    echo "║  Logs:   tail -f server-error.log               ║"
    echo "╚══════════════════════════════════════════════════╝"
else
    echo "❌ Erreur HTTP $HTTP_CODE - verifiez server-error.log"
    tail -20 server-error.log
fi
