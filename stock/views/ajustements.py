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
from stock.services.isolation_service import get_magasins_autorises
from ..decorators import magasin_requis, catch_errors
from ..forms import AjustementForm
from ..models import (
    Article, Magasin, StockItem, Ajustement, CircuitValidation,
)
from ..services.stock_service import StockService
from .catalogue import paginer
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
    magasin_actif_id = request.session.get('magasin_actif_id')
    magasin_actif = get_magasin_actif(request)

    qs = Ajustement.objects.select_related(
        'article', 'magasin', 'cree_par', 'valide_par'
    ).all()
    if magasin_actif_id:
        qs = qs.filter(magasin_id=magasin_actif_id)
    qs = qs.order_by('-date_creation')

    # Vérifier si l'utilisateur est valideur pour les ajustements
    peut_valider = request.user.is_superuser
    if not peut_valider:
        try:
            circuit = CircuitValidation.objects.get(
                type_document='AJUSTEMENT',
                is_deleted=False
            )
            if circuit.est_actif and circuit.valideurs.filter(id=request.user.id).exists():
                peut_valider = True
        except CircuitValidation.DoesNotExist:
            peut_valider = False

    extra = {
        'form': AjustementForm(),
        'magasin_actif': magasin_actif,
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
    """Branche POST : validation formulaire, création via service, redirection.

    CRITIQUE : un seul save() sur Ajustement pour éviter les doublons de signaux post_save.
    """
    # ═════ PROTECTION ANTI-DOUBLE-CLIC ═════
    post_token = request.POST.get('post_token', '')
    last_token = request.session.get('last_ajustement_token', '')

    if post_token and post_token == last_token:
        messages.warning(request, "⚠️ Cet ajustement a déjà été soumis.")
        return redirect('liste_ajustements')

    if post_token:
        request.session['last_ajustement_token'] = post_token
    # ════════════════════════════════════════

    magasins_autorises = get_magasins_autorises(request)
    magasin_actif_id = request.session.get('magasin_actif_id')
    if magasin_actif_id and not magasins_autorises.filter(id=magasin_actif_id).exists():
        messages.error(request, "⛔ Vous n'avez pas accès à ce magasin.")
        return redirect('liste_ajustements')
    form = AjustementForm(request.POST)

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

            # ═════ DÉTERMINER LE STATUT AVANT LE PREMIER (ET UNIQUE) SAVE() ═════
            # Par défaut : pas de circuit = exécution immédiate
            ajustement.statut_validation = 'VALIDE'

            try:
                circuit = CircuitValidation.objects.get(
                    type_document='AJUSTEMENT',
                    is_deleted=False
                )
                if circuit.est_actif:
                    # Circuit actif : on ne fait PAS les mouvements maintenant
                    ajustement.statut_validation = 'ATTENTE'
            except CircuitValidation.DoesNotExist:
                pass  # Pas de circuit → reste sur 'VALIDE'
            # ════════════════════════════════════════════════════════════════════

            # UN SEUL save() ici — évite les doubles déclenchements de post_save
            ajustement.save()

            # Si pas de circuit actif : exécuter le mouvement de stock maintenant
            if ajustement.statut_validation == 'VALIDE':
                StockService.ajuster_stock(ajustement)
                messages.success(
                    request,
                    f"✅ Stock ajusté ! ({ajustement.get_motif_display()}) — "
                    f"Article : {ajustement.article.designation}, Qté : {ajustement.quantite}"
                )
            else:
                messages.success(
                    request,
                    f"⏳ Ajustement {ajustement.id} créé en ATTENTE de validation. "
                    f"({ajustement.get_motif_display()}) — "
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
def valider_ajustement(request, ajustement_id):
    """Valider un ajustement en attente : exécute le mouvement de stock.

    Protection race-condition : select_for_update() + statut mis à jour AVANT ajuster_stock.
    Protection double-clic : token de session.
    """
    # ═════ PROTECTION ANTI-DOUBLE-CLIC ═════
    if request.method != 'POST':
        messages.error(request, "❌ Cette action doit être effectuée en POST.")
        return redirect('liste_ajustements')
    token = request.POST.get('token', '')
    last_token = request.session.get('last_valider_token', '')
    if token and token == last_token:
        messages.warning(request, "⚠️ Cet ajustement a déjà été validé.")
        return redirect('liste_ajustements')
    if token:
        request.session['last_valider_token'] = token
    # ════════════════════════════════════════

    with transaction.atomic():
        # Verrouiller la ligne pour éviter les race conditions
        ajustement = get_object_or_404(
            Ajustement.objects.select_for_update().select_related('article', 'magasin'),
            id=ajustement_id
        )

        # Vérifier que c'est bien en attente (bloque les doublons)
        if ajustement.statut_validation != 'ATTENTE':
            messages.error(request, "❌ Cet ajustement n'est pas en attente de validation.")
            return redirect('liste_ajustements')

        # Vérifier que l'utilisateur est valideur
        peut_valider = request.user.is_superuser
        if not peut_valider:
            try:
                circuit = CircuitValidation.objects.get(
                    type_document='AJUSTEMENT',
                    is_deleted=False
                )
                if circuit.est_actif and circuit.valideurs.filter(id=request.user.id).exists():
                    peut_valider = True
            except CircuitValidation.DoesNotExist:
                peut_valider = False

        if not peut_valider:
            messages.error(request, "⛔ Vous n'êtes pas autorisé à valider cet ajustement.")
            return redirect('liste_ajustements')

        # ═════ BLOCAGE ANTI-DOUBLON ═════
        # Mettre le statut à VALIDE AVANT d'appeler ajuster_stock.
        # Ainsi, une seconde requête (même en parallèle) verra 'VALIDE'
        # et ne passera pas le test 'ATTENTE' ci-dessus.
        ajustement.statut_validation = 'VALIDE'
        ajustement.valide_par = request.user
        ajustement.date_validation = timezone.now()
        ajustement.save(update_fields=['statut_validation', 'valide_par', 'date_validation'])

        # Exécuter le mouvement de stock
        StockService.ajuster_stock(ajustement)

    messages.success(
        request,
        f"✅ Ajustement validé ! ({ajustement.get_motif_display()}) — "
        f"Article : {ajustement.article.designation}, Qté : {ajustement.quantite}"
    )
    return redirect('liste_ajustements')


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_ajustements')
@magasin_requis
@catch_errors(redirect_url='liste_ajustements')
def rejeter_ajustement(request, ajustement_id):
    """Rejeter un ajustement en attente : passe le statut à REJETE, ne touche pas au stock."""
    if request.method != 'POST':
        messages.error(request, "❌ Cette action doit être effectuée en POST.")
        return redirect('liste_ajustements')

    ajustement = get_object_or_404(Ajustement, id=ajustement_id)

    # Vérifier que l'utilisateur est valideur
    peut_valider = request.user.is_superuser
    if not peut_valider:
        try:
            circuit = CircuitValidation.objects.get(
                type_document='AJUSTEMENT',
                is_deleted=False
            )
            if circuit.est_actif and circuit.valideurs.filter(id=request.user.id).exists():
                peut_valider = True
        except CircuitValidation.DoesNotExist:
            peut_valider = False

    if not peut_valider:
        messages.error(request, "⛔ Vous n'êtes pas autorisé à rejeter cet ajustement.")
        return redirect('liste_ajustements')

    if ajustement.statut_validation != 'ATTENTE':
        messages.error(request, "❌ Seuls les ajustements en attente peuvent être rejetés.")
        return redirect('liste_ajustements')

    article_nom = ajustement.article.designation
    ajustement.statut_validation = 'REJETE'
    ajustement.modifie_par = request.user
    ajustement.date_modification = timezone.now()
    ajustement.save(update_fields=['statut_validation', 'modifie_par', 'date_modification'])

    messages.success(request, f"🗑️ Ajustement rejeté — Article : {article_nom}")
    return redirect('liste_ajustements')
