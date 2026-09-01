from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum, F, Count, DecimalField, Value, OuterRef, Subquery, Case, When
from django.db.models.functions import Coalesce
from django.core.cache import cache
from django.utils import timezone
from datetime import timedelta
from itertools import chain
from operator import attrgetter
import json


def _json_pour_script(obj):
    """JSON sûr à injecter dans un <script> : échappe « </ » (anti-XSS)."""
    return json.dumps(obj).replace('</', '<\\/')


from accounts.permissions import verifier_permission
from ..models import (
    Article, Mouvement, StockItem, Magasin,
    Fournisseur, Service)
from ..decorators import catch_errors
from ..services.isolation_service import get_magasins_autorises


# ═══════════════════════════════════════════════════════════════════════════════
# CACHE KEYS & TTL
# ═══════════════════════════════════════════════════════════════════════════════
_TTL_KPIS       = 30
_TTL_ALERTES    = 60
_TTL_CHARTS     = 120
_TTL_PEREMPTION = 120
_TTL_HISTORIQUE = 60


def _cache_key(magasins_ids, bloc):
    """Clé de cache déterministe pour un ensemble de magasins.

    ✅ CORRECTION : l'ancienne clé « all » pour tout périmètre multi-magasins
    faisait partager la même entrée de cache à des utilisateurs avec des
    périmètres différents (fuite inter-magasins). L'empreinte de la liste
    triée garantit un scope par périmètre réel.
    """
    import hashlib
    ids = sorted(set(magasins_ids or []))
    if len(ids) == 1:
        return f"dash:m{ids[0]}:{bloc}"
    empreinte = hashlib.md5(','.join(str(i) for i in ids).encode()).hexdigest()[:10]
    return f"dash:set{empreinte}:{bloc}"


def _magasin_actif(request):
    """Magasin sélectionné en session (ou None si aucun choix)."""
    magasin_id = request.session.get('magasin_actif_id')
    if magasin_id:
        return Magasin.objects.filter(id=magasin_id).first()
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# BLOCS DE DONNÉES CACHEABLES
# ═══════════════════════════════════════════════════════════════════════════════

def _get_kpis(magasins_ids, aujourdhui):
    """KPIs du jour : 3 requêtes. Cache 30s."""
    key = _cache_key(magasins_ids, 'kpis')
    data = cache.get(key)
    if data is not None:
        return data
    mouvements_scope = Mouvement.objects.filter(magasin_id__in=magasins_ids)
    total_articles = Article.objects.count()
    sorties_jour = mouvements_scope.filter(
        type_mouvement='SORTIE', date_mouvement__date=aujourdhui
    ).count()
    entrees_jour = mouvements_scope.filter(
        type_mouvement='ENTREE', date_mouvement__date=aujourdhui
    ).count()
    data = {
        'total_articles': total_articles,
        'sorties_jour': sorties_jour,
        'entrees_jour': entrees_jour,
    }
    cache.set(key, data, _TTL_KPIS)
    return data


def _get_alertes(magasin_id, magasins_ids):
    """Alertes stock : 3 requêtes. Cache 60s."""
    key = _cache_key(magasins_ids, 'alertes')
    data = cache.get(key)
    if data is not None:
        return data
    stocks_base = StockItem.objects.select_related(
        'article', 'article__famille', 'magasin'
    ).filter(magasin_id__in=magasins_ids)
    stocks_critiques = list(stocks_base.filter(
        article__seuil_critique__isnull=False,
        quantite_physique__lte=F('article__seuil_critique')
    ).order_by('quantite_physique'))
    stocks_alerte = list(stocks_base.filter(
        article__seuil_minimum__isnull=False,
        quantite_physique__gt=Coalesce(F('article__seuil_critique'), 0),
        quantite_physique__lte=F('article__seuil_minimum')
    ).order_by('quantite_physique'))
    stocks_surstock = list(stocks_base.filter(
        article__seuil_maximum__isnull=False,
        quantite_physique__gt=F('article__seuil_maximum')
    ).order_by('-quantite_physique'))

    def _ser(s):
        return {
            'article__designation': s.article.designation,
            'article__famille__intitule': getattr(s.article.famille, 'intitule', '') if s.article.famille else '',
            'magasin__nom': s.magasin.nom if s.magasin else '',
            'quantite_physique': float(s.quantite_physique),
            'article_id': s.article_id,
            'magasin_id': s.magasin_id,
        }

    data = {
        'stocks_critiques': [_ser(s) for s in stocks_critiques],
        'stocks_alerte': [_ser(s) for s in stocks_alerte],
        'stocks_surstock': [_ser(s) for s in stocks_surstock],
        'nb_critiques': len(stocks_critiques),
        'nb_alertes': len(stocks_alerte),
        'nb_surstocks': len(stocks_surstock),
    }
    cache.set(key, data, _TTL_ALERTES)
    return data


def _get_charts(magasin_id, magasins_ids, aujourdhui):
    """Charts et agrégats 30j : ~8 requêtes. Cache 120s."""
    key = _cache_key(magasins_ids, 'charts')
    data = cache.get(key)
    if data is not None:
        return data
    mouvements_scope = Mouvement.objects.filter(magasin_id__in=magasins_ids)
    stocks_base = StockItem.objects.select_related(
        'article', 'article__famille', 'magasin'
    ).filter(magasin_id__in=magasins_ids)
    trente_jours_avant = aujourdhui - timedelta(days=30)

    # Flux 14 jours
    flux_par_jour = {}
    date_debut_flux = aujourdhui - timedelta(days=13)
    for m in mouvements_scope.filter(
        date_mouvement__date__gte=date_debut_flux
    ).values('date_mouvement__date', 'type_mouvement').annotate(total=Sum('quantite')):
        jour = m['date_mouvement__date']
        flux_par_jour.setdefault(jour, {'E': 0, 'S': 0})
        if m['type_mouvement'] == 'ENTREE':
            flux_par_jour[jour]['E'] += m['total']
        elif m['type_mouvement'] == 'SORTIE':
            flux_par_jour[jour]['S'] += m['total']
    labels_flux, entrees_flux, sorties_flux = [], [], []
    for i in range(13, -1, -1):
        jour = aujourdhui - timedelta(days=i)
        labels_flux.append(jour.strftime('%d/%m'))
        d = flux_par_jour.get(jour, {'E': 0, 'S': 0})
        entrees_flux.append(d['E'])
        sorties_flux.append(d['S'])

    top_articles = list(mouvements_scope.filter(
        type_mouvement='SORTIE', date_mouvement__date__gte=trente_jours_avant
    ).values('article__designation').annotate(
        total_sorti=Sum('quantite')
    ).order_by('-total_sorti')[:5])
    top_entrees = list(mouvements_scope.filter(
        type_mouvement='ENTREE', date_mouvement__date__gte=trente_jours_avant
    ).values('article__designation').annotate(
        total_entree=Sum('quantite')
    ).order_by('-total_entree')[:5])
    top_services = list(mouvements_scope.filter(
        type_mouvement='SORTIE', date_mouvement__date__gte=trente_jours_avant,
        service_demandeur__isnull=False
    ).values('service_demandeur__nom').annotate(
        total_sorti=Sum('quantite')
    ).order_by('-total_sorti')[:5])

    valeur_case = Case(
        When(valeur_cmup__gt=0, then=F('valeur_cmup')),
        default=Coalesce(F('article__prix_reference'), Value(0, output_field=DecimalField())),
        output_field=DecimalField()
    )
    valeur_par_famille = list(stocks_base.values('article__famille__intitule').annotate(
        total=Sum(F('quantite_physique') * valeur_case, output_field=DecimalField())
    ).order_by('-total')[:8])
    valeur_par_magasin = list(stocks_base.values('magasin__nom').annotate(
        total=Sum(F('quantite_physique') * valeur_case, output_field=DecimalField())
    ).order_by('-total'))
    resultat_valeur = stocks_base.aggregate(
        total=Sum(F('quantite_physique') * valeur_case, output_field=DecimalField())
    )
    valeur_stock_total = float(resultat_valeur['total'] or 0)

    sorties_familles_30j = {
        row['article__famille__intitule']: row['total_sorti']
        for row in mouvements_scope.filter(
            type_mouvement='SORTIE', date_mouvement__date__gte=trente_jours_avant
        ).values('article__famille__intitule').annotate(total_sorti=Sum('quantite'))
    }
    stock_par_famille = {
        row['article__famille__intitule']: row['stock_actuel']
        for row in stocks_base.values('article__famille__intitule').annotate(
            stock_actuel=Sum('quantite_physique')
        )
    }
    rotation_par_famille = []
    for fam in set(sorties_familles_30j) | set(stock_par_famille):
        sorties = sorties_familles_30j.get(fam, 0) or 0
        stock = stock_par_famille.get(fam, 0) or 0
        if stock > 0:
            taux = round(float(sorties) / float(stock), 2)
            couverture = round(30 / taux, 1) if taux > 0 else None
        else:
            taux = None
            couverture = 0 if sorties > 0 else None
        rotation_par_famille.append({
            'famille': fam or 'Général', 'sorties': sorties,
            'stock': stock, 'taux': taux, 'couverture': couverture,
        })
    rotation_par_famille.sort(key=lambda x: (x['taux'] is None, -(x['taux'] or 0)))
    rotation_par_couverture = sorted(
        rotation_par_famille,
        key=lambda x: (x['couverture'] is None, x['couverture'] if x['couverture'] is not None else float('inf'))
    )
    total_sorties_30j = sum(sorties_familles_30j.values())
    stock_moyen_total = sum(stock_par_famille.values())
    rotation_globale_30j = (
        round(float(total_sorties_30j) / float(stock_moyen_total), 2)
        if stock_moyen_total > 0 else None
    )

    data = {
        'labels_flux': labels_flux, 'entrees_flux': entrees_flux, 'sorties_flux': sorties_flux,
        'top_articles': top_articles, 'top_entrees': top_entrees, 'top_services': top_services,
        'valeur_par_famille': valeur_par_famille, 'valeur_par_magasin': valeur_par_magasin,
        'valeur_stock_total': valeur_stock_total,
        'rotation_globale_30j': rotation_globale_30j,
        'rotation_par_famille': rotation_par_famille,
        'rotation_par_couverture': rotation_par_couverture,
    }
    cache.set(key, data, _TTL_CHARTS)
    return data


def _get_peremptions(magasin_id, magasins_ids, aujourdhui):
    """Péremptions : 4 requêtes. Cache 120s."""
    key = _cache_key(magasins_ids, 'peremption')
    data = cache.get(key)
    if data is not None:
        return data
    mouvements_scope = Mouvement.objects.filter(magasin_id__in=magasins_ids)
    stocks_base = StockItem.objects.select_related(
        'article', 'article__famille', 'magasin'
    ).filter(magasin_id__in=magasins_ids)
    sorties_par_lot_map = {
        (r['article_id'], r['magasin_id'], r['numero_lot']): r['total_sorti']
        for r in mouvements_scope.filter(
            type_mouvement='SORTIE'
        ).values('article_id', 'magasin_id', 'numero_lot').annotate(total_sorti=Sum('quantite'))
    }
    stock_physique_map = {
        (r['article_id'], r['magasin_id']): r['quantite_physique']
        for r in stocks_base.values('article_id', 'magasin_id').annotate(
            quantite_physique=Sum('quantite_physique')
        )
    }
    date_alerte = aujourdhui + timedelta(days=90)
    lots_en_alerte_list = []
    for lot in Mouvement.objects.filter(
        type_mouvement='ENTREE', date_peremption__isnull=False,
        date_peremption__lte=date_alerte, date_peremption__gte=aujourdhui
    ).select_related('article', 'magasin').order_by('date_peremption'):
        qte = sorties_par_lot_map.get((lot.article_id, lot.magasin_id, lot.numero_lot), 0)
        restante = lot.quantite - qte
        phys = stock_physique_map.get((lot.article_id, lot.magasin_id), 0)
        if restante > 0 and phys > 0:
            lots_en_alerte_list.append({
                'article__designation': lot.article.designation,
                'magasin__nom': lot.magasin.nom if lot.magasin else '',
                'numero_lot': lot.numero_lot,
                'date_peremption': lot.date_peremption.isoformat(),
                'qte_sortie': qte, 'quantite_restante': restante, 'stock_physique': phys,
            })
    lots_perimes_list = []
    for lot in Mouvement.objects.filter(
        type_mouvement='ENTREE', date_peremption__isnull=False,
        date_peremption__lt=aujourdhui
    ).select_related('article', 'magasin').order_by('-date_peremption'):
        qte = sorties_par_lot_map.get((lot.article_id, lot.magasin_id, lot.numero_lot), 0)
        restante = lot.quantite - qte
        phys = stock_physique_map.get((lot.article_id, lot.magasin_id), 0)
        if restante > 0 and phys > 0:
            lots_perimes_list.append({
                'article__designation': lot.article.designation,
                'magasin__nom': lot.magasin.nom if lot.magasin else '',
                'numero_lot': lot.numero_lot,
                'date_peremption': lot.date_peremption.isoformat(),
                'qte_sortie': qte, 'quantite_restante': restante, 'stock_physique': phys,
            })
    data = {'lots_en_alerte': lots_en_alerte_list, 'lots_perimes': lots_perimes_list}
    cache.set(key, data, _TTL_PEREMPTION)
    return data


def _get_historique(magasin_id, magasins_ids, aujourdhui):
    """Historique 7 jours : 4 requêtes. Cache 60s."""
    key = _cache_key(magasins_ids, 'historique')
    data = cache.get(key)
    if data is not None:
        return data
    date_limite = aujourdhui - timedelta(days=7)
    h_articles = Article.history.filter(history_date__date__gte=date_limite).order_by('-history_date')[:12]
    h_magasins = Magasin.history.filter(history_date__date__gte=date_limite).order_by('-history_date')[:12]
    h_fournisseurs = Fournisseur.history.filter(history_date__date__gte=date_limite).order_by('-history_date')[:12]
    h_mouvements = Mouvement.history.filter(
        magasin_id__in=magasins_ids, history_date__date__gte=date_limite
    ).order_by('-history_date')[:50] if magasins_ids else []
    historique_brut = sorted(
        chain(h_articles, h_magasins, h_fournisseurs, h_mouvements),
        key=attrgetter('history_date'), reverse=True
    )[:12]
    journal = []
    for h in historique_brut:
        ht = h.history_type
        action_text = "Création" if ht == '+' else "Modification" if ht == '~' else "Suppression"
        d_color = "d4edda" if ht == '+' else "cce5ff" if ht == '~' else "f8d7da"
        c_color = "155724" if ht == '+' else "004085" if ht == '~' else "721c24"
        action_html = (
            f'<span style="background:#{d_color};'
            f'color:#{c_color};'
            f'padding:3px 8px;border-radius:12px;font-size:11px;font-weight:bold;">{action_text}</span>'
        )
        try:
            element_str = str(h)
        except Exception:
            element_str = "Élément (lié à une donnée supprimée)"
        journal.append({
            'date': h.history_date.isoformat(),
            'utilisateur': h.history_user.username.capitalize() if h.history_user else "Système",
            'action': action_html,
            'modele': h.__class__.__name__.replace('Historical', ''),
            'element': element_str,
        })
    data = {'journal_activites': journal}
    cache.set(key, data, _TTL_HISTORIQUE)
    return data


# ═══════════════════════════════════════════════════════════════════════════════
# INVALIDATION DU CACHE
# ═══════════════════════════════════════════════════════════════════════════════

def invalidate_dashboard_cache(magasin_id=None):
    """Invalide le cache du dashboard. Appeler après création/modification
    de mouvements, articles, stocks, ou péremptions."""
    cache.clear()


# ═══════════════════════════════════════════════════════════════════════════════
# VUE PRINCIPALE
# ═══════════════════════════════════════════════════════════════════════════════

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_dashboard')
@catch_errors(redirect_url='/auth/accueil/')
def dashboard_directeur(request):
    aujourdhui = timezone.now().date()
    magasin_actif = _magasin_actif(request)
    # ✅ CORRECTION : sans magasin actif, ne plus agréger TOUS les magasins
    # mais uniquement le périmètre autorisé de l'utilisateur (anti-fuite).
    if magasin_actif:
        magasins_ids = [magasin_actif.id]
    else:
        magasins_ids = list(
            get_magasins_autorises(request).values_list('id', flat=True)
        )
    magasin_id = magasin_actif.id if magasin_actif else None

    # ── Charger chaque bloc (cache hit ou miss) ──
    kpis = _get_kpis(magasins_ids, aujourdhui)
    alertes = _get_alertes(magasin_id, magasins_ids)
    charts = _get_charts(magasin_id, magasins_ids, aujourdhui)
    peremptions = _get_peremptions(magasin_id, magasins_ids, aujourdhui)
    historique = _get_historique(magasin_id, magasins_ids, aujourdhui)

    # Mouvements récents (1 requête, non caché — petit résultat)
    mouvements_recents = Mouvement.objects.filter(
        magasin_id__in=magasins_ids
    ).select_related('article', 'utilisateur').order_by('-date_mouvement')[:8]

    # Alerte sauvegarde — masquee du dashboard (visible dans /parametres/sauvegardes/)
    alerte_backup = None

    context = {
        'total_articles': kpis['total_articles'],
        'sorties_jour': kpis['sorties_jour'],
        'entrees_jour': kpis['entrees_jour'],
        'stocks_critiques': alertes['stocks_critiques'],
        'stocks_alerte': alertes['stocks_alerte'],
        'stocks_surstock': alertes['stocks_surstock'],
        'nb_critiques': alertes['nb_critiques'],
        'nb_alertes': alertes['nb_alertes'],
        'nb_surstocks': alertes['nb_surstocks'],
        'nombre_alertes': alertes['nb_critiques'] + alertes['nb_alertes'],
        'valeur_stock_total': charts['valeur_stock_total'],
        'valeur_par_famille': charts['valeur_par_famille'],
        'valeur_par_magasin': charts['valeur_par_magasin'],
        'rotation_globale_30j': charts['rotation_globale_30j'],
        'rotation_par_famille': charts['rotation_par_famille'],
        'rotation_par_couverture': charts['rotation_par_couverture'],
        'chart_articles_labels': _json_pour_script([i['article__designation'] for i in charts['top_articles']]),
        'chart_articles_data': _json_pour_script([i['total_sorti'] for i in charts['top_articles']]),
        'chart_entrees_labels': _json_pour_script([i['article__designation'] for i in charts['top_entrees']]),
        'chart_entrees_data': _json_pour_script([i['total_entree'] for i in charts['top_entrees']]),
        'chart_services_labels': _json_pour_script([i['service_demandeur__nom'] for i in charts['top_services']]),
        'chart_services_data': _json_pour_script([i['total_sorti'] for i in charts['top_services']]),
        'flux_labels': _json_pour_script(charts['labels_flux']),
        'flux_entrees': _json_pour_script(charts['entrees_flux']),
        'flux_sorties': _json_pour_script(charts['sorties_flux']),
        'chart_familles_labels': _json_pour_script([i['article__famille__intitule'] or 'Général' for i in charts['valeur_par_famille']]),
        'chart_familles_data': _json_pour_script([float(i['total']) for i in charts['valeur_par_famille']]),
        'lots_en_alerte': peremptions['lots_en_alerte'],
        'lots_perimes': peremptions['lots_perimes'],
        'journal_activites': historique['journal_activites'],
        'mouvements_recents': mouvements_recents,
        'magasin_actif': magasin_actif,
        'alerte_backup': alerte_backup,
    }
    return render(request, 'stock/dashboard.html', context)
