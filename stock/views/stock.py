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
from weasyprint import HTML

from accounts.permissions import verifier_permission
from core.models import Service, ConfigurationHopital
from core.pdf_service import DocumentGenerator
from ..decorators import magasin_requis, catch_errors
from ..forms import (
    SortieStockForm, EntreeStockForm, AjustementForm,
    MagasinParametresForm,
)
from ..models import (
    Mouvement, BonMouvement, LigneBon, MotifAnnulation,
    Article, Magasin, StockItem, Ajustement, FamilleArticle,
    Fournisseur, Beneficiaire,
    CampagneInventaire, LigneInventaire, CircuitValidation,
    LivraisonPartielle, DemandeMateriel, LigneDemande,
    AccuseReception,
    LivraisonLigne,
)
from ..services import (
    NumeroGenerator, StockService, PDFService, NotificationService
)
from .catalogue import paginer, get_magasins_autorises
from .common_views import render_liste, get_magasin_actif, build_redirect_url

logger = logging.getLogger(__name__)
User = get_user_model()

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_stock')
@magasin_requis
def etat_stock(request):
    """Vue liste de l'état du stock (GET uniquement)."""
    entreprise = request.entreprise
    magasins_autorises = get_magasins_autorises(request)
    qs = StockItem.objects.select_related(
        'article__famille', 'magasin'
    ).filter(magasin__in=magasins_autorises).order_by('article__designation')

    # ── FILTRE RECHERCHE TEXTE ──
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(article__designation__icontains=q) |
            Q(article__reference__icontains=q) |
            Q(article__famille__intitule__icontains=q)
        ).distinct()

    # ── FILTRE MAGASIN ──
    magasin_filter = request.GET.get('magasin', '').strip()
    if magasin_filter:
        if magasins_autorises.filter(id=magasin_filter).exists():
            qs = qs.filter(magasin_id=magasin_filter)

    # ── FILTRE PAR FAMILLE ──
    famille_id = request.GET.get('famille', '').strip()
    if famille_id:
        qs = qs.filter(article__famille_id=famille_id)

    # ── PAGINATION ──
    stocks_pagines, per_page = paginer(qs, request)

    # ── LISTE DES FAMILLES POUR LE SELECT ──
    familles = FamilleArticle.objects.filter(
        entreprise=entreprise
    ).order_by('intitule')

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




@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_stock')
@magasin_requis
@catch_errors(redirect_url='etat_stock')
def imprimer_etat_stock(request):
    entreprise = request.entreprise
    ids_str = request.GET.get('ids', '')
    if not ids_str:
        return HttpResponse("Aucun article sélectionné.", status=400)
    try:
        ids_list = [int(i) for i in ids_str.split(',')]
    except ValueError:
        return HttpResponse("Format d'ID invalide.", status=400)

    # CORRECTION : filtrer aussi par magasins_autorises
    magasins_autorises = get_magasins_autorises(request)
    stocks = StockItem.objects.filter(
        id__in=ids_list,
        magasin__entreprise=entreprise,
        magasin__in=magasins_autorises
    ).select_related('article__famille', 'magasin').order_by(
        'article__famille__intitule', 'article__designation'
    )

    date_range = request.GET.get('date_range', '')
    date_debut = None
    date_fin = None
    stocks_data = []

    if date_range:
        try:
            dates = date_range.split(' - ')
            if len(dates) == 2:
                date_debut = datetime.strptime(dates[0], '%d/%m/%Y').date()
                date_fin = datetime.strptime(dates[1], '%d/%m/%Y').date()
        except ValueError:
            pass

    if date_fin:
        for stock in stocks:
            qte = StockService.get_quantite_a_date(
                stock.article_id, stock.magasin_id, date_fin
            )
            stocks_data.append({
                'stock': stock,
                'quantite_physique': qte,
            })
        titre_periode = f"du {date_debut.strftime('%d/%m/%Y')} au {date_fin.strftime('%d/%m/%Y')}"
    else:
        for stock in stocks:
            stocks_data.append({
                'stock': stock,
                'quantite_physique': stock.quantite_physique,
            })
        titre_periode = "Actuel"

    gen = DocumentGenerator(request=request, entreprise=entreprise)
    pdf_bytes = gen.etat_stock(
        stocks_data=stocks_data,
        titre_periode=titre_periode,
        date_debut=date_debut,
        date_fin=date_fin,
        utilisateur=request.user
    )

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = 'inline; filename="Etat_Stock_Selection.pdf"'
    return response




@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_stock')
@magasin_requis
@catch_errors(redirect_url='etat_stock')
def imprimer_historique_article(request, article_id):
    entreprise = request.entreprise
    article = get_object_or_404(
        Article, id=article_id, entreprise=entreprise
    )
    mouvements = Mouvement.objects.filter(
        article=article, magasin__entreprise=entreprise
    ).select_related(
        'magasin', 'fournisseur', 'service_demandeur', 'utilisateur'
    )

    tri = request.GET.get('tri', 'date_desc')
    if tri == 'date_asc':
        mouvements = mouvements.order_by('date_mouvement')
    elif tri == 'alpha':
        mouvements = mouvements.order_by('type_mouvement', '-date_mouvement')
    else:
        mouvements = mouvements.order_by('-date_mouvement')

    gen = DocumentGenerator(request=request, entreprise=entreprise)
    pdf_bytes = gen.historique_article(
        article, mouvements, tri=tri,
        utilisateur=request.user  # ← AJOUTÉ pour afficher "Généré par..." dans le PDF
    )

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    ref = article.reference or str(article.id)
    response['Content-Disposition'] = f'inline; filename="Historique_{ref}.pdf"'
    return response


