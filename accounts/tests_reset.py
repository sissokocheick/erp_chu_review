# -*- coding: utf-8 -*-
"""Tests du flux « Mot de passe oublié », de la désactivation de la réinitialisation
admin (quand un canal email/SMS est configuré) et du SMS réservé aux notifications
importantes."""
from datetime import timedelta
from unittest import mock

from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import MotDePasseResetToken, Notification
from core.models import ConfigurationNotification
from stock.services import NotificationService


def configurer_email():
    """Canal email complet et livrable (SMTP renseigné)."""
    cfg = ConfigurationNotification.get_instance()
    cfg.activer_email = True
    cfg.email_expediteur = 'no-reply@chu.ci'
    cfg.smtp_host = 'smtp.gmail.com'
    cfg.smtp_user = 'no-reply@chu.ci'
    cfg.smtp_password = 'mot-de-passe-app'
    cfg.save()
    return cfg


def configurer_email_incomplete():
    """Email activé mais SMTP incomplet → canal non livrable."""
    cfg = ConfigurationNotification.get_instance()
    cfg.activer_email = True
    cfg.email_expediteur = 'no-reply@chu.ci'
    cfg.smtp_host = ''
    cfg.smtp_user = ''
    cfg.smtp_password = ''
    cfg.save()
    return cfg


def configurer_sms():
    """Canal SMS complet (mode test) — livrable du point de vue de la config."""
    cfg = ConfigurationNotification.get_instance()
    cfg.activer_sms = True
    cfg.sms_mode_test = True
    cfg.sms_provider = 'TEST'
    cfg.sms_expediteur = 'NEXUS'
    cfg.sms_api_url = 'https://api.example.com/sms'
    cfg.sms_api_key = 'cle-test'
    cfg.save()
    return cfg


class MotDePasseOublieTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='jean', password='Ancien1!', email='jean@chu.ci'
        )
        self.user.profil.contact = '0708091011'
        self.user.profil.doit_changer_mdp = False
        self.user.profil.save()

    def test_lien_cache_sans_canal_configure(self):
        resp = self.client.get(reverse('accounts:custom_login'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'mot-de-passe-oublie')

    def test_lien_affiche_avec_email(self):
        configurer_email()
        resp = self.client.get(reverse('accounts:custom_login'))
        self.assertContains(resp, 'mot-de-passe-oublie')

    def test_lien_affiche_avec_sms(self):
        configurer_sms()
        resp = self.client.get(reverse('accounts:custom_login'))
        self.assertContains(resp, 'mot-de-passe-oublie')

    def test_lien_cache_si_email_actif_mais_smtp_incomplet(self):
        """Un canal activé mais non livrable ne doit pas être proposé."""
        configurer_email_incomplete()
        resp = self.client.get(reverse('accounts:custom_login'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'mot-de-passe-oublie')
        # La page « oublié » renvoie vers le login avec un message
        resp2 = self.client.get(reverse('accounts:mot_de_passe_oublie'))
        self.assertRedirects(resp2, reverse('accounts:custom_login'))

    def test_email_non_livrable_repli_sms_possible(self):
        """Email activé mais SMTP incomplet : le canal SMS reste proposé."""
        configurer_email_incomplete()
        configurer_sms()
        resp = self.client.get(reverse('accounts:custom_login'))
        self.assertContains(resp, 'mot-de-passe-oublie')
        with self.assertLogs('stock.services', level='INFO') as logs:
            self.client.post(
                reverse('accounts:mot_de_passe_oublie'),
                {'canal': 'sms', 'identifiant': '0708091011'},
            )
        jeton = MotDePasseResetToken.objects.get(user=self.user)
        self.assertTrue(any(jeton.code in l for l in logs.output))

    def test_page_indisponible_sans_canal(self):
        resp = self.client.get(reverse('accounts:mot_de_passe_oublie'))
        self.assertRedirects(resp, reverse('accounts:custom_login'))

    def test_redirecte_utilisateur_connecte(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('accounts:mot_de_passe_oublie'))
        self.assertEqual(resp.status_code, 302)

    def test_email_envoye_avec_lien(self):
        configurer_email()
        with self.settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            resp = self.client.post(
                reverse('accounts:mot_de_passe_oublie'), {'identifiant': 'jean'}
            )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        msg = mail.outbox[0]
        self.assertEqual(msg.to, ['jean@chu.ci'])
        self.assertIn('Réinitialisation', msg.subject)
        jeton = MotDePasseResetToken.objects.get(user=self.user)
        self.assertIn(jeton.token, msg.body)
        html = next(
            (alt[0] for alt in msg.alternatives if alt[1] == 'text/html'), ''
        )
        self.assertIn('Réinitialiser mon mot de passe', html)

    def test_code_envoye_par_sms_avec_numero(self):
        """L'utilisateur choisit SMS et saisit son numéro → code envoyé."""
        configurer_sms()
        with self.assertLogs('stock.services', level='INFO') as logs:
            resp = self.client.post(
                reverse('accounts:mot_de_passe_oublie'),
                {'canal': 'sms', 'identifiant': '0708091011'},
            )
        self.assertEqual(resp.status_code, 302)
        jeton = MotDePasseResetToken.objects.get(user=self.user)
        self.assertTrue(any(jeton.code in l for l in logs.output))

    def test_code_sms_avec_numero_format_international(self):
        """Un numéro saisi au format +2250708091011 retrouve bien le compte."""
        configurer_sms()
        with self.assertLogs('stock.services', level='INFO') as logs:
            resp = self.client.post(
                reverse('accounts:mot_de_passe_oublie'),
                {'canal': 'sms', 'identifiant': '+225 07 08 09 10 11'},
            )
        self.assertEqual(resp.status_code, 302)
        jeton = MotDePasseResetToken.objects.get(user=self.user)
        self.assertTrue(any(jeton.code in l for l in logs.output))

    def test_sms_ignore_si_canal_email_choisi(self):
        """Choix email (email OK) → aucun SMS envoyé, seul l'email part."""
        configurer_email()
        configurer_sms()
        with mock.patch(
            'stock.services.NotificationService.envoyer_sms_direct'
        ) as mock_sms, self.settings(
            EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'
        ):
            self.client.post(
                reverse('accounts:mot_de_passe_oublie'),
                {'canal': 'email', 'identifiant': 'jean@chu.ci'},
            )
            mock_sms.assert_not_called()
        self.assertEqual(len(mail.outbox), 1)

    def test_email_ignore_si_canal_sms_choisi_et_sms_ok(self):
        """Choix SMS → seul le SMS part, pas d'email."""
        configurer_email()
        configurer_sms()
        with mock.patch(
            'stock.services.NotificationService.envoyer_email_direct'
        ) as mock_email, self.assertLogs('stock.services', level='INFO') as logs:
            self.client.post(
                reverse('accounts:mot_de_passe_oublie'),
                {'canal': 'sms', 'identifiant': '0708091011'},
            )
            mock_email.assert_not_called()
        jeton = MotDePasseResetToken.objects.get(user=self.user)
        self.assertTrue(any(jeton.code in l for l in logs.output))

    def test_sms_choisi_mais_echec_repli_email(self):
        """Si le SMS échoue (ex. Twilio trial), l'email part en repli."""
        configurer_email()
        configurer_sms()
        with mock.patch(
            'stock.services.NotificationService.envoyer_sms_direct',
            return_value=False,
        ), self.settings(
            EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'
        ):
            self.client.post(
                reverse('accounts:mot_de_passe_oublie'),
                {'canal': 'sms', 'identifiant': '0708091011'},
            )
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['jean@chu.ci'])

    def test_email_choisi_mais_echec_repli_sms(self):
        """Si l'email échoue, le SMS part en repli."""
        configurer_email()
        configurer_sms()
        with mock.patch(
            'stock.services.NotificationService.envoyer_email_direct',
            return_value=False,
        ), self.assertLogs('stock.services', level='INFO') as logs:
            self.client.post(
                reverse('accounts:mot_de_passe_oublie'),
                {'canal': 'email', 'identifiant': 'jean@chu.ci'},
            )
        jeton = MotDePasseResetToken.objects.get(user=self.user)
        self.assertTrue(any(jeton.code in l for l in logs.output))

    def test_message_neutre_identifiant_inconnu(self):
        configurer_email()
        resp = self.client.post(
            reverse('accounts:mot_de_passe_oublie'), {'identifiant': 'inconnu'}
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(MotDePasseResetToken.objects.count(), 0)

    def test_telephone_inconnu_aucun_jeton(self):
        """Un numéro inconnu ne crée aucun jeton (message neutre)."""
        configurer_sms()
        resp = self.client.post(
            reverse('accounts:mot_de_passe_oublie'),
            {'canal': 'sms', 'identifiant': '0500000000'},
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(MotDePasseResetToken.objects.count(), 0)

    def test_message_neutre_identique_compte_existant_ou_pas(self):
        """Le message affiché est identique que le compte existe ou non."""
        from django.contrib.messages import get_messages
        from django.test import Client

        configurer_email()
        with self.settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            resp = self.client.post(
                reverse('accounts:mot_de_passe_oublie'), {'identifiant': 'jean'},
                follow=True,
            )
        msgs_existant = [str(m) for m in get_messages(resp.wsgi_request)]

        c2 = Client()
        with self.settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            resp2 = c2.post(
                reverse('accounts:mot_de_passe_oublie'), {'identifiant': 'inconnu'},
                follow=True,
            )
        msgs_inconnu = [str(m) for m in get_messages(resp2.wsgi_request)]

        self.assertEqual(msgs_existant, msgs_inconnu)
        self.assertTrue(any('Si un compte correspond' in m for m in msgs_inconnu))

    def test_un_seul_jeton_actif_par_utilisateur(self):
        configurer_email()
        for _ in range(2):
            self.client.post(
                reverse('accounts:mot_de_passe_oublie'), {'identifiant': 'jean'}
            )
        self.assertEqual(
            MotDePasseResetToken.objects.filter(user=self.user, utilise=False).count(),
            1,
        )

    def test_code_mot_de_passe_ok_apres_reset(self):
        """Après un reset réussi, le mot de passe permet de se connecter."""
        configurer_email()
        with self.settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            self.client.post(
                reverse('accounts:mot_de_passe_oublie'), {'identifiant': 'jean'}
            )
        jeton = MotDePasseResetToken.objects.get(user=self.user)
        self.client.post(
            reverse('accounts:reinitialiser_mot_de_passe_lien', args=[jeton.token]),
            {'nouveau_mdp': 'Nouveau1!', 'confirmer_mdp': 'Nouveau1!'},
        )
        self.assertTrue(
            self.client.login(username='jean', password='Nouveau1!')
        )


class ReinitialisationParTokenTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='jean', password='Ancien1!', email='jean@chu.ci'
        )
        self.user.profil.doit_changer_mdp = True
        self.user.profil.save()

    def creer_jeton(self, expire_minutes=30, utilise=False):
        return MotDePasseResetToken.objects.create(
            user=self.user,
            token='tokentest' + 'x' * 22,
            code='123456',
            expire_le=timezone.now() + timedelta(minutes=expire_minutes),
            utilise=utilise,
        )

    def test_reset_reussi_par_lien(self):
        jeton = self.creer_jeton()
        url = reverse('accounts:reinitialiser_mot_de_passe_lien', args=[jeton.token])
        resp = self.client.post(
            url, {'nouveau_mdp': 'Nouveau1!', 'confirmer_mdp': 'Nouveau1!'}
        )
        self.assertRedirects(resp, reverse('accounts:custom_login'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Nouveau1!'))
        jeton.refresh_from_db()
        self.assertTrue(jeton.utilise)
        self.user.profil.refresh_from_db()
        self.assertFalse(self.user.profil.doit_changer_mdp)

    def test_reset_reussi_par_code_sms(self):
        self.creer_jeton()
        resp = self.client.post(reverse('accounts:reinitialiser_mot_de_passe'), {
            'code': '123456',
            'nouveau_mdp': 'Nouveau1!',
            'confirmer_mdp': 'Nouveau1!',
        })
        self.assertRedirects(resp, reverse('accounts:custom_login'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Nouveau1!'))

    def test_reset_refuse_jeton_inconnu(self):
        resp = self.client.post(reverse('accounts:reinitialiser_mot_de_passe'), {
            'token': 'inconnu',
            'nouveau_mdp': 'Nouveau1!',
            'confirmer_mdp': 'Nouveau1!',
        })
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'invalide ou a expiré')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Ancien1!'))

    def test_reset_refuse_jeton_expire(self):
        jeton = self.creer_jeton(expire_minutes=-5)
        url = reverse('accounts:reinitialiser_mot_de_passe_lien', args=[jeton.token])
        self.client.post(
            url, {'nouveau_mdp': 'Nouveau1!', 'confirmer_mdp': 'Nouveau1!'}
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Ancien1!'))

    def test_reset_refuse_jeton_deja_utilise(self):
        jeton = self.creer_jeton(utilise=True)
        url = reverse('accounts:reinitialiser_mot_de_passe_lien', args=[jeton.token])
        self.client.post(
            url, {'nouveau_mdp': 'Nouveau1!', 'confirmer_mdp': 'Nouveau1!'}
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Ancien1!'))

    def test_reset_refuse_mdp_trop_faible(self):
        jeton = self.creer_jeton()
        url = reverse('accounts:reinitialiser_mot_de_passe_lien', args=[jeton.token])
        resp = self.client.post(
            url, {'nouveau_mdp': 'faible', 'confirmer_mdp': 'faible'}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'invalide')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Ancien1!'))

    def test_reset_refuse_si_mdp_differents(self):
        jeton = self.creer_jeton()
        url = reverse('accounts:reinitialiser_mot_de_passe_lien', args=[jeton.token])
        resp = self.client.post(
            url, {'nouveau_mdp': 'Nouveau1!', 'confirmer_mdp': 'Autre1!'}
        )
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'ne correspondent pas')

    def test_reset_impossible_apres_usage(self):
        jeton = self.creer_jeton()
        url = reverse('accounts:reinitialiser_mot_de_passe_lien', args=[jeton.token])
        self.client.post(
            url, {'nouveau_mdp': 'Nouveau1!', 'confirmer_mdp': 'Nouveau1!'}
        )
        # Deuxième tentative avec le même jeton (déjà utilisé)
        self.client.post(
            url, {'nouveau_mdp': 'Nouveau2!', 'confirmer_mdp': 'Nouveau2!'}
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Nouveau1!'))
        self.assertFalse(self.user.check_password('Nouveau2!'))


class DesactivationReinitAdminTest(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username='boss', password='x')
        self.admin.profil.doit_changer_mdp = False
        self.admin.profil.save()
        self.user = User.objects.create_user(
            username='jean', password='Ancien1!', email='jean@chu.ci'
        )
        self.user.profil.doit_changer_mdp = False
        self.user.profil.save()

    def test_reinit_admin_bloquee_si_email_configure(self):
        configurer_email()
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse('accounts:reinitialiser_mdp', args=[self.user.id]),
            {'nouveau_mdp': 'Nouveau1!', 'confirmer_mdp': 'Nouveau1!'},
        )
        self.assertRedirects(resp, reverse('accounts:page_utilisateurs'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Ancien1!'))

    def test_reinit_admin_bloquee_si_sms_configure(self):
        configurer_sms()
        self.client.force_login(self.admin)
        self.client.post(
            reverse('accounts:reinitialiser_mdp', args=[self.user.id]),
            {'nouveau_mdp': 'Nouveau1!', 'confirmer_mdp': 'Nouveau1!'},
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Ancien1!'))

    def test_reinit_admin_ok_si_email_actif_mais_non_livrable(self):
        """Canal cassé → l'admin garde la main (sinon personne ne peut rien faire)."""
        configurer_email_incomplete()
        self.client.force_login(self.admin)
        self.client.post(
            reverse('accounts:reinitialiser_mdp', args=[self.user.id]),
            {'nouveau_mdp': 'Nouveau1!', 'confirmer_mdp': 'Nouveau1!'},
        )
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Nouveau1!'))

    def test_reinit_admin_ok_sans_canal(self):
        self.client.force_login(self.admin)
        resp = self.client.post(
            reverse('accounts:reinitialiser_mdp', args=[self.user.id]),
            {'nouveau_mdp': 'Nouveau1!', 'confirmer_mdp': 'Nouveau1!'},
        )
        self.assertRedirects(resp, reverse('accounts:page_utilisateurs'))
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Nouveau1!'))

    def test_bouton_masque_sur_page_utilisateurs(self):
        configurer_email()
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('accounts:page_utilisateurs'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'reinitialiser-mdp')

    def test_bouton_visible_sans_canal(self):
        self.client.force_login(self.admin)
        resp = self.client.get(reverse('accounts:page_utilisateurs'))
        self.assertContains(resp, 'reinitialiser-mdp')


class SMSNotificationsImportantesTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='dest', password='x', email='d@chu.ci'
        )
        self.user.profil.contact = '0708091011'
        self.user.profil.save()
        self.config = ConfigurationNotification.get_instance()

    def test_sms_envoye_si_importante(self):
        self.config.activer_sms = True
        self.config.sms_mode_test = True
        self.config.save()
        with self.assertLogs('stock.services', level='INFO') as logs:
            NotificationService.creer(
                self.user, 'Alerte', 'Stock bas', est_importante=True
            )
        self.assertTrue(any('SMS·TEST' in l for l in logs.output))

    def test_sms_ignore_si_non_importante(self):
        self.config.activer_sms = True
        self.config.sms_mode_test = True
        self.config.save()
        with mock.patch(
            'stock.services.NotificationService._envoyer_sms_vers'
        ) as mock_envoyer:
            NotificationService.creer(self.user, 'Info', 'Simple info')
            mock_envoyer.assert_not_called()

    def test_email_envoye_quelle_que_soit_l_importance(self):
        self.config.activer_email = True
        self.config.email_expediteur = 'no-reply@chu.ci'
        self.config.save()
        with self.settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            NotificationService.creer(self.user, 'Info', 'Simple info')
            self.assertEqual(len(mail.outbox), 1)

    def test_champ_est_importante_stocke_en_base(self):
        n = Notification.objects.create(
            utilisateur=self.user, titre='T', message='M', est_importante=True
        )
        n.refresh_from_db()
        self.assertTrue(n.est_importante)

