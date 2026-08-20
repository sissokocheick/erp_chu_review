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
from ..pdf_utils import get_pdf_config, paginate_lignes, ajouter_hauteurs_lignes, build_signature_cases
from ..forms import EntreeStockForm
from ..models import (
    Mouvement, BonMouvement, LigneBon, MotifAnnulation,
    Article, Magasin, StockItem,
    Fournisseur)
from ..services import NumeroGenerator, PDFService, NotificationService
from ..services.bon_service import BonService
from .catalogue import paginer
from .common import _has_perm_bon
from .common_views import render_liste, get_magasin_actif, build_redirect_url
from django.core.exceptions import PermissionDenied

# Constante : taille maximale de fichier upload (1 Mo)
MAX_FILE_SIZE = 1024 * 1024  # 1 Mo en octets

logger = logging.getLogger(__name__)


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_entrees')
@magasin_requis
@catch_errors(redirect_url='liste_entrees')
def liste_entrees(request):
    """Dispatcher : GET affiche, POST crée."""
    if request.method == 'POST':
        return _creer_entree(request)
    return _afficher_entrees(request)


def _afficher_entrees(request):
    """Branche GET : filtres, pagination, contexte."""
    qs = BonMouvement.objects.filter(
        type_bon='ENTREE'
    ).select_related('magasin', 'fournisseur', 'cree_par').prefetch_related(
        'lignes_bon__article'
    ).order_by('-date_bon')

    magasin_actif_id = request.session.get('magasin_actif_id')
    if magasin_actif_id:
        qs = qs.filter(magasin_id=magasin_actif_id)

    from stock.models import CircuitValidation
    circuit_entree = CircuitValidation.objects.filter(
        type_document='ENTREE', est_actif=True, is_deleted=False
    ).first()
    est_valideur_entree = False
    if circuit_entree:
        est_valideur_entree = (
            request.user.is_superuser
            or circuit_entree.valideurs.filter(id=request.user.id).exists()
        )

    extra = {
        'magasins': get_magasins_autorises(request).order_by('nom'),
        'fournisseurs': Fournisseur.objects.all().order_by('raison_sociale'),
        'articles': Article.objects.all().prefetch_related(
            'stocks__magasin'
        ).order_by('designation'),
        'motifs_annulation': MotifAnnulation.objects.filter(actif=True).order_by('libelle'),
        'peut_creer': _has_perm_bon(request.user, 'add', 'ENTREE'),
        'peut_annuler': _has_perm_bon(request.user, 'cancel', 'ENTREE'),
        'circuit_entree': circuit_entree,
        'est_valideur_entree': est_valideur_entree,
    }
    return render_liste(
        request, qs,
        template='stock/liste_entrees.html',
        ajax_template='stock/entrees_lignes.html',
        context_object_name='entrees_bons',
        date_field='date_bon',
        texte_champs=[
            'numero_bon__icontains',
            'fournisseur__raison_sociale__icontains',
            'reference_externe__icontains',
            'magasin__nom__icontains',
            'lignes_bon__article__designation__icontains',
        ],
        colonnes_tri={
            'numero_bon': 'numero_bon',
            'date_bon': 'date_bon',
            'magasin': 'magasin__nom',
            'fournisseur': 'fournisseur__raison_sociale',
        },
        tri_defaut='-date_bon',
        context_extra=extra
    )


def _creer_entree(request):
    """Branche POST : validation, création via service, upload scan, redirection."""
    magasins_autorises = get_magasins_autorises(request)

    magasin_id = request.POST.get('magasin')
    if not magasin_id or not magasins_autorises.filter(id=magasin_id).exists():
        messages.error(request, "⛔ Action interdite : Vous n'avez pas accès à ce magasin.")
        return redirect('liste_entrees')

    fournisseur_id = request.POST.get('fournisseur')
    ref_ext = request.POST.get('reference_externe')
    article_ids = request.POST.getlist('articles[]')
    quantites = request.POST.getlist('quantites[]')
    lots = request.POST.getlist('lots[]')
    peremptions = request.POST.getlist('peremptions[]')
    prix_unitaires = request.POST.getlist('prix_unitaires[]')

    if not article_ids:
        messages.error(request, "❌ Vous devez ajouter au moins un article.")
        return redirect('liste_entrees')

    # ═══ Document scanné obligatoire ═══
    fichier_scan = request.FILES.get('document_scan')
    if not fichier_scan:
        messages.error(request, "❌ Le fichier scanné est obligatoire. Veuillez joindre un document (PDF, JPG ou PNG).")
        return redirect('liste_entrees')

    if ref_ext and BonMouvement.objects.filter(
        type_bon='ENTREE', fournisseur_id=fournisseur_id,
        reference_externe__iexact=ref_ext
    ).exists():
        messages.error(request, f"Le BL/Facture '{ref_ext}' a déjà été enregistré.")
        return redirect('liste_entrees')

    magasin = Magasin.objects.get(id=magasin_id)

    # Récupération du fournisseur (objet)
    fournisseur = None
    if fournisseur_id:
        fournisseur = get_object_or_404(Fournisseur, id=fournisseur_id)

    # Validation des articles
    articles_valides = set(
        Article.objects.filter(
            id__in=[aid for aid in article_ids if aid]
        ).values_list('id', flat=True)
    )

    lignes = []
    for aid, qte, lot, peremp, pu in zip(article_ids, quantites, lots, peremptions, prix_unitaires):
        if aid and qte and int(qte) > 0:
            if int(aid) not in articles_valides:
                messages.error(
                    request,
                    f"⛔ L'article sélectionné n'est pas valide."
                )
                return redirect('liste_entrees')

            # ═══ VALIDATION LOT / PÉREMPTION ═══
            article = get_object_or_404(Article, id=aid)
            if article.requiert_lot_peremption:
                if not lot or not lot.strip():
                    messages.error(
                        request,
                        f"❌ L'article '{article.designation}' nécessite un N° de lot."
                    )
                    return redirect('liste_entrees')
                if not peremp or not peremp.strip():
                    messages.error(
                        request,
                        f"❌ L'article '{article.designation}' nécessite une date de péremption."
                    )
                    return redirect('liste_entrees')

            # ═══ BLOCAGE SANITAIRE : lot déjà périmé refusé à l'entrée ═══
            if peremp and peremp.strip():
                erreur = BonService._verifier_peremption(
                    Article.objects.filter(id=aid).first(), peremp
                )
                if erreur:
                    messages.error(request, erreur)
                    return redirect('liste_entrees')

            lignes.append({
                'article_id': aid,
                'quantite': int(qte),
                'numero_lot': lot.strip() or None,
                'date_peremption': peremp or None,
                'prix_unitaire': Decimal(pu) if pu and pu.strip() else None,
            })

    try:
        from stock.models import CircuitValidation
        circuit_entree = CircuitValidation.objects.filter(
            type_document='ENTREE', est_actif=True, is_deleted=False
        ).first()
        bon = BonService.creer_bon_entree(
            lignes=lignes,
            utilisateur=request.user,
            magasin=magasin,
            fournisseur=fournisseur,
            reference_externe=ref_ext,
            circuit_validation=circuit_entree
        )
    except ValidationError as e:
        messages.error(request, str(e))
        return redirect('liste_entrees')
    except IntegrityError as e:
        logger.exception("[ENTREE] IntegrityError création bon : %s", e)
        messages.error(request, "⛔ Erreur lors de la création du bon. Vérifiez la console pour le détail.")
        return redirect('liste_entrees')

    _traiter_upload_scan(request, bon)

    if bon.statut_validation == 'ATTENTE':
        messages.success(
            request,
            f"✅ Bon d'entrée enregistré et envoyé pour validation "
            f"({len(lignes)} article(s)) — le stock sera mis à jour après validation."
        )
    else:
        messages.success(request, f"✅ Bon d'entrée enregistré ! ({len(lignes)} article(s))")
    return redirect(f"{reverse('liste_entrees')}?print_bon={bon.id}")


def _traiter_upload_scan(request, bon):
    """Helper isolé pour la gestion du fichier scanné."""
    fichier_scan = request.FILES.get('document_scan')
    if not fichier_scan:
        return
    if fichier_scan.size > MAX_FILE_SIZE:
        messages.warning(request, f"⚠️ Fichier scanné trop lourd ({fichier_scan.size // 1024} Ko > 1 Mo). Bon créé sans scan.")
        return
    if not fichier_scan.name.lower().endswith(('.pdf', '.jpg', '.jpeg', '.png')):
        messages.warning(request, "⚠️ Format scanné invalide. Bon créé sans scan.")
        return
    bon.document_scan = fichier_scan
    bon.date_upload_scan = timezone.now()
    bon.upload_scan_par = request.user
    bon.save()
    messages.info(request, f"📎 Fichier scanné joint au bon {bon.numero_bon}.")


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_entrees')
@magasin_requis
@catch_errors(redirect_url='liste_entrees')
def annuler_entree(request, bon_id):
    if request.method != 'POST':
        return redirect('liste_entrees')

    magasins_autorises = get_magasins_autorises(request)
    bon = get_object_or_404(
        BonMouvement, id=bon_id, type_bon='ENTREE',
        magasin__in=magasins_autorises
    )

    motif_id = request.POST.get('motif_id')
    if not motif_id:
        messages.error(request, "Le motif d'annulation est obligatoire.")
        return redirect('liste_entrees')

    motif = get_object_or_404(MotifAnnulation, id=motif_id)

    try:
        BonService.annuler_bon_entree(bon, motif, request.user)
    except ValueError as e:
        logger.exception("[ENTREE] %s", e)
        messages.error(request, "⛔ Erreur lors de l'annulation. Veuillez réessayer.")
        return redirect('liste_entrees')

    # Invalidation cache PDF
    if bon.fichier_pdf and bon.fichier_pdf.name:
        try:
            if default_storage.exists(bon.fichier_pdf.name):
                default_storage.delete(bon.fichier_pdf.name)
        except Exception as e:
            logger.warning("[Annulation BE %s] Échec suppression cache PDF : %s", bon.numero_bon, e)

        bon.fichier_pdf = None
        bon.save(update_fields=['fichier_pdf'])

    messages.success(
        request,
        f"✅ Entrée {bon.numero_bon} annulée. Le stock a été décompté."
    )
    return redirect('liste_entrees')


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_entrees')
@magasin_requis
def apercu_bon_entree(request, bon_id):
    """Renvoie le HTML brut du bon d'entrée pour affichage dans SweetAlert2."""
    bon = get_object_or_404(
        BonMouvement.objects.select_related(
            'magasin', 'fournisseur', 'service_demandeur', 'cree_par', 'valide_par', 'commande_liee'
        ).prefetch_related('lignes_bon__article'),
        id=bon_id,
        type_bon='ENTREE',
    )

    pdf_config, logo_url = get_pdf_config(bon.magasin, 'BE', request)

    # Lignes harmonisées (mêmes clés que le PDF imprimable)
    lignes_data = []
    for idx, ligne in enumerate(bon.lignes_bon.all(), start=1):
        article = ligne.article
        lignes_data.append({
            'idx': idx,
            'reference': getattr(article, 'reference', ''),
            'designation': getattr(article, 'designation', ''),
            'unite': getattr(article, 'unite_distribution', None) or getattr(article, 'unite', 'U') or 'U',
            'quantite': ligne.quantite,
            'quantite_recue': ligne.quantite,
            'numero_lot': getattr(ligne, 'numero_lot', None),
            'date_peremption': getattr(ligne, 'date_peremption', None),
        })
    a_lots = any(l['numero_lot'] for l in lignes_data)

    pagination = paginate_lignes(lignes_data, pdf_config, lignes_par_page=18, type_doc='ENTREE')
    pages = [
        {'lignes': page, 'est_derniere_page': i == len(pagination.pages) - 1}
        for i, page in enumerate(pagination.pages)
    ]
    pages = ajouter_hauteurs_lignes(pages, pdf_config, type_doc='ENTREE')

    service = bon.service_demandeur

    context = {
        'is_apercu': True,
        'bon': bon,
        'magasin': bon.magasin,
        'lignes': list(bon.lignes_bon.all()),
        'lignes_data': lignes_data,
        'lignes_pages': pagination.pages,
        'pages': pages,
        'est_multi_page': pagination.est_multi_page,
        'est_reception_partielle': False,
        'est_livraison_partielle': False,
        'est_cloture': False,
        'numero_livraison': bon.numero_livraison,
        'commande': bon.commande_liee,
        'service': service,
        'service_code': getattr(service, 'code', '') if service else '',
        'service_poste': getattr(service, 'poste', '') if service else '',
        'sondage_data': None,
        'a_lots': a_lots,
        'signature_cases': build_signature_cases(bon, pdf_config, request),
        'total_qte': sum(l.quantite for l in bon.lignes_bon.all()),
        'logo_url': logo_url,
        'date_impression': timezone.now(),
        'pdf_config': pdf_config,
    }
    return render(request, 'stock/pdf/bon_entree.html', context)


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_entrees')
@magasin_requis
@catch_errors(redirect_url='liste_entrees')
def remplacer_scan_entree(request, bon_id):
    bon = get_object_or_404(
        BonMouvement, id=bon_id, type_bon='ENTREE'
    )

    if request.method == 'POST':
        nouveau_scan = request.FILES.get('nouveau_scan')
        if not nouveau_scan:
            messages.error(request, "❌ Aucun fichier sélectionné.")
        elif nouveau_scan.size > MAX_FILE_SIZE:
            messages.warning(
                request,
                f"⚠️ Fichier trop lourd ({nouveau_scan.size // 1024} Ko > 1 Mo)."
            )
        elif not nouveau_scan.name.lower().endswith(('.pdf', '.jpg', '.jpeg', '.png')):
            messages.warning(
                request,
                "⚠️ Format invalide. Seuls PDF, JPG et PNG sont acceptés."
            )
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

    return redirect('liste_entrees')


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_entrees')
@magasin_requis
@catch_errors(redirect_url='liste_entrees')
def valider_bon_entree(request, bon_id):
    """Valide un bon d'entrée en ATTENTE (circuit ENTREE actif) : applique les
    mouvements d'entrée (avec lots/péremptions) et met à jour le stock.

    Réservé aux validateurs désignés dans le circuit ENTREE (ou superuser),
    même pattern que valider_bon_sortie.
    """
    from stock.models import CircuitValidation
    from stock.services.stock_transaction_service import StockTransactionService
    from django.db import transaction as db_transaction

    bon = get_object_or_404(
        BonMouvement, id=bon_id, type_bon='ENTREE'
    )

    circuit = CircuitValidation.objects.filter(
        type_document='ENTREE', est_actif=True, is_deleted=False
    ).prefetch_related('valideurs').first()

    if not circuit:
        messages.error(request, "❌ Aucun circuit de validation actif pour les bons d'entrée.")
        return redirect('liste_entrees')

    if request.user not in circuit.valideurs.all() and not request.user.is_superuser:
        messages.error(request, "⛔ Vous n'êtes pas autorisé à valider ce bon d'entrée.")
        return redirect('liste_entrees')

    if bon.statut_validation != 'ATTENTE':
        messages.warning(request, f"⚠️ Le bon {bon.numero_bon} n'est pas en attente de validation.")
        return redirect('liste_entrees')

    try:
        with db_transaction.atomic():
            bon.statut_validation = 'VALIDE'
            bon.date_validation = timezone.now()
            bon.valide_par = request.user
            bon.save(update_fields=['statut_validation', 'date_validation', 'valide_par'])

            for ligne in bon.lignes_bon.all():
                mouvement = Mouvement(
                    type_mouvement='ENTREE',
                    article=ligne.article,
                    magasin=bon.magasin,
                    quantite=ligne.quantite,
                    prix_unitaire=ligne.prix_unitaire,
                    utilisateur=request.user,
                    reference_document=bon.numero_bon,
                    numero_lot=ligne.numero_lot,
                    date_peremption=ligne.date_peremption,
                    commentaire=f"Validation du bon {bon.numero_bon}",
                )
                StockTransactionService.executer(mouvement)
    except Exception as e:
        logger.exception("[ENTREE] Validation bon %s : %s", bon.numero_bon, e)
        messages.error(request, "❌ Une erreur est survenue lors de la validation.")
        return redirect('liste_entrees')

    messages.success(
        request,
        f"✅ Bon d'entrée {bon.numero_bon} validé par "
        f"{request.user.get_full_name() or request.user.username} — le stock a été mis à jour."
    )
    return redirect('liste_entrees')