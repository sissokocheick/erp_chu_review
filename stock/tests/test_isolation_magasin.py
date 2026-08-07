"""
Tests d'isolation par magasin - Vérification des règles d'accès

Ces tests valident que l'isolation par magasin fonctionne correctement :
1. Superuser a accès à TOUS les magasins
2. Utilisateur avec profil a accès aux magasins autorisés uniquement
3. Utilisateur sans profil n'a AUCUN accès
4. Les vues filtrent correctement les données
"""

from django.test import TestCase, RequestFactory
from django.contrib.auth import get_user_model
from django.db.models import QuerySet

from stock.models import Magasin, Article, BonMouvement
from stock.services.isolation_service import (
    get_magasins_autorises,
    verifier_acces_magasin,
    filtrer_par_magasins
)
from accounts.models import Profil

User = get_user_model()


class IsolationMagasinTest(TestCase):
    """Tests unitaires pour l'isolation par magasin."""

    @classmethod
    def setUpTestData(cls):
        """Création des données de test une seule fois."""
        # Créer 3 magasins
        cls.magasin1 = Magasin.objects.create(
            nom='Magasin Central',
            code='MC001',
            adresse='Avenue Principale'
        )
        cls.magasin2 = Magasin.objects.create(
            nom='Pharmacie Centrale',
            code='PH001',
            adresse='Rue de la Santé'
        )
        cls.magasin3 = Magasin.objects.create(
            nom='Dépôt Logistique',
            code='DL001',
            adresse='Zone Industrielle'
        )

        # Créer un superuser
        cls.superuser = User.objects.create_superuser(
            username='admin',
            email='admin@hopital.com',
            password='admin123'
        )

        # Créer un utilisateur standard avec profil
        cls.user_standard = User.objects.create_user(
            username='user_std',
            email='user@hopital.com',
            password='user123'
        )
        cls.profil_std = Profil.objects.create(
            user=cls.user_standard,
            telephone='+243999999999'
        )
        # Autoriser uniquement magasin1 et magasin2
        cls.profil_std.magasins_autorises.add(cls.magasin1, cls.magasin2)

        # Créer un utilisateur sans profil
        cls.user_sans_profil = User.objects.create_user(
            username='user_noprofil',
            email='noprofil@hopital.com',
            password='test123'
        )

        # Créer des articles dans différents magasins
        cls.article1 = Article.objects.create(
            reference='REF001',
            designation='Article Magasin 1',
            unite_mesure='UNIT',
            magasin=cls.magasin1
        )
        cls.article2 = Article.objects.create(
            reference='REF002',
            designation='Article Magasin 2',
            unite_mesure='UNIT',
            magasin=cls.magasin2
        )
        cls.article3 = Article.objects.create(
            reference='REF003',
            designation='Article Magasin 3',
            unite_mesure='UNIT',
            magasin=cls.magasin3
        )

    def setUp(self):
        """Initialisation avant chaque test."""
        self.factory = RequestFactory()

    def _create_request(self, user):
        """Crée une requête fake avec un utilisateur."""
        request = self.factory.get('/stock/')
        request.user = user
        return request

    # ═══════════════════════════════════════════════════════════════════════
    # TESTS : get_magasins_autorises
    # ═══════════════════════════════════════════════════════════════════════

    def test_superuser_acces_tous_magasins(self):
        """Le superuser doit avoir accès à TOUS les magasins."""
        request = self._create_request(self.superuser)
        magasins = get_magasins_autorises(request)

        self.assertIsInstance(magasins, QuerySet)
        self.assertEqual(magasins.count(), 3)
        self.assertIn(self.magasin1, magasins)
        self.assertIn(self.magasin2, magasins)
        self.assertIn(self.magasin3, magasins)

    def test_user_standard_acces_limit(self):
        """Un utilisateur standard n'a accès qu'aux magasins autorisés."""
        request = self._create_request(self.user_standard)
        magasins = get_magasins_autorises(request)

        self.assertIsInstance(magasins, QuerySet)
        self.assertEqual(magasins.count(), 2)
        self.assertIn(self.magasin1, magasins)
        self.assertIn(self.magasin2, magasins)
        self.assertNotIn(self.magasin3, magasins)

    def test_user_sans_profil_aucun_acces(self):
        """Un utilisateur sans profil ne doit avoir AUCUN accès."""
        request = self._create_request(self.user_sans_profil)
        magasins = get_magasins_autorises(request)

        self.assertIsInstance(magasins, QuerySet)
        self.assertEqual(magasins.count(), 0)

    def test_retour_toujours_queryset(self):
        """La fonction doit TOUJOURS retourner un QuerySet, jamais None."""
        request = self._create_request(self.user_sans_profil)
        magasins = get_magasins_autorises(request)

        self.assertIsNotNone(magasins)
        self.assertIsInstance(magasins, QuerySet)

    # ═══════════════════════════════════════════════════════════════════════
    # TESTS : verifier_acces_magasin
    # ═══════════════════════════════════════════════════════════════════════

    def test_verifier_acces_magasin_superuser(self):
        """Le superuser doit avoir accès à tous les magasins."""
        request = self._create_request(self.superuser)

        self.assertTrue(verifier_acces_magasin(request, self.magasin1.id))
        self.assertTrue(verifier_acces_magasin(request, self.magasin2.id))
        self.assertTrue(verifier_acces_magasin(request, self.magasin3.id))

    def test_verifier_acces_magasin_user_standard(self):
        """L'utilisateur standard ne doit avoir accès qu'aux magasins autorisés."""
        request = self._create_request(self.user_standard)

        self.assertTrue(verifier_acces_magasin(request, self.magasin1.id))
        self.assertTrue(verifier_acces_magasin(request, self.magasin2.id))
        self.assertFalse(verifier_acces_magasin(request, self.magasin3.id))

    def test_verifier_acces_magasin_sans_profil(self):
        """Un utilisateur sans profil ne doit avoir accès à aucun magasin."""
        request = self._create_request(self.user_sans_profil)

        self.assertFalse(verifier_acces_magasin(request, self.magasin1.id))
        self.assertFalse(verifier_acces_magasin(request, self.magasin2.id))
        self.assertFalse(verifier_acces_magasin(request, self.magasin3.id))

    # ═══════════════════════════════════════════════════════════════════════
    # TESTS : filtrer_par_magasins
    # ═══════════════════════════════════════════════════════════════════════

    def test_filtrer_articles_superuser(self):
        """Le superuser doit voir TOUS les articles."""
        request = self._create_request(self.superuser)
        queryset = Article.objects.all()
        filtre = filtrer_par_magasins(queryset, request, field_name='magasin')

        self.assertEqual(filtre.count(), 3)

    def test_filtrer_articles_user_standard(self):
        """L'utilisateur standard ne doit voir que les articles de ses magasins."""
        request = self._create_request(self.user_standard)
        queryset = Article.objects.all()
        filtre = filtrer_par_magasins(queryset, request, field_name='magasin')

        self.assertEqual(filtre.count(), 2)
        self.assertIn(self.article1, filtre)
        self.assertIn(self.article2, filtre)
        self.assertNotIn(self.article3, filtre)

    def test_filtrer_articles_sans_profil(self):
        """Un utilisateur sans profil ne doit voir AUCUN article."""
        request = self._create_request(self.user_sans_profil)
        queryset = Article.objects.all()
        filtre = filtrer_par_magasins(queryset, request, field_name='magasin')

        self.assertEqual(filtre.count(), 0)

    def test_filtrer_queryset_vide(self):
        """Filtrer un queryset vide doit retourner un queryset vide."""
        request = self._create_request(self.superuser)
        queryset = Article.objects.filter(reference='INEXISTANT')
        filtre = filtrer_par_magasins(queryset, request, field_name='magasin')

        self.assertEqual(filtre.count(), 0)


class IsolationMagasinIntegrationTest(TestCase):
    """Tests d'intégration pour l'isolation dans les vues."""

    @classmethod
    def setUpTestData(cls):
        """Création des données de test."""
        cls.magasin1 = Magasin.objects.create(
            nom='Magasin Test 1',
            code='MT001'
        )
        cls.magasin2 = Magasin.objects.create(
            nom='Magasin Test 2',
            code='MT002'
        )

        cls.user1 = User.objects.create_user(
            username='user_mag1',
            password='test123'
        )
        cls.profil1 = Profil.objects.create(user=cls.user1)
        cls.profil1.magasins_autorises.add(cls.magasin1)

        cls.superuser = User.objects.create_superuser(
            username='admin_test',
            password='admin123'
        )

    def test_isolation_bons_mouvement(self):
        """Les bons de mouvement doivent être isolés par magasin."""
        from stock.models import BonMouvement

        # Créer des BS dans différents magasins
        bs1 = BonMouvement.objects.create(
            type_bon='BS',
            numero='BS001',
            magasin=self.magasin1,
            statut='VALIDE'
        )
        bs2 = BonMouvement.objects.create(
            type_bon='BS',
            numero='BS002',
            magasin=self.magasin2,
            statut='VALIDE'
        )

        # User1 ne doit voir que le BS de son magasin
        request = RequestFactory().get('/stock/sorties/')
        request.user = self.user1

        from stock.services.isolation_service import filtrer_par_magasins
        bs_filter = filtrer_par_magasins(
            BonMouvement.objects.filter(type_bon='BS'),
            request,
            field_name='magasin'
        )

        self.assertEqual(bs_filter.count(), 1)
        self.assertIn(bs1, bs_filter)
        self.assertNotIn(bs2, bs_filter)

        # Superuser doit tout voir
        request.user = self.superuser
        bs_all = filtrer_par_magasins(
            BonMouvement.objects.filter(type_bon='BS'),
            request,
            field_name='magasin'
        )
        self.assertEqual(bs_all.count(), 2)
