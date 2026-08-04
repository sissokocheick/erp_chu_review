from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction

from accounts.permissions import verifier_permission
from ...services.parametre_service import safe_delete_entity
from ...models import MotifAnnulation

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_motifs_annulation')
@transaction.atomic
def parametres_motifs(request):
    motifs = MotifAnnulation.objects.all().order_by('libelle')

    if request.method == 'POST':
        action = request.POST.get('action', '').strip()

        if action == 'ajouter':
            libelle = request.POST.get('libelle', '').strip()
            libelle = ' '.join(libelle.split())  # Nettoyage des espaces multiples

            if not libelle:
                messages.error(request, "❌ Le libellé est obligatoire.")
            elif len(libelle) > 255:
                messages.error(request, "❌ Le libellé ne doit pas dépasser 255 caractères.")
            elif MotifAnnulation.objects.filter(libelle__iexact=libelle).exists():
                messages.error(request, f"⚠️ Le motif '{libelle}' existe déjà.")
            else:
                MotifAnnulation.objects.create(
                    libelle=libelle,
                    cree_par=request.user, modifie_par=request.user
                )
                messages.success(request, "✅ Nouveau motif d'annulation ajouté.")

        elif action == 'supprimer':
            motif_id = request.POST.get('motif_id', '').strip()
            if not motif_id:
                messages.error(request, "❌ Identifiant du motif manquant.")
                return redirect('parametres_motifs')

            try:
                motif_id = int(motif_id)
            except (ValueError, TypeError):
                messages.error(request, "❌ Identifiant du motif invalide.")
                return redirect('parametres_motifs')

            motif = get_object_or_404(
                MotifAnnulation,
                id=motif_id
            )

            if motif.bonmouvement_set.exists():
                motif.actif = False
                motif.modifie_par = request.user
                motif.save()
                messages.warning(
                    request,
                    "Le motif est utilisé dans l'historique : il a été désactivé."
                )
            else:
                safe_delete_entity(motif, request.user)
                messages.success(request, "Motif supprimé définitivement.")

        return redirect('parametres_motifs')

    return render(request, 'stock/parametres_motifs.html', {'motifs': motifs})
