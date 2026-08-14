# -*- coding: utf-8 -*-
# stock/views/transferts.py
"""Vues des transferts inter-magasins."""
import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.shortcuts import redirect, render, get_object_or_404
from django.urls import reverse
from django.utils import timezone

from accounts.permissions import verifier_permission
from stock.services.isolation_service import get_magasins_autorises
from ..decorators import magasin_requis, catch_errors
from ..models import Article, BonMouvement, Magasin, Mouvement
from ..services.transfert_service import TransfertService
from .catalogue import paginer
from .common_views import get_magasin_actif

logger = logging.getLogger(__name__)


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_transferts')
@magasin_requis
@catch_errors(redirect_url='liste_transferts')
def liste_transferts(request):
    """Liste des transferts + création via modale."""
    magasins_autorises = get_magasins_autorises(request)
    magasin_actif = get_magasin_actif(request)

    transferts = (
        BonMouvement.objects.filter(type_bon='TRANSFERT')
        .select_related('magasin', 'magasin_destination', 'cree_par', 'annule_par')
        .prefetch_related('lignes_bon__article')
        .annotate(nb_lignes=Count('lignes_bon', distinct=True))
        .order_by('-date_bon')
    )

    # Le magasin sélectionné dans l'en-tête s'applique partout :
    # seuls les transferts impliquant le magasin actif sont visibles.
    if magasin_actif:
        transferts = transferts.filter(
            Q(magasin=magasin_actif) | Q(magasin_destination=magasin_actif)
        )

    q = request.GET.get('q', '')
    if q:
        transferts = transferts.filter(
            Q(numero_bon__icontains=q) |
            Q(magasin__nom__icontains=q) |
            Q(magasin_destination__nom__icontains=q) |
            Q(lignes_bon__article__designation__icontains=q)
        ).distinct()

    transferts_pagines, per_page = paginer(transferts, request)

    if request.method == 'POST':
        magasin_source_id = request.POST.get('magasin_source')
        magasin_dest_id = request.POST.get('magasin_destination')
        article_ids = request.POST.getlist('articles[]')
        quantites = request.POST.getlist('quantites[]')
        commentaire = request.POST.get('commentaire', '').strip()

        if not magasin_source_id or not magasin_dest_id:
            messages.error(request, "❌ Les magasins source et destination sont obligatoires.")
            return redirect('liste_transferts')
        if magasin_source_id == magasin_dest_id:
            messages.error(request, "❌ Le magasin de destination doit être différent du magasin source.")
            return redirect('liste_transferts')

        # Isolation : l'utilisateur doit avoir accès au magasin SOURCE.
        if not magasins_autorises.filter(id=magasin_source_id).exists():
            messages.error(request, "⛔ Vous n'avez pas accès à ce magasin source.")
            return redirect('liste_transferts')

        if not article_ids:
            messages.error(request, "❌ Impossible d'enregistrer un transfert vide.")
            return redirect('liste_transferts')

        magasin_source = get_object_or_404(Magasin, id=magasin_source_id)
        magasin_destination = get_object_or_404(Magasin, id=magasin_dest_id)

        articles_valides = set(
            Article.objects.filter(
                id__in=[aid for aid in article_ids if aid]
            ).values_list('id', flat=True)
        )

        lignes = []
        for aid, qte in zip(article_ids, quantites):
            if aid and qte:
                try:
                    qte_int = int(qte)
                    if qte_int > 0:
                        if int(aid) not in articles_valides:
                            messages.error(
                                request,
                                "⛔ Un ou plusieurs articles sélectionnés ne sont pas valides.")
                            return redirect('liste_transferts')
                        lignes.append({
                            'article': Article.objects.get(id=int(aid)),
                            'quantite': qte_int,
                        })
                except (ValueError, Article.DoesNotExist):
                    messages.error(request, f"❌ Quantité ou article invalide.")
                    return redirect('liste_transferts')

        if not lignes:
            messages.error(request, "❌ Aucune ligne de transfert valide.")
            return redirect('liste_transferts')

        try:
            bon = TransfertService.creer_transfert(
                utilisateur=request.user,
                magasin_source=magasin_source,
                magasin_destination=magasin_destination,
                lignes=lignes,
                commentaire=commentaire,
            )
        except ValidationError as e:
            messages.error(request, f"❌ {e}")
            return redirect('liste_transferts')
        except Exception as e:
            logger.exception("[TRANSFERT] Erreur création : %s", e)
            messages.error(request, "⛔ Erreur lors de la création du transfert.")
            return redirect('liste_transferts')

        messages.success(
            request,
            f"✅ Transfert {bon.numero_bon} créé ! Le stock a été déplacé "
            f"de {magasin_source.nom} vers {magasin_destination.nom}."
        )
        return redirect(f"{reverse('liste_transferts')}?print_bon={bon.id}")

    context = {
        'transferts': transferts_pagines,
        'magasins_sources': magasins_autorises.order_by('nom'),
        'magasins_destinations': Magasin.objects.exclude(
            is_deleted=True).order_by('nom'),
        'articles': Article.objects.filter(is_deleted=False).order_by('designation'),
        'q_transfert': q,
        'per_page': per_page,
    }
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return render(request, 'stock/transferts_lignes.html', context)
    return render(request, 'stock/liste_transferts.html', context)


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_transferts')
@magasin_requis
@catch_errors(redirect_url='liste_transferts')
def annuler_transfert(request, bon_id):
    """Annule un transfert : le stock revient au magasin source."""
    if request.method != 'POST':
        return redirect('liste_transferts')

    bon = get_object_or_404(
        BonMouvement.objects.select_related('magasin', 'magasin_destination'),
        id=bon_id,
        type_bon='TRANSFERT',
    )

    magasins_autorises = get_magasins_autorises(request)
    if not magasins_autorises.filter(id=bon.magasin_id).exists():
        messages.error(request, "⛔ Vous n'avez pas accès au magasin source de ce transfert.")
        return redirect('liste_transferts')

    motif = request.POST.get('motif', '').strip() or 'Annulation manuelle'

    try:
        TransfertService.annuler_transfert(bon, request.user, motif=motif)
    except ValidationError as e:
        messages.error(request, f"❌ {e}")
        return redirect('liste_transferts')
    except Exception as e:
        logger.exception("[TRANSFERT] Erreur annulation : %s", e)
        messages.error(request, "⛔ Erreur lors de l'annulation du transfert.")
        return redirect('liste_transferts')

    messages.success(
        request,
        f"✅ Transfert {bon.numero_bon} annulé — le stock a été restitué "
        f"au magasin {bon.magasin.nom}.")
    return redirect('liste_transferts')
