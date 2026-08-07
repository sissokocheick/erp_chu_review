"""
Tests unitaires pour les services critiques du module stock.
Focus sur : BonService et StockTransactionService

Pour executer :
    python manage.py test stock.tests.test_services
"""

from decimal import Decimal
from unittest.mock import patch, MagicMock, PropertyMock
from datetime import date, timedelta

from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.core.exceptions import ValidationError, PermissionDenied
from django.apps import apps

User = get_user_model()


class BonServiceTest(TestCase):
    """Tests unitaires pour BonService."""

    def setUp(self):
        self.client = Client()
        
        # Configuration Hôpital (mono-tenant)
        from core.models import ConfigurationHopital
        self.config_hopital = ConfigurationHopital.get_instance()
        
        # Utilisateur de test
        self.user = User.objects.create_user(
            username="testuser",
            email="test@example.com",
            password="testpass123"
        )
        
        try:
            # Modèles nécessaires
            Magasin = apps.get_model('stock', 'Magasin')
            Article = apps.get_model('stock', 'Article')
            FamilleArticle = apps.get_model('stock', 'FamilleArticle')
            StockItem = apps.get_model('stock', 'StockItem')
            
            # Création des données de test
            self.famille = FamilleArticle.objects.create(
                nom="Famille Test",
                code="FAM-TEST"
            )
            
            self.magasin = Magasin.objects.create(
                nom="Magasin Principal",
                code="MP"
            )
            
            self.article = Article.objects.create(
                reference="ART-001",
                designation="Article Test",
                famille=self.famille,
                unite_mesure="UNITE"
            )
            
            self.stock_item = StockItem.objects.create(
                article=self.article,
                magasin=self.magasin,
                quantite_physique=100,
                valeur_cmup=Decimal('10.00')
            )
            
            # Import du service
            from stock.services.bon_service import BonService
            self.bon_service = BonService
            
        except LookupError as e:
            self.skipTest(f"Modèle manquant : {e}")

    def test_creer_bon_entree_valide(self):
        """Test la création d'un bon d'entrée valide."""
        lignes = [
            {
                'article_id': self.article.id,
                'quantite': 50,
                'prix_unitaire': Decimal('12.50'),
                'numero_lot': 'LOT-001',
                'date_peremption': str(date.today() + timedelta(days=365))
            }
        ]
        
        bon = self.bon_service.creer_bon_entree(
            lignes=lignes,
            utilisateur=self.user,
            magasin=self.magasin,
            commentaire="Test bon entrée"
        )
        
        # Vérifications
        self.assertIsNotNone(bon.pk)
        self.assertEqual(bon.type_bon, 'ENTREE')
        self.assertEqual(bon.statut_validation, 'VALIDE')
        self.assertEqual(bon.lignebon_set.count(), 1)
        
        ligne = bon.lignebon_set.first()
        self.assertEqual(ligne.quantite, 50)
        self.assertEqual(ligne.prix_unitaire, Decimal('12.50'))
        
        # Vérifier que le stock a été mis à jour
        self.stock_item.refresh_from_db()
        self.assertEqual(self.stock_item.quantite_physique, 150)

    def test_creer_bon_sortie_stock_insuffisant(self):
        """Test qu'une sortie avec stock insuffisant lève une ValidationError."""
        lignes = [
            {
                'article_id': self.article.id,
                'quantite': 150  # Plus que le stock disponible (100)
            }
        ]
        
        with self.assertRaises(ValidationError) as context:
            self.bon_service.creer_bon_sortie(
                lignes=lignes,
                utilisateur=self.user,
                magasin=self.magasin,
                circuit_validation=None  # Validation directe
            )
        
        self.assertIn('Stock insuffisant', str(context.exception))

    def test_creer_bon_sortie_valide(self):
        """Test la création d'un bon de sortie valide."""
        lignes = [
            {
                'article_id': self.article.id,
                'quantite': 30
            }
        ]
        
        bon = self.bon_service.creer_bon_sortie(
            lignes=lignes,
            utilisateur=self.user,
            magasin=self.magasin,
            circuit_validation=None,
            commentaire="Test bon sortie"
        )
        
        # Vérifications
        self.assertIsNotNone(bon.pk)
        self.assertEqual(bon.type_bon, 'SORTIE')
        self.assertEqual(bon.statut_validation, 'VALIDE')
        
        # Vérifier que le stock a été décrémenté
        self.stock_item.refresh_from_db()
        self.assertEqual(self.stock_item.quantite_physique, 70)

    def test_creer_bon_entree_article_inexistant(self):
        """Test qu'un article inexistant lève une ValidationError."""
        lignes = [
            {
                'article_id': 99999,  # ID inexistant
                'quantite': 10
            }
        ]
        
        with self.assertRaises(ValidationError) as context:
            self.bon_service.creer_bon_entree(
                lignes=lignes,
                utilisateur=self.user,
                magasin=self.magasin
            )
        
        self.assertIn('introuvable', str(context.exception).lower())

    def test_creer_bon_entree_quantite_invalide(self):
        """Test qu'une quantité invalide lève une ValidationError."""
        lignes = [
            {
                'article_id': self.article.id,
                'quantite': -5  # Quantité négative
            }
        ]
        
        with self.assertRaises(ValidationError) as context:
            self.bon_service.creer_bon_entree(
                lignes=lignes,
                utilisateur=self.user,
                magasin=self.magasin
            )
        
        self.assertIn('Quantité invalide', str(context.exception))

    def test_utilisateur_inactif_permission_denied(self):
        """Test qu'un utilisateur inactif ne peut pas créer de bon."""
        user_inactive = User.objects.create_user(
            username="inactive",
            email="inactive@example.com",
            password="testpass123",
            is_active=False
        )
        
        lignes = [
            {
                'article_id': self.article.id,
                'quantite': 10
            }
        ]
        
        with self.assertRaises(PermissionDenied) as context:
            self.bon_service.creer_bon_entree(
                lignes=lignes,
                utilisateur=user_inactive,
                magasin=self.magasin
            )
        
        self.assertIn('inactif', str(context.exception).lower())


class StockTransactionServiceTest(TestCase):
    """Tests unitaires pour StockTransactionService."""

    def setUp(self):
        try:
            # Modèles nécessaires
            Magasin = apps.get_model('stock', 'Magasin')
            Article = apps.get_model('stock', 'Article')
            FamilleArticle = apps.get_model('stock', 'FamilleArticle')
            StockItem = apps.get_model('stock', 'StockItem')
            Mouvement = apps.get_model('stock', 'Mouvement')
            
            # Création des données de test
            self.famille = FamilleArticle.objects.create(
                nom="Famille Test",
                code="FAM-TEST"
            )
            
            self.magasin = Magasin.objects.create(
                nom="Magasin Principal",
                code="MP"
            )
            
            self.article = Article.objects.create(
                reference="ART-001",
                designation="Article Test",
                famille=self.famille,
                unite_mesure="UNITE"
            )
            
            # Import du service
            from stock.services.stock_transaction_service import StockTransactionService
            self.transaction_service = StockTransactionService
            
        except LookupError as e:
            self.skipTest(f"Modèle manquant : {e}")

    def test_executer_mouvement_entree(self):
        """Test l'exécution d'un mouvement d'entrée."""
        mouvement = Mouvement(
            type_mouvement='ENTREE',
            article=self.article,
            magasin=self.magasin,
            quantite=50,
            prix_unitaire=Decimal('10.00'),
            utilisateur=None,
        )
        
        resultat = self.transaction_service.executer(mouvement)
        
        # Vérifications
        self.assertIsNotNone(resultat.pk)
        self.assertEqual(resultat.type_mouvement, 'ENTREE')
        
        # Vérifier que le stock a été créé/mis à jour
        stock_item = StockItem.objects.filter(
            article=self.article,
            magasin=self.magasin
        ).first()
        
        self.assertIsNotNone(stock_item)
        self.assertEqual(stock_item.quantite_physique, 50)
        self.assertEqual(stock_item.valeur_cmup, Decimal('10.00'))

    def test_executer_mouvement_sortie(self):
        """Test l'exécution d'un mouvement de sortie."""
        # Créer un stock initial
        StockItem.objects.create(
            article=self.article,
            magasin=self.magasin,
            quantite_physique=100,
            valeur_cmup=Decimal('10.00')
        )
        
        mouvement = Mouvement(
            type_mouvement='SORTIE',
            article=self.article,
            magasin=self.magasin,
            quantite=30,
            prix_unitaire=Decimal('10.00'),
            utilisateur=None,
        )
        
        resultat = self.transaction_service.executer(mouvement)
        
        # Vérifications
        self.assertIsNotNone(resultat.pk)
        
        # Vérifier que le stock a été décrémenté
        stock_item = StockItem.objects.filter(
            article=self.article,
            magasin=self.magasin
        ).first()
        
        self.assertEqual(stock_item.quantite_physique, 70)
        # Le CMUP doit rester inchangé après une sortie
        self.assertEqual(stock_item.valeur_cmup, Decimal('10.00'))

    def test_executer_mouvement_sortie_stock_insuffisant(self):
        """Test qu'une sortie avec stock insuffisant lève une ValidationError."""
        # Créer un stock initial faible
        StockItem.objects.create(
            article=self.article,
            magasin=self.magasin,
            quantite_physique=10,
            valeur_cmup=Decimal('10.00')
        )
        
        mouvement = Mouvement(
            type_mouvement='SORTIE',
            article=self.article,
            magasin=self.magasin,
            quantite=50,  # Plus que le stock
            prix_unitaire=Decimal('10.00'),
            utilisateur=None,
        )
        
        with self.assertRaises(ValidationError) as context:
            self.transaction_service.executer(mouvement)
        
        self.assertIn('Stock insuffisant', str(context.exception))

    def test_executer_batch_atomique(self):
        """Test l'exécution batch atomique de plusieurs mouvements."""
        mouvements = [
            Mouvement(
                type_mouvement='ENTREE',
                article=self.article,
                magasin=self.magasin,
                quantite=20,
                prix_unitaire=Decimal('10.00'),
                utilisateur=None,
            ),
            Mouvement(
                type_mouvement='ENTREE',
                article=self.article,
                magasin=self.magasin,
                quantite=30,
                prix_unitaire=Decimal('12.00'),
                utilisateur=None,
            )
        ]
        
        resultats = self.transaction_service.executer_batch(mouvements)
        
        # Vérifications
        self.assertEqual(len(resultats), 2)
        
        stock_item = StockItem.objects.filter(
            article=self.article,
            magasin=self.magasin
        ).first()
        
        self.assertEqual(stock_item.quantite_physique, 50)
        # Vérifier le CMUP recalculé (moyenne pondérée)
        # (10*20 + 12*30) / 50 = (200 + 360) / 50 = 11.20
        self.assertAlmostEqual(float(stock_item.valeur_cmup), 11.20, places=2)

    def test_annuler_par_contre_mouvement(self):
        """Test l'annulation d'un mouvement par contre-mouvement."""
        from django.contrib.auth import get_user_model
        User = get_user_model()
        user = User.objects.create_user(
            username="testuser2",
            email="test2@example.com",
            password="testpass123"
        )
        
        # Créer un mouvement d'entrée
        mouvement_original = Mouvement(
            type_mouvement='ENTREE',
            article=self.article,
            magasin=self.magasin,
            quantite=50,
            prix_unitaire=Decimal('10.00'),
            utilisateur=user,
        )
        
        self.transaction_service.executer(mouvement_original)
        
        # Annuler le mouvement
        contre_mouvement = self.transaction_service.annuler_par_contre_mouvement(
            mouvement_original=mouvement_original,
            utilisateur=user,
            commentaire="Test annulation"
        )
        
        # Vérifications
        self.assertIsNotNone(contre_mouvement.pk)
        self.assertEqual(contre_mouvement.type_mouvement, 'RETOUR_FOURNISSEUR')
        self.assertEqual(contre_mouvement.quantite, 50)
        
        # Le mouvement original doit être marqué comme annulé
        mouvement_original.refresh_from_db()
        self.assertTrue(mouvement_original.est_annule)
        
        # Le stock doit revenir à 0
        stock_item = StockItem.objects.filter(
            article=self.article,
            magasin=self.magasin
        ).first()
        self.assertEqual(stock_item.quantite_physique, 0)

    def test_executer_mouvement_hors_stock(self):
        """Test qu'un mouvement hors stock ne modifie pas le StockItem."""
        # Créer un stock initial
        StockItem.objects.create(
            article=self.article,
            magasin=self.magasin,
            quantite_physique=100,
            valeur_cmup=Decimal('10.00')
        )
        
        mouvement = Mouvement(
            type_mouvement='SORTIE_HORS_STOCK',
            article=self.article,
            magasin=self.magasin,
            quantite=50,
            prix_unitaire=Decimal('10.00'),
            utilisateur=None,
        )
        
        resultat = self.transaction_service.executer(mouvement)
        
        # Vérifications
        self.assertIsNotNone(resultat.pk)
        
        # Le stock ne doit PAS être modifié
        stock_item = StockItem.objects.filter(
            article=self.article,
            magasin=self.magasin
        ).first()
        
        self.assertEqual(stock_item.quantite_physique, 100)  # Inchangé

    def test_ajustement_neg_force_bloque_a_zero(self):
        """Test qu'un ajustement négatif forcé bloque à 0."""
        # Créer un stock initial
        StockItem.objects.create(
            article=self.article,
            magasin=self.magasin,
            quantite_physique=10,
            valeur_cmup=Decimal('10.00')
        )
        
        mouvement = Mouvement(
            type_mouvement='AJUSTEMENT_NEG_FORCE',
            article=self.article,
            magasin=self.magasin,
            quantite=50,  # Plus que le stock
            prix_unitaire=Decimal('10.00'),
            utilisateur=None,
        )
        
        resultat = self.transaction_service.executer(mouvement)
        
        # Vérifications
        self.assertIsNotNone(resultat.pk)
        
        # Le stock doit être bloqué à 0 (pas négatif)
        stock_item = StockItem.objects.filter(
            article=self.article,
            magasin=self.magasin
        ).first()
        
        self.assertEqual(stock_item.quantite_physique, 0)


class CMUPCalculationTest(TestCase):
    """Tests spécifiques pour le calcul du CMUP."""

    def setUp(self):
        try:
            Magasin = apps.get_model('stock', 'Magasin')
            Article = apps.get_model('stock', 'Article')
            FamilleArticle = apps.get_model('stock', 'FamilleArticle')
            StockItem = apps.get_model('stock', 'StockItem')
            Mouvement = apps.get_model('stock', 'Mouvement')
            
            self.famille = FamilleArticle.objects.create(
                nom="Famille Test",
                code="FAM-TEST"
            )
            
            self.magasin = Magasin.objects.create(
                nom="Magasin Principal",
                code="MP"
            )
            
            self.article = Article.objects.create(
                reference="ART-001",
                designation="Article Test",
                famille=self.famille,
                unite_mesure="UNITE"
            )
            
            from stock.services.stock_transaction_service import StockTransactionService
            self.transaction_service = StockTransactionService
            
        except LookupError as e:
            self.skipTest(f"Modèle manquant : {e}")

    def test_cmup_moyenne_ponderee_entree(self):
        """Test le calcul de la moyenne pondérée pour les entrées."""
        # Première entrée : 100 unités à 10€
        mouvement1 = Mouvement(
            type_mouvement='ENTREE',
            article=self.article,
            magasin=self.magasin,
            quantite=100,
            prix_unitaire=Decimal('10.00'),
            utilisateur=None,
        )
        self.transaction_service.executer(mouvement1)
        
        # Deuxième entrée : 50 unités à 15€
        mouvement2 = Mouvement(
            type_mouvement='ENTREE',
            article=self.article,
            magasin=self.magasin,
            quantite=50,
            prix_unitaire=Decimal('15.00'),
            utilisateur=None,
        )
        self.transaction_service.executer(mouvement2)
        
        stock_item = StockItem.objects.filter(
            article=self.article,
            magasin=self.magasin
        ).first()
        
        # CMUP attendu : (100*10 + 50*15) / 150 = (1000 + 750) / 150 = 11.67
        self.assertEqual(stock_item.quantite_physique, 150)
        self.assertAlmostEqual(float(stock_item.valeur_cmup), 11.67, places=2)

    def test_cmup_conserve_apres_sortie(self):
        """Test que le CMUP est conservé après une sortie."""
        # Entrée initiale
        mouvement1 = Mouvement(
            type_mouvement='ENTREE',
            article=self.article,
            magasin=self.magasin,
            quantite=100,
            prix_unitaire=Decimal('10.00'),
            utilisateur=None,
        )
        self.transaction_service.executer(mouvement1)
        
        # Sortie partielle
        mouvement2 = Mouvement(
            type_mouvement='SORTIE',
            article=self.article,
            magasin=self.magasin,
            quantite=50,
            prix_unitaire=Decimal('10.00'),
            utilisateur=None,
        )
        self.transaction_service.executer(mouvement2)
        
        stock_item = StockItem.objects.filter(
            article=self.article,
            magasin=self.magasin
        ).first()
        
        # Le CMUP doit rester à 10.00
        self.assertEqual(stock_item.quantite_physique, 50)
        self.assertEqual(stock_item.valeur_cmup, Decimal('10.00'))
