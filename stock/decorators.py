import logging
from functools import wraps
from django.shortcuts import render, redirect
from django.contrib import messages

logger = logging.getLogger(__name__)


def magasin_requis(view_func):
    """
    Remplace @module_stock_lock.
    Vérifie qu'un magasin actif est en session, ou en choisit un si unique.
    """
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if request.session.get('magasin_actif_id'):
            return view_func(request, *args, **kwargs)

        from .services import StockService
        from .models import Magasin
        entreprise = getattr(request, 'entreprise', None)
        if not entreprise:
            messages.error(request, "⛔ Aucune entreprise active.")
            return redirect('/')

        user = request.user
        if user.is_superuser:
            magasins = Magasin.objects.filter(entreprise=entreprise)
        else:
            magasins = user.profil.magasins_autorises.filter(entreprise=entreprise)

        if magasins.count() == 1:
            request.session['magasin_actif_id'] = str(magasins.first().id)
            return view_func(request, *args, **kwargs)

        return render(request, 'stock/choix_magasin_obligatoire.html', {'url_voulue': request.path})
    return _wrapped_view


def catch_errors(logger_ref=None, redirect_url='/', msg_generic="❌ Une erreur technique est survenue."):
    """
    Décorateur uniformisant la gestion des erreurs.
    """
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
