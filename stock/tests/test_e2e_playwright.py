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
