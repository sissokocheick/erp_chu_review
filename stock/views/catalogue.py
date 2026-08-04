from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.db import IntegrityError
from django.http import JsonResponse
from django.core.paginator import Paginator
from django.urls import reverse
from urllib.parse import urlencode
from django.contrib import messages
import logging

from accounts.permissions import verifier_permission
from ..models import Article, Mouvement, FamilleArticle, Magasin
from ..forms import ArticleForm, FamilleArticleForm
from ..decorators import magasin_requis, catch_errors

logger = logging.getLogger(__name__)


def get_magasins_autorises(request):
    """Retourne les magasins autorisés pour l'utilisateur (mono-tenant)."""
    user = request.user
    if user.is_superuser:
        return Magasin.objects.all()
    try:
        return user.profil.magasins_autorises.all()
    except Exception:
        return Magasin.objects.none()


def paginer(queryset, request, per_page_key='per_page', default=15):
    """Pagination. Si per_page='all', pas de pagination."""
    per_page_raw = request.GET.get(per_page_key, str(default))

    if per_page_raw == 'all':
        if hasattr(queryset, 'count'):
            liste = list(queryset)
        else:
            liste = list(queryset)
        count = len(liste)
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
    articles = Article.objects.all().select_related(
        'famille'
    ).prefetch_related('stocks__magasin').order_by('-date_creation')

    query = request.GET.get('q', '')
    if query:
        articles = articles.filter(
            Q(designation__icontains=query) |
            Q(reference__icontains=query)
        ).distinct()

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

    context = {
        'articles': articles_pagines,
        'q_article': query,
        'form': form,
        'per_page': per_page,
        'familles': familles,
        'famille_id': famille_id,
    }

    is_ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if is_ajax:
        return render(request, 'stock/articles_contenu.html', context)
    return render(request, 'stock/liste_articles.html', context)


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_stock')
@magasin_requis
def historique_article(request, article_id):
    article = get_object_or_404(Article, id=article_id)
    mouvements = Mouvement.objects.filter(
        article=article
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
    familles = FamilleArticle.objects.all().select_related(
        'cree_par', 'modifie_par'
    ).order_by('-date_creation')

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
        FamilleArticle, id=edit_famille_id
    ) if edit_famille_id else None
    form = FamilleArticleForm(instance=instance_f)

    if request.method == 'POST':
        if instance_f is None:
            code = request.POST.get('code', '').strip()
            if code:
                instance_f = FamilleArticle.objects.filter(
                    code__iexact=code
                ).first()
                if instance_f:
                    edit_famille_id = instance_f.id

        form = FamilleArticleForm(request.POST, instance=instance_f)
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