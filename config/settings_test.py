"""Configuration de test sans PostgreSQL"""
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
