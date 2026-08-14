import json
from unittest import mock

from django.test import TestCase
from django.urls import reverse

from core.models import ConfigurationNotification


class HealthCheckTest(TestCase):
    def test_retourne_200_json_ok(self):
        resp = self.client.get(reverse('health_check'))
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertEqual(data['status'], 'ok')
        self.assertEqual(data['checks']['database']['status'], 'ok')
        # Canaux non configurés par défaut
        self.assertEqual(data['checks']['smtp']['status'], 'disabled')
        self.assertEqual(data['checks']['sms']['status'], 'disabled')
        self.assertIn('timestamp', data)

    def test_base_inaccessible_retourne_503(self):
        with mock.patch('core.views.connection.cursor',
                        side_effect=Exception('connexion refusée')):
            resp = self.client.get(reverse('health_check'))
        self.assertEqual(resp.status_code, 503)
        data = json.loads(resp.content)
        self.assertEqual(data['status'], 'error')
        self.assertEqual(data['checks']['database']['status'], 'error')

    def test_smtp_configuré_mais_injoignable_degrade_sans_503(self):
        config = ConfigurationNotification.get_instance()
        config.activer_email = True
        config.smtp_host = 'smtp.invalide.test'
        config.smtp_port = 1
        config.save()
        with mock.patch('core.views.socket.create_connection',
                        side_effect=OSError('timeout')):
            resp = self.client.get(reverse('health_check'))
        self.assertEqual(resp.status_code, 200)  # la base va bien
        data = json.loads(resp.content)
        self.assertEqual(data['status'], 'degraded')
        self.assertEqual(data['checks']['smtp']['status'], 'error')

    def test_sms_mode_test_signalé(self):
        config = ConfigurationNotification.get_instance()
        config.activer_sms = True
        config.sms_mode_test = True
        config.save()
        resp = self.client.get(reverse('health_check'))
        self.assertEqual(resp.status_code, 200)
        data = json.loads(resp.content)
        self.assertEqual(data['checks']['sms']['status'], 'test')

    def test_sms_incomplet_signalé_erreur(self):
        config = ConfigurationNotification.get_instance()
        config.activer_sms = True
        config.sms_mode_test = False
        config.sms_api_url = ''
        config.sms_api_key = ''
        config.save()
        resp = self.client.get(reverse('health_check'))
        data = json.loads(resp.content)
        self.assertEqual(data['checks']['sms']['status'], 'error')
        self.assertEqual(data['status'], 'degraded')
