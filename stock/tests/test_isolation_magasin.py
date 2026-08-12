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

from stock.models import Magasin, Article, StockItem, FamilleArticle, BonMouvement
from stock.services.isolation_service import (
    get_magasins_autorises,
    verifier_acces_magasin,
    filtrer_par_magasins
)

User = get_user_model()


class IsolationMagasinTest(TestCase):
    """Tests unitaires pour l'isolation par magasin."""

    @classmethod
    def setUpTestData(cls):
        """Création des données de test une seule fois."""
        # Créer 3 magasins
        cls.magasin1 = Magasin.objects.create(nom='Magasin Central')
        cls.magasin2 = Magasin.objects.create(nom='Pharmacie Centrale')
        cls.magasin3 = Magasin.objects.create(nom='Dépôt Logistique')

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
        # Le Profil est créé automatiquement par le signal à la création du User
        cls.profil_std = cls.user_standard.profil
        cls.profil_std.contact = '+243999999999'
        cls.profil_std.save()
        # Autoriser uniquement magasin1 et magasin2
        cls.profil_std.magasins_autorises.add(cls.magasin1, cls.magasin2)

        # Créer un utilisateur sans profil
        cls.user_sans_profil = User.objects.create_user(
            username='user_noprofil',
            email='noprofil@hopital.com',
            password='test123'
        )

        # Créer des articles et des lignes de stock dans différents magasins
        # (la liaison Article → Magasin passe par StockItem)
        cls.famille = FamilleArticle.objects.create(
            intitule='Famille Test',
            code='FAM-TEST',
            type_famille='MED'
        )
        cls.article1 = Article.objects.create(
            reference='REF001',
            designation='Article Magasin 1',
            famille=cls.famille,
            unite_distribution='UNIT'
        )
        cls.article2 = Article.objects.create(
            reference='REF002',
            designation='Article Magasin 2',
            famille=cls.famille,
            unite_distribution='UNIT'
        )
        cls.article3 = Article.objects.create(
            reference='REF003',
            designation='Article Magasin 3',
            famille=cls.famille,
            unite_distribution='UNIT'
        )
        cls.stock1 = StockItem.objects.create(
            article=cls.article1, magasin=cls.magasin1, quantite_physique=10
        )
        cls.stock2 = StockItem.objects.create(
            article=cls.article2, magasin=cls.magasin2, quantite_physique=10
        )
        cls.stock3 = StockItem.objects.create(
            article=cls.article3, magasin=cls.magasin3, quantite_physique=10
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

    def test_filtrer_stock_superuser(self):
        """Le superuser doit voir les lignes de stock de TOUS les magasins."""
        request = self._create_request(self.superuser)
        queryset = StockItem.objects.all()
        filtre = filtrer_par_magasins(queryset, request, field_name='magasin')

        self.assertEqual(filtre.count(), 3)

    def test_filtrer_stock_user_standard(self):
        """L'utilisateur standard ne doit voir que les lignes de stock de ses magasins."""
        request = self._create_request(self.user_standard)
        queryset = StockItem.objects.all()
        filtre = filtrer_par_magasins(queryset, request, field_name='magasin')

        self.assertEqual(filtre.count(), 2)
        self.assertIn(self.stock1, filtre)
        self.assertIn(self.stock2, filtre)
        self.assertNotIn(self.stock3, filtre)

    def test_filtrer_stock_sans_profil(self):
        """Un utilisateur sans profil ne doit voir AUCUNE ligne de stock."""
        request = self._create_request(self.user_sans_profil)
        queryset = StockItem.objects.all()
        filtre = filtrer_par_magasins(queryset, request, field_name='magasin')

        self.assertEqual(filtre.count(), 0)

    def test_filtrer_queryset_vide(self):
        """Filtrer un queryset vide doit retourner un queryset vide."""
        request = self._create_request(self.superuser)
        queryset = StockItem.objects.filter(article__reference='INEXISTANT')
        filtre = filtrer_par_magasins(queryset, request, field_name='magasin')

        self.assertEqual(filtre.count(), 0)


class IsolationMagasinIntegrationTest(TestCase):
    """Tests d'intégration pour l'isolation dans les vues."""

    @classmethod
    def setUpTestData(cls):
        """Création des données de test."""
        cls.magasin1 = Magasin.objects.create(nom='Magasin Test 1')
        cls.magasin2 = Magasin.objects.create(nom='Magasin Test 2')

        cls.user1 = User.objects.create_user(
            username='user_mag1',
            password='test123'
        )
        # Le Profil est créé automatiquement par le signal à la création du User
        cls.profil1 = cls.user1.profil
        cls.profil1.magasins_autorises.add(cls.magasin1)

        cls.superuser = User.objects.create_superuser(
            username='admin_test',
            password='admin123'
        )

    def test_isolation_bons_mouvement(self):
        """Les bons de mouvement doivent être isolés par magasin."""
        from stock.models import BonMouvement

        # Créer des bons de sortie dans différents magasins
        bs1 = BonMouvement.objects.create(
            type_bon='SORTIE',
            magasin=self.magasin1,
            statut_validation='VALIDE'
        )
        bs2 = BonMouvement.objects.create(
            type_bon='SORTIE',
            magasin=self.magasin2,
            statut_validation='VALIDE'
        )

        # User1 ne doit voir que le BS de son magasin
        request = RequestFactory().get('/stock/sorties/')
        request.user = self.user1

        from stock.services.isolation_service import filtrer_par_magasins
        bs_filter = filtrer_par_magasins(
            BonMouvement.objects.filter(type_bon='SORTIE'),
            request,
            field_name='magasin'
        )

        self.assertEqual(bs_filter.count(), 1)
        self.assertIn(bs1, bs_filter)
        self.assertNotIn(bs2, bs_filter)

        # Superuser doit tout voir
        request.user = self.superuser
        bs_all = filtrer_par_magasins(
            BonMouvement.objects.filter(type_bon='SORTIE'),
            request,
            field_name='magasin'
        )
        self.assertEqual(bs_all.count(), 2)


class SelectionMagasinSessionTest(TestCase):
    """
    Le magasin sélectionné une fois dans l'en-tête (session magasin_actif_id)
    doit s'appliquer à TOUTES les listes : sorties, hors stock, état du stock.
    """

    @classmethod
    def setUpTestData(cls):
        cls.magasin_a = Magasin.objects.create(nom='Magasin A')
        cls.magasin_b = Magasin.objects.create(nom='Magasin B')

        cls.user = User.objects.create_superuser(
            username='admin_session', password='admin123'
        )
        # Éviter la redirection « forcer changement de mot de passe »
        cls.user.profil.doit_changer_mdp = False
        cls.user.profil.save(update_fields=['doit_changer_mdp'])

        # Un bon de sortie dans chaque magasin
        cls.bs_a = BonMouvement.objects.create(
            type_bon='SORTIE', magasin=cls.magasin_a,
            statut_validation='VALIDE', numero_bon='BS-A-001'
        )
        cls.bs_b = BonMouvement.objects.create(
            type_bon='SORTIE', magasin=cls.magasin_b,
            statut_validation='VALIDE', numero_bon='BS-B-001'
        )

        # Un bon hors stock dans chaque magasin
        cls.hs_a = BonMouvement.objects.create(
            type_bon='SORTIE_HORS_STOCK', magasin=cls.magasin_a,
            statut_validation='VALIDE', numero_bon='HS-A-001'
        )
        cls.hs_b = BonMouvement.objects.create(
            type_bon='SORTIE_HORS_STOCK', magasin=cls.magasin_b,
            statut_validation='VALIDE', numero_bon='HS-B-001'
        )

        # Un stock item dans chaque magasin (articles distincts pour
        # pouvoir distinguer les lignes du tableau dans le HTML)
        cls.famille = FamilleArticle.objects.create(intitule='Médicaments')
        cls.article_a = Article.objects.create(
            designation='Article-UNIQUEMENT-MAGASIN-A', famille=cls.famille
        )
        cls.article_b = Article.objects.create(
            designation='Article-UNIQUEMENT-MAGASIN-B', famille=cls.famille
        )
        cls.stock_a = StockItem.objects.create(
            article=cls.article_a, magasin=cls.magasin_a, quantite_physique=10
        )
        cls.stock_b = StockItem.objects.create(
            article=cls.article_b, magasin=cls.magasin_b, quantite_physique=20
        )

    def setUp(self):
        self.client.force_login(self.user)

    def _session_magasin(self, magasin):
        session = self.client.session
        session['magasin_actif_id'] = str(magasin.id)
        session.save()

    def test_liste_sorties_respecte_le_magasin_de_session(self):
        self._session_magasin(self.magasin_a)
        resp = self.client.get('/sorties/')
        if resp.status_code != 200:
            print('REDIRECT_SORTIES ->', resp.get('Location'), resp.status_code, resp.content[:300])
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('BS-A-001', html)
        self.assertNotIn('BS-B-001', html)

        # Changement de magasin → l'autre liste s'affiche
        self._session_magasin(self.magasin_b)
        resp = self.client.get('/sorties/')
        html = resp.content.decode()
        self.assertIn('BS-B-001', html)
        self.assertNotIn('BS-A-001', html)

    def test_liste_hors_stock_respecte_le_magasin_de_session(self):
        self._session_magasin(self.magasin_a)
        resp = self.client.get('/bons/hors-stock/')
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('HS-A-001', html)
        self.assertNotIn('HS-B-001', html)

    def test_etat_stock_respecte_le_magasin_de_session(self):
        self._session_magasin(self.magasin_a)
        resp = self.client.get('/etat-stock/')
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        self.assertIn('Article-UNIQUEMENT-MAGASIN-A', html)
        self.assertNotIn('Article-UNIQUEMENT-MAGASIN-B', html)

        # Un filtre magasin explicite écrase la session
        resp = self.client.get(f'/etat-stock/?magasin={self.magasin_b.id}')
        html = resp.content.decode()
        self.assertIn('Article-UNIQUEMENT-MAGASIN-B', html)
        self.assertNotIn('Article-UNIQUEMENT-MAGASIN-A', html)


class ContexteMagasinProcessorTest(TestCase):
    """Le context processor ne doit jamais choisir un magasin à la place
    de l'utilisateur quand il en a plusieurs (clé session magasin_actif_id)."""

    @classmethod
    def setUpTestData(cls):
        cls.magasin1 = Magasin.objects.create(nom='Magasin Un')
        cls.magasin2 = Magasin.objects.create(nom='Magasin Deux')
        cls.user = User.objects.create_superuser(
            username='admin_cp', password='admin123'
        )
        cls.user.profil.doit_changer_mdp = False
        cls.user.profil.save(update_fields=['doit_changer_mdp'])

    def test_plusieurs_magasins_sans_selection_pas_de_fallback(self):
        """Avec 2 magasins et aucune sélection, magasin_actif reste None
        et la clé de session magasin_actif_id n'est pas écrite."""
        self.client.force_login(self.user)
        resp = self.client.get('/sorties/')
        # Pas de sélection → écran « Choix du Magasin »
        self.assertContains(resp, 'Choix du Magasin')
        session = self.client.session
        self.assertNotIn('magasin_actif_id', session)

    def test_selection_en_session_appliquee_partout(self):
        """Une fois le magasin choisi, il reste appliqué (aucun reset)."""
        self.client.force_login(self.user)
        session = self.client.session
        session['magasin_actif_id'] = str(self.magasin2.id)
        session.save()

        resp = self.client.get('/sorties/')
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'Choix du Magasin')
        # Le magasin sélectionné est bien marqué dans l'en-tête
        html = resp.content.decode()
        self.assertIn(f'value="{self.magasin2.id}" selected', html)

    def test_un_seul_magasin_auto_selection(self):
        """Un seul magasin → auto-sélection et écriture de la clé de session."""
        Magasin.objects.exclude(id=self.magasin1.id).delete()
        self.client.force_login(self.user)
        resp = self.client.get('/sorties/')
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, 'Choix du Magasin')
        session = self.client.session
        self.assertEqual(session.get('magasin_actif_id'), str(self.magasin1.id))
