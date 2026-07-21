"""
Context processors pour le projet ERP CHU.
A placer dans : accounts/context_processors.py

Configuration dans config/settings.py :
    TEMPLATES[0]['OPTIONS']['context_processors'] = [
        ...
        'accounts.context_processors.theme_context',
        'accounts.context_processors.entreprises_nav',
    ]
"""

from django.apps import apps
import logging

logger = logging.getLogger(__name__)


# ============================================================
# 1. THEME (clair / sombre)
# ============================================================
def theme_context(request):
    """Context processor pour le theme (clair/sombre)."""
    theme = 'light'

    cookie_theme = request.COOKIES.get('theme_pref')
    if cookie_theme in ('light', 'dark'):
        theme = cookie_theme
    elif request.user.is_authenticated:
        try:
            theme = request.user.profil.theme_preference
        except AttributeError:
            # profil n'existe pas sur l'utilisateur
            theme = 'light'
        except Exception:
            # Profil.DoesNotExist ou autre erreur
            theme = 'light'

    return {
        'user_theme': theme,
        'is_dark_mode': theme == 'dark',
    }


# ============================================================
# 2. ENTREPRISES (navigation multi-tenant)
# ============================================================
def entreprises_nav(request):
    """
    Context processor pour la navigation entre entreprises.
    Ajoute 'entreprises' et 'entreprise_active' au contexte de chaque template.

    Usage dans templates :
        {% for e in entreprises %}
            <a href="?entreprise={{ e.id }}">{{ e.nom }}</a>
        {% endfor %}

    ✅ CORRECTION : accede a l'entreprise via user.profil.entreprise
       (et non user.entreprises qui n'existe pas)
    """
    context = {
        'entreprises': [],
        'entreprise_active': None,
    }

    if not request.user.is_authenticated:
        return context

    try:
        # ✅ CORRECTION : acceder au profil via la relation OneToOne
        profil = getattr(request.user, 'profil', None)
        if profil is None:
            # Essayer de recuperer le profil via le modele
            try:
                Profil = apps.get_model('accounts', 'Profil')
                profil = Profil.objects.get(user=request.user)
            except Exception:
                logger.debug(
                    "[entreprises_nav] Profil manquant pour l'utilisateur %s (id=%s)",
                    request.user.username, request.user.id
                )
                return context

        # ✅ CORRECTION : l'entreprise vient du profil, pas de user.entreprises
        entreprise = getattr(profil, 'entreprise', None)
        if entreprise:
            context['entreprises'] = [entreprise]
            context['entreprise_active'] = entreprise

        # Si l'utilisateur est superuser, il peut voir toutes les entreprises
        if request.user.is_superuser:
            try:
                Entreprise = apps.get_model('accounts', 'Entreprise')
                context['entreprises'] = list(Entreprise.objects.filter(est_active=True))
            except Exception as e:
                logger.exception("[entreprises_nav] Erreur recuperation entreprises: %s", e)

    except Exception as e:
        logger.exception("[entreprises_nav] Erreur inattendue: %s", e)

    return context
