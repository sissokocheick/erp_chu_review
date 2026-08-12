import os
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction, IntegrityError
from django.db.models import Q, F, Sum, Prefetch, OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from accounts.permissions import verifier_permission
from stock.services.isolation_service import get_magasins_autorises
from ..decorators import magasin_requis, catch_errors
from ..models import Mouvement, Article, Magasin, StockItem
from ..services.livraison_service import LivraisonService
from .catalogue import paginer
from .common_views import render_liste, get_magasin_actif, build_redirect_url
from ..models import BonMouvement

logger = logging.getLogger(__name__)

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_peremptions', 'accounts.menu_lots')
@magasin_requis
def controle_peremptions(request):
    """Vue unique : Suivi lots + Destructions + Inventaire lots (3 onglets)."""
    magasin_id = request.session.get('magasin_actif_id')
    aujourdhui = timezone.now().date()
    onglet = request.GET.get('onglet', 'suivi')
    q = request.GET.get('q', '').strip()
    per_page = request.GET.get('per_page', '15')
    magasin_actif = get_magasin_actif(request)

    # ═══════════════════════════════════════════════════════════════
    #  DONNÉES PAR ONGLET
    # ═══════════════════════════════════════════════════════════════
    lots = None
    destructions = None
    lots_inventaire = None
    nb_perimes = nb_critique = nb_attention = 0
    # ── KPIs DESTRUCTION (toujours calculés pour affichage dans les KPIs) ──
    nb_destructions_total = Mouvement.objects.filter(
        type_mouvement='SORTIE',
        service_demandeur__code='REBUTS').count()
    debut_mois = aujourdhui.replace(day=1)
    nb_destructions_mois = Mouvement.objects.filter(
        type_mouvement='SORTIE',
        service_demandeur__code='REBUTS',
        date_mouvement__date__gte=debut_mois
    ).count()

    date_debut = request.GET.get('date_debut', '')
    date_fin = request.GET.get('date_fin', '')

    # ── ONGLET SUIVI ──
    if onglet == 'suivi':
        sorties_sub = Mouvement.objects.filter(
            type_mouvement='SORTIE',
            article=OuterRef('article'),
            numero_lot=OuterRef('numero_lot'),
            magasin=OuterRef('magasin')
        ).values('article', 'numero_lot', 'magasin').annotate(
            total=Sum('quantite')
        ).values('total')[:1]

        stock_physique_sub = StockItem.objects.filter(
            article=OuterRef('article'),
            magasin=OuterRef('magasin')
        ).values('quantite_physique')[:1]

        qs = Mouvement.objects.filter(
            type_mouvement='ENTREE',
            date_peremption__isnull=False).annotate(
            qte_sortie=Coalesce(Subquery(sorties_sub), 0),
            quantite_restante=F('quantite') - F('qte_sortie'),
            stock_physique=Coalesce(Subquery(stock_physique_sub), 0)
        ).filter(
            quantite_restante__gt=0,
            stock_physique__gt=0
        ).select_related(
            'article', 'fournisseur', 'magasin', 'utilisateur'
        )

        if magasin_id:
            qs = qs.filter(magasin_id=magasin_id)
        if q:
            qs = qs.filter(
                Q(article__designation__icontains=q) |
                Q(numero_lot__icontains=q) |
                Q(article__reference__icontains=q)
            ).distinct()

        qs = qs.order_by('date_peremption')

        lots_valides = []
        for lot in qs:
            jours = (lot.date_peremption - aujourdhui).days
            lot.jours_restants = jours
            if jours < 0:
                lot.statut_peremption = 'PÉRIMÉ'
                nb_perimes += 1
            elif jours <= 90:
                lot.statut_peremption = 'CRITIQUE (< 3 mois)'
                nb_critique += 1
            elif jours <= 180:
                lot.statut_peremption = 'ATTENTION (< 6 mois)'
                nb_attention += 1
            else:
                lot.statut_peremption = 'OK'
            lots_valides.append(lot)

        lots, per_page = paginer(lots_valides, request)

    # ── ONGLET DESTRUCTION ──
    elif onglet == 'destruction':
        qs = Mouvement.objects.filter(
            type_mouvement='SORTIE',
            service_demandeur__code='REBUTS').select_related('article', 'magasin', 'utilisateur').order_by('-date_mouvement')

        if magasin_id:
            qs = qs.filter(magasin_id=magasin_id)
        if q:
            qs = qs.filter(
                Q(article__designation__icontains=q) |
                Q(numero_lot__icontains=q) |
                Q(article__reference__icontains=q) |
                Q(reference_document__icontains=q)
            ).distinct()

        destructions, per_page = paginer(qs, request)

        # Annotation bon_id sur chaque destruction (pour lien cliquable)
        bon_nums = [d.reference_document for d in destructions if d.reference_document]
        bon_map = {}
        if bon_nums:
            bon_map = {
                b.numero_bon: b.id
                for b in BonMouvement.objects.filter(numero_bon__in=bon_nums).only('id', 'numero_bon')
            }
        for d in destructions:
            d.bon_id = bon_map.get(d.reference_document)

    # ── ONGLET LOTS ──
    elif onglet == 'lots':
        if not magasin_id:
            messages.error(request, "⛔ Aucun magasin actif sélectionné.")
            return redirect('etat_stock')

        magasins_autorises = get_magasins_autorises(request)
        if not magasins_autorises.filter(id=magasin_id).exists():
            messages.error(request, "⛔ Vous n'avez pas accès à ce magasin.")
            return redirect('etat_stock')

        qs = StockItem.objects.filter(
            magasin_id=magasin_id
        ).exclude(
            Q(batch_number__isnull=True) | Q(batch_number='')
        ).select_related(
            'article__famille', 'magasin'
        ).order_by('article__designation', 'batch_number')

        if q:
            qs = qs.filter(
                Q(article__designation__icontains=q) |
                Q(batch_number__icontains=q) |
                Q(article__reference__icontains=q)
            )

        if date_debut:
            try:
                qs = qs.filter(expiry_date__gte=datetime.strptime(date_debut, '%Y-%m-%d').date())
            except ValueError:
                pass
        if date_fin:
            try:
                qs = qs.filter(expiry_date__lte=datetime.strptime(date_fin, '%Y-%m-%d').date())
            except ValueError:
                pass

        lots_inventaire, per_page = paginer(qs, request)

    context = {
        'onglet': onglet,
        'q_peremption': q,
        'per_page': per_page,
        'aujourdhui': aujourdhui,
        'magasin_actif_id': magasin_id,
        'magasin_actif': magasin_actif,
        'date_debut': date_debut,
        'date_fin': date_fin,
        # Suivi
        'lots': lots,
        'nb_perimes': nb_perimes,
        'nb_critique': nb_critique,
        'nb_attention': nb_attention,
        # Destruction
        'destructions': destructions,
        'nb_destructions_total': nb_destructions_total,
        'nb_destructions_mois': nb_destructions_mois,
        # Lots
        'lots_inventaire': lots_inventaire,
    }

    # ── AJAX : retourne le partial correspondant ──
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        if onglet == 'suivi':
            return render(request, 'stock/peremptions_lignes.html', context)
        elif onglet == 'destruction':
            return render(request, 'stock/destructions_lignes.html', context)
        return render(request, 'stock/lots_lignes.html', context)

    return render(request, 'stock/controle_peremptions.html', context)

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_peremptions', 'accounts.menu_lots')
@transaction.atomic
@catch_errors(redirect_url='controle_peremptions')
def retirer_lot_perime(request, mouvement_id):
    if request.method != 'POST':
        return redirect('controle_peremptions')

    entree = get_object_or_404(
        Mouvement, id=mouvement_id, type_mouvement='ENTREE')

    sorties = Mouvement.objects.filter(
        type_mouvement='SORTIE', article=entree.article,
        numero_lot=entree.numero_lot, magasin=entree.magasin
    ).aggregate(total=Sum('quantite'))['total'] or 0
    quantite_restante = entree.quantite - sorties

    if quantite_restante <= 0:
        messages.error(request, "❌ Ce lot a déjà été totalement retiré.")
        return redirect('controle_peremptions')

    stock_item, created = StockItem.objects.select_for_update().get_or_create(
        article=entree.article,
        magasin=entree.magasin,
        batch_number=entree.numero_lot or None,
        defaults={'quantite_physique': 0, 'valeur_cmup': Decimal('0')}
    )

    if stock_item.quantite_physique < 0:
        logger.warning(
            f"[Péremption] Stock négatif corrigé pour {entree.article.designation} "
            f"dans {entree.magasin.nom}: {stock_item.quantite_physique} → 0"
        )
        stock_item.quantite_physique = 0
        stock_item.save(update_fields=['quantite_physique'])

    qte_a_detruire = min(quantite_restante, stock_item.quantite_physique)

    if qte_a_detruire <= 0:
        messages.warning(
            request,
            f"⚠️ Le stock physique de « {entree.article.designation} » est déjà à 0. "
            "Aucune unité à détruire."
        )
        return redirect('controle_peremptions')

    try:
        bon = LivraisonService.destruction_lot_perime(entree, qte_a_detruire, request.user)
    except Exception as e:
        logger.exception("[Destruction lot] %s", e)
        messages.error(request, "❌ Erreur lors de la destruction. Veuillez réessayer.")
        return redirect('controle_peremptions')

    messages.success(
        request,
        f"✅ Destruction réussie ! {qte_a_detruire} unité(s) de « {entree.article.designation} » détruite(s). "
        f"Bon N° {bon.numero_bon} généré."
    )
    return redirect('{}?onglet=destruction'.format(reverse('controle_peremptions')))
