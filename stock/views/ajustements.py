import os
import logging
from datetime import datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone

from accounts.permissions import verifier_permission
from core.pdf_service import DocumentGenerator
from ..decorators import magasin_requis, catch_errors
from ..forms import AjustementForm
from ..models import (
    Article, Magasin, StockItem, Ajustement, CircuitValidation,
)
from ..services.stock_service import StockService
from .catalogue import paginer, get_magasins_autorises
from .common_views import render_liste, get_magasin_actif, build_redirect_url

logger = logging.getLogger(__name__)


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_ajustements')
@magasin_requis
@catch_errors(redirect_url='liste_ajustements')
def liste_ajustements(request):
    """Dispatcher : GET affiche, POST crée."""
    if request.method == 'POST':
        return _creer_ajustement(request)
    return _afficher_ajustements(request)


def _afficher_ajustements(request):
    """Branche GET : filtres, pagination, contexte."""
    entreprise = request.entreprise
    magasin_actif_id = request.session.get('magasin_actif_id')

    qs = Ajustement.objects.select_related(
        'article', 'magasin', 'cree_par'
    ).filter(magasin__entreprise=entreprise)
    if magasin_actif_id:
        qs = qs.filter(magasin_id=magasin_actif_id)
    qs = qs.order_by('-date_creation')

    # Vérifier si l'utilisateur est valideur pour les ajustements
    peut_valider = request.user.is_superuser
    if not peut_valider:
        try:
            circuit = CircuitValidation.objects.get(
                type_document='AJUSTEMENT',
                entreprise=entreprise,
                is_deleted=False
            )
            if circuit.est_actif and circuit.valideurs.filter(id=request.user.id).exists():
                peut_valider = True
        except CircuitValidation.DoesNotExist:
            # CORRECTION : fail-closed - pas de circuit = pas de validation possible
            peut_valider = False

    extra = {
        'form': AjustementForm(entreprise=entreprise),
        'peut_creer': request.user.has_perm('accounts.menu_ajustements') or request.user.is_superuser,
        'peut_modifier': request.user.has_perm('accounts.menu_ajustements') or request.user.is_superuser,
        'peut_valider': peut_valider,
    }
    return render_liste(
        request, qs,
        template='stock/liste_ajustements.html',
        ajax_template='stock/ajustements_lignes.html',
        context_object_name='ajustements',
        date_field='date_creation',
        texte_champs=['article__designation__icontains', 'motif__icontains'],
        context_extra=extra
    )


def _creer_ajustement(request):
    """Branche POST : validation formulaire, création via service, redirection."""
    entreprise = request.entreprise
    magasins_autorises = get_magasins_autorises(request)
    magasin_actif_id = request.session.get('magasin_actif_id')
    if magasin_actif_id and not magasins_autorises.filter(id=magasin_actif_id).exists():
        messages.error(request, "⛔ Vous n'avez pas accès à ce magasin.")
        return redirect('liste_ajustements')
    form = AjustementForm(request.POST, entreprise=entreprise)

    if not form.is_valid():
        messages.error(request, "❌ Veuillez corriger les erreurs dans le formulaire.")
        return redirect('liste_ajustements')

    try:
        with transaction.atomic():
            ajustement = form.save(commit=False)
            ajustement.cree_par = request.user
            ajustement.modifie_par = request.user

            # Forcer le magasin depuis la session si non défini
            if not ajustement.magasin_id:
                magasin_actif_id = request.session.get('magasin_actif_id')
                if magasin_actif_id:
                    ajustement.magasin_id = magasin_actif_id

            # ✅ Sauvegarder explicitement en base AVANT le service
            ajustement.save()

            # ✅ VÉRIFIER LE CIRCUIT DE VALIDATION
            try:
                circuit = CircuitValidation.objects.get(
                    type_document='AJUSTEMENT',
                    entreprise=entreprise,
                    is_deleted=False
                )
                if circuit.est_actif:
                    # Circuit actif : on ne fait PAS les mouvements maintenant
                    ajustement.statut_validation = 'ATTENTE'
                    ajustement.save(update_fields=['statut_validation'])
                    messages.success(
                        request,
                        f"⏳ Ajustement {ajustement.id} créé en ATTENTE de validation. "
                        f"({ajustement.get_motif_display()}) — "
                        f"Article : {ajustement.article.designation}, Qté : {ajustement.quantite}"
                    )
                    return redirect('liste_ajustements')
            except CircuitValidation.DoesNotExist:
                pass  # Pas de circuit → continue et exécute

            # Pas de circuit actif : exécuter normalement
            StockService.ajuster_stock(ajustement)

        messages.success(
            request,
            f"✅ Stock ajusté ! ({ajustement.get_motif_display()}) — "
            f"Article : {ajustement.article.designation}, Qté : {ajustement.quantite}"
        )
        return redirect('liste_ajustements')

    except (ValidationError, ValueError) as e:
        messages.error(request, f"❌ {e}")
        return redirect('liste_ajustements')


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_ajustements')
@magasin_requis
@catch_errors(redirect_url='liste_ajustements')
def imprimer_ajustement(request, ajustement_id):
    entreprise = request.entreprise
    ajustement = get_object_or_404(
        Ajustement.objects.select_related('article', 'magasin', 'cree_par'),
        id=ajustement_id, magasin__entreprise=entreprise
    )

    gen = DocumentGenerator(request=request, entreprise=entreprise)
    pdf_bytes = gen.ajustement(ajustement)

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="Ajustement_{ajustement.id}.pdf"'
    return response
