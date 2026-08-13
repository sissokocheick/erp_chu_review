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


def _magasin_actif(request):
    """Magasin sélectionné en session (ou None si aucun choix)."""
    magasin_id = request.session.get('magasin_actif_id')
    if magasin_id:
        return Magasin.objects.filter(id=magasin_id).first()
    return None


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_dashboard')
@catch_errors(redirect_url='/auth/accueil/')
def dashboard_directeur(request):
    aujourdhui = timezone.now().date()

    # ── Isolation par magasin actif (cohérent avec les autres pages) ──
    magasin_actif = _magasin_actif(request)
    magasins_ids = ([magasin_actif.id] if magasin_actif
                    else list(Magasin.objects.values_list('id', flat=True)))

    total_articles = Article.objects.all().count()
    mouvements_scope = Mouvement.objects.filter(magasin_id__in=magasins_ids)
    sorties_jour = mouvements_scope.filter(
        type_mouvement='SORTIE',
        date_mouvement__date=aujourdhui
    ).count()
    entrees_jour = mouvements_scope.filter(
        type_mouvement='ENTREE',
        date_mouvement__date=aujourdhui
    ).count()

    stocks_base = StockItem.objects.select_related('article', 'article__famille', 'magasin').filter(
        magasin_id__in=magasins_ids
    )

    # ═══════════════════════════════════════════════════════════════════════
    # FLUX 14 JOURS (entrées vs sorties) pour le graphique
    # ═══════════════════════════════════════════════════════════════════════
    flux_par_jour = {}
    date_debut_flux = aujourdhui - timedelta(days=13)
    for m in mouvements_scope.filter(
        date_mouvement__date__gte=date_debut_flux
    ).values('date_mouvement__date', 'type_mouvement').annotate(
        total=Sum('quantite')
    ):
        jour = m['date_mouvement__date']
        flux_par_jour.setdefault(jour, {'E': 0, 'S': 0})
        if m['type_mouvement'] == 'ENTREE':
            flux_par_jour[jour]['E'] += m['total']
        elif m['type_mouvement'] == 'SORTIE':
            flux_par_jour[jour]['S'] += m['total']

    labels_flux = []
    entrees_flux = []
    sorties_flux = []
    for i in range(13, -1, -1):
        jour = (aujourdhui - timedelta(days=i))
        labels_flux.append(jour.strftime('%d/%m'))
        data = flux_par_jour.get(jour, {'E': 0, 'S': 0})
        entrees_flux.append(data['E'])
        sorties_flux.append(data['S'])

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
    top_articles = mouvements_scope.filter(
        type_mouvement='SORTIE',
        date_mouvement__date__gte=trente_jours_avant
    ).values('article__designation').annotate(
        total_sorti=Sum('quantite')
    ).order_by('-total_sorti')[:5]

    top_entrees = mouvements_scope.filter(
        type_mouvement='ENTREE',
        date_mouvement__date__gte=trente_jours_avant
    ).values('article__designation').annotate(
        total_entree=Sum('quantite')
    ).order_by('-total_entree')[:5]

    top_services = mouvements_scope.filter(
        type_mouvement='SORTIE',
        date_mouvement__date__gte=trente_jours_avant,
        service_demandeur__isnull=False
    ).values('service_demandeur__nom').annotate(
        total_sorti=Sum('quantite')
    ).order_by('-total_sorti')[:5]

    mouvements_recents = mouvements_scope.select_related(
        'article', 'utilisateur'
    ).order_by('-date_mouvement')[:8]

    # ═══════════════════════════════════════════════════════════════════════
    # VALEUR DU STOCK PAR FAMILLE / PAR MAGASIN
    # ═══════════════════════════════════════════════════════════════════════
    valeur_case = Case(
        When(valeur_cmup__gt=0, then=F('valeur_cmup')),
        default=Coalesce(F('article__prix_reference'), Value(0, output_field=DecimalField())),
        output_field=DecimalField()
    )
    valeur_par_famille = stocks_base.values('article__famille__intitule').annotate(
        total=Sum(F('quantite_physique') * valeur_case, output_field=DecimalField())
    ).order_by('-total')[:8]

    valeur_par_magasin = stocks_base.values('magasin__nom').annotate(
        total=Sum(F('quantite_physique') * valeur_case, output_field=DecimalField())
    ).order_by('-total')

    # ═══════════════════════════════════════════════════════════════════════
    # VALORISATION CMUP (scopée au magasin actif)
    # ═══════════════════════════════════════════════════════════════════════
    resultat_valeur = stocks_base.aggregate(
        total=Sum(F('quantite_physique') * valeur_case, output_field=DecimalField())
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
        'magasin_actif': magasin_actif,
        'chart_articles_labels': json.dumps([i['article__designation'] for i in top_articles]),
        'chart_articles_data': json.dumps([i['total_sorti'] for i in top_articles]),
        'chart_entrees_labels': json.dumps([i['article__designation'] for i in top_entrees]),
        'chart_entrees_data': json.dumps([i['total_entree'] for i in top_entrees]),
        'chart_services_labels': json.dumps([i['service_demandeur__nom'] for i in top_services]),
        'chart_services_data': json.dumps([i['total_sorti'] for i in top_services]),
        'flux_labels': json.dumps(labels_flux),
        'flux_entrees': json.dumps(entrees_flux),
        'flux_sorties': json.dumps(sorties_flux),
        'chart_familles_labels': json.dumps([i['article__famille__intitule'] or 'Général' for i in valeur_par_famille]),
        'chart_familles_data': json.dumps([float(i['total']) for i in valeur_par_famille]),
        'valeur_par_famille': valeur_par_famille,
        'valeur_par_magasin': valeur_par_magasin,
    }
    return render(request, 'stock/dashboard.html', context)