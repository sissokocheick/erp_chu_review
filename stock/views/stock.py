import os
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from django.apps import apps
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
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

from accounts.permissions import verifier_permission
from core.models import Service, ConfigurationHopital
from ..decorators import magasin_requis, catch_errors
from ..forms import (
    SortieStockForm, EntreeStockForm, AjustementForm,
    MagasinParametresForm)
from ..models import (
    Mouvement, BonMouvement, LigneBon, MotifAnnulation,
    Article, Magasin, StockItem, Ajustement, FamilleArticle,
    Fournisseur, Beneficiaire,
    CampagneInventaire, LigneInventaire, CircuitValidation,
    LivraisonPartielle, DemandeMateriel, LigneDemande,
    AccuseReception,
    LivraisonLigne)
from ..services import (
    NumeroGenerator, StockService, PDFService, NotificationService
)
from .catalogue import paginer, get_magasins_autorises
from .common_views import render_liste, get_magasin_actif, build_redirect_url, filtrer_texte

logger = logging.getLogger(__name__)
User = get_user_model()

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_stock')
@magasin_requis
def etat_stock(request):
    """Vue liste de l'état du stock (GET uniquement)."""
    magasins_autorises = get_magasins_autorises(request)
    qs = StockItem.objects.select_related(
        'article__famille', 'magasin'
    ).filter(magasin__in=magasins_autorises).order_by('article__designation')

    # ── FILTRE MAGASIN ──
    # Par défaut : le magasin sélectionné dans l'en-tête s'applique partout.
    magasin_filter = request.GET.get('magasin', '').strip()
    if not magasin_filter:
        magasin_actif = get_magasin_actif(request)
        if magasin_actif:
            magasin_filter = str(magasin_actif.id)
    if magasin_filter:
        if magasins_autorises.filter(id=magasin_filter).exists():
            qs = qs.filter(magasin_id=magasin_filter)

    # ── FILTRE PAR FAMILLE ──
    famille_id = request.GET.get('famille', '').strip()
    if famille_id:
        qs = qs.filter(article__famille_id=famille_id)

    # ── FILTRE RECHERCHE TEXTE (insensible aux accents) ──
    q = request.GET.get('q', '').strip()
    if q:
        qs = filtrer_texte(qs, q, [
            'article__designation', 'article__reference', 'article__famille__intitule'
        ])

    # ── PAGINATION ──
    stocks_pagines, per_page = paginer(qs, request)

    # ── LISTE DES FAMILLES POUR LE SELECT ──
    familles = FamilleArticle.objects.all().order_by('intitule')

    context = {
        'stocks': stocks_pagines,
        'magasins': magasins_autorises.order_by('nom'),
        'magasin_filtre': magasin_filter,
        'familles': familles,
        'famille_id': famille_id,
        'q_stock': q,
        'per_page': per_page,
    }

    # ── AJAX : retourne seulement le tbody ──
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return render(request, 'stock/etat_stock_lignes.html', context)

    return render(request, 'stock/etat_stock.html', context)

