from datetime import datetime, timezone

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import render

from core.health import run_checks
from core.supervision import (
    _taille_lisible,
    lister_erreurs_logs,
    lister_requetes_lentes,
    lister_sauvegardes,
    taille_base,
    usage_disque,
)


def health_check(request):
    """Endpoint /health/ pour la supervision (LB, systemd HealthCheck, uptime).

    - database : canal critique → 503 si KO.
    - smtp / sms : canaux optionnels (disabled/test/error) → dégradent le
      statut mais ne font jamais tomber le service en 503.
    Anonyme : les détails d'erreur (hôte/port/SQL) restent côté serveur —
    seuls les statuts sont exposés publiquement.
    """
    import logging

    status, checks = run_checks()

    # Journaliser le détail côté serveur, ne PAS l'exposer anonymement
    # (les exceptions DB contiennent hôte, port, base et utilisateur).
    logger = logging.getLogger('core.health')
    for nom, check in checks.items():
        if check.get('status') == 'error' and check.get('detail'):
            logger.error("[health] %s KO : %s", nom, check['detail'])
            check['detail'] = 'unavailable'

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
    octets_base = taille_base()
    disque = usage_disque()
    pct = disque['pourcentage'] if disque else 0
    disque_statut = 'green' if pct < 70 else ('orange' if pct < 90 else 'red')
    context = {
        'status': status,
        'checks': checks,
        'sauvegardes': lister_sauvegardes(limit=10),
        'erreurs_logs': lister_erreurs_logs(limit=50),
        'taille_base_octets': octets_base,
        'taille_base_lisible': _taille_lisible(octets_base) if octets_base else '—',
        'disque': disque,
        'disque_statut': disque_statut,
        'requetes_lentes': lister_requetes_lentes(limit=20),
    }
    return render(request, 'core/supervision.html', context)
