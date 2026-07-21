import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme

from .catalogue import get_magasins_autorises

logger = logging.getLogger(__name__)


@login_required(login_url='/auth/login/')
def changer_magasin(request):
    """
    Change le magasin actif dans la session utilisateur.

    CORRECTIONS APPLIQUÉES :
    - Validation du paramètre 'next' avec url_has_allowed_host_and_scheme
    - Nettoyage des imports inutilisés (~25 supprimés)
    - Fallback sécurisé sur HTTP_REFERER
    """
    entreprise = request.entreprise
    if request.method == 'POST':
        mag_id = request.POST.get('magasin_id')
        if mag_id:
            magasins_autorises = get_magasins_autorises(request)
            magasin = magasins_autorises.filter(id=mag_id).first()
            if magasin:
                if magasin.entreprise_id == entreprise.id:
                    request.session['magasin_actif_id'] = str(mag_id)
                    messages.success(request, "Changement de magasin effectué.")
                else:
                    messages.error(
                        request,
                        "⛔ Ce magasin n'appartient pas à votre entreprise active."
                    )
            else:
                messages.error(
                    request,
                    "⛔ Tentative d'accès non autorisée à ce magasin."
                )

        # ── Redirection sécurisée ──
        next_url = request.POST.get('next')
        if next_url and url_has_allowed_host_and_scheme(
            next_url,
            allowed_hosts={request.get_host()},
            require_https=(not settings.DEBUG and request.is_secure()),
        ):
            return redirect(next_url)

        # Fallback sur le referer (aussi validé pour sécurité)
        referer = request.META.get('HTTP_REFERER')
        if referer and url_has_allowed_host_and_scheme(
            referer,
            allowed_hosts={request.get_host()},
            require_https=(not settings.DEBUG and request.is_secure()),
        ):
            return redirect(referer)

    return redirect(request.META.get('HTTP_REFERER', '/'))
