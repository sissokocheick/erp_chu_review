# -*- coding: utf-8 -*-
"""
Commande de supervision : vérifie la santé de l'app et ALERTE l'équipe
(email + SMS) en cas de panne.

Usage :
    python manage.py verifier_sante                     # vérifie + alerte si panne
    python manage.py verifier_sante --degraded          # alerte aussi si SMTP/SMS en erreur
    python manage.py verifier_sante --no-alert          # diagnostic, sans envoyer
    python manage.py verifier_sante --cooldown 3600     # une alerte max par heure
    python manage.py verifier_sante --quiet             # sortie minimale (cron)

Destinataires (variables d'environnement, voir .env.example) :
    ALERT_EMAILS=tel1@chu.example,tel2@chu.example
    ALERT_PHONES=+2250700000000

Cooldown : une alerte toutes les 15 min par défaut (état dans logs/.last-alert)
pour éviter le spam. Code de sortie : 0 = sain, 1 = dégradé/panne.
"""
import os
import time
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from core.health import run_checks
from core.models import ConfigurationNotification
from stock.services import NotificationService

BASE_DIR = Path(__file__).resolve().parent.parent.parent.parent
STATE_FILE = BASE_DIR / 'logs' / '.last-alert'


class Command(BaseCommand):
    help = "Vérifie la santé de l'application et alerte l'équipe en cas de panne."

    def add_arguments(self, parser):
        parser.add_argument('--degraded', action='store_true',
                            help="Alerter aussi quand SMTP ou SMS est en erreur.")
        parser.add_argument('--cooldown', type=int, default=900,
                            help="Secondes minimales entre deux alertes (défaut 900).")
        parser.add_argument('--no-alert', action='store_true',
                            help="Diagnostic uniquement : ne pas envoyer d'alerte.")
        parser.add_argument('--quiet', action='store_true',
                            help="Sortie minimale (réservée au cron).")

    # ── Cooldown ────────────────────────────────────────────────────────────
    def _cooldown_actif(self, cooldown):
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            dernier = float(STATE_FILE.read_text(encoding='utf-8').strip())
        except (OSError, ValueError):
            return False
        return (time.time() - dernier) < cooldown

    def _marquer_alerte(self):
        try:
            STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            STATE_FILE.write_text(str(time.time()), encoding='utf-8')
        except OSError:
            pass

    # ── Envoi de l'alerte ───────────────────────────────────────────────────
    def _envoyer_alerte(self, problemes):
        emails = [e.strip() for e in os.environ.get('ALERT_EMAILS', '').split(',') if e.strip()]
        telephones = [t.strip() for t in os.environ.get('ALERT_PHONES', '').split(',') if t.strip()]
        if not emails and not telephones:
            self.stderr.write(
                "Aucun destinataire ALERT_EMAILS/ALERT_PHONES configuré — alerte non envoyée."
            )
            return False

        sujet = "⚠️ ALERTE NexusERP — problème de disponibilité"
        corps = ("NexusERP signale un problème de disponibilité :\n\n- "
                 + "\n- ".join(problemes)
                 + "\n\nVérifier : journalctl -u nexuserp -f  |  "
                   "python manage.py verifier_sante --no-alert")
        html = "<h3>⚠️ Alerte NexusERP</h3><ul>" + "".join(
            f"<li>{p}</li>" for p in problemes
        ) + f"</ul><p><code>{corps.splitlines()[-1]}</code></p>"

        envoyes = []
        config = ConfigurationNotification.get_instance()
        for adresse in emails:
            if NotificationService.envoyer_email_direct(adresse, sujet, html, corps):
                envoyes.append(f"email:{adresse}")
        for tel in telephones:
            if NotificationService.envoyer_sms_direct(tel, corps):
                envoyes.append(f"sms:{tel}")

        if envoyes:
            self._marquer_alerte()
            self.stdout.write("Alerte envoyée : " + ", ".join(envoyes))
            return True
        self.stderr.write("Aucune alerte envoyée (canaux non configurés ou échec).")
        return False

    # ── Exécution ───────────────────────────────────────────────────────────
    def handle(self, *args, **options):
        degraded = options['degraded']
        cooldown = options['cooldown']
        no_alert = options['no_alert']
        quiet = options['quiet']

        status, checks = run_checks()

        problemes = []
        db = checks['database']
        if db['status'] != 'ok':
            problemes.append(f"Base de données : {db['detail'] or 'KO'}")
        if degraded:
            for nom in ('smtp', 'sms'):
                c = checks[nom]
                if c['status'] == 'error':
                    problemes.append(f"{nom.upper()} : {c['detail']}")

        if not problemes:
            if not quiet:
                self.stdout.write(self.style.SUCCESS(
                    f"Santé OK (base {db['status']}, smtp {checks['smtp']['status']}, "
                    f"sms {checks['sms']['status']})"))
            return 0

        # Échec : on imprime les problèmes puis on sort en erreur (exit 1).
        # CommandError est le mécanisme idiomatique de code de sortie en Django.
        for p in problemes:
            self.stdout.write(self.style.ERROR(p))

        if no_alert:
            raise CommandError("Problème de santé détecté (mode diagnostic, pas d'alerte).")

        if self._cooldown_actif(cooldown):
            if not quiet:
                self.stdout.write("Alerte déjà envoyée récemment — ignorée (cooldown).")
            raise CommandError("Problème de santé détecté (alerte déjà envoyée récemment).")

        self._envoyer_alerte(problemes)
        raise CommandError("Problème de santé détecté — alerte envoyée.")
