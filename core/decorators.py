# core/decorators.py — CORRIGÉ (v2)
"""
Décorateurs de sécurité pour l'architecture multi-tenant.
"""
from functools import wraps
from django.contrib import messages
from django.shortcuts import redirect, render
from django.contrib.auth.decorators import login_required
from django.urls import reverse
from django.http import HttpResponseForbidden
from django.template.loader import render_to_string
from core.managers import set_current_tenant


def tenant_required(view_func):
    """
    Décorateur qui vérifie la présence d'une entreprise active.
    Pousse automatiquement le contexte tenant pour le TenantManager.

    Usage:
        @tenant_required
        def ma_vue(request):
            ...
    """
    @login_required
    @wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not hasattr(request, 'entreprise') or not request.entreprise:
            # ✅ CORRECTION P0 (v2): Rendre un template 403 au lieu de texte brut
            # pour une meilleure UX avec le branding de l'ERP
            html_content = render_to_string('core/403_tenant.html', {
                'message': (
                    "⛔ Aucune entreprise active. "
                    "Votre compte n'est rattaché à aucune entreprise ou celle-ci est désactivée. "
                    "Contactez l'administrateur."
                ),
                'request': request,
            })
            return HttpResponseForbidden(html_content)

        # Pousse le contexte tenant pour le TenantManager
        token = set_current_tenant(request.entreprise)
        try:
            return view_func(request, *args, **kwargs)
        finally:
            # Restauration propre du contexte
            from core.managers import _tenant_context
            _tenant_context.reset(token)
    return wrapper
