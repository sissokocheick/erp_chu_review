"""
Tests de configuration PDF - Vérification de la hiérarchie de résolution

Ces tests valident que la configuration PDF suit correctement la hiérarchie :
1. ModeleDocumentMagasin (priorité maximale)
2. Valeurs par défaut (fallback, ex-ConfigDocument supprimé)
"""

from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model

from stock.models import Magasin, ModeleDocumentMagasin
from stock.pdf_utils import get_pdf_config

User = get_user_model()


class ConfigurationPDFTest(TestCase):
    """Tests unitaires pour la configuration PDF."""

    @classmethod
    def setUpTestData(cls):
        """Création des données de test une seule fois."""
        # Créer un magasin
        cls.magasin = Magasin.objects.create(nom='Magasin Central')

        # Créer un utilisateur pour les requêtes
        cls.user = User.objects.create_user(
            username='testuser',
            email='test@hopital.com',
            password='test123'
        )

    def setUp(self):
        """Initialisation avant chaque test."""
        self.factory = RequestFactory()

    def _create_request(self):
        """Crée une requête fake avec un utilisateur."""
        request = self.factory.get('/stock/')
        request.user = self.user
        return request

    def tearDown(self):
        """Nettoyage après chaque test."""
        ModeleDocumentMagasin.objects.all().delete()

    # ═══════════════════════════════════════════════════════════════════════
    # TESTS : Valeurs par défaut
    # ═══════════════════════════════════════════════════════════════════════

    def test_config_par_defaut(self):
        """Sans ModeleDocumentMagasin, utilise les valeurs par défaut."""
        request = self._create_request()
        config, logo_url = get_pdf_config(self.magasin, 'BS', request)

        # Vérifier les valeurs par défaut
        self.assertTrue(config['afficher_logo'])
        self.assertTrue(config['afficher_cachet'])
        self.assertTrue(config['afficher_cc'])
        self.assertTrue(config['afficher_ifu'])
        self.assertTrue(config['afficher_rccm'])
        self.assertTrue(config['afficher_telephone'])
        self.assertTrue(config['afficher_signatures'])
        # Défauts CHU (codes officiels, version 002)
        self.assertEqual(config['code_document'], 'ENR-BSM/DAF-001')
        self.assertEqual(config['metadonnees']['code_document'], 'ENR-BSM/DAF-001')
        self.assertTrue(config['cartouche']['afficher_republique'])
        self.assertTrue(config['cartouche']['afficher_devise'])
        self.assertEqual(config['direction_label'], 'DIRECTION DES AFFAIRES FINANCIÈRES')

    # ═══════════════════════════════════════════════════════════════════════
    # TESTS : ModeleDocumentMagasin (configuration spécifique)
    # ═══════════════════════════════════════════════════════════════════════

    def test_modele_magasin_ecrase_defauts(self):
        """ModeleDocumentMagasin doit écraser les valeurs par défaut."""
        # Créer modèle spécifique au magasin
        ModeleDocumentMagasin.objects.create(
            magasin=self.magasin,
            type_document='BS',
            est_actif=True,
            config={
                'cartouche': {'afficher_cc': False},  # Différent du défaut
                'pied_de_page': {'texte_personnalise': 'Pied magasin'},
            }
        )

        request = self._create_request()
        config, logo_url = get_pdf_config(self.magasin, 'BS', request)

        # Le modèle magasin doit écraser les défauts
        self.assertFalse(config['cartouche']['afficher_cc'])

    def test_modele_magasin_metadonnees_personnalisees(self):
        """Un modèle actif fournit des métadonnées personnalisées."""
        ModeleDocumentMagasin.objects.create(
            magasin=self.magasin,
            type_document='BS',
            est_actif=True,
            config={
                'metadonnees': {
                    'code_document': 'BS-MAGASIN-9',
                    'version_doc': '9.9',
                }
            }
        )

        request = self._create_request()
        config, _ = get_pdf_config(self.magasin, 'BS', request)

        self.assertEqual(config['code_document'], 'BS-MAGASIN-9')
        self.assertEqual(config['version_doc'], '9.9')

    def test_modele_magasin_inactif_non_utilise(self):
        """Un modèle inactif ne doit pas être utilisé."""
        # Créer modèle INACTIF
        ModeleDocumentMagasin.objects.create(
            magasin=self.magasin,
            type_document='BS',
            est_actif=False,  # Inactif
            config={
                'metadonnees': {'code_document': 'BS-INACTIF'},
            }
        )

        request = self._create_request()
        config, _ = get_pdf_config(self.magasin, 'BS', request)

        # Doit utiliser les valeurs par défaut, pas le modèle inactif
        self.assertEqual(config['code_document'], 'ENR-BSM/DAF-001')

    def test_modele_magasin_autre_magasin_non_affecte(self):
        """Le modèle d'un autre magasin ne doit pas affecter ce magasin."""
        autre_magasin = Magasin.objects.create(nom='Autre Magasin')

        # Créer modèle seulement pour l'autre magasin
        ModeleDocumentMagasin.objects.create(
            magasin=autre_magasin,
            type_document='BS',
            est_actif=True,
            config={
                'metadonnees': {'code_document': 'BS-AUTRE'},
            }
        )

        request = self._create_request()
        config, _ = get_pdf_config(self.magasin, 'BS', request)

        # Notre magasin n'a pas de modèle, donc valeurs par défaut
        self.assertEqual(config['code_document'], 'ENR-BSM/DAF-001')

    def test_modele_magasin_autre_type_non_affecte(self):
        """Le modèle d'un autre type de document ne doit pas affecter ce type."""
        ModeleDocumentMagasin.objects.create(
            magasin=self.magasin,
            type_document='BE',
            est_actif=True,
            config={
                'metadonnees': {'code_document': 'BE-PERSO'},
            }
        )

        request = self._create_request()
        config_bs, _ = get_pdf_config(self.magasin, 'BS', request)

        # BS doit utiliser les valeurs par défaut, pas celles de BE
        self.assertEqual(config_bs['code_document'], 'ENR-BSM/DAF-001')

    # ═══════════════════════════════════════════════════════════════════════
    # TESTS : Gestion des erreurs et fallbacks
    # ═══════════════════════════════════════════════════════════════════════

    def test_magasin_none_utilise_defauts(self):
        """Si magasin=None, utilise les valeurs par défaut."""
        request = self._create_request()
        config, _ = get_pdf_config(None, 'BS', request)

        self.assertTrue(config['afficher_cachet'])
        self.assertEqual(config['code_document'], 'ENR-BSM/DAF-001')

    def test_type_doc_non_configure(self):
        """Un type de document non configuré utilise les valeurs par défaut."""
        request = self._create_request()
        config, _ = get_pdf_config(self.magasin, 'BC', request)

        # BC n'a pas de configuration, donc défauts CHU (code officiel commande)
        self.assertEqual(config['code_document'], 'ENR-BCM/DAF-002')

    def test_logo_repli_statique_static_img(self):
        """Sans logo configuré, le PDF utilise le logo de stock/static/img."""
        request = self._create_request()
        _, logo_url = get_pdf_config(self.magasin, 'BS', request)

        # Le logo doit venir du dossier statique (data URI embarquable ou URL statique)
        self.assertIsNotNone(logo_url)
        self.assertTrue(
            logo_url.startswith('data:image') or '/static/img/logo.jpg' in logo_url,
            f"URL logo inattendue : {logo_url[:80]}"
        )

    def test_logo_magasin_prioritaire_sur_static(self):
        """Le logo du magasin prime sur le logo statique par défaut."""
        # Simuler un logo sur le magasin (fichier minimal valide)
        from django.core.files.uploadedfile import SimpleUploadedFile
        self.magasin.logo = SimpleUploadedFile(
            'logo_mag.png',
            b'\x89PNG\r\n\x1a\n' + b'0' * 32,
            content_type='image/png',
        )
        self.magasin.save()

        request = self._create_request()
        _, logo_url = get_pdf_config(self.magasin, 'BS', request)

        # Le logo du magasin prime : le repli statique ne doit pas être utilisé
        self.assertIsNotNone(logo_url)
        self.assertNotIn('static/img/logo.jpg', logo_url)
