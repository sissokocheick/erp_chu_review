# core/apps.py
from django.apps import AppConfig


class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'
    verbose_name = "Core - Gestion Multi-Tenant"

    def ready(self):
        # ✅ CORRECTION : import explicite des signaux (ne pas compter sur accounts.apps)
        from core import signals  # noqa
