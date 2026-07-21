# core/managers.py — CORRIGÉ (v2)
"""
Managers pour l'architecture multi-tenant avec BDD partagée.
- BaseManager    : filtre automatiquement is_deleted=False
- TenantManager  : filtre par entreprise active + soft-delete
- GlobalManager  : pas de filtre entreprise + soft-delete (réservé admin/shell)
"""
import logging
import sys
from django.db import models
import contextvars

logger = logging.getLogger(__name__)

# ContextVar pour l'entreprise active (compatible async/ASGI)
_tenant_context = contextvars.ContextVar('tenant', default=None)


def get_current_tenant():
    """
    Récupère l'entreprise active depuis le contexte (async-safe).
    Returns:
        Entreprise ou None si pas de contexte tenant.
    """
    return _tenant_context.get()


def set_current_tenant(entreprise):
    """
    Définit l'entreprise active dans le contexte (async-safe).
    Retourne le token pour pouvoir faire reset() dans un finally.
    """
    return _tenant_context.set(entreprise)


class BaseManager(models.Manager):
    """Manager de base avec filtre soft-delete automatique."""
    def get_queryset(self):
        qs = super().get_queryset()
        if hasattr(self.model, 'is_deleted'):
            qs = qs.filter(is_deleted=False)
        return qs

    def with_deleted(self):
        """Inclut les lignes supprimées logiquement (audit, admin)."""
        return super().get_queryset()


class TenantManager(BaseManager):
    """
    Manager qui filtre AUTOMATIQUEMENT par l'entreprise active.
    """
    def get_queryset(self):
        qs = super().get_queryset()
        if not hasattr(self.model, 'entreprise'):
            return qs
        tenant = get_current_tenant()
        if tenant is None:
            # ✅ CORRECTION P0 (v2): Logger un warning en mode dev/shell
            # pour éviter le silence qui masque les bugs
            if 'shell' in sys.argv or 'test' in sys.argv:
                logger.warning(
                    f"[TenantManager] {self.model.__name__}.objects.all() appelé "
                    f"sans contexte tenant → queryset vide. "
                    f"Utiliser set_current_tenant(e) ou GlobalManager."
                )
            return qs.none()
        return qs.filter(entreprise=tenant)

    def update(self, **kwargs):
        """
        ✅ CORRECTION P0 (v2): Surcharge update() pour vérifier le tenant.
        Empêche les update() cross-tenant même via TenantManager.
        """
        tenant = get_current_tenant()
        if tenant is None:
            logger.critical(
                f"[TenantManager] Tentative update() sans tenant sur {self.model.__name__}"
            )
            raise RuntimeError(
                "update() interdit sans contexte tenant. "
                "Utiliser GlobalManager explicitement si nécessaire."
            )
        # Vérifier que le queryset filtre bien par ce tenant
        qs = self.get_queryset()
        return super(TenantManager, qs).update(**kwargs)

    def bulk_create(self, objs, **kwargs):
        """
        ✅ CORRECTION P0 (v2): Surcharge bulk_create pour auto-assigner le tenant.
        """
        tenant = get_current_tenant()
        if tenant is None:
            logger.critical(
                f"[TenantManager] Tentative bulk_create() sans tenant sur {self.model.__name__}"
            )
            raise RuntimeError(
                "bulk_create() interdit sans contexte tenant. "
                "Utiliser GlobalManager explicitement si nécessaire."
            )
        for obj in objs:
            if hasattr(obj, 'entreprise') and obj.entreprise_id is None:
                obj.entreprise = tenant
        return super().bulk_create(objs, **kwargs)


class GlobalManager(BaseManager):
    """
    Manager SANS filtre entreprise.

    ⚠️ ATTENTION : Ce manager ne vérifie PAS les permissions.
    À utiliser UNIQUEMENT dans :
    - L'admin Django (où Django vérifie déjà les permissions)
    - Le shell de management (où l'opérateur est déjà authentifié)
    - Les tâches Celery avec vérification explicite du contexte

    Dans une vue web, préférer TenantManager + filtre manuel si besoin.
    """
    # ✅ CORRECTION P0 (v2): Logger un warning si utilisé hors contexte autorisé
    def get_queryset(self):
        # Détecter si on est dans le shell ou l'admin
        in_shell = 'shell' in sys.argv or 'dbshell' in sys.argv
        in_admin = hasattr(self, '_in_admin_context')  # Flag optionnel

        if not in_shell and not in_admin:
            logger.warning(
                f"[GlobalManager] {self.model.__name__}.all_objects utilisé "
                f"hors shell/admin. Vérifier que c'est intentionnel."
            )
        return super().get_queryset()
