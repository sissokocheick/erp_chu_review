# -*- coding: utf-8 -*-
from django.db import transaction
# accounts/views_fonctions.py
"""
Gestion des Fonctions (titres professionnels).
Utilisé pour l'affichage sous les signatures PDF.
Version mono-tenant.
"""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from .permissions import verifier_permission
from .models import Fonction
from .forms import FonctionForm
@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_fonctions')
@require_http_methods(["POST"])
def api_creer_fonction(request):
    """Crée une fonction via AJAX et retourne JSON {id, nom}."""
    nom = request.POST.get('nom', '').strip().title()
    description = request.POST.get('description', '').strip()
    if not nom:
        return JsonResponse({'success': False, 'error': "Le nom est obligatoire."}, status=400)
    if Fonction.objects.filter(nom__iexact=nom).exists():
        return JsonResponse({'success': False, 'error': "Cette fonction existe déjà."}, status=400)
    fonction = Fonction.objects.create(
        nom=nom,
        description=description,
        cree_par=request.user
    )
    return JsonResponse({
        'success': True,
        'id': fonction.id,
        'nom': fonction.nom,
    })
@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_fonctions')
def api_liste_fonctions(request):
    """Retourne la liste des fonctions en JSON."""
    fonctions = Fonction.objects.values('id', 'nom').order_by('nom')
    return JsonResponse({'fonctions': list(fonctions)})