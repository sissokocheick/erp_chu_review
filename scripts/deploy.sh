#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════
#  deploy.sh — Déploiement NexusERP (Linux / WSL / Git Bash)
#
#  Pipeline : validation env → migrate → collectstatic → check --deploy → gunicorn
#
#  Usage :
#    ./scripts/deploy.sh                # tout + lance gunicorn en arrière-plan
#    ./scripts/deploy.sh --check        # valide l'env + check --deploy, sans lancer
#    ./scripts/deploy.sh --backup       # sauvegarde PostgreSQL avant migrate
#    ./scripts/deploy.sh --no-migrate --no-collectstatic   # saute une étape
#    ./scripts/deploy.sh --port 8080 --workers 4 --foreground
#
#  Variables d'environnement (voir .env.example) — un fichier .env à la racine
#  du projet est chargé automatiquement (sans écraser les variables déjà posées).
# ═══════════════════════════════════════════════════════════════════════════
set -euo pipefail

# ── Chemins ────────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$BASE_DIR/.env"
VENV_PY="$BASE_DIR/venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="$BASE_DIR/venv/Scripts/python.exe"   # Git Bash / Windows
LOG_DIR="$BASE_DIR/logs"

# ── Arguments ──────────────────────────────────────────────────────────────
CHECK=0; NO_MIGRATE=0; NO_COLLECTSTATIC=0; FOREGROUND=0; BACKUP=0
PORT="${PORT:-8000}"
WORKERS="${WORKERS:-3}"
TIMEOUT="${TIMEOUT:-120}"
while [ $# -gt 0 ]; do
  case "$1" in
    --check)          CHECK=1 ;;
    --backup)         BACKUP=1 ;;
    --no-migrate)     NO_MIGRATE=1 ;;
    --no-collectstatic) NO_COLLECTSTATIC=1 ;;
    --foreground)     FOREGROUND=1 ;;
    --port)           shift; PORT="$1" ;;
    --workers)        shift; WORKERS="$1" ;;
    *) echo "❌ Argument inconnu : $1" >&2; exit 2 ;;
  esac
  shift
done

info()  { echo -e "\033[1;34m▶\033[0m $*"; }
ok()    { echo -e "\033[1;32m✔\033[0m $*"; }
fail()  { echo -e "\033[1;31m✘\033[0m $*" >&2; }

# ── 1. Chargement du .env (sans écraser l'environnement existant) ──────────
if [ -f "$ENV_FILE" ]; then
  info "Chargement de $ENV_FILE"
  while IFS='=' read -r key value; do
    key="$(echo "$key" | sed 's/^[[:space:]]*//;s/[[:space:]]*$//')"
    case "$key" in
      ''|\#*) continue ;;                       # lignes vides / commentaires
      export|export[[:space:]]*) key="${key#export }" ;;
    esac
    if [ -n "$key" ] && [ -z "${!key:-}" ]; then
      export "$key=$value"
    fi
  done < "$ENV_FILE"
else
  info "Pas de $ENV_FILE — utilisation des variables d'environnement existantes."
fi

# ── 2. Validation des variables obligatoires ───────────────────────────────
export DJANGO_DEBUG=False
MISSING=""
[ -n "${DJANGO_SECRET_KEY:-}" ] || MISSING="$MISSING DJANGO_SECRET_KEY"
if [ -z "${DATABASE_URL:-}" ] && [ -z "${DB_PASSWORD:-}" ]; then
  MISSING="$MISSING DB_PASSWORD (ou DATABASE_URL)"
fi
if [ -n "$MISSING" ]; then
  fail "Variables obligatoires manquantes :$MISSING"
  fail "Copier .env.example vers .env et renseigner les valeurs (voir PRODUCTION.md)."
  exit 1
fi
if [ "${#DJANGO_SECRET_KEY}" -lt 50 ]; then
  fail "DJANGO_SECRET_KEY fait moins de 50 caractères — générer une clé longue et aléatoire."
  exit 1
fi
if [ -z "${DJANGO_ALLOWED_HOSTS:-}" ]; then
  echo "⚠️  DJANGO_ALLOWED_HOSTS non défini (défaut '*') — à restreindre en production." >&2
fi
ok "Environnement validé (DEBUG=False)"

# ── 3. Sauvegarde (optionnelle mais recommandée avant migration) ───────────
if [ "$BACKUP" -eq 1 ]; then
  info "Sauvegarde PostgreSQL avant déploiement…"
  if ! (cd "$BASE_DIR" && "$VENV_PY" scripts/backup_db.py --quiet); then
    fail "La sauvegarde a échoué — déploiement annulé (voir scripts/backup_db.py --help)."
    exit 1
  fi
  ok "Sauvegarde effectuée (backups/)"
fi

# ── 4. Migrations ──────────────────────────────────────────────────────────
if [ "$NO_MIGRATE" -eq 0 ]; then
  info "Application des migrations…"
  (cd "$BASE_DIR" && "$VENV_PY" manage.py migrate)
  ok "Migrations appliquées"
else
  info "Migration ignorée (--no-migrate)"
fi

# ── 5. Statiques ───────────────────────────────────────────────────────────
if [ "$NO_COLLECTSTATIC" -eq 0 ]; then
  info "Collecte des fichiers statiques…"
  (cd "$BASE_DIR" && "$VENV_PY" manage.py collectstatic --noinput)
  ok "Statiques collectées"
else
  info "Collectstatic ignoré (--no-collectstatic)"
fi

# ── 6. Vérifications de sécurité ───────────────────────────────────────────
info "check --deploy…"
(cd "$BASE_DIR" && "$VENV_PY" manage.py check --deploy)
ok "check --deploy : aucun warning"

if [ "$CHECK" -eq 1 ]; then
  echo ""
  echo "✅ Vérifications terminées — lancer le serveur avec : ./scripts/deploy.sh"
  exit 0
fi

# ── 7. Lancement gunicorn ──────────────────────────────────────────────────
mkdir -p "$LOG_DIR"
GUNICORN_ARGS=(
  config.wsgi:application
  --bind "127.0.0.1:$PORT"
  --workers "$WORKERS"
  --timeout "$TIMEOUT"
  --access-logfile "$LOG_DIR/gunicorn-access.log"
  --error-logfile "$LOG_DIR/gunicorn-error.log"
)

if [ "$FOREGROUND" -eq 1 ]; then
  info "Lancement gunicorn (foreground) sur le port $PORT…"
  exec env DJANGO_DEBUG=False "$VENV_PY" -m gunicorn "${GUNICORN_ARGS[@]}"
fi

# Arrière-plan : on stoppe l'ancienne instance si elle tourne encore
PID_FILE="$BASE_DIR/.gunicorn.pid"
if [ -f "$PID_FILE" ]; then
  OLD_PID="$(cat "$PID_FILE")"
  if kill -0 "$OLD_PID" 2>/dev/null; then
    info "Arrêt de l'ancienne instance gunicorn (PID $OLD_PID)…"
    kill "$OLD_PID" 2>/dev/null || true
    sleep 2
  fi
  rm -f "$PID_FILE"
fi

info "Lancement gunicorn (arrière-plan) sur 127.0.0.1:$PORT — PID dans $PID_FILE"
(cd "$BASE_DIR" && nohup env DJANGO_DEBUG=False "$VENV_PY" -m gunicorn "${GUNICORN_ARGS[@]}" > "$LOG_DIR/gunicorn.out" 2>&1 & echo $! > "$PID_FILE")
sleep 3

if kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  ok "gunicorn démarré (PID $(cat "$PID_FILE")) — http://127.0.0.1:$PORT"
  # Vérification de santé /health/ (DB accessible => 200)
  HEALTHY=0
  for i in $(seq 1 10); do
    if curl -fsS "http://127.0.0.1:$PORT/health/" > /dev/null 2>&1; then
      HEALTHY=1
      break
    fi
    sleep 3
  done
  if [ "$HEALTHY" -eq 1 ]; then
    ok "Sain : /health/ répond (http://127.0.0.1:$PORT/health/)"
  else
    fail "/health/ ne répond pas après 30 s — base de données inaccessible ?"
    echo "   Le serveur tourne mais est probablement dégradé — voir $LOG_DIR/gunicorn-error.log"
    exit 1
  fi
  echo "   Logs : $LOG_DIR/gunicorn-access.log / gunicorn-error.log"
  echo "   Arrêter : kill \$(cat .gunicorn.pid)"
else
  fail "gunicorn n'a pas démarré — voir $LOG_DIR/gunicorn-error.log"
  if [ -s "$LOG_DIR/gunicorn-error.log" ]; then
    echo "   ── fin du log ──"
    tail -5 "$LOG_DIR/gunicorn-error.log" | sed 's/^/   /'
  fi
  echo "   ⚠️  Sur Windows, gunicorn n'est pas supporté : utiliser .\scripts\deploy.ps1 (fallback waitress)."
  exit 1
fi
