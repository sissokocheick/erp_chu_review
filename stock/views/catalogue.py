from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.db import IntegrityError
from django.http import JsonResponse

from accounts.permissions import verifier_permission
from ..models import Article, Mouvement, FamilleArticle
from ..forms import ArticleForm, FamilleArticleForm
from ..decorators import magasin_requis, catch_errors
from ..services import StockService
from ..models import Magasin
from django.core.paginator import Paginator
from django.urls import reverse
from urllib.parse import urlencode
from django.contrib import messages


def get_magasins_autorises(request):
    entreprise = request.entreprise
    if not entreprise:
        return Magasin.objects.none()
    user = request.user
    if user.is_superuser:
        return Magasin.objects.filter(entreprise=entreprise)
    return user.profil.magasins_autorises.filter(entreprise=entreprise)


def paginer(queryset, request, per_page_key='per_page', default=15):
    """Pagination. Si per_page='all', pas de pagination (retourne tout)."""
    per_page_raw = request.GET.get(per_page_key, str(default))

    if per_page_raw == 'all':
        # Pas de pagination : on force l'evaluation en liste pour eviter
        # les requetes COUNT/LIMIT inutiles
        if hasattr(queryset, 'count'):
            # C'est un QuerySet, on le convertit en liste
            liste = list(queryset)
        else:
            liste = list(queryset)
        count = len(liste)
        # On cree un paginator avec tous les elements sur une seule page
        paginator = Paginator(liste, max(count, 1))
        page = paginator.get_page(1)
        return page, 'all'

    try:
        per_page = int(per_page_raw)
    except ValueError:
        per_page = default

    page = request.GET.get('page')
    return Paginator(queryset, per_page).get_page(page), per_page


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
    entreprise = request.entreprise
    articles = Article.objects.filter(entreprise=entreprise).select_related(
        'famille'
    ).prefetch_related('stocks__magasin').order_by('-date_creation')

    query = request.GET.get('q', '')
    if query:
        articles = articles.filter(
            Q(designation__icontains=query) |
            Q(reference__icontains=query)
        ).distinct()

    # -- Filtre par famille --
    famille_id = request.GET.get('famille', '')
    if famille_id:
        articles = articles.filter(famille_id=famille_id)

    articles_pagines, per_page = paginer(articles, request)

    edit_article_id = (
        request.GET.get('edit_article')
        or request.POST.get('edit_article')
        or request.POST.get('article_id')
    )
    instance_a = get_object_or_404(
        Article, id=edit_article_id, entreprise=entreprise
    ) if edit_article_id else None
    form = ArticleForm(instance=instance_a, entreprise=entreprise)

    if request.method == 'POST':
        form = ArticleForm(request.POST, instance=instance_a, entreprise=entreprise)
        if form.is_valid():
            article = form.save(commit=False)
            article.entreprise = entreprise
            if not article.pk:
                article.cree_par = request.user
            article.modifie_par = request.user

            try:
                article.save()
                action_text = "modifie" if edit_article_id else "ajoute"
                messages.success(
                    request,
                    "L'article '" + article.designation + "' a ete " + action_text + " avec succes !"
                )
                return redirect(build_redirect_url(
                    'liste_articles',
                    query=query,
                    per_page=per_page,
                    famille_id=famille_id
                ))
            except IntegrityError:
                messages.error(request, "Erreur de base de donnees : Cet article existe deja.")
        else:
            messages.error(request, "Veuillez corriger les erreurs dans le formulaire.")

    # Recuperer les familles pour le filtre
    familles = FamilleArticle.objects.filter(entreprise=entreprise).order_by('intitule')

    context = {
        'articles': articles_pagines,
        'q_article': query,
        'form': form,
        'per_page': per_page,
        'familles': familles,
        'famille_id': famille_id,
    }

    # Detection requete AJAX (fetch vanilla)
    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if is_ajax:
        # Recharge table + pagination + compteur
        return render(request, 'stock/articles_contenu.html', context)
    return render(request, 'stock/liste_articles.html', context)


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_stock')
@magasin_requis
def historique_article(request, article_id):
    entreprise = request.entreprise
    article = get_object_or_404(Article, id=article_id, entreprise=entreprise)
    mouvements = Mouvement.objects.filter(
        article=article, magasin__entreprise=entreprise
    ).select_related('magasin', 'fournisseur', 'service_demandeur', 'utilisateur')

    tri = request.GET.get('tri', 'date_desc')
    if tri == 'date_asc':
        mouvements = mouvements.order_by('date_mouvement')
    elif tri == 'alpha':
        mouvements = mouvements.order_by('type_mouvement', '-date_mouvement')
    else:
        mouvements = mouvements.order_by('-date_mouvement')

    context = {'article': article, 'mouvements': mouvements, 'tri': tri}
    return render(request, 'stock/historique_article.html', context)


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_familles')
def liste_familles(request):
    entreprise = request.entreprise
    familles = FamilleArticle.objects.filter(
        entreprise=entreprise
    ).select_related('cree_par', 'modifie_par').order_by('-date_creation')

    query = request.GET.get('q', '')
    if query:
        familles = familles.filter(
            Q(code__icontains=query) | Q(intitule__icontains=query)
        ).distinct()

    familles_pagines, per_page = paginer(familles, request)

    edit_famille_id = (
        request.GET.get('edit_famille')
        or request.POST.get('edit_famille')
        or request.POST.get('famille_id')
    )
    instance_f = get_object_or_404(
        FamilleArticle, id=edit_famille_id, entreprise=entreprise
    ) if edit_famille_id else None
    form = FamilleArticleForm(instance=instance_f)

    if request.method == 'POST':
        if instance_f is None:
            code = request.POST.get('code', '').strip()
            if code:
                instance_f = FamilleArticle.objects.filter(
                    entreprise=entreprise, code__iexact=code
                ).first()
                if instance_f:
                    edit_famille_id = instance_f.id
        form = FamilleArticleForm(request.POST, instance=instance_f)
        if form.is_valid():
            famille = form.save(commit=False)
            famille.entreprise = entreprise
            if not famille.pk:
                famille.cree_par = request.user
            famille.modifie_par = request.user
            query_check = FamilleArticle.objects.filter(
                entreprise=entreprise, code__iexact=famille.code
            )
            if famille.pk:
                query_check = query_check.exclude(pk=famille.pk)
            if query_check.exists():
                messages.error(
                    request,
                    f"Impossible : Le code '{famille.code}' existe deja."
                )
            else:
                try:
                    famille.save()
                    action_text = "modifiee" if edit_famille_id else "ajoutee"
                    messages.success(
                        request,
                        f"La famille '{famille.intitule}' a ete {action_text} avec succes !"
                    )
                    return redirect(build_redirect_url('liste_familles', query=query, per_page=per_page))
                except IntegrityError as e:
                    logger.exception("[Catalogue] %s", e)
                    messages.error(request, "Erreur de base de données. Veuillez réessayer.")
        else:
            messages.error(request, "Veuillez corriger les erreurs dans le formulaire.")

    # -- Contexte pour AJAX (recharge table + pagination + compteur) --
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

# =======================================================================
# API VERIFICATION DOUBLON ARTICLE (AJAX)
# =======================================================================
@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_articles')
@magasin_requis
def verifier_article(request):
    """API AJAX : verifie si un article existe deja (designation ou reference)."""
    entreprise = request.entreprise
    designation = request.GET.get('designation', '').strip()
    reference = request.GET.get('reference', '').strip()
    exclude_id = request.GET.get('exclude_id', '').strip()

    article = None
    if designation:
        article = Article.objects.filter(
            entreprise=entreprise, designation__iexact=designation
        ).first()
    elif reference:
        article = Article.objects.filter(
            entreprise=entreprise, reference__iexact=reference
        ).first()

    if article:
        # Exclure l'article en cours de modification
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
