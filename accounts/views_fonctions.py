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
def page_fonctions(request):
    """Page de gestion des fonctions (CRUD)."""
    fonctions = Fonction.objects.all().order_by('nom')

    if request.method == 'POST':
        form = FonctionForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                fonction = form.save(commit=False)
                fonction.cree_par = request.user
                fonction.save()
            messages.success(request, f"✅ Fonction « {fonction.nom} » créée avec succès.")
            return redirect('accounts:page_fonctions')
        else:
            messages.error(request, "❌ Erreur lors de la création de la fonction.")
    else:
        form = FonctionForm()

    return render(request, 'accounts/fonctions.html', {
        'form': form,
        'fonctions': fonctions,
    })


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_fonctions')
def modifier_fonction(request, fonction_id):
    """Modification d'une fonction existante."""
    fonction = get_object_or_404(Fonction, id=fonction_id)

    if request.method == 'POST':
        form = FonctionForm(request.POST, instance=fonction)
        if form.is_valid():
            form.save()
            messages.success(request, f"✅ Fonction « {fonction.nom} » modifiée.")
            return redirect('accounts:page_fonctions')
    else:
        form = FonctionForm(instance=fonction)

    return render(request, 'accounts/fonctions.html', {
        'form': form,
        'fonction_edit': fonction,
        'fonctions': Fonction.objects.all().order_by('nom'),
    })


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_fonctions')
def supprimer_fonction(request, fonction_id):
    """Suppression d'une fonction (si non utilisée)."""
    fonction = get_object_or_404(Fonction, id=fonction_id)

    if fonction.utilisateurs_fonction.exists():
        messages.error(
            request,
            f"❌ Impossible de supprimer « {fonction.nom} » : "
            f"elle est assignée à {fonction.utilisateurs_fonction.count()} utilisateur(s)."
        )
    else:
        nom = fonction.nom
        fonction.delete()
        messages.success(request, f"✅ Fonction « {nom} » supprimée.")

    return redirect('accounts:page_fonctions')


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