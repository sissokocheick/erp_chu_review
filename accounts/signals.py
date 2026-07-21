from django.contrib.auth import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver
import logging

from .models import AuditConnexion

logger = logging.getLogger(__name__)


def get_client_ip(request):
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        return x_forwarded_for.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


@receiver(user_logged_in)
def log_connexion(sender, request, user, **kwargs):
    """Log une connexion réussie. Ne bloque jamais la connexion."""
    try:
        AuditConnexion.objects.create(
            utilisateur=user,
            type_action='CONNEXION',
            description="Connexion réussie",
            adresse_ip=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:255]
        )
    except Exception as e:
        logger.error(f"Erreur lors du log de connexion : {e}")


@receiver(user_logged_out)
def log_deconnexion(sender, request, user, **kwargs):
    """Log une déconnexion. Ne bloque jamais la déconnexion."""
    if not user:
        return
    try:
        AuditConnexion.objects.create(
            utilisateur=user,
            type_action='DECONNEXION',
            description="Déconnexion",
            adresse_ip=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:255]
        )
    except Exception as e:
        logger.error(f"Erreur lors du log de déconnexion : {e}")


@receiver(user_login_failed)
def log_echec_connexion(sender, credentials, request, **kwargs):
    """Log une tentative de connexion échouée."""
    try:
        username = credentials.get('username', 'inconnu') if credentials else 'inconnu'
        AuditConnexion.objects.create(
            utilisateur=None,
            type_action='ECHEC',
            description=f"Échec de connexion pour {username}",
            adresse_ip=get_client_ip(request) if request else None,
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:255] if request else ''
        )
    except Exception as e:
        logger.error(f"Erreur lors du log d'échec de connexion : {e}")
