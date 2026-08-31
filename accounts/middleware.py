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
                # Journaliser la déconnexion AVANT logout() (qui flush la session)
                try:
                    from accounts.views import log_audit
                    from accounts.models import AuditConnexion
                    from accounts.views import get_client_ip
                    log_audit(request, f"Deconnexion de securite de {request.user.username}", type_action='LOGOUT')
                    AuditConnexion.objects.create(
                        utilisateur=request.user,
                        type_action='DECONNEXION',
                        description="Deconnexion de securite (trop de requetes rapides)",
                        adresse_ip=get_client_ip(request),
                        user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
                    )
                except Exception:
                    pass
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
            'custom_logout',
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
    - Superuser   → accès à TOUS les magasins (même règle qu'isolation_service)
    - 1 magasin   → sélection automatique (silencieuse)
    - Plusieurs   → l'utilisateur choisit via le formulaire existant
    - Le choix reste en session
    - Révalidation : si le magasin en session n'est plus autorisé, on le retire
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            try:
                from stock.models import Magasin
                if request.user.is_superuser:
                    magasins = Magasin.objects.all()
                else:
                    magasins = request.user.profil.magasins_autorises.all()
                magasin_ids = [str(m.id) for m in magasins]
                actif_id = request.session.get('magasin_actif_id')

                # ✅ CORRECTION : normaliser en str avant comparaison (le
                # magasin peut être stocké en int ou str selon le code appelant)
                actif_id_str = str(actif_id) if actif_id is not None else None

                if not actif_id_str and len(magasin_ids) == 1:
                    # Sélection automatique
                    request.session['magasin_actif_id'] = magasin_ids[0]
                elif actif_id_str and actif_id_str not in magasin_ids:
                    # CORRECTION : le magasin en session n'est plus autorisé
                    request.session.pop('magasin_actif_id', None)
                    if len(magasin_ids) == 1:
                        request.session['magasin_actif_id'] = magasin_ids[0]
            except Exception:
                pass

        return self.get_response(request)


class RecentModulesMiddleware:
    """
    Track les 20 derniers modules visites par utilisateur en session.
    Utilise pour la section "Acces rapide" sur la page d'accueil.
    """
    _URL_TO_CODENAME = None

    @classmethod
    def _build_map(cls):
        if cls._URL_TO_CODENAME is not None:
            return cls._URL_TO_CODENAME
        import re
        cls._URL_TO_CODENAME = {}
        try:
            import os
            view_path = os.path.join(os.path.dirname(__file__), 'views.py')
            with open(view_path, encoding='utf-8') as f:
                source = f.read()
            for m in re.finditer(r"'(menu_\w+)':\s*\{'url':\s*'([^']+)',", source):
                codename, url = m.group(1), m.group(2)
                cls._URL_TO_CODENAME[url.rstrip('/')] = codename
        except Exception:
            pass
        return cls._URL_TO_CODENAME

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.user.is_authenticated and request.method == 'GET':
            path = request.path.rstrip('/')
            url_map = self._build_map()
            codename = url_map.get(path)
            if codename:
                recent = request.session.get('_recent_modules', [])
                recent = [r for r in recent if r != codename]
                recent.insert(0, codename)
                request.session['_recent_modules'] = recent[:20]
        return response