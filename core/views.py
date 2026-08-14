from datetime import datetime, timezone

from django.http import JsonResponse

from core.health import run_checks


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
