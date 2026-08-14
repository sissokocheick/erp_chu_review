# 🚀 Mise en production — Checklist

Ce document liste les variables d'environnement et les étapes nécessaires pour
déployer l'application en production de façon sûre. L'application est **mono-tenant**
et utilise **PostgreSQL** en production.

## 1. Variables d'environnement obligatoires

| Variable | Rôle | Exemple |
|---|---|---|
| `DJANGO_SECRET_KEY` | Clé secrète Django (≥ 50 caractères aléatoires) | `openssl rand -hex 50` |
| `DJANGO_DEBUG` | **Doit être `False`** (défaut sûr : `False`) | `False` |
| `DJANGO_ALLOWED_HOSTS` | Hôtes autorisés, séparés par des virgules | `erp.chu.example,www.erp.chu.example` |
| `DB_NAME` | Nom de la base PostgreSQL | `chu_angre_db` |
| `DB_USER` | Utilisateur PostgreSQL | `chu_app` |
| `DB_PASSWORD` | Mot de passe PostgreSQL | — |
| `DB_HOST` | Hôte PostgreSQL | `localhost` |
| `DB_PORT` | Port PostgreSQL | `5432` |

> Alternative : définir `DATABASE_URL` (ex. `postgres://user:pass@host:5432/db`)
> pour la config complète en une variable (SSL requis si le serveur l'impose).

### Variables optionnelles

| Variable | Rôle |
|---|---|
| `CSRF_TRUSTED_ORIGINS` | Origines de confiance CSRF (ex. `https://erp.chu.example`) — **à définir si le site est servi en HTTPS derrière un proxy** |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` | Serveur SMTP pour les notifications par e-mail |
| `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_FROM_NUMBER` | Notifications SMS (Twilio) |
| `DJANGO_ADMIN_USERNAME`, `DJANGO_ADMIN_EMAIL`, `DJANGO_ADMIN_PASSWORD` | Création du superutilisateur initial (optionnel, `createsuperuser` fonctionne aussi) |

**Garde-fous déjà en place** (vérifiés par `manage.py check --deploy`) :
- Sans `DJANGO_SECRET_KEY`, l'app **refuse de démarrer** si `DJANGO_DEBUG=False`.
- Sans `DB_PASSWORD` (ni `DATABASE_URL`), l'app **refuse de démarrer** en production.
- `SECURE_SSL_REDIRECT`, HSTS, cookies de session/CSRF sécurisés et
  `SECURE_CONTENT_TYPE_NOSNIFF` s'activent **automatiquement** dès que `DJANGO_DEBUG=False`.
- `X_FRAME_OPTIONS = 'SAMEORIGIN'` (volontaire pour les aperçus PDF en iframe),
  warning `security.W019` silencé explicitement.

## 2. Étapes de déploiement

### Automatisé (recommandé)

Deux scripts font tout le pipeline (chargement `.env` → validation → `migrate` →
`collectstatic` → `check --deploy` → lancement du serveur) :

```bash
# Linux / WSL / Git Bash :
./scripts/deploy.sh                     # tout + gunicorn en arrière-plan
./scripts/deploy.sh --check             # validation + check --deploy, sans lancer
./scripts/deploy.sh --port 8080 --workers 4

# Windows PowerShell :
.\scripts\deploy.ps1                    # tout + serveur (gunicorn ou waitress)
.\scripts\deploy.ps1 -Check
.\scripts\deploy.ps1 -Port 8080 -Workers 4
```

> Sur **Windows**, gunicorn n'est pas supporté : `deploy.ps1` bascule sur
> **waitress** (`pip install waitress`) ou vous guide vers WSL/Linux.

### Manuel

```bash
# 1. Dépendances (environnement propre)
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 2. Migrations
python manage.py migrate

# 3. Fichiers statiques (servis par WhiteNoise)
python manage.py collectstatic --noinput

# 4. Vérifications de sécurité
DJANGO_DEBUG=False DJANGO_SECRET_KEY=<cle> DB_PASSWORD=<mdp> \
  python manage.py check --deploy      # doit afficher 0 warning

# 5. Lancement (gunicorn, derrière nginx)
DJANGO_DEBUG=False ... gunicorn config.wsgi:application \
  --bind 127.0.0.1:8000 --workers 3 --timeout 120
```

## 3. Reverse proxy (nginx) — recommandé

- Terminer le TLS en amont (certificat Let's Encrypt / entreprise).
- Rediriger tout le trafic HTTP vers HTTPS.
- Si le proxy ajoute `X-Forwarded-Proto: https`, définir dans `settings.py` :
  ```python
  SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
  ```
  (à n'activer QUE derrière un proxy de confiance, sinon risque de spoofing).

## 4. Tâches planifiées (cron / Planificateur Windows)

- **Inventaire tournant** : `python manage.py generer_inventaires_tournants`
  (rotation du comptage par famille/zone à l'échéance ; déjà déclenché à la
  connexion, le cron le rend indépendant des connexions).
- Sauvegarde quotidienne de la base PostgreSQL (`pg_dump`).

## 5. Rappels

- Ne jamais committer `SECRET_KEY`, mots de passe DB ou identifiants Twilio
  (`.gitignore` couvre `.env*`, `media/`, `staticfiles/`).
- La session expire après 20 minutes d'inactivité (`SESSION_COOKIE_AGE`).
- La politique de mots de passe Django est active (longueur, similarité,
  mots courants, numériques).
- En développement local : `DJANGO_DEBUG=True` (voir `.freebuff/run.md`).
