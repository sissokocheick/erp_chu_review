from decimal import Decimal
import json
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from stock.models import Article, FamilleArticle, Fournisseur, ArticleFournisseur, Magasin

User = get_user_model()


class ArticleFournisseurTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username='admin_test',
            email='admin@example.com',
            password='password123'
        )
        from stock.tests.factories import desactiver_changement_mdp
        desactiver_changement_mdp(self.user)
        self.magasin = Magasin.objects.create(
            nom='Magasin Central',
            cree_par=self.user
        )
        self.famille = FamilleArticle.objects.create(
            code='BTP',
            intitule='Materiaux BTP',
            cree_par=self.user
        )
        self.article = Article.objects.create(
            famille=self.famille,
            reference='ART-CIMENT-01',
            designation='Ciment CPJ 45 50kg',
            unite_distribution='Sac',
            prix_reference=Decimal('5000.00'),
            cree_par=self.user
        )
        self.fournisseur_a = Fournisseur.objects.create(
            code='F001',
            raison_sociale='Fournisseur Alpha',
            cree_par=self.user
        )
        self.fournisseur_b = Fournisseur.objects.create(
            code='F002',
            raison_sociale='Fournisseur Beta',
            cree_par=self.user
        )

        self.client = Client()
        self.client.force_login(self.user)
        # Assurer session magasin actif
        session = self.client.session
        session['magasin_actif_id'] = self.magasin.id
        session.save()

    def test_article_fournisseur_creation_and_prix_method(self):
        # Sans tarif négocié : prix de référence par défaut
        self.assertEqual(self.article.get_prix_fournisseur(), Decimal('5000.00'))
        self.assertEqual(self.article.get_prix_fournisseur(self.fournisseur_a.id), Decimal('5000.00'))

        # Création d'un tarif négocié pour le fournisseur A
        tarif_a = ArticleFournisseur.objects.create(
            article=self.article,
            fournisseur=self.fournisseur_a,
            prix_achat=Decimal('4600.00'),
            reference_fournisseur='ALPHA-CIM-45',
            delai_livraison_jours=3,
            est_principal=True,
            cree_par=self.user
        )

        # Création d'un tarif négocié différent pour le fournisseur B
        tarif_b = ArticleFournisseur.objects.create(
            article=self.article,
            fournisseur=self.fournisseur_b,
            prix_achat=Decimal('4850.00'),
            reference_fournisseur='BETA-C45',
            delai_livraison_jours=5,
            est_principal=False,
            cree_par=self.user
        )

        # Vérification des prix selon le fournisseur
        self.assertEqual(self.article.get_prix_fournisseur(self.fournisseur_a.id), Decimal('4600.00'))
        self.assertEqual(self.article.get_prix_fournisseur(self.fournisseur_b.id), Decimal('4850.00'))
        # Fournisseur inexistant ou sans tarif -> fallback prix de référence
        self.assertEqual(self.article.get_prix_fournisseur(999999), Decimal('5000.00'))
        self.assertEqual(self.article.get_prix_fournisseur(None), Decimal('5000.00'))

    def test_api_tarifs_article_get_and_post(self):
        # Création initiale d'un tarif
        ArticleFournisseur.objects.create(
            article=self.article,
            fournisseur=self.fournisseur_a,
            prix_achat=Decimal('4600.00'),
            reference_fournisseur='ALPHA-CIM-45',
            delai_livraison_jours=3,
            est_principal=True,
            cree_par=self.user
        )

        # Test GET
        url = reverse('api_tarifs_article', kwargs={'article_id': self.article.id})
        response = self.client.get(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['article']['id'], self.article.id)
        self.assertEqual(len(data['tarifs']), 1)
        self.assertEqual(data['tarifs'][0]['prix_achat'], 4600.0)
        self.assertGreaterEqual(len(data['fournisseurs']), 2)

        # Test POST : modification / remplacement des tarifs via l'API
        post_payload = {
            'tarifs': [
                {
                    'fournisseur_id': self.fournisseur_a.id,
                    'prix_achat': 4550.0,
                    'reference_fournisseur': 'ALPHA-CIM-NEW',
                    'delai_livraison_jours': 2,
                    'est_principal': True
                },
                {
                    'fournisseur_id': self.fournisseur_b.id,
                    'prix_achat': 4750.0,
                    'reference_fournisseur': 'BETA-CIM-NEW',
                    'delai_livraison_jours': 4,
                    'est_principal': False
                }
            ]
        }
        post_response = self.client.post(
            url,
            data=json.dumps(post_payload),
            content_type='application/json',
            HTTP_X_REQUESTED_WITH='XMLHttpRequest'
        )
        self.assertEqual(post_response.status_code, 200)
        post_data = post_response.json()
        self.assertTrue(post_data['success'])

        # Vérification en base de données
        self.assertEqual(self.article.tarifs_fournisseurs.count(), 2)
        self.assertEqual(self.article.get_prix_fournisseur(self.fournisseur_a.id), Decimal('4550.00'))
        self.assertEqual(self.article.get_prix_fournisseur(self.fournisseur_b.id), Decimal('4750.00'))

    def test_api_recherche_articles_with_fournisseur(self):
        # Création d'un tarif négocié uniquement avec fournisseur_a
        ArticleFournisseur.objects.create(
            article=self.article,
            fournisseur=self.fournisseur_a,
            prix_achat=Decimal('4400.00'),
            reference_fournisseur='REF-SPEC',
            cree_par=self.user
        )

        url = reverse('projets:api_articles')

        # Recherche avec fournisseur_a -> doit renvoyer prix 4400 et prix_fournisseur_specifique = True
        response_a = self.client.get(f"{url}?q=Ciment&fournisseur_id={self.fournisseur_a.id}")
        self.assertEqual(response_a.status_code, 200)
        results_a = response_a.json().get('results', [])
        self.assertEqual(len(results_a), 1)
        self.assertEqual(results_a[0]['prix_reference'], 4400.0)
        self.assertTrue(results_a[0]['prix_fournisseur_specifique'])

        # Recherche avec fournisseur_b (sans tarif négocié) -> doit renvoyer prix 5000 et prix_fournisseur_specifique = False
        response_b = self.client.get(f"{url}?q=Ciment&fournisseur_id={self.fournisseur_b.id}")
        self.assertEqual(response_b.status_code, 200)
        results_b = response_b.json().get('results', [])
        self.assertEqual(len(results_b), 1)
        self.assertEqual(results_b[0]['prix_reference'], 5000.0)
        self.assertFalse(results_b[0]['prix_fournisseur_specifique'])
