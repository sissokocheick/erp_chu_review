import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Q, Exists, OuterRef
from django.db import IntegrityError
from django.http import JsonResponse
from django.core.paginator import Paginator
from core.utils import paginer
from django.urls import reverse
from decimal import Decimal
from urllib.parse import urlencode
from django.contrib import messages
import logging

from accounts.permissions import verifier_permission
from ..models import (
    Article, ArticleFournisseur, Fournisseur, Mouvement, FamilleArticle, FamilleParametre,
    StockItem, LigneBon, LigneCommande, UniteMesure)
from ..forms import ArticleForm, FamilleArticleForm
from ..decorators import magasin_requis, catch_errors
from .common_views import filtrer_texte

logger = logging.getLogger(__name__)


def appliquer_tri(queryset, request, colonnes, defaut):
    """Tri serveur par clic sur les en-têtes de colonnes.

    colonnes : dict {clé_GET -> champ_ordre} — seule liste blanche
               des colonnes triables (jamais d'entrée utilisateur brute).
    defaut   : order_by par défaut (ex. '-date_creation').
    Retourne (queryset, tri, ordre) où tri/ordre sont les valeurs GET
    (vides si aucune colonne demandée) pour alimenter les en-têtes.
    """
    tri = request.GET.get('tri', '')
    ordre = request.GET.get('ordre', 'asc')
    if tri in colonnes:
        champ = colonnes[tri]
        if ordre == 'desc':
            champ = '-' + champ.lstrip('-')
        queryset = queryset.order_by(champ)
    else:
        queryset = queryset.order_by(defaut)
    return queryset, tri, ordre




def build_redirect_url(base_name, query=None, per_page=None, default_per_page=15, famille_id=None):
    url = reverse(base_name)
    params = {}
    if query:
        params['q'] = query
    if per_page and str(per_page) != str(default_per_page):
        params['per_page'] = per_page
    if famille_id:
        params['famille'] = famille_id
    if params:
        url += '?' + urlencode(params)
    return url


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_articles')
@magasin_requis
@catch_errors(redirect_url='liste_articles')
def liste_articles(request):
    articles = Article.objects.all().select_related(
        'famille', 'cree_par', 'modifie_par'
    ).prefetch_related('stocks__magasin', 'tarifs_fournisseurs__fournisseur')

    articles, tri, ordre = appliquer_tri(
        articles, request,
        colonnes={
            'designation': 'designation',
            'reference': 'reference',
            'famille': 'famille__intitule',
            'seuil_min': 'seuil_minimum',
            'date_creation': 'date_creation',
        },
        defaut='-date_creation',
    )

    famille_id = request.GET.get('famille', '')
    if famille_id:
        articles = articles.filter(famille_id=famille_id)

    query = request.GET.get('q', '')
    if query:
        articles = filtrer_texte(articles, query, ['designation', 'reference'])

    # Anti N+1 : les dépendances sont évaluées dans la requête des articles
    # via EXISTS, au lieu de quatre requêtes globales après pagination.
    articles = articles.annotate(
        _a_des_dependances=Exists(Mouvement.objects.filter(article_id=OuterRef('pk')))
        | Exists(StockItem.objects.filter(article_id=OuterRef('pk')))
        | Exists(LigneBon.objects.filter(article_id=OuterRef('pk')))
        | Exists(LigneCommande.objects.filter(article_id=OuterRef('pk')))
    )

    articles_pagines, per_page = paginer(articles, request)

    edit_article_id = (
        request.GET.get('edit_article')
        or request.POST.get('edit_article')
        or request.POST.get('article_id')
    )
    instance_a = get_object_or_404(
        Article, id=edit_article_id
    ) if edit_article_id else None
    form = ArticleForm(instance=instance_a)

    if request.method == 'POST':
        form = ArticleForm(request.POST, instance=instance_a)
        if form.is_valid():
            article = form.save(commit=False)
            if not article.pk:
                article.cree_par = request.user
            article.modifie_par = request.user

            try:
                article.save()

                # Traitement des tarifs fournisseurs saisis dans le formulaire article
                fournisseur_ids = request.POST.getlist('tarif_fournisseur_id[]')
                prix_achats = request.POST.getlist('tarif_prix_achat[]')
                refs_fourn = request.POST.getlist('tarif_ref_fournisseur[]')
                delais = request.POST.getlist('tarif_delai[]')
                principal_val = request.POST.get('tarif_principal_val')

                if fournisseur_ids:
                    article.tarifs_fournisseurs.all().delete()
                    for idx, (f_id, prix) in enumerate(zip(fournisseur_ids, prix_achats)):
                        if f_id and prix:
                            try:
                                f_int = int(f_id)
                                p_dec = Decimal(str(prix).replace(',', '.'))
                                r_f = refs_fourn[idx] if idx < len(refs_fourn) else ''
                                d_j = int(delais[idx]) if idx < len(delais) and str(delais[idx]).isdigit() else None
                                is_p = (str(idx) == str(principal_val))
                                ArticleFournisseur.objects.create(
                                    article=article,
                                    fournisseur_id=f_int,
                                    prix_achat=p_dec,
                                    reference_fournisseur=r_f,
                                    delai_livraison_jours=d_j,
                                    est_principal=is_p,
                                    cree_par=request.user,
                                    modifie_par=request.user
                                )
                            except (ValueError, TypeError):
                                pass

                action_text = "modifié" if edit_article_id else "ajouté"
                messages.success(
                    request,
                    f"L'article '{article.designation}' a été {action_text} avec succès !"
                )
                return redirect(build_redirect_url(
                    'liste_articles',
                    query=query,
                    per_page=per_page,
                    famille_id=famille_id
                ))
            except IntegrityError:
                messages.error(request, "Erreur de base de données : Cet article existe déjà.")
        else:
            messages.error(request, "Veuillez corriger les erreurs dans le formulaire.")

    familles = FamilleArticle.objects.all().order_by('intitule')
    fournisseurs = Fournisseur.objects.filter(is_deleted=False).order_by('raison_sociale')
    article_tarifs = list(instance_a.tarifs_fournisseurs.filter(is_deleted=False).select_related('fournisseur')) if instance_a else []

    # Le statut est déjà annoté dans la requête principale : aucun accès DB
    # supplémentaire dans la boucle d'affichage.
    ids_lies = {
        a.id for a in articles_pagines if getattr(a, '_a_des_dependances', False)
    }

    # Donnees famille pour auto-check dans le formulaire article
    familles_data = {
        str(f.id): {
            'gere_lots_peremption': f.gere_lots_peremption,
            'est_immobilisable': f.est_immobilisable,
        }
        for f in familles
    }

    context = {
        'articles': articles_pagines,
        'q_article': query,
        'form': form,
        'per_page': per_page,
        'familles': familles,
        'fournisseurs': fournisseurs,
        'article_tarifs': article_tarifs,
        'familles_data_json': json.dumps(familles_data),
        'famille_id': famille_id,
        'articles_lies': ids_lies,
        'tri': tri,
        'ordre': ordre,
        'unites_mesure': UniteMesure.objects.filter(actif=True).order_by('nom'),
    }

    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if is_ajax:
        return render(request, 'stock/articles_contenu.html', context)
    return render(request, 'stock/liste_articles.html', context)


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_articles')
def api_tarifs_article(request, article_id):
    """API AJAX : consultation et mise à jour des tarifs fournisseurs d'un article."""
    article = get_object_or_404(Article, id=article_id, is_deleted=False)

    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            tarifs_list = data.get('tarifs', [])
            article.tarifs_fournisseurs.all().delete()
            for t in tarifs_list:
                f_id = t.get('fournisseur_id')
                prix = t.get('prix_achat')
                if f_id and prix is not None:
                    ArticleFournisseur.objects.create(
                        article=article,
                        fournisseur_id=int(f_id),
                        prix_achat=Decimal(str(prix)),
                        reference_fournisseur=t.get('reference_fournisseur', '').strip(),
                        delai_livraison_jours=int(t.get('delai_livraison_jours')) if str(t.get('delai_livraison_jours', '')).isdigit() else None,
                        est_principal=bool(t.get('est_principal', False)),
                        cree_par=request.user,
                        modifie_par=request.user
                    )
            return JsonResponse({'success': True, 'message': 'Tarifs fournisseurs enregistrés avec succès.'})
        except Exception as e:
            return JsonResponse({'success': False, 'error': str(e)}, status=400)

    # GET
    tarifs = []
    for tf in article.tarifs_fournisseurs.filter(is_deleted=False).select_related('fournisseur').order_by('-est_principal', 'prix_achat'):
        tarifs.append({
            'id': tf.id,
            'fournisseur_id': tf.fournisseur_id,
            'fournisseur_code': tf.fournisseur.code,
            'fournisseur_nom': tf.fournisseur.raison_sociale,
            'prix_achat': float(tf.prix_achat),
            'reference_fournisseur': tf.reference_fournisseur or '',
            'delai_livraison_jours': tf.delai_livraison_jours or '',
            'est_principal': tf.est_principal,
        })

    fournisseurs = [
        {'id': f.id, 'code': f.code, 'nom': f.raison_sociale}
        for f in Fournisseur.objects.filter(is_deleted=False).order_by('raison_sociale')
    ]

    return JsonResponse({
        'article': {
            'id': article.id,
            'designation': article.designation,
            'reference': article.reference or '',
            'prix_reference': float(article.prix_reference or 0),
        },
        'tarifs': tarifs,
        'fournisseurs': fournisseurs,
    })


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_stock')
@magasin_requis
def historique_article(request, article_id):
    article = get_object_or_404(Article, id=article_id)
    # Cohérence avec le PDF : isolation par magasins autorisés.
    from stock.services.isolation_service import get_magasins_autorises
    mouvements = Mouvement.objects.filter(
        article=article,
        magasin__in=get_magasins_autorises(request),
    ).select_related('magasin', 'fournisseur', 'service_demandeur', 'utilisateur')

    mouvements, tri, ordre = appliquer_tri(
        mouvements, request,
        colonnes={
            'date_mouvement': 'date_mouvement',
            'type_mouvement': 'type_mouvement',
            'quantite': 'quantite',
            'magasin': 'magasin__nom',
            'service_demandeur': 'service_demandeur__nom',
            'utilisateur': 'utilisateur__first_name',
        },
        defaut='-date_mouvement',
    )

    context = {'article': article, 'mouvements': mouvements, 'tri': tri, 'ordre': ordre}
    return render(request, 'stock/historique_article.html', context)


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_familles')
def liste_familles(request):
    familles = FamilleArticle.objects.all().select_related(
        'cree_par', 'modifie_par'
    ).order_by('-date_creation')

    query = request.GET.get('q', '')
    if query:
        familles = filtrer_texte(familles, query, ['code', 'intitule'])

    familles_pagines, per_page = paginer(familles, request)

    edit_famille_id = (
        request.GET.get('edit_famille')
        or request.POST.get('edit_famille')
        or request.POST.get('famille_id')
    )
    instance_f = get_object_or_404(
        FamilleArticle, id=edit_famille_id
    ) if edit_famille_id else None

    # Valeurs uniques pour les selects avec ajout
    categories_existantes = sorted(set(FamilleArticle.objects.exclude(categorie__isnull=True).exclude(categorie='').values_list('categorie', flat=True).distinct()) | set(FamilleParametre.objects.filter(type_parametre='CATEGORIE', actif=True).values_list('valeur', flat=True)))
    lignes_budgetaires_existantes = sorted(set(FamilleArticle.objects.exclude(ligne_budgetaire__isnull=True).exclude(ligne_budgetaire='').values_list('ligne_budgetaire', flat=True).distinct()) | set(FamilleParametre.objects.filter(type_parametre='LIGNE_BUDGETAIRE', actif=True).values_list('valeur', flat=True)))
    types_famille_existantes = sorted(set(FamilleArticle.objects.exclude(type_famille__isnull=True).exclude(type_famille='').values_list('type_famille', flat=True).distinct()) | set(FamilleParametre.objects.filter(type_parametre='TYPE_FAMILLE', actif=True).values_list('valeur', flat=True)))
    valorisations_existantes = sorted(set(FamilleArticle.objects.exclude(methode_valorisation__isnull=True).exclude(methode_valorisation='').values_list('methode_valorisation', flat=True).distinct()) | set(FamilleParametre.objects.filter(type_parametre='VALORISATION', actif=True).values_list('valeur', flat=True)))
    form = FamilleArticleForm(
        instance=instance_f,
        categories=categories_existantes,
        lignes_budgetaires=lignes_budgetaires_existantes,
        types_famille=types_famille_existantes,
        valorisations=valorisations_existantes,
    )

    if request.method == 'POST':
        if instance_f is None:
            code = request.POST.get('code', '').strip()
            if code:
                instance_f = FamilleArticle.objects.filter(
                    code__iexact=code
                ).first()
                if instance_f:
                    edit_famille_id = instance_f.id

        form = FamilleArticleForm(
            request.POST,
            instance=instance_f,
            categories=categories_existantes,
            lignes_budgetaires=lignes_budgetaires_existantes,
            types_famille=types_famille_existantes,
            valorisations=valorisations_existantes,
        )
        if form.is_valid():
            famille = form.save(commit=False)
            if not famille.pk:
                famille.cree_par = request.user
            famille.modifie_par = request.user

            query_check = FamilleArticle.objects.filter(
                code__iexact=famille.code
            )
            if famille.pk:
                query_check = query_check.exclude(pk=famille.pk)

            if query_check.exists():
                messages.error(
                    request,
                    f"Impossible : Le code '{famille.code}' existe déjà."
                )
            else:
                try:
                    famille.save()
                    action_text = "modifiée" if edit_famille_id else "ajoutée"
                    messages.success(
                        request,
                        f"La famille '{famille.intitule}' a été {action_text} avec succès !"
                    )
                    return redirect(build_redirect_url('liste_familles', query=query, per_page=per_page))
                except IntegrityError as e:
                    logger.exception("[Catalogue] %s", e)
                    messages.error(request, "Erreur de base de données. Veuillez réessayer.")
        else:
            messages.error(request, "Veuillez corriger les erreurs dans le formulaire.")

    is_ajax = (
        request.headers.get('X-Requested-With') == 'XMLHttpRequest'
        or request.META.get('HTTP_X_REQUESTED_WITH') == 'XMLHttpRequest'
    )
    if is_ajax:
        return render(request, 'stock/familles_contenu.html', {
            'familles': familles_pagines,
            'q_article': query,
            'per_page': per_page,
            'peut_creer': request.user.has_perm('accounts.menu_familles') or request.user.is_superuser,
        })

    context = {
        'familles': familles_pagines,
        'q_article': query,
        'form': form,
        'per_page': per_page,
        'peut_creer': request.user.has_perm('accounts.menu_familles') or request.user.is_superuser,
    }
    return render(request, 'stock/liste_familles.html', context)


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_articles')
@magasin_requis
def verifier_article(request):
    """API AJAX : vérifie si un article existe déjà."""
    designation = request.GET.get('designation', '').strip()
    reference = request.GET.get('reference', '').strip()
    exclude_id = request.GET.get('exclude_id', '').strip()

    article = None
    if designation:
        article = Article.objects.filter(designation__iexact=designation).first()
    elif reference:
        article = Article.objects.filter(reference__iexact=reference).first()

    if article:
        if exclude_id and str(article.id) == exclude_id:
            return JsonResponse({'existe': False})
        return JsonResponse({
            'existe': True,
            'article': {
                'id': article.id,
                'designation': article.designation,
                'reference': article.reference or '-',
                'famille': article.famille.intitule if article.famille else '-'
            }
        })
    return JsonResponse({'existe': False})