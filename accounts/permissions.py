# accounts/permissions.py
from django.shortcuts import redirect
from django.contrib import messages
from functools import wraps
import logging

logger = logging.getLogger(__name__)


def verifier_permission(*permissions_requises):
    """
    Décorateur dynamique : Vérifie qu'AU MOINS UNE permission est présente.
    - Superuser = toujours autorisé (bypass total)
    - Fallback intelligent : si accounts.xxx échoue, essaie stock.xxx
    - Accepte une ou plusieurs permissions en arguments
    """
    def decorator(view_func):
        @wraps(view_func)
        def _wrapped_view(request, *args, **kwargs):
            user = request.user

            # 1. Superuser bypass
            if user.is_superuser:
                return view_func(request, *args, **kwargs)

            # 2. Vérifier chaque permission demandée
            for permission_requise in permissions_requises:
                if user.has_perm(permission_requise):
                    return view_func(request, *args, **kwargs)

                # 3. Fallback : accounts → stock (et inversement)
                if permission_requise.startswith('accounts.'):
                    alt = permission_requise.replace('accounts.', 'stock.', 1)
                    if user.has_perm(alt):
                        return view_func(request, *args, **kwargs)
                elif permission_requise.startswith('stock.'):
                    alt = permission_requise.replace('stock.', 'accounts.', 1)
                    if user.has_perm(alt):
                        return view_func(request, *args, **kwargs)

            # 4. Refus propre — LOG D'AVERTISSEMENT
            logger.warning(
                f"Accès refusé pour {user.username} ({user.id}) sur {request.path} "
                f"— permissions requises : {permissions_requises}"
            )

            # Tentative de log d'audit (optionnel, ne pas bloquer si échoue)
            try:
                from accounts.models import JournalAudit
                JournalAudit.objects.create(
                    utilisateur=user if user.is_authenticated else None,
                    entreprise=getattr(request, 'entreprise', None),
                    action=f"Accès refusé sur {request.path}",
                    type_action='PERMISSION',
                    details={'permissions_requises': list(permissions_requises)},
                    adresse_ip=request.META.get('REMOTE_ADDR'),
                )
            except Exception:
                pass

            messages.error(
                request,
                "⛔ Accès refusé : Vous n'avez pas l'autorisation pour cette action ou cette page."
            )
            referer = request.META.get('HTTP_REFERER', '')
            if referer and '/login' not in referer and '/logout' not in referer and referer != request.build_absolute_uri():
                return redirect(referer)
            # ✅ CORRECTION : utiliser '/' au lieu d'une URL nommée inexistante
            return redirect('/')
        return _wrapped_view
    return decorator
