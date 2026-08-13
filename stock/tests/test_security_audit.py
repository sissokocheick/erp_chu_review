# -*- coding: utf-8 -*-
"""
Tests de non-régression de l'audit sécurité (2026-08).

Couverture :
1. Logout POST-only (anti logout-CSRF par GET).
2. Page de scan QR patrimoine authentifiée (plus d'exposition publique).
3. IDOR : signature d'accusé de réception bloquée pour un utilisateur
   non lié à la demande (chemin AJAX qui contournait la vérification).
4. get_client_ip : l'en-tête X-Forwarded-For ne peut plus spoof l'IP
   quand USE_X_FORWARDED_FOR est désactivé (contournement anti brute-force).
"""
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.contrib.auth import get_user_model

User = get_user_model()


def _user_ok(username, **kwargs):
    """Crée un utilisateur sans MDP obligatoire à changer (sinon le
    middleware PasswordChangeMiddleware redirige tout en 302)."""
    user = User.objects.create_user(username=username, password='testpass123', **kwargs)
    user.profil.doit_changer_mdp = False
    user.profil.save(update_fields=['doit_changer_mdp'])
    return user


class AuditLogoutTest(TestCase):
    """Le logout ne doit répondre qu'en POST (anti logout-CSRF)."""

    def setUp(self):
        self.user = _user_ok('logout_user')

    def test_logout_get_est_refuse(self):
        """GET /auth/logout/ -> 405 (et la session reste active)."""
        self.client.login(username='logout_user', password='testpass123')
        resp = self.client.get(reverse('accounts:custom_logout'))
        self.assertEqual(resp.status_code, 405)
        # Session toujours active
        self.assertTrue(self.client.session.get('_auth_user_id'))

    def test_logout_post_deconnecte(self):
        """POST /auth/logout/ -> redirection et session fermée."""
        self.client.login(username='logout_user', password='testpass123')
        resp = self.client.post(reverse('accounts:custom_logout'))
        self.assertIn(resp.status_code, [302, 200])
        self.assertFalse(self.client.session.get('_auth_user_id'))


class AuditScanMobileTest(TestCase):
    """La fiche scan QR du patrimoine ne doit plus être publique."""

    def setUp(self):
        from patrimoine.models import Immobilisation
        self.Immo = Immobilisation
        self.immo = Immobilisation.objects.create(
            code_patrimoine='SCAN-SEC-001', nom_affichage='Équipement secret')

    def test_scan_sans_login_redirige_vers_login(self):
        resp = self.client.get(
            reverse('patrimoine_scan', kwargs={'code': 'SCAN-SEC-001'}))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/auth/login/', resp.url)

    def test_scan_avec_login_ok(self):
        user = _user_ok('scan_user')
        self.client.login(username='scan_user', password='testpass123')
        resp = self.client.get(
            reverse('patrimoine_scan', kwargs={'code': 'SCAN-SEC-001'}))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'SCAN-SEC-001')


class AuditSignatureAccuseIDORTest(TestCase):
    """Un utilisateur sans lien avec la demande ne peut pas signer
    l'accusé de réception, y compris via le chemin AJAX (ex-IDOR)."""

    @classmethod
    def setUpTestData(cls):
        from core.models import Service
        from stock.models import (
            Magasin, DemandeMateriel, LigneDemande, LivraisonPartielle,
            LivraisonLigne, AccuseReception, Article, FamilleArticle,
        )
        cls.Service = Service
        cls.magasin = Magasin.objects.create(nom='Magasin Securite')
        cls.famille = FamilleArticle.objects.create(intitule='Famille Securite')
        cls.article = Article.objects.create(
            reference='SEC-ART-1', designation='Article Securite',
            famille=cls.famille)
        cls.service_a = Service.objects.create(code='SEC-A', nom='Service A')
        cls.service_b = Service.objects.create(code='SEC-B', nom='Service B')

        cls.demandeur = _user_ok('demandeur')
        cls.user_b = _user_ok('user_b')
        # membre du service A (destinataire) — autorisé à signer
        cls.service_a_user = _user_ok('service_a_user')
        cls.service_a_user.profil.service = cls.service_a
        cls.service_a_user.profil.save()
        # membre du service B — NON autorisé
        cls.service_b_user = _user_ok('service_b_user')
        cls.service_b_user.profil.service = cls.service_b
        cls.service_b_user.profil.save()

        cls.demande = DemandeMateriel.objects.create(
            numero_demande='SEC-DEM-001', demandeur=cls.demandeur,
            service_demandeur=cls.service_a, magasin_cible=cls.magasin,
            statut='EN_ATTENTE')
        LigneDemande.objects.create(
            demande=cls.demande, article=cls.article, quantite_demandee=5)

        cls.livraison = LivraisonPartielle.objects.create(
            demande=cls.demande, bon_sortie=None, quantite_livree=5)
        LivraisonLigne.objects.create(
            livraison=cls.livraison, article=cls.article,
            quantite_demandee=5, quantite_livree=5, reste=0)
        cls.accuse = AccuseReception.objects.create(
            livraison=cls.livraison, est_signe=False)

    def _ajax_sign(self, client):
        return client.post(
            reverse('signer_accuse_reception',
                    kwargs={'accuse_id': self.accuse.id}),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def test_utilisateur_autre_service_bloque(self):
        """Un user d'un autre service -> 403 sur le POST AJAX."""
        self.client.login(username='service_b_user', password='testpass123')
        resp = self._ajax_sign(self.client)
        self.assertEqual(resp.status_code, 403)
        self.accuse.refresh_from_db()
        self.assertFalse(self.accuse.est_signe)

    def test_utilisateur_sans_profil_bloque(self):
        """Un user sans profil/service -> 403."""
        self.client.login(username='user_b', password='testpass123')
        resp = self._ajax_sign(self.client)
        self.assertEqual(resp.status_code, 403)
        self.accuse.refresh_from_db()
        self.assertFalse(self.accuse.est_signe)

    def test_membre_service_destinataire_autorise(self):
        """Un user du service destinataire -> signature OK."""
        self.client.login(username='service_a_user', password='testpass123')
        resp = self._ajax_sign(self.client)
        self.assertEqual(resp.status_code, 200)
        self.accuse.refresh_from_db()
        self.assertTrue(self.accuse.est_signe)


@override_settings(USE_X_FORWARDED_FOR=False)
class AuditClientIpSpoofingTest(TestCase):
    """Sans proxy configuré, X-Forwarded-For ne doit pas être suivi :
    l'anti brute-force par IP ne peut pas être contourné en le spoofant."""

    def test_x_forwarded_for_ignore_par_defaut(self):
        from accounts.views import get_client_ip
        from django.test import RequestFactory

        factory = RequestFactory()
        request = factory.get('/auth/login/')
        request.META['REMOTE_ADDR'] = '10.0.0.5'
        request.META['HTTP_X_FORWARDED_FOR'] = '6.6.6.6, 5.5.5.5'

        self.assertEqual(get_client_ip(request), '10.0.0.5')

    @override_settings(USE_X_FORWARDED_FOR=True)
    def test_x_forwarded_for_suivi_derriere_proxy(self):
        from accounts.views import get_client_ip
        from django.test import RequestFactory

        factory = RequestFactory()
        request = factory.get('/auth/login/')
        request.META['REMOTE_ADDR'] = '10.0.0.5'
        # Le proxy ajoute l'IP réelle du client à la fin de la chaîne
        request.META['HTTP_X_FORWARDED_FOR'] = '6.6.6.6, 5.5.5.5, 203.0.113.9'

        self.assertEqual(get_client_ip(request), '203.0.113.9')
