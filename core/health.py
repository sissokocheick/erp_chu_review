"""Checks de santé partagés — utilisés par le endpoint /health/ (core/views.py)
et par la commande de supervision `manage.py verifier_sante` (alertes).

Chaque check retourne (status, detail) :
- status : 'ok' | 'error' | 'disabled' | 'test'
- detail : message tronqué (aucune donnée sensible), ou None.
"""
import socket
from urllib.parse import urlparse

from django.db import connection


def check_database():
    """La base est le canal critique : le service n'est pas sain sans elle."""
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
            cursor.fetchone()
        return 'ok', None
    except Exception as exc:  # noqa: BLE001 — on remonte TOUT (détail dans le log)
        return 'error', str(exc)[:300]


def check_smtp(config):
    if not getattr(config, 'activer_email', False) or not config.smtp_host:
        return 'disabled', None
    try:
        with socket.create_connection((config.smtp_host, config.smtp_port or 587), timeout=5):
            pass
        return 'ok', None
    except Exception as exc:  # noqa: BLE001
        return 'error', str(exc)[:300]


def check_sms(config):
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


def run_checks(config=None):
    """Tous les checks dans un dict prêt à sérialiser (endpoint + commande)."""
    from core.models import ConfigurationNotification
    if config is None:
        try:
            config = ConfigurationNotification.get_instance()
        except Exception:  # noqa: BLE001 — config indisponible ≠ base KO
            config = None

    db_status, db_detail = check_database()
    checks = {
        'database': {'status': db_status, 'detail': db_detail},
        'smtp': {'status': 'disabled', 'detail': None},
        'sms': {'status': 'disabled', 'detail': None},
    }
    if config is not None:
        smtp_status, smtp_detail = check_smtp(config)
        sms_status, sms_detail = check_sms(config)
        checks['smtp'] = {'status': smtp_status, 'detail': smtp_detail}
        checks['sms'] = {'status': sms_status, 'detail': sms_detail}

    degraded = db_status == 'ok' and (
        checks['smtp']['status'] == 'error' or checks['sms']['status'] == 'error'
    )
    status = 'error' if db_status != 'ok' else ('degraded' if degraded else 'ok')
    return status, checks
