"""Tests de la commande de supervision `verifier_sante` (alertes santé)."""
import os
import tempfile
from io import StringIO
from pathlib import Path
from unittest import mock

from django.core import mail
from django.core.management import CommandError, call_command
from django.test import TestCase, override_settings

from core.models import ConfigurationNotification
from stock.management.commands import verifier_sante


def _etat(cooldown=0):
    """Pointe l'état de cooldown vers un fichier temporaire et nettoie."""
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.close()
    path = Path(tmp.name)
    patcher = mock.patch.object(verifier_sante, 'STATE_FILE', path)
    patcher.start()
    return path, patcher


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class VerifierSanteTest(TestCase):
    def setUp(self):
        config = ConfigurationNotification.get_instance()
        config.email_expediteur = 'nexus@chu.example'
        config.save()
        os.environ['ALERT_EMAILS'] = 'ops@chu.example'
        os.environ['ALERT_PHONES'] = ''
        self.path, self._patcher = _etat()
        self.addCleanup(self._patcher.stop)
        self.addCleanup(lambda: self.path.unlink(missing_ok=True))

    def _lancer(self, *args):
        """Lance la commande ; retourne (code, stdout, stderr).
        CommandError = panne (code 1), sinon le retour explicite de handle()."""
        out, err = StringIO(), StringIO()
        try:
            code = call_command('verifier_sante', *args, stdout=out, stderr=err)
        except CommandError:
            code = 1
        return code, out.getvalue(), err.getvalue()

    def test_sain_retourne_0_sans_alerte(self):
        code, out, _ = self._lancer()
        self.assertEqual(code, 0)
        self.assertIn("Santé OK", out)
        self.assertEqual(len(mail.outbox), 0)

    def test_panne_db_envoie_alerte_et_retourne_1(self):
        with mock.patch('core.health.check_database',
                        return_value=('error', 'connexion refusée')):
            code, out, _ = self._lancer()
        self.assertEqual(code, 1)
        self.assertIn("Base de données", out)
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn("ALERTE NexusERP", mail.outbox[0].subject)
        # L'état de cooldown a été écrit
        self.assertTrue(self.path.exists())

    def test_cooldown_empeche_le_spam(self):
        with mock.patch('core.health.check_database',
                        return_value=('error', 'connexion refusée')):
            self._lancer()
        self.assertEqual(len(mail.outbox), 1)
        # Relance immédiate : cooldown actif → pas de nouveau mail
        with mock.patch('core.health.check_database',
                        return_value=('error', 'connexion refusée')):
            code, out, _ = self._lancer()
        self.assertEqual(code, 1)
        self.assertIn("cooldown", out)
        self.assertEqual(len(mail.outbox), 1)

    def test_no_alert_diagnostic(self):
        with mock.patch('core.health.check_database',
                        return_value=('error', 'connexion refusée')):
            code, out, _ = self._lancer('--no-alert')
        self.assertEqual(code, 1)
        self.assertEqual(len(mail.outbox), 0)
        # Aucune alerte → l'état de cooldown n'est pas écrit (fichier vide)
        self.assertEqual(self.path.read_text(encoding='utf-8'), '')

    def test_degraded_alerte_sur_smtp_en_erreur(self):
        config = ConfigurationNotification.get_instance()
        config.activer_email = True
        config.smtp_host = 'smtp.invalide.test'
        config.smtp_port = 1
        config.save()
        with mock.patch('core.health.check_smtp', return_value=('error', 'timeout')):
            code, out, _ = self._lancer('--degraded')
        self.assertEqual(code, 1)
        self.assertIn("SMTP", out)
        self.assertEqual(len(mail.outbox), 1)

    def test_pas_de_destinataire_sans_alerte(self):
        os.environ['ALERT_EMAILS'] = ''
        with mock.patch('core.health.check_database',
                        return_value=('error', 'connexion refusée')):
            code, _, err = self._lancer()
        self.assertEqual(code, 1)
        self.assertIn("Aucun destinataire", err)
        self.assertEqual(len(mail.outbox), 0)
