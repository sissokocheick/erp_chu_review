from django.apps import AppConfig
import logging

logger = logging.getLogger(__name__)


class AccountsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'accounts'
    verbose_name = "Comptes & Utilisateurs"

    def ready(self):
        # 1. ⚡ Sécurité multi-tenant
        try:
            import core.signals  # noqa
        except ImportError as e:
            logger.warning(f"core.signals non disponible : {e}")

        # 2. 📜 Historique des modifications sur les Groupes (Rôles)
        try:
            from simple_history import register
            from django.contrib.auth.models import Group
            register(Group, app="accounts")
        except Exception as e:
            # Logger l'erreur mais ne pas bloquer le démarrage
            logger.warning(f"Impossible d'enregistrer l'historique pour Group : {e}")

        # 3. 🔐 Audit connexions
        try:
            import accounts.signals  # noqa
        except ImportError as e:
            logger.warning(f"accounts.signals non disponible : {e}")
