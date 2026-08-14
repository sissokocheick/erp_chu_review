import socket
from datetime import datetime, timezone
from urllib.parse import urlparse

from django.db import connection
from django.http import JsonResponse


def _check_database():
    """La base est le canal critique : le service n'est pas sain sans elle."""
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
        return 'ok', None
    except Exception as exc:  # noqa: BLE001 — on remonte TOUT (le détail va dans le log)
        return 'error', str(exc)[:300]


def _check_smtp(config):
    if not getattr(config, 'activer_email', False) or not config.smtp_host:
        return 'disabled', None
    try:
        with socket.create_connection((config.smtp_host, config.smtp_port or 587), timeout=5):
            pass
        return 'ok', None
    except Exception as exc:  # noqa: BLE001
        return 'error', str(exc)[:300]


def _check_sms(config):
    if not getattr(config, 'activer_sms', False):
        return 'disabled', None
    if getattr(config, 'sms_mode_test', True):
        return 'test', None  # mode test : rien n'est réellement envoyé (journal)
    if not (config.sms_api_url and config.sms_api_key):
        return 'error', 'Configuration SMS incomplète (URL et/ou clé manquantes).'
    try:
        parsed = urlparse(config.sms_api_url)
        host = parsed.hostname
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        with socket.create_connection((host, port), timeout=5):
            pass
        return 'ok', None
    except Exception as exc:  # noqa: BLE001
        return 'error', str(exc)[:300]


def health_check(request):
    """Endpoint /health/ pour la supervision (LB, systemd, uptime checkers).

    - database : canal critique → 503 si KO.
    - smtp / sms : canaux optionnels (activés/disabled/test) → dégradent le
      statut mais ne font jamais tomber le service en 503.
    Aucune donnée sensible n'est exposée (juste le statut + un détail tronqué).
    """
    from core.models import ConfigurationNotification

    try:
        config = ConfigurationNotification.get_instance()
    except Exception:  # noqa: BLE001 — config indisponible ≠ base KO
        config = None

    db_status, db_detail = _check_database()

    smtp_status = smtp_detail = None
    sms_status = sms_detail = None
    if config is not None:
        smtp_status, smtp_detail = _check_smtp(config)
        sms_status, sms_detail = _check_sms(config)

    checks = {
        'database': {'status': db_status, 'detail': db_detail},
        'smtp': {'status': smtp_status, 'detail': smtp_detail},
        'sms': {'status': sms_status, 'detail': sms_detail},
    }
    degraded = db_status == 'ok' and (
        smtp_status == 'error' or sms_status == 'error'
    )
    status = 'error' if db_status != 'ok' else ('degraded' if degraded else 'ok')

    payload = {
        'status': status,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'checks': checks,
    }
    return JsonResponse(payload, status=200 if db_status == 'ok' else 503)
