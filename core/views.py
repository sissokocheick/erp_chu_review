from datetime import datetime, timezone

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import render

from core.health import run_checks
from core.supervision import lister_erreurs_logs, lister_sauvegardes


def health_check(request):
    """Endpoint /health/ pour la supervision (LB, systemd HealthCheck, uptime).

    - database : canal critique → 503 si KO.
    - smtp / sms : canaux optionnels (disabled/test/error) → dégradent le
      statut mais ne font jamais tomber le service en 503.
    Aucune donnée sensible n'est exposée (statut + détail tronqué).
    """
    status, checks = run_checks()
    payload = {
        'status': status,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'checks': checks,
    }
    return JsonResponse(payload, status=200 if checks['database']['status'] == 'ok' else 503)


@login_required(login_url='/auth/login/')
def supervision(request):
    """Tableau de bord de supervision — réservé au superutilisateur.

    Regroupe : l'état de santé (/health/), les sauvegardes PostgreSQL
    récentes et les erreurs de log des dernières heures.
    """
    if not request.user.is_superuser:
        return HttpResponseForbidden("⛔ Accès réservé à l'administrateur.")
    status, checks = run_checks()
    context = {
        'status': status,
        'checks': checks,
        'sauvegardes': lister_sauvegardes(limit=10),
        'erreurs_logs': lister_erreurs_logs(limit=50),
    }
    return render(request, 'core/supervision.html', context)
