"""Configuration de test sans PostgreSQL"""
from .settings import *

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    }
}

# Désactiver les migrations problématiques pour SQLite
MIGRATION_MODULES = {
    'stock': None,  # Skip stock migrations for tests
}

# Simplifier pour les tests
USE_I18N = False
USE_TZ = False
