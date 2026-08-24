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
try:
    from weasyprint import HTML
except OSError:
    HTML = None

from accounts.permissions import verifier_permission
from core.models import Service, ConfigurationHopital
from stock.services.isolation_service import get_magasins_autorises
from ..decorators import magasin_requis, catch_errors
from ..forms import (
    SortieStockForm, EntreeStockForm, AjustementForm,
    MagasinParametresForm)
from ..models import (
    Mouvement, BonMouvement, LigneBon, MotifAnnulation,
    Article, Magasin, StockItem, Ajustement,
    Fournisseur, Beneficiaire,
    CampagneInventaire, LigneInventaire, CircuitValidation,
    LivraisonPartielle, DemandeMateriel, LigneDemande,
    AccuseReception,
    LivraisonLigne)
from ..services import (
    NumeroGenerator, StockService, PDFService, NotificationService
)
from .catalogue import paginer

logger = logging.getLogger(__name__)
User = get_user_model()

def _has_perm_bon(user, action, type_bon):
    """
    Vérifie la permission custom par type de bon.
    action: 'add', 'change', 'delete'
    type_bon: 'ENTREE', 'SORTIE', 'RETOUR_SERVICE', 'SORTIE_HORS_STOCK'
    """
    mapping = {
        'ENTREE': ('can_add_bon_entree', 'can_change_bon_entree', 'can_delete_bon_entree', 'can_cancel_bon_entree'),
        'SORTIE': ('can_add_bon_sortie', 'can_change_bon_sortie', 'can_delete_bon_sortie', 'can_cancel_bon_sortie'),
        'RETOUR_SERVICE': ('can_add_bon_retour', 'can_change_bon_retour', 'can_delete_bon_retour', 'can_cancel_bon_retour'),
        'RETOUR_FOURNISSEUR': ('can_add_bon_retour', 'can_change_bon_retour', 'can_delete_bon_retour', 'can_cancel_bon_retour'),
        'SORTIE_HORS_STOCK': ('can_add_bon_hors_stock', 'can_change_bon_hors_stock', 'can_delete_bon_hors_stock', 'can_cancel_bon_hors_stock'),
    }
    perms = mapping.get(type_bon)
    if not perms:
        return user.is_superuser
    idx = {'add': 0, 'change': 1, 'delete': 2, 'cancel': 3}.get(action, 0)
    codename = perms[idx]
    return user.has_perm(f'stock.{codename}') or user.is_superuser
# ══════════════════════════════════════════════════════════════════════════════
# HELPERS CACHE PDF (storage-agnostic)
# ══════════════════════════════════════════════════════════════════════════════

