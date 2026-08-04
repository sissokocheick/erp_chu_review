import os
import logging
from datetime import datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.files.storage import default_storage
from django.db import IntegrityError
from django.http import HttpResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone

from accounts.permissions import verifier_permission
from ..decorators import magasin_requis, catch_errors
from ..forms import EntreeStockForm
from ..models import (
    Mouvement, BonMouvement, LigneBon, MotifAnnulation,
    Article, Magasin, StockItem,
    Fournisseur)
from ..services import NumeroGenerator, PDFService, NotificationService
from ..services.bon_service import BonService
from .catalogue import paginer, get_magasins_autorises
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

    extra = {
        'magasins': get_magasins_autorises(request).order_by('nom'),
        'fournisseurs': Fournisseur.objects.all().order_by('raison_sociale'),
        'articles': Article.objects.all().prefetch_related(
            'stocks__magasin'
        ).order_by('designation'),
        'motifs_annulation': MotifAnnulation.objects.filter(actif=True).order_by('libelle'),
        'peut_creer': _has_perm_bon(request.user, 'add', 'ENTREE'),
        'peut_annuler': _has_perm_bon(request.user, 'change', 'ENTREE'),
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

            lignes.append({
                'article_id': aid,
                'quantite': int(qte),
                'numero_lot': lot.strip() or None,
                'date_peremption': peremp or None,
                'prix_unitaire': Decimal(pu) if pu and pu.strip() else None,
            })

    try:
        bon = BonService.creer_bon_entree(
            lignes=lignes,
            utilisateur=request.user,
            magasin=magasin,
            fournisseur=fournisseur,
            reference_externe=ref_ext
        )
    except IntegrityError as e:
        logger.exception("[ENTREE] IntegrityError création bon : %s", e)
        messages.error(request, "⛔ Erreur lors de la création du bon. Vérifiez la console pour le détail.")
        return redirect('liste_entrees')

    _traiter_upload_scan(request, bon)

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

    pdf_config = {}
    logo_url = None

    # Signatures
    sig_magasinier_url = None
    if bon.cree_par:
        profil = getattr(bon.cree_par, 'profil', None)
        if profil and getattr(profil, 'signature', None):
            try:
                sig_magasinier_url = request.build_absolute_uri(profil.signature.url)
            except Exception:
                pass

    sig_valideur_url = None
    if bon.valide_par:
        profil = getattr(bon.valide_par, 'profil', None)
        if profil and getattr(profil, 'signature', None):
            try:
                sig_valideur_url = request.build_absolute_uri(profil.signature.url)
            except Exception:
                pass

    total_qte = sum(l.quantite for l in bon.lignes_bon.all())

    context = {
        'is_apercu': True,
        'bon': bon,
        'lignes': list(bon.lignes_bon.all()),
        'total_qte': total_qte,
        'logo_url': logo_url,
        'sig_magasinier_url': sig_magasinier_url,
        'sig_valideur_url': sig_valideur_url,
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