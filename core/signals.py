# core/signals.py — CORRIGÉ (v2)
"""
Signaux de sécurité pour l'isolation multi-tenant.
Empêche toute écriture/modification qui ne correspond pas au tenant actif.

Cas gérés:
  1. Pas de tenant + mode strict → PermissionDenied
  2. Pas de tenant + mode lax → OK (shell, migrations)
  3. Tenant actif + entreprise_id=None → auto-assignation du tenant
  4. Tenant actif + entreprise_id mismatch → PermissionDenied
"""
import logging
from django.conf import settings
from django.db.models.signals import pre_save, pre_delete, m2m_changed
from django.dispatch import receiver
from django.core.exceptions import PermissionDenied
from core.managers import get_current_tenant

logger = logging.getLogger('tenant_security')

# Mode strict configurable
TENANT_STRICT_MODE = getattr(settings, 'TENANT_STRICT_MODE', False)

# Allowlist explicite des modèles tenant-aware
TENANT_AWARE_MODELS = set()

# Allowlist des modèles THROUGH (tables intermédiaires M2M)
TENANT_AWARE_THROUGH_MODELS = set()


def register_tenant_model(model_class):
    """Enregistre un modèle comme tenant-aware pour le signal de sécurité."""
    TENANT_AWARE_MODELS.add(model_class)
    return model_class


def register_tenant_through_model(through_model_class):
    """
    Enregistre un modèle THROUGH (table intermédiaire M2M) comme tenant-aware.
    Le sender de m2m_changed est le modèle THROUGH, pas le modèle final.
    """
    TENANT_AWARE_THROUGH_MODELS.add(through_model_class)
    return through_model_class


def _check_tenant(sender, instance, action):
    """
    Vérifie l'isolation tenant pour une instance donnée.

    Logique:
      - Si pas de tenant et mode strict → PermissionDenied
      - Si pas de tenant et mode lax → OK (shell, migrations)
      - Si tenant actif et entreprise_id=None → auto-assigne le tenant
      - Si tenant actif et entreprise_id mismatch → PermissionDenied
    """
    if not hasattr(instance, 'entreprise_id'):
        return

    tenant = get_current_tenant()

    if tenant is None:
        if TENANT_STRICT_MODE:
            msg = (
                f"⛔ TENTATIVE {action} SANS CONTEXTE TENANT (mode strict) : "
                f"{sender.__name__} (ID={instance.pk})"
            )
            logger.critical(msg)
            raise PermissionDenied("Opération interdite hors contexte tenant (mode strict)")
        return

    # ✅ CORRECTION P0 (v2): Auto-assigner le tenant si entreprise_id est None
    # au lieu de lever PermissionDenied immédiatement
    if instance.entreprise_id is None:
        instance.entreprise = tenant
        logger.info(
            f"[TenantSecurity] {action} : {sender.__name__} (ID={instance.pk}) "
            f"→ entreprise auto-assignée au tenant {tenant.id}"
        )
        return

    if instance.entreprise_id != tenant.id:
        logger.critical(
            f"⛔ TENTATIVE {action} HORS TENANT : "
            f"{sender.__name__} (ID={instance.pk}) entreprise={instance.entreprise_id} "
            f"tenant={tenant.id}"
        )
        raise PermissionDenied("Isolation tenant violée")


@receiver(pre_save)
def verify_tenant_on_write(sender, instance, **kwargs):
    """Vérifie que toute écriture appartient bien au tenant actif."""
    if sender not in TENANT_AWARE_MODELS:
        return
    _check_tenant(sender, instance, "D'ISOLATION")


@receiver(pre_delete)
def verify_tenant_on_delete(sender, instance, **kwargs):
    """Même vérification pour les suppressions."""
    if sender not in TENANT_AWARE_MODELS:
        return
    _check_tenant(sender, instance, "DE SUPPRESSION")


@receiver(m2m_changed)
def verify_tenant_on_m2m(sender, instance, action, pk_set, model, **kwargs):
    """
    Vérifie les relations ManyToMany entre objets tenant.

    ✅ CORRECTION P0 : Le sender de m2m_changed est le modèle THROUGH (table
    intermédiaire), PAS le modèle final. On vérifie donc :
    1. Si sender est dans TENANT_AWARE_THROUGH_MODELS
    2. OU si instance.__class__ est dans TENANT_AWARE_MODELS

    ✅ CORRECTION P0 (v2): pre_clear n'a pas de pk_set (None).
    Dans ce cas, seule l'instance est vérifiée (pas les objets liés).
    """
    if action not in ('pre_add', 'pre_remove', 'pre_clear'):
        return

    # Vérifier que l'instance ou le through model est tenant-aware
    instance_class = instance.__class__
    if instance_class not in TENANT_AWARE_MODELS and sender not in TENANT_AWARE_THROUGH_MODELS:
        return

    tenant = get_current_tenant()
    if tenant is None:
        if TENANT_STRICT_MODE:
            raise PermissionDenied("Opération M2M interdite hors contexte tenant")
        return

    # Vérifier l'instance
    if hasattr(instance, 'entreprise_id'):
        if instance.entreprise_id is None:
            instance.entreprise = tenant
        elif instance.entreprise_id != tenant.id:
            logger.critical(f"⛔ M2M instance hors tenant : {instance_class.__name__} ID={instance.pk}")
            raise PermissionDenied("Isolation tenant violée (instance)")

    # ✅ CORRECTION P0 (v2): pre_clear n'a pas de pk_set → on skippe la vérification
    # des objets liés (seule l'instance est vérifiée ci-dessus)
    if action == 'pre_clear':
        logger.debug(f"[TenantSecurity] M2M pre_clear sur {instance_class.__name__} — "
                     f"vérification des objets liés impossible (pk_set=None)")
        return

    # Vérifier que TOUS les objets dans pk_set appartiennent au tenant
    if pk_set and hasattr(model, 'entreprise_id'):
        count_cross = model.objects.filter(
            pk__in=pk_set
        ).exclude(
            entreprise_id=tenant.id
        ).count()
        if count_cross > 0:
            logger.critical(
                f"⛔ M2M cross-tenant détecté : "
                f"{count_cross} objets {model.__name__} n'appartiennent pas au tenant {tenant.id}"
            )
            raise PermissionDenied("Association inter-tenant interdite")
