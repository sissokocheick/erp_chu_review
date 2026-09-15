import json
from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.utils import timezone
from stock.models import Article, FamilleArticle, Fournisseur, Magasin, StockItem, BonMouvement, LigneBon
from stock.tests.factories import desactiver_changement_mdp
from projets.models import Projet, ProjetBesoin, ProjetProforma, ProjetProformaLigne

User = get_user_model()


class ProjetProformaTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_superuser(
            username="admin_projets",
            email="admin_projets@example.com",
            password="adminpassword123"
        )
        desactiver_changement_mdp(self.user)
        self.client.force_login(self.user)

        self.fournisseur = Fournisseur.objects.create(
            code="FOURN-01",
            raison_sociale="SARL Quincaillerie Moderne",
            telephone="01020304"
        )
        self.famille = FamilleArticle.objects.create(
            intitule="Matériaux BTP",
            code="BTP"
        )
        self.article1 = Article.objects.create(
            famille=self.famille,
            reference="CIM-001",
            designation="Sac de Ciment 50kg",
            prix_reference=Decimal("5000.00")
        )
        self.article2 = Article.objects.create(
            famille=self.famille,
            reference="FER-012",
            designation="Barre de Fer à Béton 12mm",
            prix_reference=Decimal("3500.00")
        )

        self.projet = Projet.objects.create(
            nom="Extension Bâtiment Pédiatrie",
            statut="EN_COURS",
            fournisseur=self.fournisseur,
            budget_alloue=Decimal("15000000.00"),
            chef_de_projet=self.user,
            cree_par=self.user
        )

    def test_proforma_models_creation_and_properties(self):
        """Vérifie le modèle ProjetProforma, ses lignes, et ses propriétés calculées."""
        pf = ProjetProforma.objects.create(
            projet=self.projet,
            numero_proforma="PF-2026-001",
            date_proforma=timezone.now().date(),
            fournisseur=self.fournisseur,
            objet="Fourniture gros oeuvre",
            statut="ACTIF",
            cree_par=self.user
        )
        l1 = ProjetProformaLigne.objects.create(
            proforma=pf,
            article=self.article1,
            quantite_prevue=20,
            prix_unitaire_estime=Decimal("5000.00")
        )
        l2 = ProjetProformaLigne.objects.create(
            proforma=pf,
            article=self.article2,
            quantite_prevue=30,
            prix_unitaire_estime=Decimal("3500.00")
        )

        self.assertIn("PF-2026-001", str(pf))
        self.assertEqual(pf.total_articles, 50)
        # Total montant = (20 * 5000) + (30 * 3500) = 100000 + 105000 = 205000
        self.assertEqual(pf.total_montant_estime, Decimal("205000.00"))
        self.assertEqual(l1.montant_estime, Decimal("100000.00"))

    def test_creer_proforma_view(self):
        """Vérifie l'enregistrement d'une proforma via la vue modale."""
        url = reverse('projets:creer_proforma', kwargs={'projet_id': self.projet.id})
        post_data = {
            'numero_proforma': 'PF-TEST-VIEW-01',
            'date_proforma': '2026-09-11',
            'fournisseur': str(self.fournisseur.id),
            'objet': 'Devis armature et béton',
            'articles[]': [str(self.article1.id), str(self.article2.id)],
            'quantites[]': ['25', '40'],
            'prix_unitaires[]': ['5200', '3600'],
        }
        response = self.client.post(url, post_data)
        self.assertRedirects(response, reverse('projets:detail', kwargs={'projet_id': self.projet.id}))

        pf = ProjetProforma.objects.get(numero_proforma='PF-TEST-VIEW-01')
        self.assertEqual(pf.projet, self.projet)
        self.assertEqual(pf.fournisseur, self.fournisseur)
        self.assertEqual(pf.lignes.count(), 2)

        # Vérifie la synchronisation automatique des ProjetBesoin
        besoin1 = ProjetBesoin.objects.get(projet=self.projet, article=self.article1)
        self.assertEqual(besoin1.quantite_prevue, 25)
        besoin2 = ProjetBesoin.objects.get(projet=self.projet, article=self.article2)
        self.assertEqual(besoin2.quantite_prevue, 40)

    def test_api_detail_proforma(self):
        """Vérifie que l'API JSON renvoie bien les données pour la modale d'édition."""
        pf = ProjetProforma.objects.create(
            projet=self.projet,
            numero_proforma="PF-API-01",
            date_proforma=timezone.now().date(),
            fournisseur=self.fournisseur,
            objet="Devis électricité",
            statut="ACTIF",
            cree_par=self.user
        )
        ProjetProformaLigne.objects.create(
            proforma=pf,
            article=self.article1,
            quantite_prevue=15,
            prix_unitaire_estime=Decimal("5000.00")
        )

        url = reverse('projets:api_detail_proforma', kwargs={'proforma_id': pf.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data['id'], pf.id)
        self.assertEqual(data['numero_proforma'], 'PF-API-01')
        self.assertEqual(data['objet'], 'Devis électricité')
        self.assertEqual(data['fournisseur_id'], self.fournisseur.id)
        self.assertEqual(len(data['lignes']), 1)
        self.assertEqual(data['lignes'][0]['article_id'], self.article1.id)
        self.assertEqual(data['lignes'][0]['quantite_prevue'], 15)

    def test_modifier_proforma_view(self):
        """Vérifie la mise à jour d'une proforma existante et le recalcul des besoins."""
        pf = ProjetProforma.objects.create(
            projet=self.projet,
            numero_proforma="PF-MODIF-01",
            date_proforma=timezone.now().date(),
            fournisseur=self.fournisseur,
            objet="Devis initial",
            statut="ACTIF",
            cree_par=self.user
        )
        ProjetProformaLigne.objects.create(
            proforma=pf,
            article=self.article1,
            quantite_prevue=10
        )
        from projets.views import _synchroniser_besoins_projet
        _synchroniser_besoins_projet(self.projet)

        url = reverse('projets:modifier_proforma', kwargs={'projet_id': self.projet.id, 'proforma_id': pf.id})
        post_data = {
            'numero_proforma': 'PF-MODIF-01-V2',
            'date_proforma': '2026-09-12',
            'fournisseur': str(self.fournisseur.id),
            'objet': 'Devis révisé V2',
            'articles[]': [str(self.article1.id)],
            'quantites[]': ['35'],
            'prix_unitaires[]': ['5100'],
        }
        response = self.client.post(url, post_data)
        self.assertRedirects(response, reverse('projets:detail', kwargs={'projet_id': self.projet.id}))

        pf.refresh_from_db()
        self.assertEqual(pf.numero_proforma, 'PF-MODIF-01-V2')
        self.assertEqual(pf.objet, 'Devis révisé V2')
        self.assertEqual(pf.lignes.first().quantite_prevue, 35)

        besoin = ProjetBesoin.objects.get(projet=self.projet, article=self.article1)
        self.assertEqual(besoin.quantite_prevue, 35)

    def test_annuler_et_reactiver_proforma(self):
        """Vérifie que l'annulation d'une proforma l'exclut des besoins prévus, et la réactivation la restaure."""
        pf = ProjetProforma.objects.create(
            projet=self.projet,
            numero_proforma="PF-ANNULER-01",
            date_proforma=timezone.now().date(),
            statut="ACTIF",
            cree_par=self.user
        )
        ProjetProformaLigne.objects.create(
            proforma=pf,
            article=self.article1,
            quantite_prevue=50
        )
        from projets.views import _synchroniser_besoins_projet
        _synchroniser_besoins_projet(self.projet)

        besoin = ProjetBesoin.objects.get(projet=self.projet, article=self.article1)
        self.assertEqual(besoin.quantite_prevue, 50)

        # 1. Annulation
        url = reverse('projets:annuler_proforma', kwargs={'projet_id': self.projet.id, 'proforma_id': pf.id})
        response = self.client.post(url)
        self.assertRedirects(response, reverse('projets:detail', kwargs={'projet_id': self.projet.id}))

        pf.refresh_from_db()
        self.assertEqual(pf.statut, 'ANNULE')
        self.assertFalse(ProjetBesoin.objects.filter(projet=self.projet, article=self.article1).exists())

        # 2. Réactivation
        response2 = self.client.post(url)
        self.assertRedirects(response2, reverse('projets:detail', kwargs={'projet_id': self.projet.id}))

        pf.refresh_from_db()
        self.assertEqual(pf.statut, 'ACTIF')
        besoin_restaure = ProjetBesoin.objects.get(projet=self.projet, article=self.article1)
        self.assertEqual(besoin_restaure.quantite_prevue, 50)

    def test_imprimer_proforma_pdf(self):
        """Vérifie la génération du bordereau officiel de proforma au format PDF."""
        pf = ProjetProforma.objects.create(
            projet=self.projet,
            numero_proforma="PF-PDF-001",
            date_proforma=timezone.now().date(),
            fournisseur=self.fournisseur,
            objet="Devis officiel impression",
            statut="ACTIF",
            cree_par=self.user
        )
        ProjetProformaLigne.objects.create(
            proforma=pf,
            article=self.article1,
            quantite_prevue=10,
            prix_unitaire_estime=Decimal("5000.00")
        )

        url = reverse('projets:imprimer_proforma', kwargs={'projet_id': self.projet.id, 'proforma_id': pf.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response.content.startswith(b'%PDF'))

    def test_creer_projet_avec_proforma_initiale(self):
        """Vérifie que la création d'un projet avec articles génère automatiquement une proforma initiale."""
        url = reverse('projets:creer')
        post_data = {
            'nom': 'Nouveau Chantier Chirurgie',
            'statut': 'PREPARATION',
            'fournisseur': str(self.fournisseur.id),
            'budget_alloue': '20000000',
            'numero_proforma': 'PF-INIT-2026',
            'date_proforma': '2026-09-11',
            'articles[]': [str(self.article1.id)],
            'quantites[]': ['80'],
        }
        response = self.client.post(url, post_data)
        nouveau_projet = Projet.objects.get(nom='Nouveau Chantier Chirurgie')
        self.assertRedirects(response, reverse('projets:detail', kwargs={'projet_id': nouveau_projet.id}))

        pf = nouveau_projet.proformas.first()
        self.assertIsNotNone(pf)
        self.assertEqual(pf.numero_proforma, 'PF-INIT-2026')
        self.assertEqual(pf.lignes.count(), 1)
        self.assertEqual(pf.lignes.first().quantite_prevue, 80)

        besoin = ProjetBesoin.objects.get(projet=nouveau_projet, article=self.article1)
        self.assertEqual(besoin.quantite_prevue, 80)

    def test_detail_projet_page_and_comparatif_balance(self):
        """Vérifie l'affichage de la page de détails avec le tableau comparatif des prévisions et réceptions."""
        # Création d'une proforma active
        pf = ProjetProforma.objects.create(
            projet=self.projet,
            numero_proforma="PF-DETAIL-001",
            date_proforma=timezone.now().date(),
            fournisseur=self.fournisseur,
            statut="ACTIF",
            cree_par=self.user
        )
        ProjetProformaLigne.objects.create(
            proforma=pf,
            article=self.article1,
            quantite_prevue=100,
            prix_unitaire_estime=Decimal("5000.00")
        )
        from projets.views import _synchroniser_besoins_projet
        _synchroniser_besoins_projet(self.projet)

        # Création d'une réception et d'une sortie réelles liées au projet
        magasin = Magasin.objects.create(nom="Magasin Technique", gere_projets=True)
        StockItem.objects.create(magasin=magasin, article=self.article1, quantite_physique=100)

        # Bon d'entrée (réception fournisseur)
        bon_e = BonMouvement.objects.create(
            type_bon="ENTREE",
            magasin=magasin,
            projet=self.projet,
            fournisseur=self.fournisseur,
            cree_par=self.user
        )
        LigneBon.objects.create(bon=bon_e, article=self.article1, quantite=60, prix_unitaire=Decimal("5000.00"))

        # Bon de sortie (consommation chantier)
        bon_s = BonMouvement.objects.create(
            type_bon="SORTIE",
            magasin=magasin,
            projet=self.projet,
            fournisseur=self.fournisseur,
            cree_par=self.user
        )
        LigneBon.objects.create(bon=bon_s, article=self.article1, quantite=40, prix_unitaire=Decimal("5000.00"))

        url = reverse('projets:detail', kwargs={'projet_id': self.projet.id})
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        bilan = list(response.context['bilan'])
        self.assertEqual(len(bilan), 1)
        item = bilan[0]
        self.assertEqual(item['prevu'], 100)
        self.assertEqual(item['recu'], 60)
        self.assertEqual(item['sorti'], 40)
        self.assertEqual(item['retourne'], 0)
        self.assertEqual(item['net'], 40)
        self.assertEqual(item['progression_recu'], 60.0)
        self.assertFalse(item['alerte_surconsommation'])

        bilan_global = response.context['bilan_global']
        self.assertEqual(bilan_global['total_articles'], 1)
        self.assertEqual(bilan_global['total_prevu'], 100)
        self.assertEqual(bilan_global['total_recu'], 60)
        self.assertEqual(bilan_global['total_sorti'], 40)
        self.assertEqual(bilan_global['total_net'], 40)

    def test_api_recherche_articles(self):
        """Vérifie l'API AJAX de recherche des articles pour Select2."""
        url = reverse('projets:api_articles')
        response = self.client.get(url, {'q': 'Ciment'})
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn('results', data)
        self.assertTrue(len(data['results']) >= 1)
        self.assertEqual(data['results'][0]['id'], self.article1.id)

    def test_creer_projet_avec_proformas_json(self):
        """Vérifie la création d'un projet avec proforma issue de la modale JSON."""
        url = reverse('projets:creer')
        pf_payload = [
            {
                'numero_proforma': 'PF-MODALE-2026-01',
                'date_proforma': '2026-09-11',
                'fournisseur_id': str(self.fournisseur.id),
                'objet': 'Lot Gros Oeuvre',
                'lignes': [
                    {
                        'article_id': self.article1.id,
                        'quantite': 120,
                        'prix_unitaire': 4500
                    }
                ]
            }
        ]
        post_data = {
            'nom': 'Chantier Extension Laboratoire',
            'statut': 'EN_COURS',
            'fournisseur': str(self.fournisseur.id),
            'budget_alloue': '15000000',
            'proformas_json': json.dumps(pf_payload)
        }
        response = self.client.post(url, post_data)
        projet = Projet.objects.get(nom='Chantier Extension Laboratoire')
        self.assertRedirects(response, reverse('projets:detail', kwargs={'projet_id': projet.id}))

        pf = projet.proformas.filter(statut='ACTIF').first()
        self.assertIsNotNone(pf)
        self.assertEqual(pf.numero_proforma, 'PF-MODALE-2026-01')
        self.assertEqual(pf.objet, 'Lot Gros Oeuvre')
        self.assertEqual(pf.lignes.count(), 1)
        self.assertEqual(pf.lignes.first().quantite_prevue, 120)
        self.assertEqual(pf.lignes.first().prix_unitaire_estime, Decimal('4500'))

        besoin = ProjetBesoin.objects.get(projet=projet, article=self.article1)
        self.assertEqual(besoin.quantite_prevue, 120)

    def test_modifier_projet_avec_proformas_json(self):
        """Vérifie la mise à jour d'un projet via proformas_json."""
        # Création d'une proforma initiale
        pf = ProjetProforma.objects.create(
            projet=self.projet,
            numero_proforma='PF-EXIST-01',
            date_proforma=timezone.now().date(),
            fournisseur=self.fournisseur,
            statut='ACTIF',
            cree_par=self.user
        )
        ProjetProformaLigne.objects.create(
            proforma=pf,
            article=self.article1,
            quantite_prevue=25,
            prix_unitaire_estime=Decimal('5000')
        )

        url = reverse('projets:modifier', kwargs={'projet_id': self.projet.id})
        # Mise à jour avec modification de la proforma existante
        pf_payload = [
            {
                'id': pf.id,
                'numero_proforma': 'PF-EXIST-01-V2',
                'date_proforma': '2026-09-12',
                'fournisseur_id': str(self.fournisseur.id),
                'objet': 'Lot Révisé V2',
                'lignes': [
                    {
                        'article_id': self.article1.id,
                        'quantite': 95,
                        'prix_unitaire': 5200
                    }
                ]
            }
        ]
        post_data = {
            'nom': self.projet.nom,
            'statut': self.projet.statut,
            'fournisseur': str(self.fournisseur.id),
            'proformas_json': json.dumps(pf_payload)
        }
        response = self.client.post(url, post_data)
        self.assertRedirects(response, reverse('projets:detail', kwargs={'projet_id': self.projet.id}))

        pf.refresh_from_db()
        self.assertEqual(pf.numero_proforma, 'PF-EXIST-01-V2')
        self.assertEqual(pf.objet, 'Lot Révisé V2')
        self.assertEqual(pf.lignes.first().quantite_prevue, 95)
        self.assertEqual(pf.lignes.first().prix_unitaire_estime, Decimal('5200'))

        besoin = ProjetBesoin.objects.get(projet=self.projet, article=self.article1)
        self.assertEqual(besoin.quantite_prevue, 95)

    def test_creer_et_modifier_projet_meme_fournisseur_livreur(self):
        """Vérifie la création et modification avec l'option meme_fournisseur_livreur."""
        # 1. Création avec case cochée
        post_data_on = {
            'nom': 'Projet Avec Meme Fournisseur',
            'statut': 'PLANIFIE',
            'fournisseur': str(self.fournisseur.id),
            'meme_fournisseur_livreur': '1',
            'proformas_json': '[]'
        }
        res_on = self.client.post(reverse('projets:creer'), post_data_on)
        p_on = Projet.objects.get(nom='Projet Avec Meme Fournisseur')
        self.assertTrue(p_on.meme_fournisseur_livreur)

        # 2. Création avec case décochée (non envoyée)
        post_data_off = {
            'nom': 'Projet Sans Meme Fournisseur',
            'statut': 'PLANIFIE',
            'fournisseur': str(self.fournisseur.id),
            'proformas_json': '[]'
        }
        res_off = self.client.post(reverse('projets:creer'), post_data_off)
        p_off = Projet.objects.get(nom='Projet Sans Meme Fournisseur')
        self.assertFalse(p_off.meme_fournisseur_livreur)

        # 3. Modification : basculer p_off à True
        post_edit = {
            'nom': 'Projet Sans Meme Fournisseur',
            'statut': 'PLANIFIE',
            'fournisseur': str(self.fournisseur.id),
            'meme_fournisseur_livreur': 'on',
            'proformas_json': '[]'
        }
        self.client.post(reverse('projets:modifier', kwargs={'projet_id': p_off.id}), post_edit)
        p_off.refresh_from_db()
        self.assertTrue(p_off.meme_fournisseur_livreur)

    def test_liste_entrees_attribut_data_meme_fournisseur(self):
        """Vérifie que la vue liste_entrees génère bien les attributs data-meme-fournisseur."""
        magasin = Magasin.objects.create(nom="Magasin Projets", gere_projets=True)
        session = self.client.session
        session['magasin_actif_id'] = str(magasin.id)
        session.save()

        p_true = Projet.objects.create(nom="Projet True", fournisseur=self.fournisseur, meme_fournisseur_livreur=True)
        p_false = Projet.objects.create(nom="Projet False", fournisseur=self.fournisseur, meme_fournisseur_livreur=False)

        res = self.client.get(reverse('liste_entrees'))
        self.assertEqual(res.status_code, 200)
        self.assertContains(res, f'value="{p_true.id}" data-fournisseur-id="{self.fournisseur.id}" data-meme-fournisseur="1"')
        self.assertContains(res, f'value="{p_false.id}" data-fournisseur-id="{self.fournisseur.id}" data-meme-fournisseur="0"')

    def test_liste_projets_pagination_et_recherche_ajax(self):
        """Vérifie la pagination serveur et la recherche optimisée sur la liste des projets."""
        # Créer 35 projets pour tester la pagination (page size = 15)
        for i in range(1, 36):
            Projet.objects.create(
                nom=f"Chantier Lot {i:02d}",
                statut='EN_COURS' if i % 2 == 0 else 'PREPARATION',
                fournisseur=self.fournisseur,
                cree_par=self.user
            )

        url = reverse('projets:liste')
        
        # 1. Première page (per_page=15)
        res_p1 = self.client.get(url, {'per_page': '15', 'page': '1'})
        self.assertEqual(res_p1.status_code, 200)
        self.assertEqual(len(res_p1.context['projets']), 15)
        self.assertTrue(res_p1.context['projets_page'].has_next())

        # 2. Deuxième page
        res_p2 = self.client.get(url, {'per_page': '15', 'page': '2'})
        self.assertEqual(res_p2.status_code, 200)
        self.assertEqual(len(res_p2.context['projets']), 15)

        # 3. Recherche serveur ciblée
        res_q = self.client.get(url, {'q': 'Chantier Lot 07'})
        self.assertEqual(res_q.status_code, 200)
        self.assertEqual(res_q.context['total_filtre'], 1)

        # 4. Requête AJAX pour le rechargement partiel
        res_ajax = self.client.get(url, {'ajax': '1', 'q': 'Lot 10'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(res_ajax.status_code, 200)
        self.assertTemplateUsed(res_ajax, 'projets/projets_lignes.html')

    def test_api_recherche_projets_select2(self):
        """Vérifie l'API AJAX paginée Select2 pour rechercher des projets."""
        url = reverse('projets:api_projets')
        res = self.client.get(url, {'q': 'Extension'})
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertIn('results', data)
        self.assertIn('pagination', data)
        self.assertTrue(any(p['nom'] == self.projet.nom for p in data['results']))

    def test_api_articles_projet_lazy_loading(self):
        """Vérifie l'endpoint léger de récupération des articles d'un projet pour les mouvements de stock."""
        # Associer un article au projet
        ProjetBesoin.objects.create(projet=self.projet, article=self.article1, quantite_prevue=10)
        url = reverse('api_articles_projet', kwargs={'projet_id': self.projet.id})
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        data = res.json()
        self.assertTrue(data['success'])
        self.assertIn(self.article1.id, data['article_ids'])

    def test_format_milliers_filter(self):
        """Vérifie que le filtre format_milliers formate correctement en milliers avec espaces."""
        from projets.templatetags.projets_tags import format_milliers
        self.assertEqual(format_milliers(15000000), '15 000 000')
        self.assertEqual(format_milliers(Decimal('5000000'), 'FCFA'), '5 000 000 FCFA')
        self.assertEqual(format_milliers(1234567890), '1 234 567 890')
        self.assertEqual(format_milliers(0), '0')
        self.assertEqual(format_milliers(None), '')
        self.assertEqual(format_milliers(''), '')
        self.assertEqual(format_milliers(None, 'FCFA'), '—')

    def test_affichage_montants_milliers_dans_liste_projets(self):
        """Vérifie que les montants et budgets dans la liste des projets s'affichent bien sous forme 'xxx xxx xxx FCFA'."""
        self.projet.budget_alloue = Decimal('25000000')
        self.projet.save()

        url = reverse('projets:liste')
        res = self.client.get(url)
        self.assertEqual(res.status_code, 200)
        # Vérifie la présence du montant formaté avec séparateur de milliers
        self.assertContains(res, '25 000 000 FCFA')
        # Vérifie que le format brut sans espace n'est pas utilisé
        self.assertNotContains(res, '25000000 FCFA')

    def test_choix_chef_de_projet_creation_et_modification(self):
        """Vérifie qu'on peut désigner un chef de projet actif différent du créateur et le modifier."""
        autre_user = User.objects.create_user(
            username='ingenieur_travaux',
            password='password123',
            first_name='Moussa',
            last_name='Kone',
            is_active=True
        )

        # 1. Création avec un chef de projet choisi
        url_creer = reverse('projets:creer')
        res = self.client.post(url_creer, {
            'nom': 'Nouveau Bloc Scanner 2026',
            'statut': 'EN_COURS',
            'chef_de_projet': str(autre_user.id),
        })
        self.assertEqual(res.status_code, 302)
        nouveau_proj = Projet.objects.get(nom='Nouveau Bloc Scanner 2026')
        self.assertEqual(nouveau_proj.chef_de_projet, autre_user)
        self.assertEqual(nouveau_proj.cree_par, self.user)  # Le créateur reste l'utilisateur connecté

        # 2. Modification du chef de projet
        url_modifier = reverse('projets:modifier', kwargs={'projet_id': nouveau_proj.id})
        res_mod = self.client.post(url_modifier, {
            'nom': 'Nouveau Bloc Scanner 2026',
            'statut': 'EN_COURS',
            'chef_de_projet': str(self.user.id),  # On réassigne au créateur
        })
        self.assertEqual(res_mod.status_code, 302)
        nouveau_proj.refresh_from_db()
        self.assertEqual(nouveau_proj.chef_de_projet, self.user)

    def test_verrouillage_actions_selon_statut_projet(self):
        """Vérifie que les projets terminés ou annulés bloquent l'ajout ou la modification de proformas."""
        self.projet.statut = 'TERMINE'
        self.projet.save()

        # Tentative d'ajout d'une proforma sur projet terminé
        url_add_pf = reverse('projets:creer_proforma', kwargs={'projet_id': self.projet.id})
        res = self.client.post(url_add_pf, {
            'numero_proforma': 'PF-TEST-TERMINE',
        })
        self.assertEqual(res.status_code, 302)
        self.assertFalse(ProjetProforma.objects.filter(numero_proforma='PF-TEST-TERMINE').exists())


