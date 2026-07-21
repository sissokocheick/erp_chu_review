# stock/apps.py
from django.apps import AppConfig


class StockConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'stock'
    verbose_name = "Gestion des Stocks"

    def ready(self):
        # ⚡ Import des signaux de sécurité
        import core.signals  # noqa