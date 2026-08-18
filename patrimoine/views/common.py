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

        # Liste des permissions patrimoine existantes dans MenuAccess

        perms_pat = [

            'accounts.menu_pat_tickets', 'accounts.menu_pat_tech', 'accounts.menu_pat_dispatch',

            'accounts.menu_pat_historique', 'accounts.menu_pat_registre', 'accounts.menu_pat_sas',

            'accounts.menu_pat_contrats', 'accounts.menu_pat_import', 'accounts.menu_pat_inventaire',

            'accounts.menu_pat_rebuts', 'accounts.menu_pat_pertes', 'accounts.menu_pat_parametres'

        ]

        has_any = any(request.user.has_perm(p) for p in perms_pat)

        if not (request.user.is_staff or request.user.is_superuser or has_any):

            messages.error(request, "⛔ Accès non autorisé au module Patrimoine.")

            return redirect('/')

        return view_func(request, *args, **kwargs)

    return wrapper
