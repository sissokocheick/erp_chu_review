import os
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from django.apps import apps
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction, IntegrityError
from django.db.models import Q, F, Sum, Prefetch, OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
try:
    from weasyprint import HTML
except OSError:
    HTML = None

from itertools import chain
from operator import attrgetter

from accounts.permissions import verifier_permission
from core.models import Service
from ..decorators import magasin_requis, catch_errors
from ..models import (
    Mouvement, BonMouvement, LigneBon, MotifAnnulation,
    Article, Magasin, StockItem, Ajustement,
    Fournisseur, Beneficiaire,
    CampagneInventaire, LigneInventaire, CircuitValidation,
    LivraisonPartielle, DemandeMateriel, LigneDemande,
    AccuseReception,
    LivraisonLigne)
from .catalogue import paginer, get_magasins_autorises

logger = logging.getLogger(__name__)
User = get_user_model()


def _element_historique(h):
    """Description d'un enregistrement historique sans accès FK par ligne (anti N+1)."""
    modele = h.__class__.__name__.replace('Historical', '')
    if modele == 'Mouvement':
        try:
            art = h.article
            designation = art.designation if art else ''
        except Exception:
            designation = '(Article supprimé)'
        return f"{getattr(h, 'type_mouvement', '') or ''} — {designation} x{getattr(h, 'quantite', '') or ''}"
    if modele == 'Group':
        return getattr(h, 'name', '') or ''
    if modele == 'Magasin':
        return getattr(h, 'nom', '') or ''
    if modele == 'Article':
        ref = getattr(h, 'reference', '') or ''
        des = getattr(h, 'designation', '') or ''
        return f"[{ref}] {des}" if ref else des
    if modele == 'Fournisseur':
        return f"{getattr(h, 'code', '') or ''} - {getattr(h, 'raison_sociale', '') or ''}"
    if modele == 'Service':
        return f"{getattr(h, 'code', '') or ''} - {getattr(h, 'nom', '') or ''}"
    return str(getattr(h, 'id', ''))


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_historique')
@magasin_requis
def journal_historique(request):
    """Vue journal d'historique (GET uniquement)."""
    q = request.GET.get('q', '').lower()
    date_range = request.GET.get('date_range', '')

    magasin_id = request.session.get('magasin_actif_id')
    magasin_nom = "TOUS LES MAGASINS"
    if magasin_id:
        try:
            magasin_nom = Magasin.objects.get(id=magasin_id).nom
        except Magasin.DoesNotExist:
            pass

    date_debut = None
    date_fin = None
    if date_range:
        try:
            dates = date_range.split(' - ')
            if len(dates) == 2:
                date_debut = datetime.strptime(dates[0].strip(), '%d/%m/%Y').date()
                date_fin = datetime.strptime(dates[1].strip(), '%d/%m/%Y').date()
        except ValueError:
            pass

    if not date_debut or not date_fin:
        date_fin = timezone.now().date()
        date_debut = date_fin - timedelta(days=60)

    h_articles = Article.history.select_related('history_user').filter(
        history_date__date__gte=date_debut,
        history_date__date__lte=date_fin
    ).order_by('-history_date')[:50]
    h_magasins = Magasin.history.select_related('history_user').filter(
        history_date__date__gte=date_debut,
        history_date__date__lte=date_fin
    ).order_by('-history_date')[:50]
    h_fournisseurs = Fournisseur.history.select_related('history_user').filter(
        history_date__date__gte=date_debut,
        history_date__date__lte=date_fin
    ).order_by('-history_date')[:50]

    # ✅ CORRECTION : restreindre le journal au périmètre autorisé de
    # l'utilisateur (et non à TOUS les magasins) quand aucun magasin actif.
    magasins_ids = list(
        get_magasins_autorises(request).values_list('id', flat=True)
    )
    if magasins_ids:
        h_mouvements = Mouvement.history.select_related(
            'history_user', 'article', 'magasin', 'service_demandeur'
        ).filter(
            magasin_id__in=magasins_ids,
            history_date__date__gte=date_debut,
            history_date__date__lte=date_fin
        ).order_by('-history_date')[:50]
    else:
        h_mouvements = Mouvement.history.none()

    h_services = Service.history.select_related('history_user').filter(
        history_date__date__gte=date_debut,
        history_date__date__lte=date_fin
    ).order_by('-history_date')[:50] if hasattr(Service, 'history') else Service.objects.none()

    h_roles = Group.history.select_related('history_user').filter(
        history_date__date__gte=date_debut,
        history_date__date__lte=date_fin
    ).order_by('-history_date')[:50] if hasattr(Group, 'history') else Group.objects.none()

    if magasin_id:
        h_mouvements = [m for m in h_mouvements if getattr(m, 'magasin_id', None) == int(magasin_id)]
        h_magasins = [m for m in h_magasins if m.id == int(magasin_id)]

    historique_brut = sorted(
        chain(h_articles, h_magasins, h_services, h_fournisseurs, h_mouvements, h_roles),
        key=attrgetter('history_date'), reverse=True
    )

    journal_activites = []
    for h in historique_brut:
        utilisateur = h.history_user.username.capitalize() if getattr(h, 'history_user', None) else "Système"
        modele = h.__class__.__name__.replace('Historical', '')
        if modele == 'Group':
            modele = 'Rôle / Accès'
        # Construction explicite : évite les accès FK par ligne (N+1) via str(h)
        element = _element_historique(h)
        action_text = "Création" if h.history_type == '+' else "Modification" if h.history_type == '~' else "Suppression"

        if q:
            texte_global = f"{utilisateur} {modele} {element} {action_text}".lower()
            if q not in texte_global:
                continue

        if h.history_type == '+':
            action_html = '<span style="background: #d4edda; color: #155724; padding: 4px 10px; border-radius: 4px; font-weight: bold; font-size: 12px;"><i class="fas fa-plus"></i> Création</span>'
        elif h.history_type == '~':
            action_html = '<span style="background: #cce5ff; color: #004085; padding: 4px 10px; border-radius: 4px; font-weight: bold; font-size: 12px;"><i class="fas fa-edit"></i> Modification</span>'
        else:
            action_html = '<span style="background: #f8d7da; color: #721c24; padding: 4px 10px; border-radius: 4px; font-weight: bold; font-size: 12px;"><i class="fas fa-trash"></i> Suppression</span>'

        journal_activites.append({
            'date': h.history_date,
            'utilisateur': utilisateur,
            'action': action_html,
            'modele': modele,
            'element': element
        })

    page_obj, _ = paginer(journal_activites, request, per_page_key='per_page', default=15)

    context = {
        'page_obj': page_obj,
        'journal_activites': page_obj,
        'q_historique': q,
        'magasin_nom': magasin_nom,
        'date_range': date_range if date_range else f"{date_debut.strftime('%d/%m/%Y')} - {date_fin.strftime('%d/%m/%Y')}"
    }
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return render(request, 'stock/historique_lignes.html', context)
    return render(request, 'stock/historique.html', context)

# ══════════════════════════════════════════════════════════════════════════════
# BONS HORS STOCK
# ══════════════════════════════════════════════════════════════════════════════
