# config/settings_perf.py — Settings override pour test de charge SQLite
import os

# Must set these BEFORE importing config.settings
os.environ['DJANGO_DEBUG'] = 'True'
os.environ['DJANGO_SECRET_KEY'] = 'perf-test-key-not-for-production'
os.environ['DJANGO_ALLOWED_HOSTS'] = 'localhost,127.0.0.1'

from config.settings import *  # noqa: F401, F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'db_perf_test.sqlite3'),
    }
}

DEBUG = True
