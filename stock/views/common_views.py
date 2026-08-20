"""
Helpers pour standardiser les vues fonctionnelles (FBV) du module stock.
À importer dans chaque fichier de vues pour remplacer le copier/coller répété.
"""
from datetime import datetime
import unicodedata
from django.db.models import Q
from django.core.paginator import Paginator
from core.utils import paginer
from django.shortcuts import render
from ..models import Magasin
from django.urls import reverse
from urllib.parse import urlencode


def normaliser_texte(texte):
    """Normalise un texte pour la recherche : minuscules, sans accents,
    sans apostrophes (droites ou typographiques) ni espaces superflus."""
    normalise = ''.join(
        c for c in unicodedata.normalize('NFD', str(texte))
        if unicodedata.category(c) != 'Mn'
    ).lower()
    return normalise.replace("'", '').replace('\u2019', '').replace('\u2018', '')


def _get_valeurs(obj, chemin):
    """Résout un chemin 'a__b__c' en une liste de valeurs, en gérant les relations
    multiples (related managers) via .all()."""
    valeurs = [obj]
    for partie in chemin.split('__'):
        nouvelles = []
        for v in valeurs:
            if v is None:
                continue
            attr = getattr(v, partie, None)
            if hasattr(attr, 'all'):
                nouvelles.extend(list(attr.all()))
            else:
                nouvelles.append(attr)
        valeurs = nouvelles
    return [v for v in valeurs if v is not None]


def filtrer_texte(qs, q, champs):
    """
    Filtre un queryset/une liste en ignorant les accents.
    champs : chemins de champs, ex : ['designation', 'reference', 'article__designation'].
    Retourne une liste (compatible Paginator).
    """
    if not q:
        return qs
    q_norm = normaliser_texte(q)
    if not q_norm:
        return qs
    if hasattr(qs, 'all'):
        qs = list(qs)
    resultats = []
    for obj in qs:
        for champ in champs:
            if any(q_norm in normaliser_texte(v) for v in _get_valeurs(obj, champ)):
                resultats.append(obj)
                break
    return resultats

def get_magasin_actif(request):
    """Retourne le magasin actif de la session si autorisé."""
    magasin_id = request.session.get('magasin_actif_id')
    return Magasin.objects.filter(
        id=magasin_id
    ).first()


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
    Applique un filtre OR sur plusieurs champs, insensible aux accents.
    champs: liste de strings, ex: ['numero_bon__icontains', 'fournisseur__raison_sociale__icontains']
    """
    q = request.GET.get(param, '')
    if q and champs:
        chemins = [c.split('__icontains')[0].split('__contains')[0] for c in champs]
        qs = filtrer_texte(qs, q, chemins)
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
                 date_field='date_creation', texte_champs=None,
                 colonnes_tri=None, tri_defaut=None):
    """
    Prépare le contexte complet pour une vue liste et renvoie le bon template
    (HTML complet ou fragment AJAX).

    colonnes_tri : dict {clé_GET -> champ_ordre} des colonnes triables par
    clic sur les en-têtes (None = pas de tri). tri_defaut : order_by par
    défaut (sinon '-<date_field>').
    """
    if texte_champs:
        qs, q = filtrer_par_texte(qs, request, texte_champs)
    else:
        q = ''

    qs, date_range = filtrer_par_date(qs, request, date_field)
    if colonnes_tri:
        from .catalogue import appliquer_tri
        qs, tri, ordre = appliquer_tri(
            qs, request, colonnes_tri,
            defaut=tri_defaut or f'-{date_field}',
        )
    else:
        tri, ordre = '', 'asc'
    page_obj, per_page = paginer(qs, request)

    context = {
        context_object_name: page_obj,
        'q': q,
        'date_range': date_range,
        'per_page': per_page,
        'magasin_actif': get_magasin_actif(request),
        'tri': tri,
        'ordre': ordre,
    }
    if context_extra:
        context.update(context_extra)

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return render(request, ajax_template, context)
    return render(request, template, context)