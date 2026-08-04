from django.db import models


class BaseManager(models.Manager):
    """
    Manager de base avec filtre soft-delete automatique.
    ✅ CORRECTION : suppression de TenantManager/GlobalManager.
    """
    def get_queryset(self):
        qs = super().get_queryset()
        if hasattr(self.model, 'is_deleted'):
            qs = qs.filter(is_deleted=False)
        return qs

    def with_deleted(self):
        """Inclut les lignes supprimées logiquement (audit, admin)."""
        return super().get_queryset()
