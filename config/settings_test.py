"""Configuration de test sur PostgreSQL (même moteur qu'en production).

La suite de tests s'exécute sur PostgreSQL : les migrations, le SQL et le
comportement testés sont donc identiques à la production. Aucun autre moteur
n'est supporté (voir config/settings.py).
"""
import os

# Depuis le durcissement production, DEBUG défaut à False et settings.py lève
# si DJANGO_SECRET_KEY est absente. En test on force le mode dev AVANT l'import
# (les tests Client + E2E LiveServer tournent en HTTP : SECURE_SSL_REDIRECT et
# les cookies sécurisés doivent rester inactifs).
os.environ.setdefault('DJANGO_DEBUG', 'True')
# Désactive la journalisation des requêtes lentes (pas d'écriture disque
# dans les tests, et le logger django.db.backends resterait silencieux).
os.environ['TEST_MODE'] = '1'
# Les tests E2E Playwright (sync_api) font tourner leur propre boucle
# d'événements : Django l'interprète comme un contexte async et lève
# SynchronousOnlyOperation. On autorise l'accès sync aux objets ORM
# (limité à l'exécution des tests).
os.environ.setdefault('DJANGO_ALLOW_ASYNC_UNSAFE', '1')

from .settings import *

# PostgreSQL — même moteur qu'en production. Django crée automatiquement la
# base de test (test_<NAME>) à chaque exécution. Paramétrable via les mêmes
# variables d'environnement que le développement (DB_NAME, DB_USER, ...).
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': os.environ.get('DB_NAME', 'chu_angre_test'),
        'USER': os.environ.get('DB_USER', 'postgres'),
        'PASSWORD': os.environ.get('DB_PASSWORD', 'admin'),
        'HOST': os.environ.get('DB_HOST', 'localhost'),
        'PORT': os.environ.get('DB_PORT', '5432'),
    }
}

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

