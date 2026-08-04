from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.contrib.auth.models import User
import logging

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# SIGNALS MONO-TENANT (get_current_tenant SUPPRIMÉ)
# ══════════════════════════════════════════════════════════════════════════════

@receiver(post_save, sender=User)
def log_user_creation(sender, instance, created, **kwargs):
    """Log la création d'un nouvel utilisateur."""
    if created:
        logger.info(f"Nouvel utilisateur créé : {instance.username} (id={instance.id})")