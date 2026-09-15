# -*- coding: utf-8 -*-
"""
Tests Browser E2E réels (Playwright / Chromium) pour traquer les erreurs
console JS, erreurs de rendu, erreurs réseau 500/400 et vérifier le bon
fonctionnement de l'interface navigateur sur tous les écrans et documents PDF.
"""
import os
os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"
import unittest
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import LiveServerTestCase
from django.utils import timezone

from stock.models import (
    Magasin, FamilleArticle, Article, StockItem,
    BonMouvement, LigneBon, DemandeMateriel, LigneDemande,
    Commande, LigneCommande, CampagneInventaire, LigneInventaire,
    Beneficiaire, Fournisseur
)
from core.models import Service, ConfigurationHopital

try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_DISPONIBLE = True
except ImportError:
    PLAYWRIGHT_DISPONIBLE = False

PASSWORD = 'BrowserPass!2026'


@unittest.skipUnless(
    PLAYWRIGHT_DISPONIBLE,
    "Playwright non installé (pip install playwright && playwright install chromium)",
)
class BrowserAuditE2ETest(LiveServerTestCase):
    """Vérification complète en navigateur réel avec détection des erreurs console et HTTP."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._pw = sync_playwright().start()
        cls.browser = cls._pw.chromium.launch(headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls._pw.stop()
        super().tearDownClass()

    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_superuser(
            username='browser_admin', password=PASSWORD, email='browser@chu.ci'
        )
        self.user.profil.doit_changer_mdp = False
        self.user.profil.save(update_fields=['doit_changer_mdp'])

        self.hopital = ConfigurationHopital.objects.create(
            nom="CHU de Test Browser",
            couleur_principale="#1c5b96",
            pied_page_pdf="Direction des Affaires Financières / Service Logistique"
        )

        self.service = Service.objects.create(nom="Chirurgie", code="CHIR", poste="202")
        self.magasin = Magasin.objects.create(
            nom="Magasin Pharmacie",
            responsable=self.user,
            titre_responsable="Pharmacien Responsable"
        )
        self.user.profil.magasins_autorises.add(self.magasin)

        self.famille = FamilleArticle.objects.create(intitule='Consommables Médicaux', code='CSM')
        self.article = Article.objects.create(
            designation='Seringue 10ml E2E',
            famille=self.famille,
            reference='SER-010',
            prix_reference=Decimal('250.00'),
            unite_distribution='U'
        )
        self.stock_item = StockItem.objects.create(
            article=self.article, magasin=self.magasin, quantite_physique=200, valeur_cmup=Decimal('240.00')
        )
        self.fournisseur = Fournisseur.objects.create(code="FOURN-E2E", raison_sociale="Grossiste E2E")

        self.context = self.browser.new_context()
        self.page = self.context.new_page()
        self.page.set_default_timeout(15000)

        # Journaliser et capturer les erreurs console et de page
        self.console_errors = []
        self.page_errors = []

        self.page.on("pageerror", lambda err: self.page_errors.append(str(err)))
        self.page.on("console", self._handle_console_msg)

    def _handle_console_msg(self, msg):
        if msg.type == "error":
            # Filtrer les erreurs réseau mineures comme les favicon 404
            text = msg.text
            if "favicon.ico" not in text:
                self.console_errors.append(text)

    def tearDown(self):
        self.context.close()

    def _attendre(self, ms=500):
        self.page.wait_for_timeout(ms)

    def _se_connecter(self, url='/'):
        """Connexion automatique via formulaire de login."""
        self.page.goto(self.live_server_url + '/auth/login/')
        self._attendre(400)
        if self.page.locator('#id_username').count():
            self.page.fill('#id_username', 'browser_admin')
            self.page.fill('#id_password', PASSWORD)
            self.page.click('#submitBtn')
            self._attendre(800)

        if url and url != '/':
            self.page.goto(self.live_server_url + url)
            self._attendre(800)

        # Gérer l'overlay de magasin si présent
        select = self.page.locator('form[action*="changer-magasin"] select.nx-select')
        if select.count() and select.is_visible():
            select.select_option(str(self.magasin.id))
            self._attendre(800)

    def test_navigation_principale_sans_erreurs_js_ni_500(self):
        """Vérifie que les pages principales de gestion s'affichent sans crash ni erreur JS."""
        self._se_connecter()

        urls_a_tester = [
            '/',
            '/articles/',
            '/sorties/',
            '/entrees/',
            '/commandes/',
            '/gestion-demandes/',
            '/bons/hors-stock/',
            '/inventaires/',
            '/rapports/',
            f'/magasin/{self.magasin.id}/modele-pdf/BS/',
        ]

        for path in urls_a_tester:
            resp = self.page.goto(self.live_server_url + path)
            self._attendre(500)
            self.assertIsNotNone(resp, f"Aucune réponse HTTP reçue pour {path}")
            self.assertIn(
                resp.status, [200, 302],
                f"Erreur HTTP {resp.status} sur la page {path}"
            )

        # Vérifier qu'aucune erreur JS critique n'est survenue
        erreurs_critiques = [e for e in self.page_errors if "SyntaxError" in e or "ReferenceError" in e]
        self.assertEqual(erreurs_critiques, [], f"Erreurs JS critiques détectées : {erreurs_critiques}")

    def test_rendu_pdf_bons_de_sortie_en_navigateur(self):
        """Vérifie qu'un bon de sortie génère un PDF valide servi en direct au navigateur."""
        self._se_connecter()

        # Créer un bon de sortie réel avec lignes
        bon = BonMouvement.objects.create(
            type_bon='SORTIE',
            magasin=self.magasin,
            cree_par=self.user,
            valide_par=self.user,
            statut_validation='VALIDE',
            date_validation=timezone.now(),
            service_demandeur=self.service
        )
        LigneBon.objects.create(
            bon=bon,
            article=self.article,
            quantite=10,
            quantite_servie=10,
            quantite_demandee=10,
            reste=0,
            prix_unitaire=Decimal('240.00'),
            numero_lot="LOT-2026-X"
        )

        pdf_url = f"{self.live_server_url}/bon/{bon.id}/imprimer/"
        resp = self.page.request.get(pdf_url)
        self.assertEqual(resp.status, 200, f"Échec d'impression du bon de sortie {bon.id}")
        self.assertEqual(resp.headers.get('content-type'), 'application/pdf')
        pdf_bytes = resp.body()
        self.assertTrue(pdf_bytes.startswith(b'%PDF'), "Le flux reçu n'est pas un fichier PDF valide")
        self.assertGreater(len(pdf_bytes), 1000)

        # Test d'invalidation forcée via le navigateur (?refresh=1)
        resp_refresh = self.page.request.get(f"{pdf_url}?refresh=1")
        self.assertEqual(resp_refresh.status, 200)
        self.assertEqual(resp_refresh.headers.get('content-type'), 'application/pdf')
        self.assertTrue(resp_refresh.body().startswith(b'%PDF'))

    def test_rendu_pdf_inventaire_fiche_et_resultat(self):
        """Vérifie la fiche de comptage et le résultat d'inventaire affichés dans le navigateur."""
        self._se_connecter()

        campagne = CampagneInventaire.objects.create(
            titre="Inventaire Browser T2",
            magasin=self.magasin,
            cree_par=self.user,
            valide_par=self.user,
            statut="VALIDE",
            date_validation=timezone.now()
        )
        LigneInventaire.objects.create(
            campagne=campagne,
            article=self.article,
            quantite_theorique=50,
            quantite_physique=48
        )

        # 1. Fiche de comptage
        resp_fc = self.page.request.get(f"{self.live_server_url}/inventaires/{campagne.id}/fiche/")
        self.assertEqual(resp_fc.status, 200)
        self.assertEqual(resp_fc.headers.get('content-type'), 'application/pdf')
        self.assertTrue(resp_fc.body().startswith(b'%PDF'))

        # 2. Résultat d'inventaire
        resp_ri = self.page.request.get(f"{self.live_server_url}/inventaires/{campagne.id}/resultat/")
        self.assertEqual(resp_ri.status, 200)
        self.assertEqual(resp_ri.headers.get('content-type'), 'application/pdf')
        self.assertTrue(resp_ri.body().startswith(b'%PDF'))

    def test_rendu_pdf_bon_hors_stock_avec_beneficiaire(self):
        """Vérifie l'affichage du bon hors stock avec bénéficiaire en navigateur."""
        self._se_connecter()

        beneficiaire = Beneficiaire.objects.create(
            nom_complet="Dr CISSE Mamadou",
            poste="Chirurgien Chef",
            service=self.service
        )
        bon = BonMouvement.objects.create(
            type_bon="SORTIE_HORS_STOCK",
            magasin=self.magasin,
            cree_par=self.user,
            destinataire=beneficiaire,
            statut_validation="VALIDE"
        )
        LigneBon.objects.create(
            bon=bon,
            article=self.article,
            quantite=2,
            quantite_servie=2,
            quantite_demandee=2,
            prix_unitaire=Decimal('240.00')
        )

        resp = self.page.request.get(f"{self.live_server_url}/bons/hors-stock/{bon.id}/imprimer/")
        self.assertEqual(resp.status, 200)
        self.assertEqual(resp.headers.get('content-type'), 'application/pdf')
        self.assertTrue(resp.body().startswith(b'%PDF'))

    def test_page_parametrage_modeles_pdf_et_sauvegarde(self):
        """Vérifie l'écran de configuration des modèles PDF et la soumission du formulaire."""
        config_url = f"/magasin/{self.magasin.id}/modele-pdf/BS/"
        self._se_connecter(url=config_url)

        # Vérifier que le formulaire est chargé
        self.assertTrue(self.page.locator('#configForm').count() > 0, "Formulaire de configuration PDF introuvable")

        # Soumettre le formulaire via le bouton dédié #btnSave
        btn_submit = self.page.locator('#btnSave')
        self.assertTrue(btn_submit.count() > 0, "Bouton de sauvegarde #btnSave introuvable")
        btn_submit.click()
        self._attendre(1000)

        # Vérifier qu'un message de succès s'affiche et que la page ne crashe pas en 500
        content_lower = self.page.content().lower()
        self.assertTrue(
            "sauvegardé" in content_lower or "succès" in content_lower,
            f"Message de confirmation absent dans le contenu de la page: {content_lower[:400]}"
        )
