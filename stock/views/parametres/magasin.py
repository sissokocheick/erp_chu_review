from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction

from accounts.permissions import verifier_permission
from ...forms import MagasinParametresForm
from ...models import Magasin


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_magasins')
@transaction.atomic
def parametres_magasin(request, magasin_id):
    entreprise = request.entreprise
    if not entreprise:
        messages.error(request, "❌ Aucune entreprise associée à votre compte.")
        return redirect('dashboard_directeur')

    magasin = get_object_or_404(Magasin, id=magasin_id, entreprise=entreprise)

    if request.method == 'POST':
        form = MagasinParametresForm(request.POST, instance=magasin, entreprise=entreprise)
        if form.is_valid():
            form.save()
            messages.success(
                request,
                f"✅ Les paramètres du magasin '{magasin.nom}' ont été mis à jour."
            )
            return redirect('parametres_magasin', magasin_id=magasin.id)
        else:
            messages.error(request, "❌ Veuillez corriger les erreurs dans le formulaire.")
    else:
        form = MagasinParametresForm(instance=magasin, entreprise=entreprise)

    return render(request, 'stock/parametres_magasin.html', {'form': form, 'magasin': magasin})
