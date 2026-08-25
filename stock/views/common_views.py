"""
Helpers pour standardiser les vues fonctionnelles (FBV) du module stock.
À importer dans chaque fichier de vues pour remplacer le copier/coller répété.
"""
from datetime import datetime
import unicodedata
from django.core.exceptions import FieldError
from django.db import connection
from django.db.models import CharField, F, Func, Q
from django.core.paginator import Paginator
from core.utils import paginer
from django.shortcuts import render
from ..models import Magasin
from django.urls import reverse
from urllib.parse import urlencode

# Constantes de normalisation SQL : chaque caractère accentué de FROM est
# remplacé par son équivalent de TO ; les apostrophes (en fin de FROM,
# au-delà de la longueur de TO) sont supprimées. Mêmes règles que
# normaliser_texte(), appliquées côté base de données.
_ACCENTS_SQL_FROM = "àáâãäåçèéêëìíîïñòóôõöùúûüýÿ'’‘"
_ACCENTS_SQL_TO = "aaaaaaceeeeiiiinooooouuuuyy"


def normaliser_texte(texte):
    """Normalise un texte pour la recherche : minuscules, sans accents,
    sans apostrophes (droites ou typographiques) ni espaces superflus."""
    normalise = ''.join(
        c for c in unicodedata.normalize('NFD', str(texte))
        if unicodedata.category(c) != 'Mn'
    ).lower()
    return normalise.replace("'", '').replace('\u2019', '').replace('\u2018', '')


def _expr_sans_accents(champ):
    """Expression PostgreSQL : LOWER(champ) privé d'accents et d'apostrophes.

    TRANSLATE/LOWER sont natifs PostgreSQL (aucune extension requise).
    Les constantes _ACCENTS_SQL_* sont du code, pas des entrées utilisateur :
    la requête utilisateur ne transite jamais dans le texte SQL. L'apostrophe
    droite est doublée pour rester un littéral SQL valide.
    """
    from_sql = _ACCENTS_SQL_FROM.replace("'", "''")
    return Func(
        F(champ),
        function='TRANSLATE',
        template=(
            "TRANSLATE(LOWER(%(expressions)s), "
            f"'{from_sql}', '{_ACCENTS_SQL_TO}')"
        ),
        output_field=CharField(),
    )


def _chemin_multi_valeurs(model, chemin):
    """True si un chemin 'a__b__c' traverse une relation multiple (M2M ou
    reverse FK) — auquel cas la jointure peut dupliquer des lignes."""
    m = model
    for partie in chemin.split('__')[:-1]:
        try:
            f = m._meta.get_field(partie)
        except Exception:
            return True  # champ inconnu → prudence
        if getattr(f, 'one_to_many', False) or getattr(f, 'many_to_many', False):
            return True
        if not f.is_relation:
            return False
        m = f.related_model
    return False


def _filtrer_texte_sql(qs, q_norm, champs):
    """Filtre accent-insensible exécuté par la base (jamais de chargement
    mémoire de la table). Lève une exception si un chemin est invalide →
    repli Python assuré par l'appelant."""
    from django.core.exceptions import FieldDoesNotExist

    annotations = {}
    q_obj = Q()
    distinct = False
    for i, chemin in enumerate(champs):
        # Valide le chemin via model Meta (lève FieldDoesNotExist sinon)
        m = qs.model
        parties = chemin.split('__')
        for j, partie in enumerate(parties):
            try:
                f = m._meta.get_field(partie)
            except FieldDoesNotExist:
                raise FieldError(f"Chemin de recherche invalide : {chemin}")
            if j < len(parties) - 1:
                if not f.is_relation:
                    raise FieldError(f"Chemin de recherche invalide : {chemin}")
                m = f.related_model
        annotations[f'_nx{i}'] = _expr_sans_accents(chemin)
        # icontains : %, _ et \ sont échappés automatiquement par Django
        # (PatternLookup / connection.ops.pattern_escape).
        q_obj |= Q(**{f'_nx{i}__icontains': q_norm})
        if _chemin_multi_valeurs(qs.model, chemin):
            distinct = True
    qs = qs.annotate(**annotations).filter(q_obj)
    return qs.distinct() if distinct else qs


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
    Retourne un QuerySet (si l'entrée était un QuerySet) ou une liste.

    ✅ CORRECTION PERF : sur QuerySet + PostgreSQL, le filtre est exécuté par
    la base (LOWER + TRANSLATE natifs, aucune extension requise) — plus aucun
    chargement de table entière en mémoire ni re-requête par pk__in.
    Repli Python conservé pour les listes déjà matérialisées.

    IMPORTANT : conserve toujours un QuerySet si l'entrée est un QuerySet,
    pour que les appels .filter()/.order_by() en aval fonctionnent.
    """
    if not q:
        return qs
    q_norm = normaliser_texte(q)
    if not q_norm:
        return qs

    # Voie SQL : QuerySet sur PostgreSQL → filtre côté base de données.
    if hasattr(qs, 'all') and getattr(qs, 'model', None) is not None \
            and connection.vendor == 'postgresql':
        try:
            return _filtrer_texte_sql(qs, q_norm, champs)
        except FieldError:
            pass  # chemin inattendu → repli Python (comportement historique)

    # Voie Python : listes matérialisées (ou SGBD sans TRANSLATE).
    qs_model = getattr(qs, 'model', None)
    if hasattr(qs, 'all'):
        qs = list(qs)
    resultats = []
    for obj in qs:
        for champ in champs:
            if any(q_norm in normaliser_texte(v) for v in _get_valeurs(obj, champ)):
                resultats.append(obj)
                break
    # Si l'entrée était un QuerySet, retourner un QuerySet filtré
    # (compatible .filter()/.order_by() en aval).
    if resultats and qs_model is not None:
        ids = [obj.pk for obj in resultats]
        return qs_model._default_manager.filter(pk__in=ids)
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