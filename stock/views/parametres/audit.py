from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required

from accounts.permissions import verifier_permission
from ...services.parametre_service import get_audit_data


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_journal_audit')
def journal_audit_securite(request):
    entreprise = request.entreprise
    if not entreprise:
        messages.error(request, "❌ Aucune entreprise associée à votre compte.")
        return redirect('dashboard_directeur')

    context = get_audit_data(request)
    return render(request, 'stock/journal_audit_securite.html', context)
