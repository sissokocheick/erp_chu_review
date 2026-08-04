"""
Helpers pour standardiser les vues fonctionnelles (FBV) du module stock.
À importer dans chaque fichier de vues pour remplacer le copier/coller répété.
"""
from datetime import datetime
from django.db.models import Q
from django.core.paginator import Paginator
from django.shortcuts import render
from ..models import Magasin
from django.urls import reverse
from urllib.parse import urlencode

def get_magasin_actif(request):
    """Retourne le magasin actif de la session si autorisé."""
    magasin_id = request.session.get('magasin_actif_id')
    # if magasin_id and None  # SUPPRIMÉ (mono-tenant)
    return Magasin.objects.filter(
        id=magasin_id
    ).first()
    return None

def paginer(qs, request, per_page_key='per_page', default=15, max_all=500):
    """Pagination identique à catalogue.paginer()."""
    per_page = request.GET.get(per_page_key, str(default))
    is_list = isinstance(qs, list)
    if per_page == 'all':
        count = len(qs) if is_list else qs.count()
        limite = min(count, max_all) if count > 0 else 1
    else:
        try:
            limite = int(per_page)
        except ValueError:
            limite = default
    page = request.GET.get('page')
    return Paginator(qs, limite).get_page(page), per_page

def filtrer_par_date(qs, request, date_field='date_creation'):
    """Applique le filtre date_range sur un queryset."""
    date_range = request.GET.get('date_range', '')
    if date_range:
        try:
            dates = date_range.split(' - ')
            if len(dates) == 2:
                date_debut = datetime.strptime(dates[0], '%d/%m/%Y').date()
                date_fin = datetime.strptime(dates[1], '%d/%m/%Y').date()
                qs = qs.filter(
                    **{f'{date_field}__date__gte': date_debut,
                       f'{date_field}__date__lte': date_fin}
                )
        except ValueError:
            pass
    return qs, date_range

def filtrer_par_texte(qs, request, champs, param='q'):
    """
    Applique un filtre Q() OR sur plusieurs champs.
    champs: liste de strings, ex: ['numero_bon__icontains', 'fournisseur__raison_sociale__icontains']
    """
    q = request.GET.get(param, '')
    if q and champs:
        q_filter = Q()
        for champ in champs:
            q_filter |= Q(**{champ: q})
        qs = qs.filter(q_filter).distinct()
    return qs, q

def build_redirect_url(base_name, query=None, per_page=None, default_per_page='15'):
    """Construit une URL de redirection en conservant filtres & pagination."""
    url = reverse(base_name)
    params = {}
    if query:
        params['q'] = query
    if per_page and str(per_page) != default_per_page:
        params['per_page'] = per_page
    if params:
        url += '?' + urlencode(params)
    return url

def render_liste(request, qs, template, ajax_template,
                 context_extra=None, context_object_name='items',
                 date_field='date_creation', texte_champs=None):
    """
    Prépare le contexte complet pour une vue liste et renvoie le bon template
    (HTML complet ou fragment AJAX).
    """
    if texte_champs:
        qs, q = filtrer_par_texte(qs, request, texte_champs)
    else:
        q = ''

    qs, date_range = filtrer_par_date(qs, request, date_field)
    page_obj, per_page = paginer(qs, request)

    context = {
        context_object_name: page_obj,
        'q': q,
        'date_range': date_range,
        'per_page': per_page,
        'magasin_actif': get_magasin_actif(request),
    }
    if context_extra:
        context.update(context_extra)

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return render(request, ajax_template, context)
    return render(request, template, context)