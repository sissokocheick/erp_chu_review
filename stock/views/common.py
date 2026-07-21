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
from django.http import HttpResponse, JsonResponse
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

def _has_perm_bon(user, action, type_bon):
    """
    Vérifie la permission custom par type de bon.
    action: 'add', 'change', 'delete'
    type_bon: 'ENTREE', 'SORTIE', 'RETOUR_SERVICE', 'SORTIE_HORS_STOCK'
    """
    mapping = {
        'ENTREE': ('can_add_bon_entree', 'can_change_bon_entree', 'can_delete_bon_entree'),
        'SORTIE': ('can_add_bon_sortie', 'can_change_bon_sortie', 'can_delete_bon_sortie'),
        'RETOUR_SERVICE': ('can_add_bon_retour', 'can_change_bon_retour', 'can_delete_bon_retour'),
        'SORTIE_HORS_STOCK': ('can_add_bon_hors_stock', 'can_change_bon_hors_stock', 'can_delete_bon_hors_stock'),
    }
    perms = mapping.get(type_bon)
    if not perms:
        return user.is_superuser
    idx = {'add': 0, 'change': 1, 'delete': 2}.get(action, 0)
    codename = perms[idx]
    return user.has_perm(f'stock.{codename}') or user.is_superuser
# ══════════════════════════════════════════════════════════════════════════════
# HELPERS CACHE PDF (storage-agnostic)
# ══════════════════════════════════════════════════════════════════════════════



def _servir_pdf_cache(bon, filename):
    """
    Lit un PDF depuis le stockage Django et retourne HttpResponse.
    Retourne None si le cache est absent ou invalide.
    """
    if not bon.fichier_pdf or not bon.fichier_pdf.name:
        return None
    try:
        if default_storage.exists(bon.fichier_pdf.name):
            with default_storage.open(bon.fichier_pdf.name, 'rb') as f:
                pdf_bytes = f.read()
            response = HttpResponse(pdf_bytes, content_type='application/pdf')
            response['Content-Disposition'] = f'inline; filename="{filename}"'
            return response
    except Exception as e:
        logger.warning("[PDF] Cache inaccessible : %s", e)
    return None




def _sauver_pdf_cache(bon, filename, pdf_bytes):
    """
    Sauvegarde les bytes PDF dans le FileField du bon.
    Supprime l'ancien fichier s'il existe pour éviter les conflits.
    """
    try:
        if bon.fichier_pdf and bon.fichier_pdf.name and default_storage.exists(bon.fichier_pdf.name):
            default_storage.delete(bon.fichier_pdf.name)
        bon.fichier_pdf.save(filename, ContentFile(pdf_bytes), save=True)
    except Exception as e:
        logger.warning("[PDF] Sauvegarde cache échouée : %s", e)


# ══════════════════════════════════════════════════════════════════════════════
# ENTRÉES
# ══════════════════════════════════════════════════════════════════════════════

