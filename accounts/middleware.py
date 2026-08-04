# accounts/middleware.py — MONO-TENANT final
import time
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.contrib import messages
from django.urls import resolve


class AntiSpamMiddleware:
    """Anti-spam intelligent : ne compte que les requêtes POST."""
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and request.method == 'POST':
            LIMITE_REQUETES = 20
            FENETRE_TEMPS = 10

            maintenant = time.time()
            historique = request.session.get('historique_requetes', [])
            historique = [t for t in historique if maintenant - t < FENETRE_TEMPS]
            historique.append(maintenant)
            request.session['historique_requetes'] = historique

            if len(historique) > LIMITE_REQUETES:
                request.session['historique_requetes'] = []
                logout(request)
                messages.error(request, "⚠️ Trop de requêtes rapides. Déconnexion de sécurité.")
                return redirect('accounts:custom_login')

        return self.get_response(request)


class PasswordChangeMiddleware:
    """
    Bloque l'accès tant que l'utilisateur n'a pas changé son mot de passe initial.
    Vérifie BOTH session ET base (pour les réinit admin en temps réel).
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated:
            return self.get_response(request)

        must_change = request.session.get('must_change_password', False)
        # CORRECTION : si la session dit non, vérifier la base (réinit admin)
        if not must_change:
            try:
                if request.user.profil.doit_changer_mdp:
                    request.session['must_change_password'] = True
                    must_change = True
            except Exception:
                pass
        if not must_change:
            return self.get_response(request)

        try:
            current_url_name = resolve(request.path_info).url_name
        except Exception:
            current_url_name = None

        allowed_url_names = [
            'custom_login',
            'logout',
            'changer_mdp_obligatoire',
        ]

        if request.path.startswith(('/static/', '/media/')):
            return self.get_response(request)

        if current_url_name in allowed_url_names:
            return self.get_response(request)

        return redirect('accounts:changer_mdp_obligatoire')


class ThemeMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        theme = 'light'
        cookie_theme = request.COOKIES.get('theme_pref')

        if cookie_theme in ('light', 'dark'):
            theme = cookie_theme
        elif request.user.is_authenticated:
            try:
                theme = request.user.profil.theme_preference
            except Exception:
                theme = 'light'

        request.user_theme = theme

        response = self.get_response(request)

        if request.COOKIES.get('theme_pref') != theme:
            response.set_cookie(
                'theme_pref',
                theme,
                max_age=30*24*60*60,
                httponly=False,
                samesite='Lax'
            )
        return response


class MagasinAutoSelectMiddleware:
    """
    Comportement mono-tenant :
    - 1 magasin  → sélection automatique (silencieuse)
    - Plusieurs  → l'utilisateur choisit via le formulaire existant
    - Le choix reste en session
    - Révalidation : si le magasin en session n'est plus autorisé, on le retire
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            try:
                magasins = request.user.profil.magasins_autorises.all()
                magasin_ids = [str(m.id) for m in magasins]
                actif_id = request.session.get('magasin_actif_id')

                if not actif_id and len(magasin_ids) == 1:
                    # Sélection automatique
                    request.session['magasin_actif_id'] = magasin_ids[0]
                elif actif_id and actif_id not in magasin_ids:
                    # CORRECTION : le magasin en session n'est plus autorisé
                    request.session.pop('magasin_actif_id', None)
                    if len(magasin_ids) == 1:
                        request.session['magasin_actif_id'] = magasin_ids[0]
            except Exception:
                pass

        return self.get_response(request)