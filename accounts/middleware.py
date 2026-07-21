# accounts/middleware.py
import time
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.contrib import messages
from django.http import HttpResponseRedirect
from django.urls import resolve, reverse
from accounts.models import Entreprise
from core.managers import set_current_tenant


class AntiSpamMiddleware:
    """
    Anti-spam intelligent : ne compte que les requêtes POST non-AJAX.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and request.method == 'POST':
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return self.get_response(request)

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


class SaaSMiddleware:
    """
    Middleware multi-tenant :
    - Superuser : peut naviguer même si aucune entreprise active (fallback)
    - Utilisateur normal : déconnecté seulement si vraiment orphelin
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        set_current_tenant(None)
        request.entreprise = None

        if request.user.is_authenticated:
            if request.user.is_superuser:
                eid = request.session.get('entreprise_id')
                if eid:
                    try:
                        request.entreprise = Entreprise.objects.get(id=eid, est_active=True)
                    except Entreprise.DoesNotExist:
                        request.session.pop('entreprise_id', None)
                        request.entreprise = None

                # 🔧 FALLBACK : si aucune active, prendre la première (même inactive)
                if not request.entreprise:
                    first = Entreprise.objects.filter(est_active=True).first()
                    if not first:
                        first = Entreprise.objects.first()
                    if first:
                        request.session['entreprise_id'] = first.id
                        request.entreprise = first
                    else:
                        # ✅ Message clair quand aucune entreprise n'existe
                        messages.warning(
                            request,
                            "⚠️ Aucune entreprise n'existe dans le système. Veuillez en créer une depuis la page de gestion des entreprises."
                        )
            else:
                profil = getattr(request.user, 'profil', None)
                if profil and profil.entreprise:
                    if profil.entreprise.est_active:
                        request.entreprise = profil.entreprise
                    else:
                        request.entreprise = profil.entreprise
                else:
                    logout(request)
                    request.session.flush()
                    messages.error(
                        request,
                        "⛔ Votre compte n'est associé à aucune entreprise. Contactez l'administrateur."
                    )
                    return redirect('accounts:custom_login')

            if request.entreprise:
                set_current_tenant(request.entreprise)

        try:
            response = self.get_response(request)
        finally:
            set_current_tenant(None)

        return response


class PasswordChangeMiddleware:
    """Bloque tout accès tant que l'utilisateur n'a pas changé son mot de passe initial."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not request.user.is_authenticated:
            return self.get_response(request)

        if not request.session.get('must_change_password'):
            return self.get_response(request)

        # ✅ CORRECTION : utiliser resolve() + reverse() au lieu de hardcoder /accounts/
        try:
            current_url_name = resolve(request.path_info).url_name
        except Exception:
            current_url_name = None

        # URLs autorisées même avec must_change_password
        allowed_url_names = [
            'custom_login',
            'logout',
            'changer_mdp_obligatoire',
        ]

        # Autoriser les fichiers statiques et médias
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
