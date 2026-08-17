import os
import logging
from datetime import datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone

from accounts.permissions import verifier_permission
from stock.services.isolation_service import get_magasins_autorises
from ..decorators import magasin_requis, catch_errors
from ..pdf_utils import get_pdf_config, paginate_lignes, ajouter_hauteurs_lignes, build_signature_cases
from ..models import (
    BonMouvement, LigneBon, MotifAnnulation,
    Article, Magasin, Service,
    Fournisseur, Beneficiaire, Mouvement)
from ..services import NumeroGenerator, StockService, PDFService, NotificationService
from ..services.bon_service import BonService
from .catalogue import paginer
from .common import _has_perm_bon
from .common_views import render_liste, get_magasin_actif, build_redirect_url
from django.contrib.auth import get_user_model

logger = logging.getLogger(__name__)


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_retours_services')
@magasin_requis
@catch_errors(redirect_url='liste_retours_services')
def liste_retours_services(request):
    """Dispatcher : GET affiche, POST crée."""
    if request.method == 'POST':
        return _creer_retour(request)
    return _afficher_retours(request)


def _afficher_retours(request):
    """Branche GET : filtres, pagination, contexte."""
    magasin_id = request.session.get('magasin_actif_id')

    qs = BonMouvement.objects.filter(
        type_bon='RETOUR_SERVICE',
        magasin_id=magasin_id
    ).select_related('magasin', 'service_demandeur', 'cree_par').prefetch_related(
        'lignes_bon__article'
    ).order_by('-date_bon')

    # Circuit ENTREE actif → les retours (réintégrations) passent par
    # validation différée : on expose l'état + le statut de validateur.
    from ..models import CircuitValidation
    circuit_retour = CircuitValidation.objects.filter(
        type_document='ENTREE', est_actif=True, is_deleted=False
    ).prefetch_related('valideurs').first()
    est_valideur = (
        request.user.is_superuser
        or (circuit_retour and circuit_retour.valideurs.filter(id=request.user.id).exists())
    )

    extra = {
        'services': Service.objects.all().order_by('nom'),
        'magasins': Magasin.objects.all().order_by('nom'),
        'articles': Article.objects.all().order_by('designation'),
        'magasin_actif': get_magasin_actif(request),
        'peut_creer': _has_perm_bon(request.user, 'add', 'RETOUR_SERVICE'),
        'peut_annuler': _has_perm_bon(request.user, 'change', 'RETOUR_SERVICE'),
        'circuit_retour': circuit_retour,
        'est_valideur_retour': est_valideur,
    }
    return render_liste(
        request, qs,
        template='stock/liste_retours.html',
        ajax_template='stock/retours_lignes.html',
        context_object_name='retours_bons',
        date_field='date_bon',
        texte_champs=[
            'numero_bon__icontains',
            'service_demandeur__nom__icontains',
            'reference_externe__icontains',
        ],
        context_extra=extra
    )


def _creer_retour(request):
    """Branche POST : validation, création via service, redirection."""
    magasin_id = request.session.get('magasin_actif_id')

    action = request.POST.get('action')
    if action == 'creer_beneficiaire':
        nom = request.POST.get('nom_complet', '').strip()
        poste = request.POST.get('poste', '').strip()
        service_id = request.POST.get('service')
        if nom:
            b = Beneficiaire.objects.create(
                nom_complet=nom, poste=poste,
                service_id=service_id if service_id else None
            )
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True, 'id': b.id,
                    'nom': b.nom_complet, 'poste': b.poste,
                    'service_id': b.service_id
                })
        return JsonResponse({'success': False})

    service_id = request.POST.get('service_demandeur')
    ref_ext = request.POST.get('reference_externe', '').strip()
    article_ids = request.POST.getlist('articles[]')
    quantites = request.POST.getlist('quantites[]')
    lots = request.POST.getlist('lots[]')
    peremptions = request.POST.getlist('peremptions[]')

    magasin_post = request.POST.get('magasin')
    magasin_id_effectif = magasin_post or magasin_id

    # ── Vérification autorisation magasin ──
    magasins_autorises = get_magasins_autorises(request)
    if magasin_id_effectif and not magasins_autorises.filter(id=magasin_id_effectif).exists():
        messages.error(request, "⛔ Vous n'avez pas accès à ce magasin.")
        return redirect('liste_retours_services')

    if not magasin_id_effectif:
        messages.error(request, "⛔ Aucun magasin actif sélectionné.")
        return redirect('liste_retours_services')
    if not article_ids:
        messages.error(request, "❌ Vous devez ajouter au moins un article.")
        return redirect('liste_retours_services')

    if not magasins_autorises.filter(id=magasin_id_effectif).exists():
        messages.error(request, "⛔ Magasin non autorisé.")
        return redirect('liste_retours_services')

    # Conversion IDs → objets
    magasin = get_object_or_404(Magasin, id=magasin_id_effectif)

    service = None
    if service_id:
        service = get_object_or_404(Service, id=service_id)

    # Validation des articles
    articles_valides = set(
        Article.objects.filter(
            id__in=[aid for aid in article_ids if aid]
        ).values_list('id', flat=True)
    )

    lignes = []
    for aid, qte, lot, peremp in zip(article_ids, quantites, lots, peremptions):
        if aid and qte and int(qte) > 0:
            if int(aid) not in articles_valides:
                messages.error(
                    request,
                    "⛔ Un ou plusieurs articles sélectionnés ne sont pas valides."
                )
                return redirect('liste_retours_services')
            lignes.append({
                'article_id': aid,
                'quantite': int(qte),
                'numero_lot': lot or None,
                'date_peremption': peremp or None,
            })

    from ..models import CircuitValidation
    circuit_retour = CircuitValidation.objects.filter(
        type_document='ENTREE', est_actif=True, is_deleted=False
    ).first()

    try:
        bon = BonService.creer_bon_retour(
            lignes=lignes,
            utilisateur=request.user,
            magasin=magasin,
            service=service,
            reference_externe=ref_ext,
            circuit_validation=circuit_retour,
        )
    except IntegrityError as e:
        logger.exception("[RETOUR] IntegrityError création bon : %s", e)
        messages.error(request, "⛔ Erreur lors de la création du bon. Vérifiez la console pour le détail.")
        return redirect('liste_retours_services')

    if bon.statut_validation == 'ATTENTE':
        messages.info(
            request,
            f"🕒 Bon de retour {bon.numero_bon} créé — en attente de validation "
            "par le circuit ENTREE (le stock sera réintégré après validation)."
        )
    else:
        messages.success(request, f"✅ Bon de retour {bon.numero_bon} enregistré ! ({len(lignes)} article(s))")
    return redirect(f"{reverse('liste_retours_services')}?print_bon={bon.id}")


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_retours_services')
def apercu_bon_retour(request, bon_id):
    User = get_user_model()

    bon = get_object_or_404(
        BonMouvement,
        id=bon_id,
        type_bon='RETOUR_SERVICE',
    )

    lignes_brutes = list(bon.lignes_bon.select_related('article').all())
    total_qte = sum(l.quantite for l in lignes_brutes)

    pdf_config, logo_url = get_pdf_config(bon.magasin, 'BR', request)

    lignes_data = []
    for idx, ligne in enumerate(lignes_brutes, start=1):
        article = ligne.article
        unite = 'U'
        for attr in ('unite_distribution', 'unite_mesure', 'unite'):
            if hasattr(article, attr):
                val = getattr(article, attr)
                if val:
                    unite = val
                    break
        lignes_data.append({
            'idx': idx,
            'reference': getattr(article, 'reference', '') or '',
            'designation': getattr(article, 'designation', '') or '',
            'unite': unite,
            'quantite': ligne.quantite,
            'numero_lot': getattr(ligne, 'numero_lot', None),
            'date_peremption': getattr(ligne, 'date_peremption', None),
        })
    a_lots = any(l['numero_lot'] for l in lignes_data)

    pagination = paginate_lignes(lignes_data, pdf_config, lignes_par_page=18, type_doc='RETOUR_SERVICE')
    pages = [
        {'lignes': page, 'est_derniere_page': i == len(pagination.pages) - 1}
        for i, page in enumerate(pagination.pages)
    ]
    pages = ajouter_hauteurs_lignes(pages, pdf_config, type_doc='RETOUR_SERVICE')

    chef_service = None
    if bon.service_demandeur:
        chef_service = User.objects.filter(
            profil__service=bon.service_demandeur,
            profil__est_chef_service=True,
            is_active=True
        ).first()

    service = bon.service_demandeur
    responsable = getattr(bon.magasin, 'responsable', None) if bon.magasin else None
    magasinier = bon.cree_par

    context = {
        'is_apercu': True,
        'bon': bon,
        'magasin': bon.magasin,
        'lignes': lignes_brutes,
        'lignes_data': lignes_data,
        'lignes_pages': pagination.pages,
        'pages': pages,
        'est_multi_page': pagination.est_multi_page,
        'a_lots': a_lots,
        'total_qte': total_qte,
        'chef_service': chef_service,
        'responsable': responsable,
        'magasinier': magasinier,
        'service': service,
        'service_code': getattr(service, 'code', '') if service else '',
        'service_poste': getattr(service, 'poste', '') if service else '',
        'signature_cases': build_signature_cases(bon, pdf_config, request),
        'logo_url': logo_url,
        'date_impression': timezone.now(),
        'pdf_config': pdf_config,
    }
    return render(request, 'stock/pdf/bon_retour.html', context)


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_retours_services')
@magasin_requis
@catch_errors(redirect_url='liste_retours_services')
def valider_bon_retour(request, bon_id):
    """Valide un bon de retour en ATTENTE (circuit ENTREE actif) : applique les
    mouvements de réintégration et met à jour le stock.

    Réservé aux validateurs désignés dans le circuit ENTREE (ou superuser),
    même pattern que valider_bon_entree / valider_bon_sortie.
    """
    from ..models import CircuitValidation
    from ..services.stock_transaction_service import StockTransactionService
    from django.db import transaction as db_transaction

    bon = get_object_or_404(
        BonMouvement, id=bon_id, type_bon='RETOUR_SERVICE'
    )

    circuit = CircuitValidation.objects.filter(
        type_document='ENTREE', est_actif=True, is_deleted=False
    ).prefetch_related('valideurs').first()

    if not circuit:
        messages.error(request, "❌ Aucun circuit de validation actif pour les bons de retour.")
        return redirect('liste_retours_services')

    if request.user not in circuit.valideurs.all() and not request.user.is_superuser:
        messages.error(request, "⛔ Vous n'êtes pas autorisé à valider ce bon de retour.")
        return redirect('liste_retours_services')

    if bon.statut_validation != 'ATTENTE':
        messages.warning(request, f"⚠️ Le bon {bon.numero_bon} n'est pas en attente de validation.")
        return redirect('liste_retours_services')

    try:
        with db_transaction.atomic():
            bon.statut_validation = 'VALIDE'
            bon.date_validation = timezone.now()
            bon.valide_par = request.user
            bon.save(update_fields=['statut_validation', 'date_validation', 'valide_par'])

            for ligne in bon.lignes_bon.all():
                mouvement = Mouvement(
                    type_mouvement='RETOUR_SERVICE',
                    article=ligne.article,
                    magasin=bon.magasin,
                    quantite=ligne.quantite,
                    prix_unitaire=ligne.prix_unitaire,
                    utilisateur=request.user,
                    reference_document=bon.numero_bon,
                    numero_lot=ligne.numero_lot,
                    date_peremption=ligne.date_peremption,
                    commentaire=f"Validation du bon de retour {bon.numero_bon}",
                )
                StockTransactionService.executer(mouvement)
    except Exception as e:
        logger.exception("[RETOUR] Validation bon %s : %s", bon.numero_bon, e)
        messages.error(request, "❌ Une erreur est survenue lors de la validation.")
        return redirect('liste_retours_services')

    messages.success(
        request,
        f"✅ Bon de retour {bon.numero_bon} validé par "
        f"{request.user.get_full_name() or request.user.username} — le stock a été réintégré."
    )
    return redirect('liste_retours_services')