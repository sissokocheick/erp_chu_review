import logging
from functools import wraps
from django.shortcuts import render, redirect
from django.contrib import messages

logger = logging.getLogger(__name__)


def magasin_requis(view_func):
    """
    Vérifie qu'un magasin actif est en session, ou en choisit un si unique.
    Version mono-tenant.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if request.session.get('magasin_actif_id'):
            return view_func(request, *args, **kwargs)

        from .models import Magasin

        user = request.user
        if user.is_superuser:
            magasins = Magasin.objects.all()
        else:
            try:
                magasins = user.profil.magasins_autorises.all()
            except Exception:
                magasins = Magasin.objects.none()

        if magasins.count() == 1:
            request.session['magasin_actif_id'] = str(magasins.first().id)
            return view_func(request, *args, **kwargs)

        if magasins.count() == 0:
            messages.error(request, "⛔ Vous n'avez accès à aucun magasin.")
            return redirect('/')

        return render(request, 'stock/choix_magasin_obligatoire.html', {'url_voulue': request.path})
    return _wrapped_view


def catch_errors(logger_ref=None, redirect_url='/', msg_generic="❌ Une erreur technique est survenue."):
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            try:
                return view_func(request, *args, **kwargs)
            except ValueError as e:
                try:
                    messages.error(request, f"⚠️ {str(e)}")
                except Exception:
                    pass
                # ✅ UX : en cas d'erreur de validation, rester sur la page d'origine
                # (le referer) plutôt que de renvoyer à l'accueil, qui fait perdre
                # la saisie. La conservation complète des données (form_data)
                # reste à faire vue par vue (voir UX_POLICY §2).
                return redirect(_referer_sur(request, redirect_url))
            except Exception as e:
                log = logger_ref or logger
                log.exception(f"[{view_func.__name__}] {e}")
                try:
                    messages.error(request, msg_generic)
                except Exception:
                    pass
                return redirect(redirect_url)
        return _wrapped_view
    return decorator


def _referer_sur(request, fallback):
    """Retourne le referer s'il est interne (même hôte), sinon le fallback."""
    referer = request.META.get('HTTP_REFERER', '')
    if referer:
        try:
            from urllib.parse import urlparse
            hote = request.get_host()
            if urlparse(referer).netloc == hote:
                return referer
        except Exception:
            pass
    return fallback