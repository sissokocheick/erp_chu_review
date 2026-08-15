# -*- coding: utf-8 -*-
"""
Tests E2E (navigateur réel, Playwright) — parcours utilisateur de bout en bout.

Ces tests démarrent un vrai serveur Django (LiveServerTestCase) et pilotent
Chromium : connexion, sélection du magasin, recherche, création d'article,
navigation entre pages, pagination, cohérence magasin.

Prérequis (une fois) :
    pip install playwright
    playwright install chromium

Si Playwright n'est pas disponible, la suite est ignorée proprement.

Lancement :
    DJANGO_SETTINGS_MODULE=config.settings_test \\
        python manage.py test stock.tests.test_e2e_playwright

(config/settings_test.py pose DJANGO_ALLOW_ASYNC_UNSAFE=1 automatiquement :
Playwright sync tourne sa propre boucle d'événements, ce que Django
interprète comme un contexte async sans cette variable.)
"""
import unittest

from django.contrib.auth import get_user_model
from django.test import LiveServerTestCase

from stock.models import Magasin, FamilleArticle, Article, StockItem, BonMouvement

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_DISPONIBLE = True
except ImportError:  # pragma: no cover
    PLAYWRIGHT_DISPONIBLE = False

PASSWORD = 'E2ePass!2026'


@unittest.skipUnless(
    PLAYWRIGHT_DISPONIBLE,
    "Playwright non installé (pip install playwright && playwright install chromium)",
)
class E2EBase(LiveServerTestCase):
    """Base : 1 navigateur par classe, 1 contexte (session) par test."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._pw = sync_playwright().start()
        cls.browser = cls._pw.chromium.launch()

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls._pw.stop()
        super().tearDownClass()

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_superuser(
            username='e2e_admin', password=PASSWORD, email='e2e@chu.ci')
        self.user.profil.doit_changer_mdp = False
        self.user.profil.save(update_fields=['doit_changer_mdp'])

        self.mag_a = Magasin.objects.create(nom='Magasin E2E A')
        self.mag_b = Magasin.objects.create(nom='Magasin E2E B')
        self.user.profil.magasins_autorises.add(self.mag_a, self.mag_b)

        self.famille = FamilleArticle.objects.create(intitule='E2E Famille')
        self.article_para = Article.objects.create(
            designation='Paracétamol 500mg E2E',
            famille=self.famille, reference='E2E-001')
        StockItem.objects.create(
            article=self.article_para, magasin=self.mag_a, quantite_physique=50)

        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        self.page.set_default_timeout(10000)

    def tearDown(self):
        self.context.close()

    # ──────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────
    def _attendre(self, ms=400):
        """Petite attente fixe — évite les wait_for_load_state('networkidle')
        qui ne se terminent jamais (polling de la cloche notifications)."""
        self.page.wait_for_timeout(ms)

    def _attendre_visible(self, selector, timeout_ms=20000):
        """Attente conditionnelle robuste (CI) : attend que le sélecteur soit
        visible au lieu d'un délai fixe — évite la flakiness sur runner chargé."""
        self.page.wait_for_selector(
            selector, state='visible', timeout=timeout_ms)

    def _attendre_url(self, fragment, timeout_ms=20000):
        """Attend que l'URL contienne `fragment` (navigation après soumission)."""
        self.page.wait_for_url(
            f'**{fragment}**', timeout=timeout_ms)

    def _se_connecter(self, url='/', magasin=None):
        """Connexion puis navigation vers `url`.

        L'overlay « Choix du Magasin » n'apparaît que sur les pages protégées
        (magasin_requis) : on navigue donc d'abord vers la cible, puis on
        choisit le magasin si l'overlay est présent (le formulaire renvoie
        vers url_voulue = la page cible). Si l'utilisateur est déjà connecté
        (appelé plusieurs fois dans un même test), la connexion est sautée.
        """
        # Toujours passer par /auth/login/ : si l'utilisateur est déjà connecté,
        # la vue redirige vers l'accueil et le formulaire n'est pas affiché.
        self.page.goto(self.live_server_url + '/auth/login/')
        self._attendre(500)
        if self.page.locator('#id_username').count():
            # Page de connexion affichée → on se connecte
            self.page.fill('#id_username', 'e2e_admin')
            self.page.fill('#id_password', PASSWORD)
            self.page.click('#submitBtn')
            self._attendre(800)

        if url:
            self.page.goto(self.live_server_url + url)
            self._attendre(800)

        self._choisir_magasin_si_necessaire(magasin)

    def _choisir_magasin_si_necessaire(self, magasin=None):
        """Sélectionne le magasin via l'overlay s'il est visible.

        NB : le sélecteur de la topbar partage la même action de formulaire
        (changer-magasin) — on cible donc le select de l'overlay par sa
        classe nx-select.
        """
        select = self.page.locator(
            'form[action*="changer-magasin"] select.nx-select')
        if select.count() and select.is_visible():
            select.select_option(str((magasin or self.mag_a).id))
            self._attendre(200)
            self.page.locator(
                'form[action*="changer-magasin"] button[type="submit"]'
            ).click()
            self._attendre(900)

    def _changer_magasin_header(self, magasin):
        """Change le magasin via le sélecteur de l'en-tête (auto-submit)."""
        select = self.page.locator('.topbar select[name="magasin_id"]')
        if not select.count():
            raise AssertionError('Sélecteur de magasin introuvable dans la topbar')
        select.select_option(str(magasin.id))
        self._attendre(900)

    def _magasin_actif_header(self):
        return self.page.locator(
            '.topbar select[name="magasin_id"]').input_value()

    # ──────────────────────────────────────────────────────────────────
    # Connexion
    # ──────────────────────────────────────────────────────────────────
    def test_login_erreur_puis_reussite(self):
        """Mot de passe erroné → message d'erreur ; correct → accès."""
        self.page.goto(self.live_server_url + '/auth/login/')
        self.page.fill('#id_username', 'e2e_admin')
        self.page.fill('#id_password', 'mauvais-mdp')
        self.page.click('#submitBtn')
        self._attendre(800)
        self.assertIn('Identifiants incorrects', self.page.inner_text('body'))

        # Maintenant le bon mot de passe
        self._se_connecter()
        self.assertNotIn('/auth/login/', self.page.url)

    def test_mot_de_passe_oublie_lien_present(self):
        """Le lien « Mot de passe oublié » est présent quand un canal est livrable."""
        from core.models import ConfigurationNotification
        cfg = ConfigurationNotification.get_instance()
        cfg.activer_email = True
        cfg.email_expediteur = 'noreply@chu.ci'
        cfg.smtp_host = 'smtp.gmail.com'
        cfg.smtp_user = 'test@chu.ci'
        cfg.smtp_password = 'secret'
        cfg.save()

        self.page.goto(self.live_server_url + '/auth/login/')
        self.assertGreater(
            self.page.locator('a[href*="mot-de-passe-oublie"]').count(), 0)

    def test_mot_de_passe_oublie_sms_225_contact_stocke_225(self):
        """« Mot de passe oublié » par SMS : un contact stocké avec +225
        (13 chiffres) est retrouvé par une saisie locale, et le code part en
        mode test SMS (loggé)."""
        from django.contrib.auth import get_user_model
        from django.test import override_settings
        from core.models import ConfigurationNotification
        from accounts.models import MotDePasseResetToken

        User = get_user_model()
        cible = User.objects.create_user(
            username='sms225', password='Ancien123!', email='sms225@chu.ci')
        # Contact stocké au format +225 (13 chiffres, comme produit par un
        # ancien formulaire saisi avec l'indicatif)
        cible.profil.contact = '2250708091011'
        cible.profil.doit_changer_mdp = False
        cible.profil.save()

        # Canal SMS actif en mode test (aucun envoi réel, code loggé)
        cfg = ConfigurationNotification.get_instance()
        cfg.activer_sms = True
        cfg.sms_mode_test = True
        cfg.sms_provider = 'TEST'
        cfg.sms_expediteur = 'NEXUS'
        cfg.sms_api_url = 'https://api.example.com/sms'
        cfg.sms_api_key = 'cle-test'
        cfg.save()

        # Le lien « Mot de passe oublié » est présent sur la page de connexion
        self.page.goto(self.live_server_url + '/auth/login/')
        self._attendre(600)
        lien = self.page.locator('a[href*="mot-de-passe-oublie"]')
        self.assertGreater(lien.count(), 0)
        lien.first.click()
        self._attendre(900)
        self.assertIn('mot-de-passe-oublie', self.page.url)

        # Sélection du canal SMS + saisie locale du numéro
        self.page.locator('#opt_sms input[type="radio"]').check(force=True)
        self.page.fill('#id_identifiant', '07 08 09 10 11')
        self.page.click('form button[type="submit"]')

        # Attente du message neutre (robuste : pas de délai fixe)
        self._attendre_visible('text=Si un compte correspond')

        # Un jeton a été créé pour le bon compte (le numéro +225 a matché)
        jeton = MotDePasseResetToken.objects.filter(user=cible).first()
        self.assertIsNotNone(
            jeton, "Le compte avec contact +225 doit être retrouvé")
        self.assertFalse(jeton.utilise)

        # Le message neutre est affiché (ne révèle pas l'existence du compte)
        body = self.page.inner_text('body')
        self.assertIn('Si un compte correspond', body)

    def test_mot_de_passe_oublie_sms_repli_email(self):
        """« Mot de passe oublié » : SMS choisi mais échec → repli sur email.
        Vérifie le repli automatique de bout en bout dans le navigateur."""
        import logging
        from django.contrib.auth import get_user_model
        from django.test import override_settings
        from core.models import ConfigurationNotification
        from accounts.models import MotDePasseResetToken

        User = get_user_model()
        cible = User.objects.create_user(
            username='repli', password='Ancien123!', email='repli@chu.ci')
        cible.profil.contact = '0708091011'
        cible.profil.doit_changer_mdp = False
        cible.profil.save()

        # Email actif + SMS configuré mais qui échoue (hors mode test)
        cfg = ConfigurationNotification.get_instance()
        cfg.activer_email = True
        cfg.email_expediteur = 'no-reply@chu.ci'
        cfg.smtp_host = 'smtp.gmail.com'
        cfg.smtp_user = 'no-reply@chu.ci'
        cfg.smtp_password = 'secret-app'
        cfg.activer_sms = True
        cfg.sms_mode_test = False
        cfg.sms_expediteur = 'NexusERP'
        cfg.sms_provider = 'GENERIQUE'
        cfg.sms_api_url = 'https://api.invalide.invalid/sms'
        cfg.sms_api_key = 'cle-invalide'
        cfg.save()

        # Navigation directe vers la page « oublié » (robuste)
        self.page.goto(
            self.live_server_url + '/auth/mot-de-passe-oublie/')
        self._attendre(800)
        self.assertIn('mot-de-passe-oublie', self.page.url)

        # Canal SMS (même mécanisme que le test SMS 225 : check force)
        sms_radio = self.page.locator('#opt_sms input[type="radio"]')
        self.assertGreater(
            sms_radio.count(), 0, "Le canal SMS doit être proposé")
        sms_radio.check(force=True)
        self.page.fill('#id_identifiant', '0708091011')
        self._attendre(300)

        from django.core import mail
        from unittest import mock
        # Le SMS échoue (ex. Twilio trial) → repli sur email attendu
        with mock.patch(
            'stock.services.NotificationService.envoyer_sms_direct',
            return_value=False,
        ), override_settings(
                EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            self.page.click('form button[type="submit"]')
            self._attendre_visible('text=Si un compte correspond')
            # Le SMS a échoué → repli email automatique
            jeton = MotDePasseResetToken.objects.filter(user=cible).first()
            self.assertIsNotNone(
                jeton, "Le compte doit être retrouvé et un jeton créé")
            self.assertEqual(len(mail.outbox), 1)
            self.assertEqual(mail.outbox[0].to, ['repli@chu.ci'])
            self.assertIn(jeton.token, mail.outbox[0].body)

    def test_reset_admin_bouton_visible_et_email_envoye(self):
        """Reset admin de bout en bout : bouton visible devant le compte, saisie du
        nouveau mot de passe, confirmation, retour à la liste, mot de passe changé
        et email envoyé contenant le nouveau mot de passe (canal configuré)."""
        from django.contrib.auth import get_user_model
        from django.core import mail
        from django.test.utils import override_settings
        from core.models import ConfigurationNotification

        User = get_user_model()
        cible = User.objects.create_user(
            username='cible_reset', password='Ancien123!',
            email='cible@chu.ci', first_name='Cible', last_name='Reset')
        cible.profil.doit_changer_mdp = False
        cible.profil.save(update_fields=['doit_changer_mdp'])

        # Canal email livrable → le nouveau mot de passe doit partir par email
        cfg = ConfigurationNotification.get_instance()
        cfg.activer_email = True
        cfg.email_expediteur = 'no-reply@chu.ci'
        cfg.smtp_host = 'smtp.gmail.com'
        cfg.smtp_user = 'no-reply@chu.ci'
        cfg.smtp_password = 'secret-app'
        cfg.save()

        self._se_connecter('/auth/utilisateurs/', magasin=self.mag_a)

        # 1) Le bouton de réinitialisation est visible devant le compte cible
        lien = self.page.locator(
            f'a[href*="utilisateurs/{cible.id}/reinitialiser-mdp"]')
        self.assertGreater(
            lien.count(), 0,
            "Le bouton de réinitialisation doit être visible devant le compte")
        self.assertTrue(lien.first.is_visible())

        # 2) Ouverture de la page de reset
        lien.first.click()
        self._attendre(900)
        self.assertIn('reinitialiser-mdp', self.page.url)

        # 3) Saisie + validation du nouveau mot de passe
        with override_settings(
                EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            self.page.fill('#newPwd', 'Nouveau123!')
            self.page.fill('#confirmPwd', 'Nouveau123!')
            self._attendre(300)
            self.page.click('#btnSubmit')
            self._attendre(600)
            # Confirmation SweetAlert (NxUX.confirm)
            swal_ok = self.page.locator('.swal2-confirm')
            if swal_ok.count():
                swal_ok.first.click()
            # Retour à la liste des utilisateurs (robuste : pas de délai fixe)
            self._attendre_url('/auth/utilisateurs/')

        # 4) Retour à la liste + mot de passe changé + email envoyé
        self.assertIn('/auth/utilisateurs/', self.page.url)
        cible.refresh_from_db()
        self.assertTrue(
            cible.check_password('Nouveau123!'),
            "Le mot de passe doit être mis à jour")
        self.assertEqual(len(mail.outbox), 1, "Un email doit être envoyé")
        self.assertIn('Nouveau123!', mail.outbox[0].body)
        self.assertIn(cible.email, mail.outbox[0].to)

    def test_creation_utilisateur_modale_et_email_mdp(self):
        """Création d'un utilisateur avec canal email actif : la modale affiche le
        mot de passe temporaire (identifiant + MDP) ET l'email reçu contient le
        même MDP (vérifié par check_password)."""
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Group
        from django.core import mail
        from django.test.utils import override_settings
        from core.models import ConfigurationNotification

        User = get_user_model()
        groupe = Group.objects.create(name='Magasinier E2E')

        # Canal email livrable → le MDP initial doit partir par email
        cfg = ConfigurationNotification.get_instance()
        cfg.activer_email = True
        cfg.email_expediteur = 'no-reply@chu.ci'
        cfg.smtp_host = 'smtp.gmail.com'
        cfg.smtp_user = 'no-reply@chu.ci'
        cfg.smtp_password = 'secret-app'
        cfg.save()

        self._se_connecter('/auth/utilisateurs/', magasin=self.mag_a)

        # 1) Ouvrir la modale de création
        self.page.locator('button.btn-add-user').first.click()
        self._attendre(600)
        self.assertIn(
            'open', self.page.locator('#modalUser').get_attribute('class') or '',
            "La modale de création doit s'ouvrir")

        # 2) Remplir le formulaire (groupe requis)
        self.page.fill('#inp_nom', 'TRAORE')
        self.page.fill('#inp_prenom', 'Awa')
        self.page.fill('#inp_username', 'awa.traore')
        self.page.fill('#inp_contact', '0708091011')
        self.page.fill('#inp_email', 'awa@chu.ci')
        self.page.select_option('#inp_groupe', str(groupe.id))
        self._attendre(300)

        # 3) Enregistrer + confirmation SweetAlert (NxUX.confirm)
        with override_settings(
                EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            self.page.click('#btnSaveUser')
            self._attendre(700)
            swal_ok = self.page.locator('.swal2-confirm')
            self.assertGreater(
                swal_ok.count(), 0,
                "Une confirmation SweetAlert doit apparaître avant la création")
            swal_ok.first.click()
            # Attente de la modale des identifiants (robuste)
            self._attendre_visible('#modalCredentials.open')

        # 4) Modale d'affichage du mot de passe (session new_user_credentials)
        cred = self.page.locator('#modalCredentials')
        self.assertTrue(cred.count() > 0, "La modale des identifiants doit s'afficher")
        self.assertIn('open', cred.get_attribute('class') or '')
        username_modale = self.page.locator('#credUsername').inner_text().strip()
        mdp_modale = self.page.locator('#credPassword').inner_text().strip()
        self.assertEqual(username_modale, 'awa.traore')
        self.assertGreater(len(mdp_modale), 0, "Le mot de passe doit être affiché")

        # 5) Email reçu avec le MDP réel du compte
        awa = User.objects.get(username='awa.traore')
        self.assertEqual(len(mail.outbox), 1, "Un email doit être envoyé")
        self.assertEqual(mail.outbox[0].to, ['awa@chu.ci'])
        self.assertIn('awa.traore', mail.outbox[0].body)
        self.assertTrue(
            awa.check_password(mdp_modale),
            "Le MDP affiché dans la modale doit être celui du compte et de l'email")

    # ──────────────────────────────────────────────────────────────────
    # Sélection du magasin
    # ──────────────────────────────────────────────────────────────────
    def test_selection_magasin_persiste_dans_header(self):
        """Le magasin choisi s'affiche dans l'en-tête et persiste."""
        self._se_connecter('/articles/', magasin=self.mag_a)
        self.assertEqual(self._magasin_actif_header(), str(self.mag_a.id))

        self._changer_magasin_header(self.mag_b)
        self.assertEqual(self._magasin_actif_header(), str(self.mag_b.id))

    # ──────────────────────────────────────────────────────────────────
    # Recherche (insensible aux accents)
    # ──────────────────────────────────────────────────────────────────
    def _rechercher_articles(self, terme):
        """Saisit une recherche (le champ est readonly jusqu'au focus)."""
        self.page.click('#search-q')
        self.page.fill('#search-q', terme)
        self.page.press('#search-q', 'Enter')
        self._attendre(900)

    def test_recherche_articles_sans_accent(self):
        """« paracetamol » (sans accent) trouve « Paracétamol »."""
        self._se_connecter('/articles/', magasin=self.mag_a)
        self._rechercher_articles('paracetamol')
        self.assertIn(
            'Paracétamol 500mg E2E', self.page.inner_text('#tableArticles'))

    def test_recherche_articles_avec_accent(self):
        """La recherche avec l'accent fonctionne aussi."""
        self._se_connecter('/articles/', magasin=self.mag_a)
        self._rechercher_articles('Paracétamol')
        self.assertIn(
            'Paracétamol 500mg E2E', self.page.inner_text('#tableArticles'))

    # ──────────────────────────────────────────────────────────────────
    # Création d'article (modale + validation)
    # ──────────────────────────────────────────────────────────────────
    def test_creation_article_validation_vide(self):
        """Modale : soumission vide → message « obligatoire »."""
        self._se_connecter('/articles/', magasin=self.mag_a)
        self.page.click('#btn-nouvel-article')
        self._attendre(400)
        self.page.locator('[data-action="enregistrer-article"]').click()
        self._attendre(900)
        body = self.page.inner_text('body').lower()
        self.assertTrue(
            'obligatoire' in body or 'désignation' in body,
            f"Message attendu absent : {self.page.inner_text('body')[:200]}",
        )

    def test_creation_article_reussie(self):
        """Création d'un article valide → il apparaît dans la liste."""
        self._se_connecter('/articles/', magasin=self.mag_a)
        self.page.click('#btn-nouvel-article')
        self._attendre(400)
        # NB : le formulaire de création n'a pas de champ « référence »
        # (il est géré ailleurs) — on remplit famille / designation / unité / prix.
        self.page.select_option('#id_famille', str(self.famille.id))
        self.page.fill('#id_designation', 'Sérum physiologique E2E')
        self.page.fill('#id_unite_distribution', 'Flacon')
        self.page.fill('#id_prix_reference', '1500')
        self.page.locator('[data-action="enregistrer-article"]').click()
        self._attendre(600)
        # SweetAlert de confirmation → cliquer « Oui, creer » pour soumettre
        confirm = self.page.locator('.swal2-confirm')
        self.assertGreater(confirm.count(), 0, 'Confirmation SweetAlert absente')
        confirm.click()
        self._attendre(1200)

        from stock.models import Article as Art
        self.assertTrue(
            Art.objects.filter(designation='Sérum physiologique E2E').exists())

        # Confirmer le SweetAlert puis revoir la page
        self.page.keyboard.press('Escape')
        self._attendre(500)
        self.page.goto(self.live_server_url + '/articles/')
        self._attendre(800)
        self._rechercher_articles('sérum')
        self.assertIn(
            'Sérum physiologique E2E', self.page.inner_text('#tableArticles'))

    # ──────────────────────────────────────────────────────────────────
    # Pagination
    # ──────────────────────────────────────────────────────────────────
    def test_pagination_articles_deux_pages(self):
        """Plus de 15 articles → pagination fonctionnelle sur la page 2."""
        from stock.models import Article as Art
        for i in range(18):
            Art.objects.create(
                designation=f'Article pagination E2E {i:02d}',
                famille=self.famille, reference=f'E2E-PAG-{i:02d}')
        self._se_connecter('/articles/', magasin=self.mag_a)
        page2 = self.page.locator('a.page-btn[href*="page=2"]')
        self.assertGreater(page2.count(), 0, 'Pagination page 2 absente')
        page2.first.click()
        self._attendre(900)
        self.assertIn('page=2', self.page.url)

    # ──────────────────────────────────────────────────────────────────
    # Pages principales
    # ──────────────────────────────────────────────────────────────────
    def test_pages_stock_principales_chargent(self):
        """Entrées, Sorties, État du Stock, Hors Stock chargent sans erreur."""
        self._se_connecter('/entrees/', magasin=self.mag_a)
        for url in ('/sorties/', '/etat-stock/', '/bons/hors-stock/'):
            with self.subTest(url=url):
                self.page.goto(self.live_server_url + url)
                self._attendre(800)
                self._choisir_magasin_si_necessaire(self.mag_a)
                body = self.page.inner_text('body')
                self.assertNotIn('Traceback', body)
                self.assertNotIn('Internal Server Error', body)

    def test_hors_stock_respecte_le_magasin_selectionne(self):
        """Un bon HS du magasin A disparaît quand on passe au magasin B."""
        BonMouvement.objects.create(
            type_bon='SORTIE_HORS_STOCK',
            magasin=self.mag_a,
            statut_validation='VALIDE',
            numero_bon='E2E-HS-001',
            commentaire='Bon HS magasin A',
        )
        self._se_connecter('/bons/hors-stock/', magasin=self.mag_a)
        self.assertIn('E2E-HS-001', self.page.inner_text('body'))

        self._changer_magasin_header(self.mag_b)
        self.assertNotIn('E2E-HS-001', self.page.inner_text('body'))

        self._changer_magasin_header(self.mag_a)
        self.assertIn('E2E-HS-001', self.page.inner_text('body'))

    # ──────────────────────────────────────────────────────────────────
    # Profil
    # ──────────────────────────────────────────────────────────────────
    def test_page_profil_charge(self):
        """La page Profil (fix du lien en dur) charge correctement."""
        self._se_connecter('/auth/profil/')
        body = self.page.inner_text('body')
        self.assertNotIn('Traceback', body)
        self.assertIn('profil', body.lower())

    # ──────────────────────────────────────────────────────────────────
    # UX grandes listes (sticky header + état de chargement)
    # ──────────────────────────────────────────────────────────────────
    def test_sticky_header_et_loading_sur_liste_articles(self):
        """Avec beaucoup d'articles, le header du tableau reste sticky et
        la recherche affiche un overlay de chargement (NxUX.setTableLoading)."""
        from stock.models import Article as ArticleModel
        # 40 articles pour rendre le tableau scrollable
        for i in range(40):
            ArticleModel.objects.create(
                designation=f'Article UX {i:03d}', famille=self.famille,
                reference=f'E2E-UX-{i:03d}')

        self._se_connecter('/articles/', magasin=self.mag_a)

        # 1) Header sticky dans le conteneur de scroll
        sticky = self.page.evaluate(
            "getComputedStyle(document.querySelector('#tableArticles thead th')).position"
        )
        self.assertEqual(sticky, 'sticky')

        # 2) Conteneur avec hauteur bornée (scroll vertical)
        maxh = self.page.evaluate(
            "getComputedStyle(document.querySelector('#tableArticles')).maxHeight")
        self.assertTrue(maxh and maxh != 'none', f"max-height attendu, obtenu : {maxh}")

        # 3) La recherche affiche l'overlay de chargement puis le retire.
        # On retarde la réponse du fetch (1,5 s) pour que l'overlay reste
        # visible le temps de l'observer (le fetch local est sinon instantané).
        import time

        def _delay_search(route):
            time.sleep(1.5)
            route.continue_()

        # Le design system (NxUX) doit être servi : la config E2E sert les
        # statiques depuis le dossier source (STATIC_ROOT en settings_test).
        diag = self.page.evaluate("""async () => ({
            nxux: typeof window.NxUX,
            nxux_status: await fetch('/static/js/nx-ux.js').then(function(r){ return r.status; }).catch(function(){ return 'err'; })
        })""")
        self.assertEqual(diag['nxux'], 'object', f"NxUX non chargé : {diag}")
        self.assertEqual(diag['nxux_status'], 200, f"nx-ux.js non servi : {diag}")

        # 3) La recherche affiche l'overlay de chargement puis le retire.
        # On retarde la réponse du fetch (1,5 s) pour que l'overlay reste
        # visible le temps de l'observer (le fetch local est sinon instantané).
        import time

        def _delay_search(route):
            time.sleep(1.5)
            route.continue_()

        self.page.route('**/articles/?*', _delay_search)
        self.page.click('#search-q')  # le champ est readonly jusqu'au focus
        self.page.fill('#search-q', 'Article UX 0')
        states = {}
        for ms in (300, 500, 700, 900, 1200):
            self._attendre(ms - (states.get('last', 0)))
            states['last'] = ms
            states[ms] = self.page.evaluate(
                "document.querySelector('.nx-table-loading') ? "
                "getComputedStyle(document.querySelector('.nx-table-loading')).display : 'absent'")
        self.assertTrue(
            any(v == 'flex' for v in states.values()),
            f"L'overlay de chargement doit apparaître pendant la recherche. États : {states}",
        )
        # après la réponse retardée : overlay masqué
        self._attendre(2500)
        overlay_gone = self.page.evaluate(
            "!document.querySelector('.nx-table-loading') || "
            "getComputedStyle(document.querySelector('.nx-table-loading')).display === 'none'")
        self.assertTrue(overlay_gone, "L'overlay de chargement doit disparaître après la recherche")
        self.page.unroute('**/articles/?*')

    # ──────────────────────────────────────────────────────────────────
    # Charge réaliste : 200 articles, recherche, tri, pagination
    # ──────────────────────────────────────────────────────────────────
    def test_charge_200_articles_recherche_tri_pagination(self):
        """Simule l'utilisation réelle avec 200 articles :
        - le chargement de la page reste fluide (< 3 s)
        - la recherche filtre instantanément (AJAX + debounce)
        - le tri par défaut (plus récent d'abord) est respecté
        - la pagination navigue sur plusieurs pages sans erreur
        """
        from datetime import timedelta
        from django.utils import timezone
        from stock.models import Article as ArticleModel

        # 200 articles supplémentaires
        articles = [
            ArticleModel(
                designation=f'Article charge E2E {i:03d}',
                famille=self.famille,
                reference=f'E2E-CHG-{i:03d}',
                unite_distribution='Boîte',
                cree_par=self.user,
            )
            for i in range(200)
        ]
        ArticleModel.objects.bulk_create(articles)
        # date_creation est auto_now_add : on la décale explicitement via
        # update() (qui ne passe pas par save()) pour tester le tri
        # « plus récent d'abord » de façon déterministe.
        now = timezone.now()
        for i in range(200):
            ArticleModel.objects.filter(reference=f'E2E-CHG-{i:03d}').update(
                date_creation=now - timedelta(minutes=200 - i))

        # 1) Chargement fluide : la navigation complète (DOM + rendu)
        #    répond en moins de 3 s avec 200 articles
        self._se_connecter('/articles/', magasin=self.mag_a)
        import time as _time
        start = _time.monotonic()
        self.page.goto(
            self.live_server_url + '/articles/', wait_until='domcontentloaded')
        self._attendre(600)
        elapsed = (_time.monotonic() - start) * 1000
        self.assertLess(
            elapsed, 3000,
            f"Chargement trop lent avec 200 articles : {elapsed:.0f} ms",
        )
        body = self.page.inner_text('body')
        self.assertNotIn('Traceback', body)
        self.assertNotIn('Internal Server Error', body)

        # 2) Compteur : 200 articles + celui du setUp = 201
        self.assertIn('sur', body)
        self.assertIn('201', self.page.inner_text('.pagination-info'))

        # 3) Tri par défaut : le plus récent (Article charge E2E 199) en premier
        premieres_lignes = self.page.inner_text('#tbody-articles')
        self.assertIn('Article charge E2E 199', premieres_lignes)
        self.assertNotIn('Article charge E2E 000', premieres_lignes)

        # 4) Pagination sur plusieurs pages
        page2 = self.page.locator('a.page-btn[href*="page=2"]')
        self.assertGreater(page2.count(), 0, 'Lien page 2 absent')
        page2.first.click()
        self._attendre(900)
        self.assertIn('page=2', self.page.url)
        lignes_p2 = self.page.inner_text('#tbody-articles')
        self.assertIn('Article charge E2E 184', lignes_p2)
        self.assertNotIn('Article charge E2E 199', lignes_p2)

        # Dernière page (201 articles / 15 par page = 14 pages)
        last = self.page.locator('a.page-btn[href*="page=14"]')
        self.assertGreater(last.count(), 0, 'Lien page 14 absent')
        last.first.click()
        self._attendre(900)
        self.assertIn('page=14', self.page.url)
        self.assertIn(
            'Article charge E2E 000', self.page.inner_text('#tbody-articles'))

        # 5) Recherche AJAX : filtre précis et rapide
        self.page.click('#search-q')
        self.page.fill('#search-q', 'charge E2E 042')
        self.page.press('#search-q', 'Enter')
        self._attendre(900)
        self.assertIn(
            'Article charge E2E 042', self.page.inner_text('#tbody-articles'))
        # Un seul résultat → compteur « 1 - 1 sur 1 »
        info = self.page.inner_text('.pagination-info')
        self.assertIn('1 - 1', info)
        self.assertIn('sur 1', info)

        # 6) Recherche large : 200 résultats attendus (le préfixe « charge E2E »)
        self.page.click('#search-q')
        self.page.fill('#search-q', 'charge E2E')
        self.page.press('#search-q', 'Enter')
        self._attendre(900)
        info2 = self.page.inner_text('.pagination-info')
        self.assertIn('sur 200', info2)

    # ──────────────────────────────────────────────────────────────────
    # Dashboard : rendu des nouveaux graphiques avec données réelles
    # ──────────────────────────────────────────────────────────────────
    def test_dashboard_graphiques_rendus_avec_donnees(self):
        """Le dashboard initialise les 5 graphiques (Chart.js) avec de
        vraies données : flux 14j, valeur par famille, top entrées,
        top articles et top services."""
        from datetime import timedelta
        from decimal import Decimal
        from django.utils import timezone
        from stock.models import Article as Art, StockItem, Mouvement, Service

        # Articles valorisés (CMUP renseignée)
        art1 = Art.objects.create(
            designation='Dashboard Graph A', famille=self.famille,
            reference='E2E-GRAPH-A', prix_reference=Decimal('100'))
        art2 = Art.objects.create(
            designation='Dashboard Graph B', famille=self.famille,
            reference='E2E-GRAPH-B', prix_reference=Decimal('250'))
        StockItem.objects.create(
            article=art1, magasin=self.mag_a,
            quantite_physique=50, valeur_cmup=Decimal('95'))
        StockItem.objects.create(
            article=art2, magasin=self.mag_a,
            quantite_physique=100, valeur_cmup=Decimal('240'))

        # Mouvements répartis sur 14 jours (flux) — update_stock=False
        # pour ne pas altérer les valeurs CMUP déclarées ci-dessus.
        now = timezone.now()
        for jour in range(14):
            date = now - timedelta(days=jour)
            for _ in range(3):
                Mouvement(
                    article=art1, magasin=self.mag_a, type_mouvement='ENTREE',
                    quantite=5, date_mouvement=date,
                    utilisateur=self.user).save(update_stock=False)
            for _ in range(2):
                Mouvement(
                    article=art2, magasin=self.mag_a, type_mouvement='SORTIE',
                    quantite=2, date_mouvement=date,
                    utilisateur=self.user).save(update_stock=False)

        # Service demandeur pour le top services
        svc = Service.objects.create(
            code='E2E-SVC', nom='Service Graph E2E')
        for _ in range(5):
            Mouvement(
                article=art2, magasin=self.mag_a, type_mouvement='SORTIE',
                quantite=3, date_mouvement=now - timedelta(days=1),
                service_demandeur=svc,
                utilisateur=self.user).save(update_stock=False)

        # Dashboard à la racine — pas de magasin actif → toutes les données
        self._se_connecter('/')

        # Chart.js (CDN) doit être chargé avant d'interroger les instances
        self.page.wait_for_function(
            "typeof window.Chart !== 'undefined'", timeout=15000)
        self._attendre(600)

        # 1) Les 5 canvas existent
        for cid in ('chartFlux', 'chartFamilles', 'chartEntrees',
                    'chartArticles', 'chartServices'):
            self.assertGreater(
                self.page.locator(f'#{cid}').count(), 0,
                f'Canvas #{cid} absent du dashboard')

        # 2) Chart.js les a initialisés avec le bon type
        types = self.page.evaluate("""() => {
            const ids = ['chartFlux','chartFamilles','chartEntrees',
                         'chartArticles','chartServices'];
            const out = {};
            for (const id of ids) {
                const canvas = document.getElementById(id);
                const chart = canvas && window.Chart.getChart
                    ? Chart.getChart(canvas) : null;
                out[id] = chart ? chart.config.type : null;
            }
            return out;
        }""")
        self.assertEqual(types['chartFlux'], 'line')
        self.assertEqual(types['chartFamilles'], 'doughnut')
        self.assertEqual(types['chartEntrees'], 'bar')
        self.assertEqual(types['chartArticles'], 'bar')
        self.assertEqual(types['chartServices'], 'doughnut')

        # 3) Données réelles injectées dans le flux (14 jours, entrées non nulles)
        flux_labels = self.page.evaluate(
            "Chart.getChart(document.getElementById('chartFlux')).data.labels.length")
        self.assertEqual(flux_labels, 14)
        flux_entrees_total = self.page.evaluate(
            "Chart.getChart(document.getElementById('chartFlux'))"
            ".data.datasets[0].data.reduce((a,b)=>a+b,0)")
        self.assertGreater(
            flux_entrees_total, 0,
            "Le flux d'entrées doit contenir des quantités réelles")

        # 4) KPI valeur du stock affiché (50×95 + 100×240 = 28750 F).
        # Le libellé est rendu en MAJUSCULES par le CSS (.kpi-lbl).
        body = self.page.inner_text('body')
        self.assertIn('VALEUR STOCK CMUP', body.upper())
        self.assertIn('28750', body.replace('\u202f', '').replace(' ', ''))
