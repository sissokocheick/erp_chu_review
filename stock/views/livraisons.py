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
from core.pdf_service import DocumentGenerator
from stock.services.isolation_service import get_magasins_autorises
from ..decorators import magasin_requis, catch_errors
from ..forms import (
    SortieStockForm, EntreeStockForm, AjustementForm,
    MagasinParametresForm)
from ..models import (
    Mouvement, BonMouvement, LigneBon, MotifAnnulation,
    Article, Magasin, StockItem, Ajustement,
    Fournisseur, Beneficiaire,
    CampagneInventaire, LigneInventaire, CircuitValidation,
    LivraisonPartielle, DemandeMateriel, LigneDemande,
    AccuseReception,
    LivraisonLigne)
from ..services import (
    NumeroGenerator, StockService, PDFService, NotificationService
)
from .catalogue import paginer
from .common_views import render_liste, get_magasin_actif, build_redirect_url

logger = logging.getLogger(__name__)
User = get_user_model()

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_livraisons')
@magasin_requis
def liste_livraisons(request):
    """Vue liste des livraisons (GET uniquement)."""
    magasin_id = request.session.get('magasin_actif_id')

    qs = LivraisonPartielle.objects.select_related(
        'demande__service_demandeur', 'demande__magasin_cible',
        'livre_par', 'bon_sortie').prefetch_related(
        'lignes_livraison__article', 'accuse__receptionne_par__profil'
    ).order_by('-date_livraison')

    if magasin_id:
        qs = qs.filter(demande__magasin_cible_id=magasin_id)
    else:
        magasins_autorises_ids = get_magasins_autorises(request).values_list('id', flat=True)
        qs = qs.filter(demande__magasin_cible_id__in=magasins_autorises_ids)

    # ── FILTRES ──
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(numero_livraison__icontains=q) |
            Q(demande__numero_demande__icontains=q) |
            Q(demande__service_demandeur__nom__icontains=q) |
            Q(livre_par__username__icontains=q) |
            Q(livre_par__first_name__icontains=q) |
            Q(livre_par__last_name__icontains=q)
        ).distinct()

    statut = request.GET.get('statut', '').strip()
    if statut == 'signe':
        qs = qs.filter(accuse__est_signe=True)
    elif statut == 'attente':
        qs = qs.filter(accuse__est_signe=False)

    magasin_filter = request.GET.get('magasin', '').strip()
    if magasin_filter and magasin_filter.isdigit():
        # Le filtre GET ne doit pas contourner l'isolation : uniquement
        # parmi les magasins déjà autorisés.
        autorises_ids = set(
            get_magasins_autorises(request).values_list('id', flat=True))
        if int(magasin_filter) in autorises_ids:
            qs = qs.filter(demande__magasin_cible_id=magasin_filter)

    total_livraisons = qs.count()
    total_signees = qs.filter(accuse__est_signe=True).count()

    per_page = request.GET.get('per_page', '25')
    livraisons, _ = paginer(qs, request, per_page_key='per_page', default=25)

    context = {
        'livraisons': livraisons,
        'total_livraisons': total_livraisons,
        'total_signees': total_signees,
        'total_attente': total_livraisons - total_signees,
        'magasins': get_magasins_autorises(request),
        'per_page': per_page,
        'q_livraison': q,
        'statut_filtre': statut,
        'magasin_filtre': magasin_filter,
    }
    return render(request, 'stock/liste_livraisons.html', context)

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_livraisons')
def detail_livraisons_demande(request, demande_id):
    demande = get_object_or_404(
        DemandeMateriel.objects.select_related(
            'service_demandeur', 'demandeur', 'magasin_cible'
        ).prefetch_related(
            Prefetch(
                'livraisons',
                queryset=LivraisonPartielle.objects.select_related(
                    'livre_par', 'bon_sortie'
                ).prefetch_related(
                    Prefetch(
                        'lignes_livraison',
                        queryset=LivraisonLigne.objects.select_related('article')
                    ),
                    'accuse__receptionne_par__profil')
            ),
            'lignes_demande__article'),
        id=demande_id)

    profil = getattr(request.user, 'profil', None)
    magasin_id = request.session.get('magasin_actif_id')
    est_magasinier = (
        request.user.has_perm('accounts.menu_guichet') and
        str(demande.magasin_cible_id) == str(magasin_id)
    )
    est_demandeur = (demande.demandeur == request.user)
    est_du_service = (profil and profil.service == demande.service_demandeur)

    if not (est_magasinier or est_demandeur or est_du_service or request.user.is_staff):
        messages.error(request, "⛔ Accès non autorisé.")
        return redirect('/')

    recap_articles = []
    for ligne in demande.lignes_demande.all():
        recap_articles.append({
            'article': ligne.article,
            'qte_demandee': ligne.quantite_demandee,
            'qte_livree': ligne.quantite_livree,
            'reste': ligne.reste,
        })

    motifs_annulation = MotifAnnulation.objects.filter(
        actif=True
    ).order_by('libelle')

    context = {
        'demande': demande,
        'livraisons': demande.livraisons.all(),
        'recap_articles': recap_articles,
        'est_magasinier': est_magasinier,
        'est_demandeur': est_demandeur or est_du_service,
        'peut_livrer': est_magasinier and demande.reste > 0 and demande.statut not in ('RECEPTIONNE', 'CLOTUREE', 'REFUSEE', 'ANNULEE'),
        'peut_cloturer': est_magasinier and demande.statut in ('LIVRAISON_PARTIELLE', 'EN_COURS', 'EN_ATTENTE'),
        'peut_bon_global': demande.livraisons.exists(),
        'motifs_annulation': motifs_annulation,
    }
    return render(request, 'stock/detail_livraisons.html', context)

# ══════════════════════════════════════════════════════════════════════════════
# UTILITAIRES MAGASIN
# ══════════════════════════════════════════════════════════════════════════════
