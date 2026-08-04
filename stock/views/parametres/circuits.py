from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction

from accounts.permissions import verifier_permission
from ...services.parametre_service import update_circuit
from ...models import CircuitValidation

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_circuits_validation')
def page_circuits_validation(request):
    # Initialisation des circuits (idéalement dans une migration ou signal)
    for code, nom in CircuitValidation.TYPE_DOC_CHOICES:
        CircuitValidation.objects.get_or_create(
            type_document=code,
            defaults={'est_actif': False}
        )

    if request.method == 'POST':
        circuit_id = request.POST.get('circuit_id', '').strip()
        est_actif = request.POST.get('est_actif', '') == 'on'
        valideurs_ids = request.POST.getlist('valideurs')

        # Validation du circuit_id
        if not circuit_id:
            messages.error(request, "❌ Identifiant du circuit manquant.")
            return redirect('page_circuits_validation')

        try:
            circuit_id = int(circuit_id)
        except (ValueError, TypeError):
            messages.error(request, "❌ Identifiant du circuit invalide.")
            return redirect('page_circuits_validation')

        # Vérifier que le circuit appartient à l'entreprise
        circuit = get_object_or_404(
            CircuitValidation,
            id=circuit_id
        )

        with transaction.atomic():
            circuit = update_circuit(circuit_id, est_actif, valideurs_ids)

        messages.success(
            request,
            f"✅ Le circuit '{circuit.get_type_document_display()}' a été mis à jour."
        )
        return redirect('page_circuits_validation')

    circuits = CircuitValidation.objects.all().order_by('type_document')

    utilisateurs = CircuitValidation.valideurs.field.related_model.objects.filter(
        is_active=True).order_by('first_name', 'last_name')

    return render(
        request,
        'stock/circuits_validation.html',
        {'circuits': circuits, 'utilisateurs': utilisateurs}
    )
