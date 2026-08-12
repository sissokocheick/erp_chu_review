# -*- coding: utf-8 -*-
"""Tests du système de notifications : modèle, service (email/SMS), vues, config."""
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse

from accounts.models import Notification
from core.models import ConfigurationNotification
from stock.services import NotificationService
from stock.tests.factories import creer_magasin


class NotificationModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='dest', password='x', email='dest@chu.ci'
        )

    def test_creation_defauts(self):
        n = Notification.objects.create(
            utilisateur=self.user, titre='T', message='M'
        )
        self.assertEqual(n.categorie, 'SYSTEME')
        self.assertEqual(n.type_notif, 'INFO')
        self.assertFalse(n.est_lue)

    def test_marquer_lue(self):
        n = Notification.objects.create(
            utilisateur=self.user, titre='T', message='M'
        )
        n.marquer_lue()
        n.refresh_from_db()
        self.assertTrue(n.est_lue)
        self.assertIsNotNone(n.date_lecture)

    def test_marquer_toutes_lues(self):
        for _ in range(3):
            Notification.objects.create(utilisateur=self.user, titre='T', message='M')
        nb = Notification.marquer_toutes_lues(self.user)
        self.assertEqual(nb, 3)
        self.assertEqual(
            Notification.objects.filter(utilisateur=self.user, est_lue=False).count(), 0
        )

    def test_tout_effacer(self):
        for _ in range(2):
            Notification.objects.create(utilisateur=self.user, titre='T', message='M')
        other = User.objects.create_user(username='autre', password='x')
        Notification.objects.create(utilisateur=other, titre='T', message='M')
        Notification.tout_effacer(self.user)
        self.assertEqual(Notification.objects.filter(utilisateur=self.user).count(), 0)
        self.assertEqual(Notification.objects.filter(utilisateur=other).count(), 1)


class NotificationServiceTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='dest', password='x', email='dest@chu.ci'
        )
        self.profil = self.user.profil
        self.profil.contact = '0708091011'
        self.profil.save()
        self.config = ConfigurationNotification.get_instance()

    def test_creer_sans_canaux_active(self):
        n = NotificationService.creer(
            self.user, 'Titre', 'Message', url='/', type_notif='SUCCESS',
            categorie='DEMANDE',
        )
        self.assertIsNotNone(n)
        self.assertEqual(n.categorie, 'DEMANDE')
        self.assertEqual(Notification.objects.filter(utilisateur=self.user).count(), 1)

    def test_email_envoye_quand_canal_global_actif(self):
        self.config.activer_email = True
        self.config.email_expediteur = 'no-reply@chu.ci'
        self.config.smtp_host = 'smtp.test.local'
        self.config.save()

        with self.settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            n = NotificationService.creer(self.user, 'Titre', 'Message', url='/')
            self.assertIsNotNone(n)
            self.assertEqual(len(mail.outbox), 1)
            self.assertEqual(mail.outbox[0].to, ['dest@chu.ci'])
            self.assertIn('Titre', mail.outbox[0].subject)

    def test_diffusion_globale_sans_preference_utilisateur(self):
        """La config globale suffit : plus aucune préférence sur le Profil."""
        self.assertFalse(hasattr(self.profil, 'notif_email'))
        self.assertFalse(hasattr(self.profil, 'notif_sms'))
        self.config.activer_email = True
        self.config.email_expediteur = 'no-reply@chu.ci'
        self.config.save()
        with self.settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            NotificationService.creer(self.user, 'Titre', 'Message')
            self.assertEqual(len(mail.outbox), 1)

    def test_email_pas_envoye_sans_config(self):
        self.config.activer_email = False
        self.config.save()
        with self.settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            NotificationService.creer(self.user, 'Titre', 'Message')
            self.assertEqual(len(mail.outbox), 0)

    def test_email_sans_adresse_utilisateur(self):
        self.config.activer_email = True
        self.config.email_expediteur = 'no-reply@chu.ci'
        self.config.save()
        self.user.email = ''
        self.user.save()
        with self.settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            n = NotificationService.creer(self.user, 'Titre', 'Message')
            self.assertIsNotNone(n)  # la création ne doit jamais échouer
            self.assertEqual(len(mail.outbox), 0)

    def test_sms_test_mode_journalise(self):
        self.config.activer_sms = True
        self.config.sms_mode_test = True
        self.config.save()
        with self.assertLogs('stock.services', level='INFO') as logs:
            n = NotificationService.creer(self.user, 'Titre', 'Message', est_importante=True)
        self.assertIsNotNone(n)
        self.assertTrue(any('SMS·TEST' in l for l in logs.output))

    def test_sms_api_generique_appelee(self):
        self.config.activer_sms = True
        self.config.sms_mode_test = False
        self.config.sms_provider = 'GENERIQUE'
        self.config.sms_api_url = 'https://api.sms.test/send'
        self.config.sms_api_key = 'cle-secrete'
        self.config.sms_expediteur = 'CHU'
        self.config.save()

        with mock.patch('requests.post') as mock_post:
            mock_post.return_value.raise_for_status.return_value = None
            mock_post.return_value.ok = True
            n = NotificationService.creer(self.user, 'Titre', 'Message', est_importante=True)
            self.assertIsNotNone(n)
            mock_post.assert_called_once()
            args, kwargs = mock_post.call_args
            self.assertEqual(args[0], 'https://api.sms.test/send')
            self.assertEqual(kwargs['json']['to'], '+2250708091011')
            self.assertIn('Titre', kwargs['json']['message'])
            self.assertEqual(kwargs['headers']['Authorization'], 'Bearer cle-secrete')

    def test_sms_sans_telephone_ignore(self):
        self.config.activer_sms = True
        self.config.sms_mode_test = False
        self.config.sms_provider = 'GENERIQUE'
        self.config.sms_api_url = 'https://api.sms.test/send'
        self.config.save()
        self.profil.contact = ''
        self.profil.save()
        with mock.patch('requests.post') as mock_post:
            n = NotificationService.creer(self.user, 'Titre', 'Message', est_importante=True)
        self.assertIsNotNone(n)
        mock_post.assert_not_called()

    def test_telephone_normalise_e164(self):
        """Numéro ivoirien local → E.164 (+225) avant envoi (Twilio l'exige)."""
        from stock.services import _normaliser_telephone

        self.assertEqual(_normaliser_telephone('0708091011'), '+2250708091011')
        self.assertEqual(_normaliser_telephone(' 07 08 09 10 11 '), '+2250708091011')
        self.assertEqual(_normaliser_telephone('0173915282'), '+2250173915282')
        self.assertEqual(_normaliser_telephone('+2250708091011'), '+2250708091011')
        self.assertEqual(_normaliser_telephone('+15017122661'), '+15017122661')
        self.assertEqual(_normaliser_telephone(''), '')

    def test_sms_twilio_utilise_e164(self):
        """La branche Twilio reçoit un To au format E.164 (+225...)."""
        self.config.activer_sms = True
        self.config.sms_mode_test = False
        self.config.sms_provider = 'TWILIO'
        self.config.sms_api_key = 'ACsid123:tokensecret'
        self.config.sms_expediteur = '+15017122661'
        self.config.sms_api_url = ''
        self.config.save()

        with mock.patch('requests.post') as mock_post:
            mock_post.return_value.raise_for_status.return_value = None
            mock_post.return_value.ok = True
            n = NotificationService.creer(self.user, 'Titre', 'Message', est_importante=True)
            self.assertIsNotNone(n)
            mock_post.assert_called_once()
            args, kwargs = mock_post.call_args
            self.assertEqual(
                args[0],
                'https://api.twilio.com/2010-04-01/Accounts/ACsid123/Messages.json',
            )
            self.assertEqual(kwargs['auth'], ('ACsid123', 'tokensecret'))
            self.assertEqual(kwargs['data']['To'], '+2250708091011')
            self.assertEqual(kwargs['data']['From'], '+15017122661')
            self.assertIn('Titre', kwargs['data']['Body'])

    def test_sms_twilio_trial_utilise_modele_predefini(self):
        """En compte trial, le Body doit être un nom de modèle prédéfini Twilio
        (texte libre refusé — erreur 572006)."""
        self.config.activer_sms = True
        self.config.sms_mode_test = False
        self.config.sms_provider = 'TWILIO'
        self.config.sms_api_key = 'ACsid123:tokensecret'
        self.config.sms_expediteur = '+15017122661'
        self.config.sms_twilio_template = 'sms_appointment_reminders'
        self.config.save()

        with mock.patch('requests.post') as mock_post:
            mock_post.return_value.raise_for_status.return_value = None
            mock_post.return_value.ok = True
            n = NotificationService.creer(self.user, 'Rappel RDV', 'Message', est_importante=True)
            self.assertIsNotNone(n)
            args, kwargs = mock_post.call_args
            self.assertEqual(
                kwargs['data']['Body'], 'sms_appointment_reminders'
            )

    def test_email_bout_en_bout_html_rendu(self):
        """Email réellement envoyé (backend locmem) avec le VRAI template HTML."""
        self.config.activer_email = True
        self.config.email_expediteur = 'no-reply@chu.ci'
        self.config.smtp_host = ''  # pas de SMTP dédié → backend par défaut
        self.config.save()
        with self.settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            n = NotificationService.creer(
                self.user, 'Alerte Stock', 'Stock bas : 5 restants', url='/stock/'
            )
            self.assertIsNotNone(n)
            self.assertEqual(len(mail.outbox), 1)
            msg = mail.outbox[0]
            self.assertEqual(msg.to, ['dest@chu.ci'])
            self.assertIn('Alerte Stock', msg.subject)
            # La version HTML provient bien du template emails/notification_email.html
            html = next(
                (alt[0] for alt in msg.alternatives if alt[1] == 'text/html'), ''
            )
            self.assertIn('Alerte Stock', html)
            self.assertIn('Stock bas : 5 restants', html)
            self.assertIn('Voir le détail', html)
            self.assertIn('NexusERP', html)

    def test_sms_api_reelle_http(self):
        """Vraie requête HTTP vers un serveur local : payload + en-têtes vérifiés côté serveur.

        Aucun mock : le service appelle requests.post et un vrai socket reçoit
        la requête — c'est la preuve que le canal SMS-via-API fonctionne de bout en bout.
        """
        import json
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        received = {}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length)
                received['path'] = self.path
                received['auth'] = self.headers.get('Authorization')
                received['content_type'] = self.headers.get('Content-Type')
                received['json'] = json.loads(body)
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"status":"ok"}')

            def log_message(self, *args):
                pass

        server = HTTPServer(('127.0.0.1', 0), Handler)
        port = server.server_address[1]
        thread = threading.Thread(target=server.handle_request, daemon=True)
        thread.start()
        try:
            self.config.activer_sms = True
            self.config.sms_mode_test = False
            self.config.sms_provider = 'GENERIQUE'
            self.config.sms_api_url = f'http://127.0.0.1:{port}/send'
            self.config.sms_api_key = 'cle-reelle'
            self.config.sms_expediteur = 'CHU'
            self.config.sms_param_numero = 'to'
            self.config.sms_param_message = 'message'
            self.config.save()

            n = NotificationService.creer(
                self.user, 'Urgent', 'SMS de test reel', url='/', est_importante=True
            )
            self.assertIsNotNone(n)
            thread.join(timeout=10)

            self.assertEqual(received.get('path'), '/send')
            self.assertEqual(received.get('auth'), 'Bearer cle-reelle')
            self.assertIn('application/json', received.get('content_type', ''))
            payload = received.get('json', {})
            self.assertEqual(payload.get('to'), '+2250708091011')
            self.assertIn('SMS de test reel', payload.get('message', ''))
            self.assertEqual(payload.get('from'), 'CHU')
        finally:
            server.server_close()

    def test_creer_ne_leve_jamais(self):
        with mock.patch('accounts.models.Notification.objects.create',
                        side_effect=Exception('boom')):
            n = NotificationService.creer(self.user, 'Titre', 'Message')
        self.assertIsNone(n)


class NotificationViewsTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser(
            username='admin_notif', password='x', email='a@a.ci'
        )
        cls.user.profil.doit_changer_mdp = False
        cls.user.profil.save()
        creer_magasin(nom='Magasin Notif')

    def setUp(self):
        self.client.force_login(self.user)
        for i in range(5):
            Notification.objects.create(
                utilisateur=self.user, titre=f'Notif {i}', message=f'Msg {i}',
                type_notif='SUCCESS' if i % 2 else 'INFO',
                categorie='DEMANDE' if i % 2 else 'STOCK',
            )

    def test_liste_notifications(self):
        resp = self.client.get('/notifications/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Notif 0')
        self.assertContains(resp, '5 non lue')

    def test_filtre_categorie(self):
        resp = self.client.get('/notifications/?categorie=STOCK')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Notif 0')
        self.assertNotContains(resp, 'Notif 1')

    def test_filtre_type(self):
        resp = self.client.get('/notifications/?type=SUCCESS')
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'Notif 0')
        self.assertContains(resp, 'Notif 1')

    def test_filtre_recherche(self):
        resp = self.client.get('/notifications/?q=Notif%203')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Notif 3')
        self.assertNotContains(resp, 'Notif 0')

    def test_tout_marquer_lues_global(self):
        # Crée une 6e notification pour vérifier que TOUTES sont marquées (pas seulement la page)
        Notification.objects.create(utilisateur=self.user, titre='Hors page', message='X')
        resp = self.client.get('/notifications/?marquer_lues=1')
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(
            Notification.objects.filter(utilisateur=self.user, est_lue=False).count(), 0
        )

    def test_marquer_lue_ajax(self):
        n = Notification.objects.filter(utilisateur=self.user).first()
        resp = self.client.post(f'/notifications/{n.id}/lue/')
        self.assertEqual(resp.status_code, 200)
        n.refresh_from_db()
        self.assertTrue(n.est_lue)

    def test_supprimer_notification(self):
        n = Notification.objects.filter(utilisateur=self.user).first()
        resp = self.client.post(f'/notifications/{n.id}/supprimer/')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Notification.objects.filter(id=n.id).exists())

    def test_tout_effacer(self):
        resp = self.client.post('/notifications/tout-effacer/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(Notification.objects.filter(utilisateur=self.user).count(), 0)

    def test_supprimer_notification_autre_utilisateur_interdit(self):
        other = User.objects.create_user(username='autre', password='x')
        n = Notification.objects.create(utilisateur=other, titre='T', message='M')
        resp = self.client.post(f'/notifications/{n.id}/supprimer/')
        self.assertEqual(resp.status_code, 404)
        self.assertTrue(Notification.objects.filter(id=n.id).exists())

    def test_api_notifications(self):
        resp = self.client.get('/notifications/api/')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['count'], 5)
        self.assertEqual(data['total_non_lues'], 5)


class ConfigurationNotificationTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser(
            username='admin_cfg', password='x', email='a@a.ci'
        )
        cls.user.profil.doit_changer_mdp = False
        cls.user.profil.save()
        creer_magasin(nom='Magasin Cfg')

    def setUp(self):
        self.client.force_login(self.user)

    def test_page_config_rendue(self):
        resp = self.client.get(reverse('parametres_notifications'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Canal Email')
        self.assertContains(resp, 'Canal SMS')

    def test_sauvegarde_config(self):
        resp = self.client.post(reverse('parametres_notifications'), {
            'activer_email': 'on',
            'smtp_host': 'smtp.gmail.com',
            'smtp_port': '587',
            'smtp_user': 'noreply@chu.ci',
            'smtp_password': 'secret',
            'email_expediteur': 'noreply@chu.ci',
            'smtp_use_tls': 'on',
            'activer_sms': 'on',
            'sms_provider': 'GENERIQUE',
            'sms_api_url': 'https://api.sms.test/send',
            'sms_api_key': 'cle',
            'sms_expediteur': 'CHU',
            'sms_param_numero': 'to',
            'sms_param_message': 'message',
            'sms_mode_test': 'on',
        })
        self.assertEqual(resp.status_code, 302)
        cfg = ConfigurationNotification.get_instance()
        self.assertTrue(cfg.activer_email)
        self.assertEqual(cfg.smtp_host, 'smtp.gmail.com')
        self.assertTrue(cfg.activer_sms)
        self.assertEqual(cfg.sms_provider, 'GENERIQUE')
        self.assertEqual(cfg.sms_api_url, 'https://api.sms.test/send')
