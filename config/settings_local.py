"""
Override temporaire — SQLite pour test local sans PostgreSQL.
Usage: python manage.py --settings=config.settings_local runserver
"""
import os

os.environ.setdefault('DJANGO_DEBUG', 'True')
os.environ.setdefault('DJANGO_ALLOWED_HOSTS', '*')
os.environ.setdefault('TRUSTED_INTERNAL', '1')

from config.settings import *  # noqa: F401,F403

# ── Remplacer PostgreSQL par SQLite pour le test local ──
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db_test.sqlite3',
    }
}

# Pas de STATICFILES_STORAGE en SQLite local
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage",
    },
}

# Désactiver SSL en local
SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_HSTS_SECONDS = 0

# Désactiver WeasyPrint (non disponible sur Windows sans GTK)
WEASYPRINT_ENABLED = False

DEBUG = True
