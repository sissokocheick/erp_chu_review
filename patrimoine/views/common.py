# -*- coding: utf-8 -*-
"""Commun : imports partages et decorateur patrimoine_required."""
import logging
from functools import wraps

from django.shortcuts import redirect
from django.contrib import messages

logger = logging.getLogger(__name__)


def patrimoine_required(view_func):

    """Vérifie que l'utilisateur a au moins une permission Patrimoine."""

    from functools import wraps

    @wraps(view_func)

    def wrapper(request, *args, **kwargs):

        if not request.user.is_authenticated:

            return redirect('/auth/login/')

        # Toutes les permissions patrimoine, y compris les sous-pages
        # véhicules, salles, tickets et demandes, sont attribuables depuis
        # la page Rôles. On les détecte par préfixe pour ne jamais oublier
        # une permission ajoutée ultérieurement.
        has_any = any(
            permission.startswith('accounts.menu_pat_')
            for permission in request.user.get_all_permissions()
        )

        if not (request.user.is_superuser or has_any):

            messages.error(request, "⛔ Accès non autorisé au module Patrimoine.")

            return redirect('/')

        return view_func(request, *args, **kwargs)

    return wrapper
