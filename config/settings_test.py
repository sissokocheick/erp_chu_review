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
