# accounts/views_fonctions.py
"""
Gestion des Fonctions (titres professionnels par entreprise).
Utilisé pour l'affichage sous les signatures PDF.
"""

import json
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from .permissions import verifier_permission
from .models import Fonction
from .forms import FonctionForm


@login_required(login_url='/accounts/login/')
@verifier_permission('accounts.menu_fonctions')
def page_fonctions(request):
    """Page de gestion des fonctions (CRUD)."""
    entreprise = request.entreprise
    fonctions = entreprise.fonctions.all()

    if request.method == 'POST':
        form = FonctionForm(request.POST, entreprise=entreprise)
        if form.is_valid():
            fonction = form.save(commit=False)
            fonction.entreprise = entreprise
            fonction.cree_par = request.user
            fonction.save()
            messages.success(request, f"✅ Fonction « {fonction.nom} » créée avec succès.")
            return redirect('page_fonctions')
        else:
            messages.error(request, "❌ Erreur lors de la création de la fonction.")
    else:
        form = FonctionForm(entreprise=entreprise)

    return render(request, 'accounts/fonctions.html', {
        'form': form,
        'fonctions': fonctions,
        'entreprise': entreprise,
    })


@login_required(login_url='/accounts/login/')
@verifier_permission('accounts.menu_fonctions')
def modifier_fonction(request, fonction_id):
    """Modification d'une fonction existante."""
    entreprise = request.entreprise
    fonction = get_object_or_404(Fonction, id=fonction_id, entreprise=entreprise)

    if request.method == 'POST':
        form = FonctionForm(request.POST, instance=fonction, entreprise=entreprise)
        if form.is_valid():
            form.save()
            messages.success(request, f"✅ Fonction « {fonction.nom} » modifiée.")
            return redirect('page_fonctions')
    else:
        form = FonctionForm(instance=fonction, entreprise=entreprise)

    return render(request, 'accounts/fonctions.html', {
        'form': form,
        'fonction_edit': fonction,
        'fonctions': entreprise.fonctions.all(),
        'entreprise': entreprise,
    })


@login_required(login_url='/accounts/login/')
@verifier_permission('accounts.menu_fonctions')
def supprimer_fonction(request, fonction_id):
    """Suppression d'une fonction (si non utilisée)."""
    entreprise = request.entreprise
    fonction = get_object_or_404(Fonction, id=fonction_id, entreprise=entreprise)

    if fonction.utilisateurs_fonction.exists():
        messages.error(request, f"❌ Impossible de supprimer « {fonction.nom} » : elle est assignée à {fonction.utilisateurs_fonction.count()} utilisateur(s).")
    else:
        nom = fonction.nom
        fonction.delete()
        messages.success(request, f"✅ Fonction « {nom} » supprimée.")

    return redirect('page_fonctions')


# ═══════════════════════════════════════════════════════════════
# API AJAX — Création rapide depuis le formulaire utilisateur
# ═══════════════════════════════════════════════════════════════

@login_required(login_url='/accounts/login/')
@verifier_permission('accounts.menu_fonctions')
@require_http_methods(["POST"])
def api_creer_fonction(request):
    """Crée une fonction via AJAX et retourne JSON {id, nom} pour mise à jour du <select>."""
    # ── VÉRIFICATION ENTREPRISE ACTIVE ──
    entreprise = request.entreprise
    if not entreprise or not entreprise.est_active:
        return JsonResponse({'success': False, 'error': "Aucune entreprise active associée."}, status=403)

    nom = request.POST.get('nom', '').strip()
    description = request.POST.get('description', '').strip()

    if not nom:
        return JsonResponse({'success': False, 'error': "Le nom est obligatoire."}, status=400)

    if Fonction.objects.filter(entreprise=entreprise, nom__iexact=nom).exists():
        return JsonResponse({'success': False, 'error': "Cette fonction existe déjà."}, status=400)

    fonction = Fonction.objects.create(
        entreprise=entreprise,
        nom=nom,
        description=description,
        cree_par=request.user
    )

    return JsonResponse({
        'success': True,
        'id': fonction.id,
        'nom': fonction.nom,
    })


@login_required(login_url='/accounts/login/')
@verifier_permission('accounts.menu_fonctions')
def api_liste_fonctions(request):
    """Retourne la liste des fonctions de l'entreprise en JSON (pour select2 ou datalist)."""
    entreprise = request.entreprise
    if not entreprise or not entreprise.est_active:
        return JsonResponse({'fonctions': []})

    fonctions = entreprise.fonctions.values('id', 'nom').order_by('nom')
    return JsonResponse({'fonctions': list(fonctions)})
