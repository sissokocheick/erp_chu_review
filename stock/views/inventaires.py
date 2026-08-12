import os
import logging
from datetime import datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.core.paginator import Paginator
from django.views.decorators.http import require_POST

from accounts.permissions import verifier_permission
from stock.services.isolation_service import get_magasins_autorises
from ..decorators import magasin_requis, catch_errors
from ..models import (
    Article, Magasin, StockItem, Ajustement,
    CampagneInventaire, LigneInventaire, CircuitValidation,
    FamilleArticle)
from ..services.inventaire_service import InventaireService
from .catalogue import paginer
from .common_views import render_liste, get_magasin_actif, build_redirect_url

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════
# CONSTANTE : nombre d'articles par page en saisie
# ═══════════════════════════════════════════════════════════
LIGNES_PAR_PAGE = 400

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_inventaires')
@magasin_requis
def liste_inventaires(request):
    """Dispatcher : GET affiche, POST crée."""
    if request.method == 'POST':
        return _creer_inventaire(request)
    return _afficher_inventaires(request)

def _afficher_inventaires(request):
    """Branche GET : filtres, pagination, contexte."""
    magasin_actif_id = request.session.get('magasin_actif_id')

    circuit = CircuitValidation.objects.filter(
        type_document='INVENTAIRE'
    ).first()
    circuit_actif = circuit.est_actif if circuit else False
    user_est_valideur = False
    if circuit and circuit_actif:
        user_est_valideur = circuit.valideurs.filter(id=request.user.id).exists() or request.user.is_superuser

    qs = CampagneInventaire.objects.select_related(
        'magasin', 'cree_par'
    ).filter()
    if magasin_actif_id:
        qs = qs.filter(magasin_id=magasin_actif_id)

    active_tab = request.GET.get('tab', 'en_cours')
    if active_tab == 'historique':
        qs = qs.filter(statut__in=['VALIDE', 'ANNULE'])
    else:
        qs = qs.filter(statut__in=['EN_COURS', 'A_VALIDER'])
    qs = qs.order_by('-date_creation')

    extra = {
        'magasins': Magasin.objects.all().order_by('nom'),
        'active_tab': active_tab,
        'circuit_actif': circuit_actif,
        'user_est_valideur': user_est_valideur,
        'peut_creer': request.user.has_perm('accounts.menu_inventaires') or request.user.is_superuser,
        'peut_modifier': request.user.has_perm('accounts.menu_inventaires') or request.user.is_superuser,
        # Pour le modal de création
        'familles': FamilleArticle.objects.filter(is_deleted=False).order_by('intitule'),
    }
    return render_liste(
        request, qs,
        template='stock/liste_inventaires.html',
        ajax_template='stock/inventaires_lignes.html',
        context_object_name='campagnes',
        date_field='date_creation',
        texte_champs=['titre__icontains', 'magasin__nom__icontains'],
        context_extra=extra
    )

def _creer_inventaire(request):
    """Branche POST : création campagne via service, redirection."""
    magasins_autorises = get_magasins_autorises(request)
    titre = request.POST.get('titre')
    magasin_id = request.POST.get('magasin_id')
    if magasin_id and not magasins_autorises.filter(id=magasin_id).exists():
        messages.error(request, "⛔ Vous n'avez pas accès à ce magasin.")
        return redirect('liste_inventaires')
    type_campagne = request.POST.get('type_campagne', 'GENERAL')
    familles_ids = request.POST.getlist('familles_ids')
    articles_ids = request.POST.getlist('articles_ids')

    if titre and magasin_id:
        magasin = get_object_or_404(Magasin, id=magasin_id)
        try:
            campagne = InventaireService.creer_campagne(
                titre=titre, magasin=magasin, user=request.user)
            # ═══ Post-traitement selon le type ═══
            campagne.type_campagne = type_campagne
            campagne.save(update_fields=['type_campagne'])

            if type_campagne == 'PAR_FAMILLE' and familles_ids:
                campagne.familles_cibles.set(familles_ids)
                # Supprimer les lignes qui ne sont pas dans les familles choisies
                lignes_a_supprimer = campagne.lignes_inventaire.exclude(
                    article__famille_id__in=familles_ids
                )
                lignes_a_supprimer.delete()

            elif type_campagne == 'PERSONNALISE' and articles_ids:
                campagne.articles_cibles.set(articles_ids)
                # Supprimer les lignes qui ne sont pas dans les articles choisis
                lignes_a_supprimer = campagne.lignes_inventaire.exclude(
                    article_id__in=articles_ids
                )
                lignes_a_supprimer.delete()

            messages.success(request, f"✅ La campagne '{titre}' a été créée avec succès.")
        except Exception as e:
            logger.exception("[Inventaire] %s", e)
            messages.error(request, "❌ Erreur lors de la création de la campagne.")
    return redirect('liste_inventaires')

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_inventaires')
@magasin_requis
@catch_errors(redirect_url='liste_inventaires')
def saisir_inventaire(request, campagne_id):
    campagne = get_object_or_404(
        CampagneInventaire, id=campagne_id)

    circuit = CircuitValidation.objects.filter(
        type_document='INVENTAIRE'
    ).first()
    circuit_actif = circuit.est_actif if circuit else False
    user_est_valideur = False
    if circuit and circuit_actif:
        user_est_valideur = circuit.valideurs.filter(
            id=request.user.id
        ).exists() or request.user.is_superuser

    if campagne.statut in ['VALIDE', 'ANNULE'] and request.method == 'POST':
        messages.error(request, "⛔ Cet inventaire est clôturé ou annulé.")
        return redirect('liste_inventaires')

    # ═══ Recherche sur la saisie ═══
    q = request.GET.get('q', '').strip()
    if not q and request.method == 'POST':
        q = request.POST.get('q', '').strip()

    # ═══ Pagination des lignes : 400 par page ═══
    lignes_qs = campagne.lignes_inventaire.select_related('article__famille').order_by(
        'article__famille__intitule', 'article__designation'
    )

    if q:
        lignes_qs = lignes_qs.filter(
            Q(article__designation__icontains=q) |
            Q(article__famille__intitule__icontains=q) |
            Q(article__reference__icontains=q)
        )

    paginator = Paginator(lignes_qs, LIGNES_PAR_PAGE)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    if request.method == 'POST':
        action = request.POST.get('action')
        try:
            if action == 'annuler':
                InventaireService.annuler_campagne(campagne)
                messages.success(request, "🗑️ L'inventaire a été annulé.")
                return redirect(reverse('liste_inventaires') + '?tab=historique')

            # ═══ Sauvegarde classique (fallback si JS désactivé) ═══
            if campagne.statut == 'EN_COURS' and action in ['brouillon', 'soumettre', 'approuver']:
                quantites_dict = {}
                for ligne in page_obj:
                    val = request.POST.get(f'qty_{ligne.id}')
                    if val is not None:
                        if val.strip() == '':
                            quantites_dict[ligne.id] = None
                        else:
                            quantites_dict[ligne.id] = int(val)
                if quantites_dict:
                    InventaireService.sauvegarder_saisie(campagne, quantites_dict, request.user)

            if circuit_actif:
                if action == 'soumettre':
                    InventaireService.soumettre_validation(campagne)
                    messages.success(
                        request,
                        "✅ Inventaire soumis ! En attente de validation."
                    )
                    return redirect('liste_inventaires')

            peut_valider_inventaire = (
                user_est_valideur
                or not circuit_actif
            )

            if action in ['approuver', 'rejeter']:
                if not peut_valider_inventaire:
                    messages.error(
                        request,
                        "⛔ Vous n'avez pas les droits pour valider."
                    )
                    return redirect('saisir_inventaire', campagne_id=campagne.id)
                if action == 'rejeter':
                    InventaireService.rejeter_campagne(campagne)
                    messages.warning(
                        request,
                        "🔙 Inventaire rejeté et renvoyé en saisie."
                    )
                    return redirect('liste_inventaires')

            if action == 'approuver':
                ajustements_crees = InventaireService.valider_campagne(campagne, request.user)
                messages.success(
                    request,
                    f"🎉 Inventaire clôturé ! {ajustements_crees} écart(s) corrigé(s)."
                )
                return redirect(reverse('liste_inventaires') + '?tab=historique')

            elif action == 'brouillon':
                messages.success(request, "💾 Brouillon sauvegardé.")
                # Redirection sur la même page en conservant le filtre
                url = f"{reverse('saisir_inventaire', args=[campagne.id])}?page={page_number}"
                if q:
                    url += f"&q={q}"
                return redirect(url)

        except Exception as e:
            logger.exception("[Inventaire] %s", e)
            messages.error(request, "❌ Une erreur critique est survenue.")
            url = f"{reverse('saisir_inventaire', args=[campagne.id])}?page={page_number}"
            if q:
                url += f"&q={q}"
            return redirect(url)

    # ═══ Rendu AJAX partiel (uniquement le tableau) ═══
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' and request.method == 'GET':
        return render(request, 'stock/saisir_inventaire_table.html', {
            'campagne': campagne,
            'lignes': page_obj,
            'page_obj': page_obj,
            'q_inventaire': q,
        })

    return render(request, 'stock/saisir_inventaire.html', {
        'campagne': campagne,
        'lignes': page_obj,
        'page_obj': page_obj,
        'circuit_actif': circuit_actif,
        'user_est_valideur': user_est_valideur,
        'lignes_par_page': LIGNES_PAR_PAGE,
        'q_inventaire': q,
    })

# ═══════════════════════════════════════════════════════════
# API AJAX : sauvegarde auto d'une seule ligne (pas de limite)
# ═══════════════════════════════════════════════════════════
@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_inventaires')
@require_POST
def api_sauvegarder_ligne_inventaire(request, campagne_id):
    """
    Sauvegarde la quantité physique d'une seule ligne.
    Appelée en AJAX à chaque blur/change d'input.
    """
    campagne = get_object_or_404(
        CampagneInventaire, id=campagne_id)

    if campagne.statut != 'EN_COURS':
        return JsonResponse({'success': False, 'error': 'Inventaire non modifiable.'}, status=403)

    ligne_id = request.POST.get('ligne_id')
    val = request.POST.get('quantite')

    if not ligne_id:
        return JsonResponse({'success': False, 'error': 'ligne_id manquant.'}, status=400)

    try:
        ligne = campagne.lignes_inventaire.get(id=ligne_id)
    except LigneInventaire.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Ligne introuvable.'}, status=404)

    if val is None or val.strip() == '':
        ligne.quantite_physique = None
    else:
        try:
            ligne.quantite_physique = int(val)
        except ValueError:
            return JsonResponse({'success': False, 'error': 'Quantité invalide.'}, status=400)

    ligne.save(update_fields=['quantite_physique'])
    ecart = ligne.ecart()

    return JsonResponse({
        'success': True,
        'ecart': ecart,
        'ligne_id': ligne.id,
    })
