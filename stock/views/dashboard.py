from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, F, Count, DecimalField, Value, OuterRef, Subquery, Case, When
from django.db.models.functions import Coalesce
from django.utils import timezone
from datetime import timedelta
from itertools import chain
from operator import attrgetter
import json

from accounts.permissions import verifier_permission
from ..models import (
    Article, Mouvement, StockItem, Magasin,
    Fournisseur, Service)
from ..decorators import catch_errors


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_dashboard')
@catch_errors(redirect_url='/auth/accueil/')
def dashboard_directeur(request):
    aujourdhui = timezone.now().date()
    total_articles = Article.objects.all().count()
    sorties_jour = Mouvement.objects.filter(
        type_mouvement='SORTIE',
        date_mouvement__date=aujourdhui
    ).count()
    entrees_jour = Mouvement.objects.filter(
        type_mouvement='ENTREE',
        date_mouvement__date=aujourdhui
    ).count()

    stocks_base = StockItem.objects.select_related('article', 'article__famille', 'magasin')

    # ═══════════════════════════════════════════════════════════════════════
    # ALERTES STOCK
    # ═══════════════════════════════════════════════════════════════════════
    stocks_critiques = stocks_base.filter(
        article__seuil_critique__isnull=False,
        quantite_physique__lte=F('article__seuil_critique')
    ).order_by('quantite_physique')

    stocks_alerte = stocks_base.filter(
        article__seuil_minimum__isnull=False,
        quantite_physique__gt=Coalesce(F('article__seuil_critique'), 0),
        quantite_physique__lte=F('article__seuil_minimum')
    ).order_by('quantite_physique')

    stocks_surstock = stocks_base.filter(
        article__seuil_maximum__isnull=False,
        quantite_physique__gt=F('article__seuil_maximum')
    ).order_by('-quantite_physique')

    trente_jours_avant = aujourdhui - timedelta(days=30)
    top_articles = Mouvement.objects.filter(
        type_mouvement='SORTIE',
        date_mouvement__date__gte=trente_jours_avant
    ).values('article__designation').annotate(
        total_sorti=Sum('quantite')
    ).order_by('-total_sorti')[:5]

    top_services = Mouvement.objects.filter(
        type_mouvement='SORTIE',
        date_mouvement__date__gte=trente_jours_avant,
        service_demandeur__isnull=False
    ).values('service_demandeur__nom').annotate(
        total_sorti=Sum('quantite')
    ).order_by('-total_sorti')[:5]

    mouvements_recents = Mouvement.objects.select_related(
        'article', 'utilisateur'
    ).order_by('-date_mouvement')[:8]

    # ═══════════════════════════════════════════════════════════════════════
    # VALORISATION CMUP
    # ═══════════════════════════════════════════════════════════════════════
    resultat_valeur = StockItem.objects.aggregate(
        total=Sum(
            F('quantite_physique') * Case(
                When(valeur_cmup__gt=0, then=F('valeur_cmup')),
                default=Coalesce(F('article__prix_reference'), Value(0, output_field=DecimalField())),
                output_field=DecimalField()
            ),
            output_field=DecimalField()
        )
    )
    valeur_stock_total = resultat_valeur['total'] or 0

    # ═══════════════════════════════════════════════════════════════════════
    # HISTORIQUE (7 jours)
    # ═══════════════════════════════════════════════════════════════════════
    date_limite_historique = aujourdhui - timedelta(days=7)

    h_articles = Article.history.filter(
        history_date__date__gte=date_limite_historique
    ).order_by('-history_date')[:12]

    h_magasins = Magasin.history.filter(
        history_date__date__gte=date_limite_historique
    ).order_by('-history_date')[:12]

    h_fournisseurs = Fournisseur.history.filter(
        history_date__date__gte=date_limite_historique
    ).order_by('-history_date')[:12]

    magasins_ids = list(Magasin.objects.values_list('id', flat=True))
    if magasins_ids:
        h_mouvements = Mouvement.history.filter(
            magasin_id__in=magasins_ids,
            history_date__date__gte=date_limite_historique
        ).order_by('-history_date')[:50]
    else:
        h_mouvements = []

    historique_brut = sorted(
        chain(h_articles, h_magasins, h_fournisseurs, h_mouvements),
        key=attrgetter('history_date'), reverse=True
    )[:12]

    journal_activites = []
    for h in historique_brut:
        action_text = "Création" if h.history_type == '+' else "Modification" if h.history_type == '~' else "Suppression"
        action_html = (
            f'<span style="background:#{"d4edda" if h.history_type=="+" else "cce5ff" if h.history_type=="~" else "f8d7da"};'
            f'color:#{"155724" if h.history_type=="+" else "004085" if h.history_type=="~" else "721c24"};'
            f'padding:3px 8px;border-radius:12px;font-size:11px;font-weight:bold;">{action_text}</span>'
        )
        journal_activites.append({
            'date': h.history_date,
            'utilisateur': h.history_user.username.capitalize() if h.history_user else "Système",
            'action': action_html,
            'modele': h.__class__.__name__.replace('Historical', ''),
            'element': str(h),
        })

    # ═══════════════════════════════════════════════════════════════════════
    # PÉREMPTIONS
    # ═══════════════════════════════════════════════════════════════════════
    sorties_par_lot = Mouvement.objects.filter(
        type_mouvement='SORTIE',
        article=OuterRef('article'),
        magasin=OuterRef('magasin'),
        numero_lot=OuterRef('numero_lot')
    ).values('article', 'magasin', 'numero_lot').annotate(
        total_sorti=Sum('quantite')
    ).values('total_sorti')

    stock_physique_sub = StockItem.objects.filter(
        article=OuterRef('article'),
        magasin=OuterRef('magasin')
    ).values('quantite_physique')[:1]

    date_alerte = aujourdhui + timedelta(days=90)

    lots_en_alerte = Mouvement.objects.filter(
        type_mouvement='ENTREE',
        date_peremption__isnull=False,
        date_peremption__lte=date_alerte,
        date_peremption__gte=aujourdhui
    ).annotate(
        qte_sortie=Coalesce(Subquery(sorties_par_lot), 0),
        quantite_restante=F('quantite') - F('qte_sortie'),
        stock_physique=Coalesce(Subquery(stock_physique_sub), 0)
    ).filter(
        quantite_restante__gt=0,
        stock_physique__gt=0
    ).select_related('article', 'magasin').order_by('date_peremption')

    lots_perimes = Mouvement.objects.filter(
        type_mouvement='ENTREE',
        date_peremption__isnull=False,
        date_peremption__lt=aujourdhui
    ).annotate(
        qte_sortie=Coalesce(Subquery(sorties_par_lot), 0),
        quantite_restante=F('quantite') - F('qte_sortie'),
        stock_physique=Coalesce(Subquery(stock_physique_sub), 0)
    ).filter(
        quantite_restante__gt=0,
        stock_physique__gt=0
    ).select_related('article', 'magasin').order_by('-date_peremption')

    context = {
        'total_articles': total_articles,
        'sorties_jour': sorties_jour,
        'entrees_jour': entrees_jour,
        'nombre_alertes': stocks_critiques.count() + stocks_alerte.count(),
        'valeur_stock_total': valeur_stock_total,
        'stocks_critiques': stocks_critiques,
        'stocks_alerte': stocks_alerte,
        'stocks_surstock': stocks_surstock,
        'nb_critiques': stocks_critiques.count(),
        'nb_alertes': stocks_alerte.count(),
        'nb_surstocks': stocks_surstock.count(),
        'mouvements_recents': mouvements_recents,
        'journal_activites': journal_activites,
        'lots_en_alerte': lots_en_alerte,
        'lots_perimes': lots_perimes,
        'chart_articles_labels': json.dumps([i['article__designation'] for i in top_articles]),
        'chart_articles_data': json.dumps([i['total_sorti'] for i in top_articles]),
        'chart_services_labels': json.dumps([i['service_demandeur__nom'] for i in top_services]),
        'chart_services_data': json.dumps([i['total_sorti'] for i in top_services]),
    }
    return render(request, 'stock/dashboard.html', context)