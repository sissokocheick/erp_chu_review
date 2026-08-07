"""
Tests de configuration PDF - Vérification de la hiérarchie de résolution

Ces tests valident que la configuration PDF suit correctement la hiérarchie :
1. ModeleDocumentMagasin (priorité maximale)
2. ConfigDocument (configuration globale)
3. Valeurs par défaut (fallback)
"""

from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model

from stock.models import Magasin, ModeleDocumentMagasin
from accounts.models import ConfigDocument
from stock.pdf_utils import get_pdf_config

User = get_user_model()


class ConfigurationPDFTest(TestCase):
    """Tests unitaires pour la configuration PDF."""

    @classmethod
    def setUpTestData(cls):
        """Création des données de test une seule fois."""
        # Créer un magasin
        cls.magasin = Magasin.objects.create(
            nom='Magasin Central',
            code='MC001',
            adresse='Avenue Principale'
        )

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
        ConfigDocument.objects.all().delete()

    # ═══════════════════════════════════════════════════════════════════════
    # TESTS : Valeurs par défaut
    # ═══════════════════════════════════════════════════════════════════════

    def test_config_par_defaut(self):
        """Sans ConfigDocument ni ModeleDocumentMagasin, utilise les valeurs par défaut."""
        request = self._create_request()
        config, logo_url = get_pdf_config(self.magasin, 'BS', request)

        # Vérifier les valeurs par défaut
        self.assertTrue(config['afficher_logo'])
        self.assertFalse(config['afficher_cachet'])
        self.assertFalse(config['afficher_cc'])
        self.assertFalse(config['afficher_ifu'])
        self.assertFalse(config['afficher_rccm'])
        self.assertTrue(config['afficher_telephone'])
        self.assertTrue(config['afficher_signatures'])
        self.assertEqual(config['code_document'], 'BS')
        self.assertEqual(config['version_doc'], '1.0')
        self.assertEqual(config['couleur_principale'], '#1c5b96')

    # ═══════════════════════════════════════════════════════════════════════
    # TESTS : ConfigDocument (configuration globale)
    # ═══════════════════════════════════════════════════════════════════════

    def test_config_document_globale(self):
        """ConfigDocument doit être appliqué comme configuration de base."""
        # Créer une configuration globale pour BS
        ConfigDocument.objects.create(
            type_doc='BS',
            afficher_logo=True,
            afficher_cachet=True,  # Différent du défaut
            afficher_cc=True,      # Différent du défaut
            afficher_ifu=True,     # Différent du défaut
            afficher_rccm=True,    # Différent du défaut
            afficher_telephone=False,  # Différent du défaut
            afficher_signatures=True,
            code_document='BS-FORM-001',
            version_doc='2.0',
        )

        request = self._create_request()
        config, logo_url = get_pdf_config(self.magasin, 'BS', request)

        # Vérifier que la config globale est appliquée
        self.assertTrue(config['afficher_logo'])
        self.assertTrue(config['afficher_cachet'])  # Écrasé par ConfigDocument
        self.assertTrue(config['afficher_cc'])      # Écrasé par ConfigDocument
        self.assertTrue(config['afficher_ifu'])     # Écrasé par ConfigDocument
        self.assertTrue(config['afficher_rccm'])    # Écrasé par ConfigDocument
        self.assertFalse(config['afficher_telephone'])  # Écrasé par ConfigDocument
        self.assertEqual(config['code_document'], 'BS-FORM-001')
        self.assertEqual(config['version_doc'], '2.0')

    def test_config_document_autre_type_non_affecte(self):
        """ConfigDocument d'un type ne doit pas affecter les autres types."""
        # Créer config seulement pour BE
        ConfigDocument.objects.create(
            type_doc='BE',
            afficher_cachet=True,
        )

        request = self._create_request()
        config_bs, _ = get_pdf_config(self.magasin, 'BS', request)

        # BS doit utiliser les valeurs par défaut, pas celles de BE
        self.assertFalse(config_bs['afficher_cachet'])

    # ═══════════════════════════════════════════════════════════════════════
    # TESTS : ModeleDocumentMagasin (configuration spécifique)
    # ═══════════════════════════════════════════════════════════════════════

    def test_modele_magasin_ecrase_config_globale(self):
        """ModeleDocumentMagasin doit écraser ConfigDocument."""
        # Créer config globale
        ConfigDocument.objects.create(
            type_doc='BS',
            afficher_cachet=True,
            afficher_cc=True,
            couleur_principale='#FF0000',  # Rouge
        )

        # Créer modèle spécifique au magasin
        ModeleDocumentMagasin.objects.create(
            magasin=self.magasin,
            type_document='BS',
            est_actif=True,
            config={
                'afficher_cachet': False,  # Différent de ConfigDocument
                'couleur_principale': '#00FF00',  # Vert, différent de ConfigDocument
            }
        )

        request = self._create_request()
        config, logo_url = get_pdf_config(self.magasin, 'BS', request)

        # Le modèle magasin doit écraser la config globale
        self.assertFalse(config['afficher_cachet'])  # Du modèle magasin
        self.assertTrue(config['afficher_cc'])       # De ConfigDocument (non écrasé)
        self.assertEqual(config['couleur_principale'], '#00FF00')  # Du modèle magasin

    def test_modele_magasin_inactif_non_utilise(self):
        """Un modèle inactif ne doit pas être utilisé."""
        # Créer config globale
        ConfigDocument.objects.create(
            type_doc='BS',
            afficher_cachet=True,
        )

        # Créer modèle INACTIF
        ModeleDocumentMagasin.objects.create(
            magasin=self.magasin,
            type_document='BS',
            est_actif=False,  # Inactif
            config={
                'afficher_cachet': False,
            }
        )

        request = self._create_request()
        config, _ = get_pdf_config(self.magasin, 'BS', request)

        # Doit utiliser ConfigDocument, pas le modèle inactif
        self.assertTrue(config['afficher_cachet'])

    def test_modele_magasin_autre_magasin_non_affecte(self):
        """Le modèle d'un autre magasin ne doit pas affecter ce magasin."""
        autre_magasin = Magasin.objects.create(
            nom='Autre Magasin',
            code='AM001'
        )

        # Créer modèle seulement pour l'autre magasin
        ModeleDocumentMagasin.objects.create(
            magasin=autre_magasin,
            type_document='BS',
            est_actif=True,
            config={
                'afficher_cachet': True,
            }
        )

        request = self._create_request()
        config, _ = get_pdf_config(self.magasin, 'BS', request)

        # Notre magasin n'a pas de modèle, donc valeurs par défaut
        self.assertFalse(config['afficher_cachet'])

    # ═══════════════════════════════════════════════════════════════════════
    # TESTS : Hiérarchie complète
    # ═══════════════════════════════════════════════════════════════════════

    def test_hierarchie_complete(self):
        """Test complet de la hiérarchie : Défaut < ConfigDocument < ModeleMagasin."""
        # Niveau 1 : ConfigDocument
        ConfigDocument.objects.create(
            type_doc='BS',
            afficher_logo=True,
            afficher_cachet=True,
            afficher_cc=True,
            afficher_ifu=True,
            afficher_rccm=True,
            afficher_telephone=True,
            afficher_signatures=True,
            code_document='BS-GLOBAL',
            version_doc='1.5',
            couleur_principale='#FF0000',
        )

        # Niveau 2 : ModeleMagasin (écrase partiellement)
        ModeleDocumentMagasin.objects.create(
            magasin=self.magasin,
            type_document='BS',
            est_actif=True,
            config={
                'afficher_cachet': False,  # Écrase ConfigDocument
                'couleur_principale': '#0000FF',  # Écrase ConfigDocument
                # afficher_cc reste de ConfigDocument
            }
        )

        request = self._create_request()
        config, logo_url = get_pdf_config(self.magasin, 'BS', request)

        # Vérifier la hiérarchie
        self.assertTrue(config['afficher_logo'])      # ConfigDocument
        self.assertFalse(config['afficher_cachet'])   # ModeleMagasin (écrase)
        self.assertTrue(config['afficher_cc'])        # ConfigDocument
        self.assertTrue(config['afficher_ifu'])       # ConfigDocument
        self.assertTrue(config['afficher_rccm'])      # ConfigDocument
        self.assertTrue(config['afficher_telephone']) # ConfigDocument
        self.assertTrue(config['afficher_signatures'])# ConfigDocument
        self.assertEqual(config['code_document'], 'BS-GLOBAL')  # ConfigDocument
        self.assertEqual(config['version_doc'], '1.5')  # ConfigDocument
        self.assertEqual(config['couleur_principale'], '#0000FF')  # ModeleMagasin (écrase)

    def test_pas_de_config_document_avec_modele_magasin(self):
        """ModeleMagasin seul (sans ConfigDocument) doit fonctionner."""
        ModeleDocumentMagasin.objects.create(
            magasin=self.magasin,
            type_document='BS',
            est_actif=True,
            config={
                'afficher_cachet': True,
                'couleur_principale': '#FFFF00',
            }
        )

        request = self._create_request()
        config, _ = get_pdf_config(self.magasin, 'BS', request)

        self.assertTrue(config['afficher_cachet'])
        self.assertEqual(config['couleur_principale'], '#FFFF00')
        # Les autres champs doivent être aux valeurs par défaut
        self.assertFalse(config['afficher_cc'])

    # ═══════════════════════════════════════════════════════════════════════
    # TESTS : Gestion des erreurs et fallbacks
    # ═══════════════════════════════════════════════════════════════════════

    def test_magasin_none_utilise_config_globale(self):
        """Si magasin=None, utilise seulement ConfigDocument."""
        ConfigDocument.objects.create(
            type_doc='BS',
            afficher_cachet=True,
        )

        request = self._create_request()
        config, _ = get_pdf_config(None, 'BS', request)

        self.assertTrue(config['afficher_cachet'])

    def test_type_doc_non_configure(self):
        """Un type de document non configuré utilise les valeurs par défaut."""
        request = self._create_request()
        config, _ = get_pdf_config(self.magasin, 'BC', request)

        # BC n'a pas de configuration, donc défaut
        self.assertFalse(config['afficher_cachet'])
        self.assertEqual(config['code_document'], 'BC')
