"""
Package services du module stock.

L'ancien stock/services.py a été renommé stock/_services.py.
Ce __init__.py ré-exporte les symboles legacy pour ne pas casser les imports existants.
"""

# ═══ Nouveaux services (refacto couches métier) ═══
from .bon_service import BonService
from .stock_service import StockService
from .inventaire_service import InventaireService
from .livraison_service import LivraisonService
from .stock_transaction_service import StockTransactionService

# ═══ Legacy — ré-importés depuis stock/_services.py ═══
try:
    from stock._services import (
        NumeroGenerator,
        PDFService,
        NotificationService,
        DemandeService,
    )
except ModuleNotFoundError:
    # _services.py n'existe pas → fallback normal
    from ._services_legacy_stubs import (
        NumeroGenerator,
        PDFService,
        NotificationService,
        DemandeService,
    )
except ImportError as e:
    # ✅ CORRECTION : _services.py existe mais est corrompu → log + fallback
    import logging
    logging.getLogger(__name__).warning(
        "stock/_services.py corrompu ou incomplet, fallback vers stubs legacy: %s", e
    )
    from ._services_legacy_stubs import (
        NumeroGenerator,
        PDFService,
        NotificationService,
        DemandeService,
    )

from .parametre_service import (
    get_dependances,
    paginer_donnees,
    get_or_create_logistique_config,
    save_delai_remplacement,
    supprimer_entite,
    update_circuit,
    get_audit_data,
)

__all__ = [
    # Nouveaux services
    "BonService",
    "StockService",
    "InventaireService",
    "LivraisonService",
    "StockTransactionService",
    # Legacy
    "NumeroGenerator",
    "PDFService",
    "NotificationService",
    "DemandeService",
    # Paramètres
    "get_dependances",
    "paginer_donnees",
    "get_or_create_logistique_config",
    "save_delai_remplacement",
    "supprimer_entite",
    "update_circuit",
    "get_audit_data",
]
