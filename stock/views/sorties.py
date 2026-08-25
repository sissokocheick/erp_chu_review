import os
import logging
from datetime import datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.core.files.storage import default_storage
from django.db import IntegrityError
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone

from accounts.permissions import verifier_permission
from stock.services.isolation_service import get_magasins_autorises
from ..decorators import magasin_requis, catch_errors
from ..models import (
    BonMouvement, LigneBon, MotifAnnulation,
    Article, Magasin, Mouvement,
    Service, LivraisonPartielle, CircuitValidation)
from django.db.models import Q, Count
from ..services import NumeroGenerator, PDFService, NotificationService
from ..services.bon_service import BonService
from .catalogue import paginer, appliquer_tri
from .common import _has_perm_bon
from .common_views import render_liste, get_magasin_actif, build_redirect_url

# Constante : taille maximale de fichier upload (1 Mo)
MAX_FILE_SIZE = 1024 * 1024  # 1 Mo en octets

logger = logging.getLogger(__name__)


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_sorties')
@magasin_requis
@catch_errors(redirect_url='liste_sorties')
def liste_sorties(request):
    magasins_autorises = get_magasins_autorises(request)

    circuit_sortie = CircuitValidation.objects.filter(
        type_document='SORTIE', est_actif=True
    ).prefetch_related('valideurs').first()
    est_valideur = False

    if circuit_sortie:
        est_valideur = circuit_sortie.valideurs.filter(id=request.user.id).exists() or request.user.is_superuser

    sorties_bons = (
        BonMouvement.objects.filter(
            type_bon='SORTIE', magasin__in=magasins_autorises
        )
        .select_related('magasin', 'service_demandeur', 'cree_par', 'valide_par')
        .prefetch_related('lignes_bon__article')
        .annotate(nb_lignes=Count('lignes_bon', distinct=True))
    )

    sorties_bons, tri, ordre = appliquer_tri(
        sorties_bons, request,
        colonnes={
            'numero_bon': 'numero_bon',
            'date_bon': 'date_bon',
            'magasin': 'magasin__nom',
            'service_demandeur': 'service_demandeur__nom',
            'articles': 'nb_lignes',
        },
        defaut='-date_bon',
    )

    # Le magasin sélectionné dans l'en-tête s'applique partout :
    # la liste ne montre que le magasin actif de la session.
    magasin_actif = get_magasin_actif(request)
    if magasin_actif:
        sorties_bons = sorties_bons.filter(magasin=magasin_actif)

    q = request.GET.get('q', '')
    date_range = request.GET.get('date_range', '')
    if date_range:
        try:
            dates = date_range.split(' - ')
            if len(dates) == 2:
                date_debut = datetime.strptime(dates[0], '%d/%m/%Y').date()
                date_fin = datetime.strptime(dates[1], '%d/%m/%Y').date()
                sorties_bons = sorties_bons.filter(
                    date_bon__date__gte=date_debut, date_bon__date__lte=date_fin
                )
        except ValueError:
            pass

    if q:
        sorties_bons = sorties_bons.filter(
            Q(numero_bon__icontains=q) |
            Q(service_demandeur__nom__icontains=q) |
            Q(reference_externe__icontains=q) |
            Q(magasin__nom__icontains=q) |
            Q(lignes_bon__article__designation__icontains=q)
        ).distinct()

    sorties_bons_pagines, per_page = paginer(sorties_bons, request)

    if request.method == 'POST':
        magasin_id = request.POST.get('magasin')
        if not magasin_id or not magasins_autorises.filter(id=magasin_id).exists():
            messages.error(request, "⛔ Vous n'avez pas accès à ce magasin source.")
            return redirect('liste_sorties')

        service_id = request.POST.get('service_demandeur')
        ref_ext = request.POST.get('reference_externe')
        article_ids = request.POST.getlist('articles[]')
        quantites = request.POST.getlist('quantites[]')

        if not article_ids:
            messages.error(request, "❌ Impossible d'enregistrer un bon de sortie vide.")
        else:
            if ref_ext and BonMouvement.objects.filter(
                type_bon='SORTIE', service_demandeur_id=service_id,
                reference_externe__iexact=ref_ext
            ).exists():
                nom_service = Service.objects.get(id=service_id).nom
                messages.error(
                    request,
                    f"La référence '{ref_ext}' a déjà été traitée pour le service '{nom_service}'."
                )
                return redirect('liste_sorties')

            # Validation des articles
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
                                    "⛔ Un ou plusieurs articles sélectionnés ne sont pas valides."
                                )
                                return redirect('liste_sorties')
                            lignes.append({'article_id': aid, 'quantite': qte_int})
                    except ValueError:
                        messages.error(request, f"❌ Quantité invalide pour l'article.")
                        return redirect('liste_sorties')

            # Conversion IDs → objets
            magasin = get_object_or_404(Magasin, id=magasin_id)
            service_demandeur = None
            if service_id:
                service_demandeur = get_object_or_404(Service, id=service_id)

            try:
                bon = BonService.creer_bon_sortie(
                    lignes=lignes,
                    utilisateur=request.user,
                    magasin=magasin,
                    service_demandeur=service_demandeur,
                    reference_externe=ref_ext,
                    circuit_validation=circuit_sortie
                )
            except IntegrityError as e:
                logger.exception("[SORTIE] IntegrityError création bon : %s", e)
                messages.error(request, "⛔ Erreur lors de la création du bon. Vérifiez la console pour le détail.")
                return redirect('liste_sorties')

            messages.success(
                request,
                f"✅ Bon de sortie {bon.numero_bon} créé !"
                + (" En attente de validation." if circuit_sortie else "")
            )
            if circuit_sortie:
                return redirect('liste_sorties')
            else:
                return redirect(f"{reverse('liste_sorties')}?print_bon={bon.id}")

    magasins = magasins_autorises.order_by('nom')
    services = Service.objects.all().order_by('nom')
    # ✅ CORRECTION PERF : conserver prefetch_related('stocks__magasin') —
    # sans lui, chaque ligne de la modale interroge la base (N+1 mesuré :
    # 115 requêtes / page). Le filtre is_deleted + plafond 200 sont conservés.
    articles = Article.objects.filter(is_deleted=False).order_by(
        'designation'
    ).select_related('famille').prefetch_related(
        'stocks__magasin'
    )[:200]
    motifs_annulation = MotifAnnulation.objects.filter(
        actif=True
    ).order_by('libelle')

    context = {
        'sorties_bons': sorties_bons_pagines,
        'magasins': magasins,
        'services': services,
        'articles': articles,
        'q_bon': q,
        'date_range': date_range,
        'per_page': per_page,
        'tri': tri,
        'ordre': ordre,
        'motifs_annulation': motifs_annulation,
        'circuit_sortie': circuit_sortie,
        'est_valideur': est_valideur,
        'peut_creer': _has_perm_bon(request.user, 'add', 'SORTIE'),
        'peut_annuler': _has_perm_bon(request.user, 'cancel', 'SORTIE'),
    }
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return render(request, 'stock/sorties_lignes.html', context)
    return render(request, 'stock/liste_sorties.html', context)


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_sorties')
@magasin_requis
@catch_errors(redirect_url='liste_sorties')
def annuler_sortie(request, bon_id):
    if request.method != 'POST':
        return redirect('liste_sorties')

    magasins_autorises = get_magasins_autorises(request)
    bon = get_object_or_404(
        BonMouvement, id=bon_id, type_bon='SORTIE',
        magasin__in=magasins_autorises
    )

    if bon.est_annule:
        messages.error(request, f"Le bon {bon.numero_bon} est déjà annulé.")
        return redirect('liste_sorties')

    if bon.service_demandeur and bon.service_demandeur.code == 'REBUTS':
        messages.error(request, "⛔ Bon de destruction automatique — non annulable.")
        return redirect('liste_sorties')

    if bon.statut_validation == 'ATTENTE':
        messages.error(
            request,
            "⛔ Ce bon est en attente de validation. Utilisez 'Rejeter' dans le circuit de validation."
        )
        return redirect('liste_sorties')

    try:
        livraison = LivraisonPartielle.objects.select_related('accuse').get(bon_sortie=bon)
        if livraison.accuse and livraison.accuse.est_signe:
            messages.error(
                request,
                "⛔ Impossible d'annuler : l'accusé de réception a déjà été signé par le demandeur."
            )
            return redirect('liste_sorties')
    except LivraisonPartielle.DoesNotExist:
        pass

    motif_id = request.POST.get('motif_id')
    if not motif_id:
        messages.error(request, "Le motif d'annulation est obligatoire.")
        return redirect('liste_sorties')

    motif = get_object_or_404(MotifAnnulation, id=motif_id)

    try:
        mouvements_existants = BonService.annuler_bon_sortie(bon, motif, request.user)
    except ValueError as e:
        logger.exception("[SORTIE] %s", e)
        messages.error(request, "❌ Une erreur est survenue lors de l'annulation.")
        return redirect('liste_sorties')

    # Invalidation cache PDF
    if bon.fichier_pdf and bon.fichier_pdf.name:
        try:
            if default_storage.exists(bon.fichier_pdf.name):
                default_storage.delete(bon.fichier_pdf.name)
        except Exception as e:
            logger.warning("[Annulation BS %s] Échec suppression cache PDF : %s", bon.numero_bon, e)
        bon.fichier_pdf = None
        bon.save(update_fields=['fichier_pdf'])

    if mouvements_existants:
        messages.success(
            request,
            f"✅ Sortie {bon.numero_bon} annulée. Stock remis en place, livraison(s) supprimée(s)."
        )
    else:
        messages.success(
            request,
            f"✅ Sortie {bon.numero_bon} annulée (aucun stock à remettre — bon en attente)."
        )
    return redirect('liste_sorties')


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_sorties')
@magasin_requis
@catch_errors(redirect_url='liste_sorties')
def valider_bon_sortie(request, bon_id):
    if request.method != 'POST':
        messages.error(request, "❌ Cette action doit être effectuée en POST.")
        return redirect('liste_sorties')

    circuit = CircuitValidation.objects.filter(
        type_document='SORTIE', est_actif=True
    ).prefetch_related('valideurs').first()

    if not circuit:
        messages.error(request, "❌ Aucun circuit de validation actif pour les bons de sortie.")
        return redirect('liste_sorties')

    if request.user not in circuit.valideurs.all() and not request.user.is_superuser:
        messages.error(request, "⛔ Vous n'êtes pas autorisé à valider ce bon.")
        return redirect('liste_sorties')

    # Verrouiller la ligne du bon : le statut est relu SOUS le verrou pour
    # empêcher deux validations concurrentes (double décompte de stock).
    from django.db import transaction as db_transaction
    try:
        with db_transaction.atomic():
            bon = get_object_or_404(
                BonMouvement.objects.select_for_update(),
                id=bon_id, type_bon='SORTIE'
            )

            if bon.est_annule:
                messages.error(request, f"❌ Le bon {bon.numero_bon} est annulé et ne peut pas être validé.")
                return redirect('liste_sorties')

            stock_decompte = BonService.valider_bon_sortie(bon, request.user)
    except ValidationError as e:
        # Message métier (stock insuffisant, bon annulé…) directement affiché
        logger.info("[SORTIE] Validation refusée : %s", e)
        messages.error(request, f"❌ {e}")
        return redirect('liste_sorties')
    except ValueError as e:
        logger.exception("[SORTIE] %s", e)
        messages.error(request, f"❌ {e}")
        return redirect('liste_sorties')

    # Invalidation cache PDF pour forcer régénération avec signature
    if bon.fichier_pdf and bon.fichier_pdf.name:
        try:
            if default_storage.exists(bon.fichier_pdf.name):
                default_storage.delete(bon.fichier_pdf.name)
        except Exception as e:
            logger.warning("[Validation BS %s] Échec suppression cache : %s", bon.numero_bon, e)

        bon.fichier_pdf = None
        bon.save()

    messages.success(
        request,
        f"✅ Bon {bon.numero_bon} validé par {request.user.get_full_name() or request.user.username}. "
        f"{'Le stock a été décompté. ' if stock_decompte else ''}"
        f"Le PDF sera régénéré avec votre signature dans 'Vu pour exécution'."
    )
    return redirect('liste_sorties')


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_sorties')
@magasin_requis
@catch_errors(redirect_url='liste_sorties')
def remplacer_scan_sortie(request, bon_id):
    """Permet de remplacer le fichier scanné d'un bon de sortie."""
    bon = get_object_or_404(
        BonMouvement, id=bon_id, type_bon='SORTIE',
        magasin__in=get_magasins_autorises(request),
    )

    if request.method == 'POST':
        from core.file_validation import valider_scan_document
        nouveau_scan = request.FILES.get('nouveau_scan')
        if not nouveau_scan:
            messages.error(request, "❌ Aucun fichier sélectionné.")
        else:
            ok, erreur = valider_scan_document(nouveau_scan, taille_max=MAX_FILE_SIZE)
            if not ok:
                messages.warning(request, f"⚠️ Scan refusé : {erreur}")
            else:
                if bon.document_scan and bon.document_scan.name and default_storage.exists(bon.document_scan.name):
                    default_storage.delete(bon.document_scan.name)

                bon.document_scan = nouveau_scan
                bon.date_upload_scan = timezone.now()
                bon.upload_scan_par = request.user
                bon.save(update_fields=[
                    'document_scan', 'date_upload_scan', 'upload_scan_par'
                ])
                messages.success(
                    request,
                    f"✅ Fichier scanné remplacé pour le bon {bon.numero_bon}."
                )

    return redirect('liste_sorties')