import os
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from django.apps import apps
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction, IntegrityError
from django.db.models import Q, F, Sum, Prefetch, OuterRef, Subquery
from django.db.models.functions import Coalesce
from django.http import HttpResponse, JsonResponse, HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from weasyprint import HTML

from accounts.permissions import verifier_permission
from core.models import Service, ConfigurationHopital
from core.pdf_service import DocumentGenerator
from ..decorators import magasin_requis, catch_errors
from ..forms import (
    SortieStockForm, EntreeStockForm, AjustementForm,
    MagasinParametresForm,
)
from ..models import (
    Mouvement, BonMouvement, LigneBon, MotifAnnulation,
    Article, Magasin, StockItem, Ajustement,
    Fournisseur, Beneficiaire,
    CampagneInventaire, LigneInventaire, CircuitValidation,
    LivraisonPartielle, DemandeMateriel, LigneDemande,
    AccuseReception,
    LivraisonLigne,
)
from ..services import (
    NumeroGenerator, StockService, PDFService, NotificationService
)
from .catalogue import paginer, get_magasins_autorises

logger = logging.getLogger(__name__)
User = get_user_model()

from .common import _servir_pdf_cache, _sauver_pdf_cache


@login_required(login_url='/auth/login/')
@magasin_requis
def imprimer_bon_multi_lignes(request, bon_id):
    """
    Genere et retourne le PDF d'un bon (ENTREE, SORTIE, RETOUR, HORS STOCK).
    NE JAMAIS rediriger — toujours retourner HttpResponse pour l'iframe.
    """
    entreprise = request.entreprise

    bon = get_object_or_404(
        BonMouvement.objects.filter(
            magasin__entreprise=entreprise
        ).prefetch_related(
            'lignes_bon__article', 'lignes_bon__article__famille'
        ).select_related('magasin', 'fournisseur', 'service_demandeur', 'cree_par', 'valide_par'),
        id=bon_id
    )

    # ═══════════════════════════════════════════════════════════════════════
    # ✅ CORRECTION : VERIFICATION ENTREPRISE via request.entreprise (middleware)
    # Le middleware positionne request.entreprise selon le profil utilisateur.
    # Si le bon appartient a une autre entreprise → 403
    # ═══════════════════════════════════════════════════════════════════════
    if bon.magasin.entreprise_id != entreprise.id:
        if not request.user.is_superuser:
            return HttpResponseForbidden(
                "<div style='font-family:sans-serif;text-align:center;padding:60px 20px;'>"
                "<h2 style='color:#dc3545;'>⛔ Acces refuse</h2>"
                "<p>Vous n'avez pas acces aux documents d'une autre entreprise.</p></div>",
                content_type="text/html; charset=utf-8"
            )

    # ═══════════════════════════════════════════════════════════════════════
    # VERIFICATION PERMISSION DYNAMIQUE SELON LE TYPE DE BON
    # ═══════════════════════════════════════════════════════════════════════
    perm_map_pdf = {
        'ENTREE': 'accounts.menu_entrees',
        'SORTIE': 'accounts.menu_sorties',
        'RETOUR_SERVICE': 'accounts.menu_retours_services',
        'SORTIE_HORS_STOCK': 'accounts.menu_sorties_hors_stock',
    }
    required_perm = perm_map_pdf.get(bon.type_bon)
    if required_perm and not (request.user.has_perm(required_perm) or request.user.is_superuser):
        return HttpResponse(
            "<div style='font-family:sans-serif;text-align:center;padding:60px 20px;'>"
            "<h2 style='color:#dc3545;'>⛔ Acces refuse</h2>"
            "<p>Vous n'avez pas la permission d'imprimer ce type de bon.</p></div>",
            status=403, content_type="text/html; charset=utf-8"
        )

    # ═══════════════════════════════════════════════════════════════════════
    # BLOCAGE SERVEUR : bon SORTIE en attente de validation = interdit
    # sauf pour les valideurs du circuit SORTIE et les superusers
    # ═══════════════════════════════════════════════════════════════════════
    if bon.type_bon == 'SORTIE' and bon.statut_validation == 'ATTENTE':
        circuit = CircuitValidation.objects.filter(
            type_document='SORTIE', entreprise=entreprise, est_actif=True
        ).prefetch_related('valideurs').first()
        est_valideur = (
            circuit and (
                circuit.valideurs.filter(id=request.user.id).exists()
                or request.user.is_superuser
            )
        )
        if not est_valideur:
            return HttpResponse(
                "<div style='font-family:sans-serif;text-align:center;padding:60px 20px;'>"
                "<h2 style='color:#dc3545;'><i class='fas fa-lock'></i> Impression bloquee</h2>"
                "<p style='color:#666;font-size:15px;'>Ce bon de sortie est en attente de validation hierarchique.<br>"
                "L'impression sera disponible des qu'un valideur l'aura approuve.</p>"
                "</div>",
                status=403,
                content_type="text/html; charset=utf-8"
            )

    prefix_map = {
        'ENTREE': 'BE',
        'RETOUR_SERVICE': 'BR',
        'SORTIE_HORS_STOCK': 'BSHS',
        'SORTIE': 'BS',
    }
    prefixe = prefix_map.get(bon.type_bon, 'BS')
    filename = f"{prefixe}_{bon.numero_bon}.pdf"

    # ═══════════════════════════════════════════════════════════════════════
    # 1. ACCUSE DE RECEPTION
    # ═══════════════════════════════════════════════════════════════════════
    accuse_reception = None
    if bon.type_bon == 'SORTIE':
        try:
            livraison = LivraisonPartielle.objects.select_related(
                'accuse__receptionne_par__profil'
            ).get(bon_sortie=bon)
            if livraison.accuse and livraison.accuse.est_signe:
                accuse_reception = livraison.accuse
        except (LivraisonPartielle.DoesNotExist, AccuseReception.DoesNotExist, AttributeError):
            pass

    # ═══════════════════════════════════════════════════════════════════════
    # 2. VALIDATEUR DU CIRCUIT DE VALIDATION SORTIE
    # ═══════════════════════════════════════════════════════════════════════
    valide_par_user = None
    circuit_sortie = None
    if bon.type_bon == 'SORTIE':
        circuit_sortie = CircuitValidation.objects.filter(
            type_document='SORTIE', entreprise=entreprise, est_actif=True
        ).prefetch_related('valideurs').first()

        # Uniquement si le bon est VALIDE — requete optimisee
        if circuit_sortie and bon.statut_validation == 'VALIDE' and bon.valide_par_id:
            if circuit_sortie.valideurs.filter(id=bon.valide_par_id).exists() or request.user.is_superuser:
                valide_par_user = bon.valide_par

    # ═══════════════════════════════════════════════════════════════════════
    # 3. INVALIDER LE CACHE si accuse signe OU validation presente
    # ═══════════════════════════════════════════════════════════════════════
    doit_invalider = False
    if accuse_reception and bon.fichier_pdf and bon.fichier_pdf.name:
        doit_invalider = True
    if valide_par_user and bon.fichier_pdf and bon.fichier_pdf.name:
        doit_invalider = True

    if doit_invalider and bon.fichier_pdf and bon.fichier_pdf.name:
        try:
            if default_storage.exists(bon.fichier_pdf.name):
                default_storage.delete(bon.fichier_pdf.name)
            bon.fichier_pdf = None
            bon.save(update_fields=['fichier_pdf'])
            logger.info("[PDF BS %s] Cache invalide — accuse signe ou validation detectee", bon.numero_bon)
        except Exception as e:
            logger.warning("[PDF BS %s] Echec suppression cache : %s", bon.numero_bon, e)

    # ═══════════════════════════════════════════════════════════════════════
    # 4. POSTE DU SERVICE DEMANDEUR
    # ═══════════════════════════════════════════════════════════════════════
    service_poste = getattr(bon.service_demandeur, 'poste_telephone', '') if bon.service_demandeur else ''

    # ── CACHE : servir instantanement si existant ──
    cached = _servir_pdf_cache(bon, filename)
    if cached:
        return cached

    # ── GENERATION PDF ──
    try:
        gen = DocumentGenerator(request=request, entreprise=entreprise)

        method_map = {
            'ENTREE': gen.bon_entree,
            'RETOUR_SERVICE': gen.bon_retour,
            'SORTIE_HORS_STOCK': gen.bon_hors_stock,
            'SORTIE': gen.bon_sortie,
        }
        pdf_method = method_map.get(bon.type_bon, gen.bon_sortie)

        extra = {}
        if accuse_reception:
            extra['accuse'] = accuse_reception
        if valide_par_user:
            extra['valide_par'] = valide_par_user
        if circuit_sortie:
            extra['circuit_sortie'] = circuit_sortie
        extra['service_poste'] = service_poste

        pdf_bytes = pdf_method(bon, extra_context=extra if extra else None)

        if not pdf_bytes:
            return HttpResponse("ERREUR : Le generateur PDF a retourne un fichier vide.", status=500)

        _sauver_pdf_cache(bon, filename, pdf_bytes)

        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        response['Content-Disposition'] = f'inline; filename="{filename}"'
        return response

    except Exception as e:
        # ═══════════════════════════════════════════════════════════════════
        # ✅ CORRECTION : Traceback masqué — fuite d'informations critique
        # Avant : traceback.format_exc() exposé au client
        # Après : message générique + log serveur
        # ═══════════════════════════════════════════════════════════════════
        logger.exception("[PDF GENERATION ERROR] Bon #%s : %s", bon_id, e)
        return HttpResponse(
            "<div style='font-family:sans-serif;text-align:center;padding:60px 20px;'>"
            "<h2 style='color:#dc3545;'>Erreur de génération PDF</h2>"
            "<p>Une erreur technique est survenue lors de la génération du document.<br>"
            "Veuillez réessayer ou contacter l'administrateur.</p></div>",
            status=500,
            content_type="text/html; charset=utf-8"
        )
