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
    DJANGO_ALLOW_ASYNC_UNSAFE=1 DJANGO_SETTINGS_MODULE=config.settings_test \\
        python manage.py test stock.tests.test_e2e_playwright

(le DJANGO_ALLOW_ASYNC_UNSAFE est requis car Playwright sync tourne sa
propre boucle d'événements, ce que Django interprète comme un contexte async)
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
