#!/bin/bash
# ================================================================
#  Lancement Gunicorn — Production ERP CHU
#  Usage: bash start_prod.sh
# ================================================================
set -e

cd /home/chuangre/erp_chu_review
source venv/bin/activate

echo "=== Application des migrations ==="
python manage.py migrate --noinput

echo "=== Collecte des fichiers statiques ==="
python manage.py collectstatic --noinput

echo "=== Arret des anciens process ==="
pkill -9 -f 'gunicorn.*config.wsgi' 2>/dev/null || true
pkill -9 -f 'manage.py runserver' 2>/dev/null || true
sleep 1

echo "=== Demarrage Gunicorn ==="
# Workers = (2 * CPU cores) + 1
# Bind sur 127.0.0.1:8000 (nginx devant) ou 0.0.0.0:8000 (direct)
exec gunicorn config.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 3 \
    --threads 2 \
    --timeout 120 \
    --max-requests 1000 \
    --max-requests-jitter 50 \
    --access-logfile server-access.log \
    --error-logfile server-error.log \
    --log-level info \
    --pid gunicorn.pid
