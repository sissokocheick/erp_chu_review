import json
from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse

from stock.models import (
    Magasin, Article, FamilleArticle, BonMouvement, LigneBon, Mouvement,
    StockItem, Fournisseur
)
from stock.forms import MagasinForm, MagasinParametresForm
from projets.models import Projet, ProjetBesoin, ProjetProforma, ProjetProformaLigne
from stock.services.projet_article_service import (
    get_articles_ids_pour_projet,
    article_appartient_au_projet,
    get_map_articles_projets
)

User = get_user_model()

class MagasinFiltreArticlesProjetTest(TestCase):
    def setUp(self):
        self.client = Client()
        self.superuser = User.objects.create_superuser(
            username="admin_test",
            email="admin@example.com",
            password="adminpassword123"
        )
        from stock.tests.factories import desactiver_changement_mdp
        desactiver_changement_mdp(self.superuser)
        self.client.force_login(self.superuser)

        self.magasin = Magasin.objects.create(
            nom="Pharmacie Centrale",
            gere_projets=True,
            filtrer_articles_par_projet=True
        )

        session = self.client.session
        session['magasin_actif_id'] = str(self.magasin.id)
        session.save()

        self.fournisseur = Fournisseur.objects.create(
            code="FOURN-01",
            raison_sociale="Labo Pharma Med"
        )

        self.famille = FamilleArticle.objects.create(
            code="MED",
            intitule="Médicaments"
        )

        self.art_projet_entree = Article.objects.create(
            reference="ART-PRJ-01",
            designation="Article Projet Entree",
            famille=self.famille,
            prix_reference=Decimal("500.00")
        )
        self.art_projet_proforma = Article.objects.create(
            reference="ART-PRJ-02",
            designation="Article Projet Proforma",
            famille=self.famille,
            prix_reference=Decimal("750.00")
        )
        self.art_hors_projet = Article.objects.create(
            reference="ART-EXT-99",
            designation="Article Hors Projet",
            famille=self.famille,
            prix_reference=Decimal("1200.00")
        )

        # Stock initial
        StockItem.objects.create(article=self.art_projet_entree, magasin=self.magasin, quantite_physique=50, valeur_cmup=Decimal("500.00"))
        StockItem.objects.create(article=self.art_projet_proforma, magasin=self.magasin, quantite_physique=50, valeur_cmup=Decimal("750.00"))
        StockItem.objects.create(article=self.art_hors_projet, magasin=self.magasin, quantite_physique=50, valeur_cmup=Decimal("1200.00"))

        # Projet
        self.projet = Projet.objects.create(
            nom="Construction Extension Bloc",
            fournisseur=self.fournisseur,
            statut="EN_COURS"
        )

        # 1. Associer art_projet_entree via un bon d'entrée validé lié au projet
        bon_entree = BonMouvement.objects.create(
            numero_bon="BE-2026-0001",
            type_bon="ENTREE",
            magasin=self.magasin,
            magasin_destination=self.magasin,
            fournisseur=self.fournisseur,
            projet=self.projet,
            statut_validation="VALIDE",
            cree_par=self.superuser
        )
        LigneBon.objects.create(
            bon=bon_entree,
            article=self.art_projet_entree,
            quantite=10,
            prix_unitaire=Decimal("500")
        )

        # 2. Associer art_projet_proforma via proforma du projet
        proforma = ProjetProforma.objects.create(
            projet=self.projet,
            numero_proforma="PROF-2026-01",
            statut="ACTIF"
        )
        ProjetProformaLigne.objects.create(
            proforma=proforma,
            article=self.art_projet_proforma,
            quantite_prevue=20,
            prix_unitaire_estime=Decimal("750")
        )

    def test_magasin_model_and_form_filtrer_articles_par_projet(self):
        """Vérifie le champ filtrer_articles_par_projet et sa modification via formulaire."""
        mag = Magasin.objects.create(nom="Nouveau Magasin")
        self.assertTrue(mag.filtrer_articles_par_projet)

        form = MagasinForm(instance=mag, data={
            'nom': 'Nouveau Magasin',
            'filtrer_articles_par_projet': False
        })
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertFalse(saved.filtrer_articles_par_projet)

        param_form = MagasinParametresForm(instance=mag, data={
            'titre_responsable': 'Gestionnaire',
            'responsable': self.superuser.id,
            'filtrer_articles_par_projet': True
        })
        self.assertTrue(param_form.is_valid(), param_form.errors)
        saved_param = param_form.save()
        self.assertTrue(saved_param.filtrer_articles_par_projet)

    def test_service_projet_articles(self):
        """Vérifie que get_articles_ids_pour_projet retourne les articles d'entrée et de proforma."""
        art_ids = get_articles_ids_pour_projet(self.projet.id, inclure_previsions=True)
        self.assertIn(self.art_projet_entree.id, art_ids)
        self.assertIn(self.art_projet_proforma.id, art_ids)
        self.assertNotIn(self.art_hors_projet.id, art_ids)

        self.assertTrue(article_appartient_au_projet(self.art_projet_entree.id, self.projet.id))
        self.assertTrue(article_appartient_au_projet(self.art_projet_proforma.id, self.projet.id))
        self.assertFalse(article_appartient_au_projet(self.art_hors_projet.id, self.projet.id))

    def test_get_map_articles_projets(self):
        """Vérifie que la map batch retourne bien la correspondance projet -> [article_ids]."""
        mapping = get_map_articles_projets([self.projet], inclure_previsions=True)
        self.assertIn(str(self.projet.id), mapping)
        self.assertIn(self.art_projet_entree.id, mapping[str(self.projet.id)])
        self.assertIn(self.art_projet_proforma.id, mapping[str(self.projet.id)])
        self.assertNotIn(self.art_hors_projet.id, mapping[str(self.projet.id)])

    def test_api_articles_json_filtrage_active(self):
        """Avec filtrer_articles_par_projet=True et projet_id, seuls les articles du projet sont renvoyés."""
        url = reverse('api_articles_json')
        resp = self.client.get(url, {'projet_id': self.projet.id})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()['articles']
        ids_renvoyes = [item['id'] for item in data]
        self.assertIn(self.art_projet_entree.id, ids_renvoyes)
        self.assertIn(self.art_projet_proforma.id, ids_renvoyes)
        self.assertNotIn(self.art_hors_projet.id, ids_renvoyes)

    def test_api_articles_json_filtrage_desactive(self):
        """Avec filtrer_articles_par_projet=False, tous les articles sont renvoyés même avec projet_id."""
        self.magasin.filtrer_articles_par_projet = False
        self.magasin.save()

        url = reverse('api_articles_json')
        resp = self.client.get(url, {'projet_id': self.projet.id})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()['articles']
        ids_renvoyes = [item['id'] for item in data]
        self.assertIn(self.art_projet_entree.id, ids_renvoyes)
        self.assertIn(self.art_projet_proforma.id, ids_renvoyes)
        self.assertIn(self.art_hors_projet.id, ids_renvoyes)

    def test_api_articles_json_aucun_projet_selectionne(self):
        """Sans projet_id, tous les articles sont renvoyés."""
        url = reverse('api_articles_json')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()['articles']
        ids_renvoyes = [item['id'] for item in data]
        self.assertIn(self.art_projet_entree.id, ids_renvoyes)
        self.assertIn(self.art_hors_projet.id, ids_renvoyes)

    def test_backend_sortie_rejet_article_hors_projet(self):
        """Vérifie que la vue liste_sorties rejette un article hors-projet si le filtre est actif."""
        post_data = {
            'magasin': str(self.magasin.id),
            'type_sortie': 'SORTIE_PROJET',
            'projet': str(self.projet.id),
            'reference_externe': 'SORTIE-TEST-01',
            'articles[]': [str(self.art_hors_projet.id)],
            'quantites[]': ['5']
        }
        resp = self.client.post(reverse('liste_sorties'), post_data, follow=True)
        bons = BonMouvement.objects.filter(reference_externe='SORTIE-TEST-01')
        self.assertEqual(bons.count(), 0)
        self.assertContains(resp, "n&#x27;est pas affecté au projet")

    def test_backend_sortie_accepte_article_projet(self):
        """Vérifie que la sortie projet fonctionne normalement pour un article du projet."""
        post_data = {
            'magasin': str(self.magasin.id),
            'type_sortie': 'SORTIE_PROJET',
            'projet': str(self.projet.id),
            'reference_externe': 'SORTIE-TEST-02',
            'articles[]': [str(self.art_projet_entree.id)],
            'quantites[]': ['2']
        }
        resp = self.client.post(reverse('liste_sorties'), post_data, follow=True)
        bon = BonMouvement.objects.filter(reference_externe='SORTIE-TEST-02').first()
        self.assertIsNotNone(bon)
        self.assertEqual(bon.projet, self.projet)
        self.assertEqual(bon.type_bon, 'SORTIE_PROJET')
        self.assertEqual(bon.lignes_bon.first().article, self.art_projet_entree)

    def test_backend_retour_rejet_article_hors_projet(self):
        """Vérifie que le retour projet rejette un article hors-projet."""
        post_data = {
            'magasin': str(self.magasin.id),
            'type_retour': 'RETOUR_PROJET',
            'projet': str(self.projet.id),
            'reference_externe': 'RET-TEST-01',
            'articles[]': [str(self.art_hors_projet.id)],
            'quantites[]': ['1'],
            'lots[]': ['LOT-123'],
            'peremptions[]': ['2027-01-01'],
        }
        resp = self.client.post(reverse('liste_retours_services'), post_data, follow=True)
        bons = BonMouvement.objects.filter(reference_externe='RET-TEST-01')
        self.assertEqual(bons.count(), 0)
        self.assertContains(resp, "n&#x27;est pas affecté au projet")
