"""Configuration de test sans PostgreSQL"""
import os

# Depuis le durcissement production, DEBUG défaut à False et settings.py lève
# si DJANGO_SECRET_KEY est absente. En test on force le mode dev AVANT l'import
# (les tests Client + E2E LiveServer tournent en HTTP : SECURE_SSL_REDIRECT et
# les cookies sécurisés doivent rester inactifs).
os.environ.setdefault('DJANGO_DEBUG', 'True')

from .settings import *

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# Les migrations stock sont compatibles SQLite : on les garde actives.
# (Désactiver stock cassait le graphe : accounts.0001 dépend de stock.0001)
MIGRATION_MODULES = {}

# Simplifier pour les tests
USE_I18N = False
USE_TZ = False

# ── Performance des tests ───────────────────────────────────────────
# Hachage rapide pour la création d'utilisateurs en test (PBKDF2 à
# 720 000 itérations coûte ~300-500 ms par utilisateur). Aucun test ne
# vérifie la force du hasher, donc MD5 est sûr ici et accélère
# massivement les suites qui créent beaucoup d'utilisateurs.
PASSWORD_HASHERS = [
    'django.contrib.auth.hashers.MD5PasswordHasher',
]

# ── E2E (Playwright) ────────────────────────────────────────────────
# LiveServerTestCase sert les statiques depuis STATIC_ROOT (le dossier
# « collecté ») — vide sans collectstatic préalable. On pointe donc
# STATIC_ROOT vers le dossier source pour que les tests E2E exercent les
# vrais fichiers statiques (nx-ux.js, CSS…) sans étape supplémentaire.
STATIC_ROOT = BASE_DIR / 'static'
STATICFILES_DIRS = []

