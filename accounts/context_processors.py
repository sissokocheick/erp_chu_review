from django.apps import apps
from django.conf import settings
import logging

logger = logging.getLogger(__name__)


def theme_context(request):
    """Ajoute le thème préféré au contexte de chaque template."""
    theme = 'light'
    if hasattr(request, 'COOKIES'):
        cookie_theme = request.COOKIES.get('theme_pref')
        if cookie_theme in ('light', 'dark'):
            theme = cookie_theme
    elif request.user.is_authenticated:
        try:
            theme = request.user.profil.theme_preference
        except Exception:
            pass
    return {'theme': theme}


def notifications_context(request):
    """Notifications non lues pour l'utilisateur connecté."""
    if not request.user.is_authenticated:
        return {}

    try:
        from accounts.models import Notification
        from django.db.models import Count
        # CORRECTION : une seule requête avec slicing
        qs = Notification.objects.filter(utilisateur=request.user, est_lue=False)
        notifications = list(qs.order_by('-date_creation')[:5])
        count = qs.count()
        return {
            'notifications_non_lues': notifications,
            'notifications_count': count,
        }
    except Exception:
        return {}