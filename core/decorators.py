# core/decorators.py — MONO-TENANT v1
"""
Décorateurs de sécurité pour l'architecture mono-tenant.

Legacy : @tenant_required est conservé pour compatibilité avec les autres
modules (stock, patrimoine, etc.) qui l'importent, mais se comporte désormais
comme un simple @login_required. Le code multi-tenant (set_current_tenant,
_tenant_context, request.entreprise) a été supprimé car il provoquait un
ImportError à l'import du module (ces symboles n'existent plus dans managers.py).
"""
from functools import wraps
from django.contrib.auth.decorators import login_required


def tenant_required(view_func):
    """
    Décorateur legacy multi-tenant, simplifié pour mono-tenant.
    Vérifie simplement que l'utilisateur est authentifié.
    Les vues protégées par @tenant_required continuent de fonctionner
    sans modification dans les autres modules.
    """
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        # En mono-tenant, il n'y a plus de vérification d'entreprise.
        # La configuration unique est toujours accessible via ConfigurationHopital.get_instance()
        return view_func(request, *args, **kwargs)
    return wrapper
