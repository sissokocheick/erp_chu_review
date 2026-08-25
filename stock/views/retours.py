import os
import logging
from datetime import datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
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
        'articles': Article.objects.filter(is_deleted=False).order_by('designation').select_related('famille').prefetch_related('stocks__magasin')[:200],
        'magasin_actif': get_magasin_actif(request),
        'peut_creer': _has_perm_bon(request.user, 'add', 'RETOUR_SERVICE'),
        'peut_annuler': _has_perm_bon(request.user, 'cancel', 'RETOUR_SERVICE'),
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
        try:
            qte_val = int(qte) if qte and str(qte).strip() else 0
        except (TypeError, ValueError):
            qte_val = 0
        if aid and qte_val > 0:
            if int(aid) not in articles_valides:
                messages.error(
                    request,
                    "⛔ Un ou plusieurs articles sélectionnés ne sont pas valides."
                )
                return redirect('liste_retours_services')
            lignes.append({
                'article_id': aid,
                'quantite': qte_val,
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
        magasin__in=get_magasins_autorises(request),
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

    if request.method != 'POST':
        messages.error(request, "❌ Cette action doit être effectuée en POST.")
        return redirect('liste_retours_services')

    circuit = CircuitValidation.objects.filter(
        type_document='ENTREE', est_actif=True, is_deleted=False
    ).prefetch_related('valideurs').first()

    if not circuit:
        messages.error(request, "❌ Aucun circuit de validation actif pour les bons de retour.")
        return redirect('liste_retours_services')

    if request.user not in circuit.valideurs.all() and not request.user.is_superuser:
        messages.error(request, "⛔ Vous n'êtes pas autorisé à valider ce bon de retour.")
        return redirect('liste_retours_services')

    try:
        with db_transaction.atomic():
            # Verrouiller la ligne : statut relu SOUS le verrou (anti double
            # validation concurrente).
            bon = get_object_or_404(
                BonMouvement.objects.select_for_update(),
                id=bon_id, type_bon='RETOUR_SERVICE'
            )

            if bon.est_annule:
                messages.error(request, f"❌ Le bon {bon.numero_bon} est annulé et ne peut pas être validé.")
                return redirect('liste_retours_services')

            if bon.statut_validation != 'ATTENTE':
                messages.warning(request, f"⚠️ Le bon {bon.numero_bon} n'est pas en attente de validation.")
                return redirect('liste_retours_services')

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
        logger.exception("[RETOUR] Validation bon %s : %s", getattr(bon, 'numero_bon', bon_id), e)
        messages.error(request, "❌ Une erreur est survenue lors de la validation.")
        return redirect('liste_retours_services')

    messages.success(
        request,
        f"✅ Bon de retour {bon.numero_bon} validé par "
        f"{request.user.get_full_name() or request.user.username} — le stock a été réintégré."
    )
    return redirect('liste_retours_services')


# ═══════════════════════════════════════════════════════════════════════
# RETOURS FOURNISSEURS — sortie de stock vers le fournisseur (litige)
# Un retour fournisseur RETIRE du stock : il est gouverné par le circuit
# SORTIE (circuit actif → ATTENTE, stock intact jusqu'à validation).
# ═══════════════════════════════════════════════════════════════════════

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_retours_fournisseurs')
@magasin_requis
@catch_errors(redirect_url='liste_retours_fournisseurs')
def liste_retours_fournisseurs(request):
    """Dispatcher : GET affiche, POST crée un retour fournisseur."""
    if request.method == 'POST':
        return _creer_retour_fournisseur(request)
    return _afficher_retours_fournisseurs(request)


def _afficher_retours_fournisseurs(request):
    """Branche GET : filtres, pagination, contexte."""
    magasin_id = request.session.get('magasin_actif_id')

    qs = BonMouvement.objects.filter(
        type_bon='RETOUR_FOURNISSEUR',
        magasin_id=magasin_id
    ).select_related('magasin', 'fournisseur', 'cree_par').prefetch_related(
        'lignes_bon__article'
    ).order_by('-date_bon')

    # ── Pré-remplissage « retour fournisseur en 1 clic » ──
    # Depuis un bon d'entrée (?from_bon=) ou une commande réceptionnée
    # (?from_commande=) : on pré-charge le fournisseur et les lignes dans la
    # modale de création. L'utilisateur ajuste les quantités puis enregistre.
    prefill_retour = _build_prefill_retour(request, magasin_id)

    # Circuit SORTIE actif → les retours fournisseurs (sorties de stock)
    # passent par validation différée : on expose l'état + le statut de validateur.
    from ..models import CircuitValidation
    circuit_sortie = CircuitValidation.objects.filter(
        type_document='SORTIE', est_actif=True, is_deleted=False
    ).prefetch_related('valideurs').first()
    est_valideur = (
        request.user.is_superuser
        or (circuit_sortie and circuit_sortie.valideurs.filter(id=request.user.id).exists())
    )

    extra = {
        'fournisseurs': Fournisseur.objects.all().order_by('raison_sociale'),
        'magasins': Magasin.objects.all().order_by('nom'),
        'articles': Article.objects.filter(is_deleted=False).order_by('designation').select_related('famille').prefetch_related('stocks__magasin')[:200],
        'magasin_actif': get_magasin_actif(request),
        'peut_creer': _has_perm_bon(request.user, 'add', 'RETOUR_FOURNISSEUR'),
        'peut_annuler': _has_perm_bon(request.user, 'cancel', 'RETOUR_FOURNISSEUR'),
        'circuit_sortie': circuit_sortie,
        'est_valideur_retour_fournisseur': est_valideur,
        'prefill_retour': prefill_retour,
        'motifs_annulation': MotifAnnulation.objects.filter(is_deleted=False).order_by('libelle'),
    }
    return render_liste(
        request, qs,
        template='stock/liste_retours_fournisseurs.html',
        ajax_template='stock/retours_fournisseurs_lignes.html',
        context_object_name='retours_fournisseurs',
        date_field='date_bon',
        texte_champs=[
            'numero_bon__icontains',
            'fournisseur__raison_sociale__icontains',
            'reference_externe__icontains',
        ],
        context_extra=extra
    )


def _build_prefill_retour(request, magasin_id):
    """Construit le pré-remplissage de la modale de retour fournisseur.

    Sources :
    - `?from_bon=<id>` : un bon d'entrée (ENTREE) du magasin actif
    - `?from_commande=<id>` : une commande réceptionnée (toutes ses réceptions)

    Retourne None si aucune source valide ou aucun fournisseur trouvé.
    """
    from ..models import Commande

    from_bon_id = request.GET.get('from_bon')
    from_commande_id = request.GET.get('from_commande')
    if not from_bon_id and not from_commande_id:
        return None

    fournisseur = None
    lignes = []
    vus = set()

    def _ajouter_ligne(ligne_bon):
        """Ajoute une ligne avec dédoublonnage (article + lot + péremption)."""
        article = ligne_bon.article
        lot = (ligne_bon.numero_lot or '').strip()
        peremp = ligne_bon.date_peremption.isoformat() if ligne_bon.date_peremption else ''
        cle = (ligne_bon.article_id, lot, peremp)
        if cle in vus:
            return
        vus.add(cle)
        lignes.append({
            'article_id': article.id,
            'designation': article.designation,
            'reference': getattr(article, 'reference', '') or '',
            'quantite': ligne_bon.quantite,
            'numero_lot': lot,
            'date_peremption': peremp,
        })

    if from_bon_id:
        bon_source = BonMouvement.objects.filter(
            id=from_bon_id, type_bon='ENTREE',
            magasin_id=magasin_id, est_annule=False,
        ).select_related('fournisseur', 'commande_liee__fournisseur').first()
        if bon_source:
            fournisseur = bon_source.fournisseur or (
                bon_source.commande_liee.fournisseur
                if bon_source.commande_liee else None
            )
            for ligne in bon_source.lignes_bon.select_related('article').all():
                _ajouter_ligne(ligne)

    elif from_commande_id:
        commande = Commande.objects.filter(
            id=from_commande_id, magasin_id=magasin_id
        ).select_related('fournisseur').first()
        if commande:
            fournisseur = commande.fournisseur
            bons = commande.bons_reception.filter(est_annule=False)
            for bon in bons.prefetch_related('lignes_bon__article').all():
                for ligne in bon.lignes_bon.all():
                    _ajouter_ligne(ligne)

    if not fournisseur:
        return None
    return {'fournisseur_id': fournisseur.id, 'lignes': lignes}


def _creer_retour_fournisseur(request):
    """Branche POST : validation, création via service, redirection."""
    magasin_id = request.session.get('magasin_actif_id')

    fournisseur_id = request.POST.get('fournisseur')
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
        return redirect('liste_retours_fournisseurs')

    if not magasin_id_effectif:
        messages.error(request, "⛔ Aucun magasin actif sélectionné.")
        return redirect('liste_retours_fournisseurs')
    if not fournisseur_id:
        messages.error(request, "❌ Vous devez sélectionner un fournisseur.")
        return redirect('liste_retours_fournisseurs')
    if not article_ids:
        messages.error(request, "❌ Vous devez ajouter au moins un article.")
        return redirect('liste_retours_fournisseurs')

    # Conversion IDs → objets
    magasin = get_object_or_404(Magasin, id=magasin_id_effectif)
    fournisseur = get_object_or_404(Fournisseur, id=fournisseur_id)

    # Validation des articles
    articles_valides = set(
        Article.objects.filter(
            id__in=[aid for aid in article_ids if aid]
        ).values_list('id', flat=True)
    )

    lignes = []
    for aid, qte, lot, peremp in zip(article_ids, quantites, lots, peremptions):
        try:
            qte_val = int(qte) if qte and str(qte).strip() else 0
        except (TypeError, ValueError):
            qte_val = 0
        if aid and qte_val > 0:
            if int(aid) not in articles_valides:
                messages.error(
                    request,
                    "⛔ Un ou plusieurs articles sélectionnés ne sont pas valides."
                )
                return redirect('liste_retours_fournisseurs')
            lignes.append({
                'article_id': aid,
                'quantite': qte_val,
                'numero_lot': lot or None,
                'date_peremption': peremp or None,
            })

    from ..models import CircuitValidation
    circuit_sortie = CircuitValidation.objects.filter(
        type_document='SORTIE', est_actif=True, is_deleted=False
    ).first()

    try:
        bon = BonService.creer_bon_retour_fournisseur(
            lignes=lignes,
            utilisateur=request.user,
            magasin=magasin,
            fournisseur=fournisseur,
            reference_externe=ref_ext,
            circuit_validation=circuit_sortie,
        )
    except IntegrityError as e:
        logger.exception("[RETOUR FOURNISSEUR] IntegrityError création bon : %s", e)
        messages.error(request, "⛔ Erreur lors de la création du bon. Vérifiez la console pour le détail.")
        return redirect('liste_retours_fournisseurs')
    except (ValidationError, ValueError) as e:
        # Erreur métier (ex. stock insuffisant pour un lot) : on affiche le
        # message réel au lieu du message générique « erreur technique ».
        logger.warning("[RETOUR FOURNISSEUR] Validation échouée : %s", e)
        if isinstance(e, ValidationError):
            detail = ' '.join(e.messages) if hasattr(e, 'messages') else str(e)
        else:
            detail = str(e)
        messages.error(request, f"⛔ {detail}")
        return redirect('liste_retours_fournisseurs')

    if bon.statut_validation == 'ATTENTE':
        messages.info(
            request,
            f"🕒 Bon de retour fournisseur {bon.numero_bon} créé — en attente de validation "
            "par le circuit SORTIE (le stock sera retiré après validation)."
        )
    else:
        messages.success(
            request,
            f"✅ Bon de retour fournisseur {bon.numero_bon} enregistré ! ({len(lignes)} article(s))"
        )
    return redirect(f"{reverse('liste_retours_fournisseurs')}?print_bon={bon.id}")


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_retours_fournisseurs')
@magasin_requis
@catch_errors(redirect_url='liste_retours_fournisseurs')
def valider_bon_retour_fournisseur(request, bon_id):
    """Valide un bon de retour fournisseur en ATTENTE (circuit SORTIE actif) :
    exécute les mouvements de sortie (décrément) et met à jour le stock.

    Réservé aux validateurs désignés dans le circuit SORTIE (ou superuser),
    même pattern que valider_bon_sortie / valider_bon_retour.
    """
    from ..models import CircuitValidation
    from ..services.stock_transaction_service import StockTransactionService
    from django.db import transaction as db_transaction

    if request.method != 'POST':
        messages.error(request, "❌ Cette action doit être effectuée en POST.")
        return redirect('liste_retours_fournisseurs')

    circuit = CircuitValidation.objects.filter(
        type_document='SORTIE', est_actif=True, is_deleted=False
    ).prefetch_related('valideurs').first()

    if not circuit:
        messages.error(request, "❌ Aucun circuit de validation SORTIE actif pour les retours fournisseur.")
        return redirect('liste_retours_fournisseurs')

    if request.user not in circuit.valideurs.all() and not request.user.is_superuser:
        messages.error(request, "⛔ Vous n'êtes pas autorisé à valider ce bon de retour fournisseur.")
        return redirect('liste_retours_fournisseurs')

    try:
        with db_transaction.atomic():
            # Verrouiller la ligne : statut relu SOUS le verrou (anti double
            # validation concurrente).
            bon = get_object_or_404(
                BonMouvement.objects.select_for_update(),
                id=bon_id, type_bon='RETOUR_FOURNISSEUR'
            )

            if bon.est_annule:
                messages.error(request, f"❌ Le bon {bon.numero_bon} est annulé et ne peut pas être validé.")
                return redirect('liste_retours_fournisseurs')

            if bon.statut_validation != 'ATTENTE':
                messages.warning(request, f"⚠️ Le bon {bon.numero_bon} n'est pas en attente de validation.")
                return redirect('liste_retours_fournisseurs')

            bon.statut_validation = 'VALIDE'
            bon.date_validation = timezone.now()
            bon.valide_par = request.user
            bon.save(update_fields=['statut_validation', 'date_validation', 'valide_par'])

            for ligne in bon.lignes_bon.all():
                mouvement = Mouvement(
                    type_mouvement='RETOUR_FOURNISSEUR',
                    article=ligne.article,
                    magasin=bon.magasin,
                    quantite=ligne.quantite,
                    prix_unitaire=ligne.prix_unitaire,
                    utilisateur=request.user,
                    reference_document=bon.numero_bon,
                    fournisseur=bon.fournisseur,
                    numero_lot=ligne.numero_lot,
                    date_peremption=ligne.date_peremption,
                    commentaire=f"Validation du bon de retour fournisseur {bon.numero_bon}",
                )
                StockTransactionService.executer(mouvement)
    except Exception as e:
        logger.exception("[RETOUR FOURNISSEUR] Validation bon %s : %s", getattr(bon, 'numero_bon', bon_id), e)
        messages.error(request, "❌ Une erreur est survenue lors de la validation.")
        return redirect('liste_retours_fournisseurs')

    messages.success(
        request,
        f"✅ Bon de retour fournisseur {bon.numero_bon} validé par "
        f"{request.user.get_full_name() or request.user.username} — le stock a été retiré."
    )
    return redirect('liste_retours_fournisseurs')


# ──────────────────────────────────────────────────────────────────
# Annulation bon retour fournisseur
# ──────────────────────────────────────────────────────────────────
@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_retours_fournisseurs')
@magasin_requis
@catch_errors(redirect_url='liste_retours_fournisseurs')
def annuler_retour_fournisseur(request, bon_id):
    """Annule un bon de retour fournisseur et réintègre le stock."""
    if request.method != 'POST':
        return redirect('liste_retours_fournisseurs')

    magasins_autorises = get_magasins_autorises(request)
    bon = get_object_or_404(
        BonMouvement, id=bon_id, type_bon='RETOUR_FOURNISSEUR',
        magasin__in=magasins_autorises
    )

    if bon.est_annule:
        messages.error(request, f"Le bon {bon.numero_bon} est déjà annulé.")
        return redirect('liste_retours_fournisseurs')

    motif_id = request.POST.get('motif_id')
    if not motif_id:
        messages.error(request, "Le motif d'annulation est obligatoire.")
        return redirect('liste_retours_fournisseurs')

    motif = get_object_or_404(MotifAnnulation, id=motif_id)

    try:
        _, nb_reintegres = BonService.annuler_bon_retour_fournisseur(
            bon, motif, request.user
        )
    except ValueError as e:
        logger.exception("[RETOUR FOURNISSEUR] Annulation %s : %s", bon.numero_bon, e)
        messages.error(request, f"❌ {e}")
        return redirect('liste_retours_fournisseurs')
    except Exception as e:
        logger.exception("[RETOUR FOURNISSEUR] Erreur annulation %s : %s", bon.numero_bon, e)
        messages.error(request, "❌ Une erreur est survenue lors de l'annulation.")
        return redirect('liste_retours_fournisseurs')

    # Invalidation cache PDF
    if bon.fichier_pdf and bon.fichier_pdf.name:
        try:
            from django.core.files.storage import default_storage
            if default_storage.exists(bon.fichier_pdf.name):
                default_storage.delete(bon.fichier_pdf.name)
        except Exception as e:
            logger.warning("[Annulation BR %s] Échec suppression cache PDF : %s", bon.numero_bon, e)
        bon.fichier_pdf = None
        bon.save(update_fields=['fichier_pdf'])

    if nb_reintegres > 0:
        messages.success(
            request,
            f"✅ Retour fournisseur {bon.numero_bon} annulé — "
            f"{nb_reintegres} mouvement(s) réintégré(s) dans le stock."
        )
    else:
        messages.success(
            request,
            f"✅ Retour fournisseur {bon.numero_bon} annulé "
            f"(aucun stock à réintégrer — bon en attente)."
        )
    return redirect('liste_retours_fournisseurs')