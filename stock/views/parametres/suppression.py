from django.shortcuts import redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.http import require_POST
from django.urls import reverse

from accounts.permissions import verifier_permission
from ...decorators import catch_errors
from ...services.parametre_service import supprimer_entite, redirect_url_with_tab

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_parametres')
@require_POST
@catch_errors(redirect_url='/')
def supprimer_parametre(request, type_entite, id_entite):
    perm_map = {
        'famille': 'accounts.menu_fournisseurs',
        'fournisseur': 'accounts.menu_fournisseurs',
        'article': 'accounts.menu_fournisseurs',
        'magasin': 'accounts.menu_magasins',
        'service': 'accounts.menu_services',
        'specialite': 'accounts.menu_specialites',
        'fonction': 'accounts.menu_fonctions',
        'beneficiaire': 'accounts.menu_param_logistique',
        'motif': 'accounts.menu_motifs_annulation',
    }

    required_perm = perm_map.get(type_entite)
    if required_perm and not request.user.has_perm(required_perm) and not request.user.is_superuser:
        messages.error(request, "⛔ Accès refusé.")
        return redirect(reverse('parametres_administratifs'))

    try:
        id_entite = int(id_entite)
    except (ValueError, TypeError):
        messages.error(request, "❌ Identifiant invalide.")
        return redirect(reverse('parametres_administratifs'))

    ok, msg, url_name, tab = supprimer_entite(type_entite, id_entite, request.user)
    if ok:
        messages.success(request, msg)
    else:
        messages.error(request, msg)

    if url_name:
        if tab:
            return redirect(redirect_url_with_tab(url_name, tab))
        return redirect(url_name)
    return redirect(reverse('parametres_administratifs'))