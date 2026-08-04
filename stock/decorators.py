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
                return redirect(redirect_url)
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