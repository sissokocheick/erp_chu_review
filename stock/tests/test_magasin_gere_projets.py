from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from stock.models import Magasin, Article, FamilleArticle, StockItem, Service, Fournisseur
from stock.forms import MagasinForm, MagasinParametresForm
from projets.models import Projet, ProjetBesoin

User = get_user_model()

class MagasinGereProjetsTest(TestCase):
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

        self.magasin_sans_projet = Magasin.objects.create(
            nom="Pharmacie Centrale",
            gere_projets=False
        )
        self.magasin_avec_projet = Magasin.objects.create(
            nom="Magasin Technique & Projets",
            gere_projets=True
        )

        self.service = Service.objects.create(nom="Chirurgie")
        self.fournisseur = Fournisseur.objects.create(code="F001", raison_sociale="Fournisseur Pharma")
        self.projet = Projet.objects.create(
            nom="Extension Bloc Operatoire",
            statut="EN_COURS"
        )

        self.famille = FamilleArticle.objects.create(
            intitule="Divers",
            code="DIV"
        )
        self.article = Article.objects.create(
            famille=self.famille,
            reference="ART-PROJ-01",
            designation="Ciment Spécial Bloc",
            prix_reference=Decimal("5000.00")
        )
        ProjetBesoin.objects.create(
            projet=self.projet,
            article=self.article,
            quantite_prevue=50
        )
        # Création de stock initial dans les deux magasins
        StockItem.objects.create(
            magasin=self.magasin_sans_projet,
            article=self.article,
            quantite_physique=100,
            valeur_cmup=Decimal("5000.00")
        )
        StockItem.objects.create(
            magasin=self.magasin_avec_projet,
            article=self.article,
            quantite_physique=100,
            valeur_cmup=Decimal("5000.00")
        )

    def test_magasin_model_default_gere_projets(self):
        """Vérifie que gere_projets vaut False par défaut."""
        mag = Magasin.objects.create(nom="Nouveau Magasin")
        self.assertFalse(mag.gere_projets)

    def test_magasin_form_and_parametres_form(self):
        """Vérifie que les formulaires gèrent bien gere_projets."""
        form = MagasinForm(instance=self.magasin_sans_projet, data={
            'nom': 'Pharmacie Centrale',
            'localisation': 'Bâtiment B',
            'gere_projets': True
        })
        self.assertTrue(form.is_valid(), form.errors)
        saved = form.save()
        self.assertTrue(saved.gere_projets)

        param_form = MagasinParametresForm(instance=self.magasin_avec_projet, data={
            'titre_responsable': 'Chef de Projet',
            'responsable': self.superuser.id,
            'gere_projets': False
        })
        self.assertTrue(param_form.is_valid(), param_form.errors)
        saved_param = param_form.save()
        self.assertFalse(saved_param.gere_projets)

    def test_entrees_page_with_and_without_gere_projets(self):
        """Vérifie que le champ projet apparaît/disparaît selon le magasin actif."""
        # 1. Magasin sans projets
        session = self.client.session
        session['magasin_actif_id'] = str(self.magasin_sans_projet.id)
        session.save()

        response = self.client.get(reverse('liste_entrees'))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['magasin_gere_projets'])
        self.assertNotContains(response, 'id="div-entree-projet"')

        # 2. Magasin avec projets
        session['magasin_actif_id'] = str(self.magasin_avec_projet.id)
        session.save()

        response = self.client.get(reverse('liste_entrees'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['magasin_gere_projets'])
        self.assertContains(response, 'id="div-entree-projet"')

    def test_sorties_page_and_guard(self):
        """Vérifie les sorties avec et sans gestion de projet."""
        session = self.client.session
        session['magasin_actif_id'] = str(self.magasin_sans_projet.id)
        session.save()

        # Sans gestion projet : pas d'option SORTIE_PROJET dans le HTML
        response = self.client.get(reverse('liste_sorties'))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['magasin_gere_projets'])
        self.assertNotContains(response, '<option value="SORTIE_PROJET">')

        # Tentative de POST SORTIE_PROJET sur magasin_sans_projet -> doit échouer
        post_data = {
            'magasin': str(self.magasin_sans_projet.id),
            'type_sortie': 'SORTIE_PROJET',
            'projet': str(self.projet.id),
            'reference_externe': 'SORTIE-TEST-001',
            'articles[]': [str(self.article.id)],
            'quantites[]': ['5'],
        }
        res_post = self.client.post(reverse('liste_sorties'), post_data, follow=True)
        self.assertContains(res_post, "n&#x27;est pas configuré pour gérer les projets")

        # Avec gestion projet
        session['magasin_actif_id'] = str(self.magasin_avec_projet.id)
        session.save()

        response = self.client.get(reverse('liste_sorties'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['magasin_gere_projets'])
        self.assertContains(response, '<option value="SORTIE_PROJET">')

    def test_retours_page_and_guard(self):
        """Vérifie les retours avec et sans gestion de projet."""
        session = self.client.session
        session['magasin_actif_id'] = str(self.magasin_sans_projet.id)
        session.save()

        # Sans gestion projet
        response = self.client.get(reverse('liste_retours_services'))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context['magasin_gere_projets'])
        self.assertNotContains(response, '<option value="RETOUR_PROJET">')

        # Tentative de POST RETOUR_PROJET sur magasin_sans_projet -> doit échouer
        post_data = {
            'magasin': str(self.magasin_sans_projet.id),
            'type_retour': 'RETOUR_PROJET',
            'projet': str(self.projet.id),
            'reference_externe': 'RET-TEST-001',
            'articles[]': [str(self.article.id)],
            'quantites[]': ['2'],
            'lots[]': ['LOT-123'],
            'peremptions[]': ['2028-12-31'],
        }
        res_post = self.client.post(reverse('liste_retours_services'), post_data, follow=True)
        self.assertContains(res_post, "n&#x27;est pas configuré pour gérer les projets")

        # Avec gestion projet
        session['magasin_actif_id'] = str(self.magasin_avec_projet.id)
        session.save()

        response = self.client.get(reverse('liste_retours_services'))
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['magasin_gere_projets'])
        self.assertContains(response, '<option value="RETOUR_PROJET">')

    def test_creer_et_modifier_projet_avec_fournisseur(self):
        """Vérifie la création et la modification d'un projet avec sélection du fournisseur/entreprise."""
        from projets.models import ProjetBesoin
        # 1. Création
        res_create = self.client.post(reverse('projets:creer'), {
            'nom': 'Projet Salle d\'Opération',
            'description': 'Modernisation',
            'statut': 'EN_COURS',
            'fournisseur': str(self.fournisseur.id),
            'articles[]': [str(self.article.id)],
            'quantites[]': ['15'],
        }, follow=True)
        self.assertEqual(res_create.status_code, 200)
        proj = Projet.objects.get(nom='Projet Salle d\'Opération')
        self.assertEqual(proj.fournisseur, self.fournisseur)
        self.assertTrue(ProjetBesoin.objects.filter(projet=proj, article=self.article, quantite_prevue=15).exists())

        # 2. Modification
        autre_fournisseur = Fournisseur.objects.create(code="F002", raison_sociale="Entreprise BTP SARL")
        res_mod = self.client.post(reverse('projets:modifier', args=[proj.id]), {
            'nom': 'Projet Salle d\'Opération Rénovée',
            'description': 'Modernisation V2',
            'statut': 'EN_COURS',
            'fournisseur': str(autre_fournisseur.id),
            'articles[]': [str(self.article.id)],
            'quantites[]': ['25'],
        }, follow=True)
        self.assertEqual(res_mod.status_code, 200)
        proj.refresh_from_db()
        self.assertEqual(proj.nom, 'Projet Salle d\'Opération Rénovée')
        self.assertEqual(proj.fournisseur, autre_fournisseur)

    def test_sortie_projet_affecte_fournisseur_et_pdf(self):
        """Vérifie qu'une sortie de projet affecte le fournisseur du projet et l'affiche sur le PDF."""
        from stock.models import BonMouvement
        from stock.pdf_utils import get_pdf_config
        from django.template.loader import render_to_string

        self.projet.fournisseur = self.fournisseur
        self.projet.save()

        session = self.client.session
        session['magasin_actif_id'] = str(self.magasin_avec_projet.id)
        session.save()

        post_data = {
            'magasin': str(self.magasin_avec_projet.id),
            'type_sortie': 'SORTIE_PROJET',
            'projet': str(self.projet.id),
            'reference_externe': 'SORTIE-PROJ-TEST',
            'articles[]': [str(self.article.id)],
            'quantites[]': ['4'],
        }
        res = self.client.post(reverse('liste_sorties'), post_data, follow=True)
        self.assertEqual(res.status_code, 200)

        bon = BonMouvement.objects.filter(projet=self.projet, type_bon='SORTIE_PROJET').first()
        self.assertIsNotNone(bon)
        self.assertEqual(bon.fournisseur, self.fournisseur)

        # Vérification vue PDF
        res_pdf = self.client.get(reverse('imprimer_bon_multi_lignes', args=[bon.id]))
        self.assertEqual(res_pdf.status_code, 200)

        # Rendu template HTML PDF
        pdf_config, _ = get_pdf_config(bon.magasin, 'BS', None)
        html = render_to_string('stock/pdf/bon_sortie.html', {'bon': bon, 'service': None, 'pdf_config': pdf_config})
        self.assertIn('DESTINATAIRE (PROJET)', html)
        self.assertIn(self.projet.nom, html)
        self.assertIn('ENTREPRISE EN CHARGE :', html)
        self.assertIn(self.fournisseur.raison_sociale, html)

    def test_entree_projet_fournisseur_par_defaut_et_pdf(self):
        """Vérifie qu'une entrée liée au projet hérite du fournisseur du projet et l'affiche sur le PDF."""
        from stock.models import BonMouvement
        from stock.pdf_utils import get_pdf_config
        from django.template.loader import render_to_string

        self.projet.fournisseur = self.fournisseur
        self.projet.save()

        session = self.client.session
        session['magasin_actif_id'] = str(self.magasin_avec_projet.id)
        session.save()

        post_data = {
            'magasin': str(self.magasin_avec_projet.id),
            'projet': str(self.projet.id),
            'reference_externe': 'BL-PROJ-TEST',
            'articles[]': [str(self.article.id)],
            'quantites[]': ['10'],
            'lots[]': ['LOT-BL-01'],
            'peremptions[]': ['2030-01-01'],
            'prix_unitaires[]': ['5000'],
        }
        res = self.client.post(reverse('liste_entrees'), post_data, follow=True)
        self.assertEqual(res.status_code, 200)

        bon = BonMouvement.objects.filter(projet=self.projet, type_bon='ENTREE').first()
        self.assertIsNotNone(bon)
        self.assertEqual(bon.fournisseur, self.fournisseur)

        # Vérification vue PDF
        res_pdf = self.client.get(reverse('bon_entree_pdf', args=[bon.id]))
        self.assertEqual(res_pdf.status_code, 200)

        # Rendu template HTML PDF
        pdf_config, _ = get_pdf_config(bon.magasin, 'BE', None)
        html = render_to_string('stock/pdf/bon_entree.html', {'bon': bon, 'pdf_config': pdf_config})
        self.assertIn('DESTINATION / PROJET', html)
        self.assertIn(self.projet.nom, html)
        self.assertIn('FOURNISSEUR :', html)
        self.assertIn(self.fournisseur.raison_sociale, html)

    def test_retour_projet_fournisseur_et_pdf(self):
        """Vérifie qu'un retour projet associe le fournisseur et l'affiche sur le PDF."""
        from stock.models import BonMouvement
        from stock.pdf_utils import get_pdf_config
        from django.template.loader import render_to_string

        self.projet.fournisseur = self.fournisseur
        self.projet.save()

        session = self.client.session
        session['magasin_actif_id'] = str(self.magasin_avec_projet.id)
        session.save()

        post_data = {
            'magasin': str(self.magasin_avec_projet.id),
            'type_retour': 'RETOUR_PROJET',
            'projet': str(self.projet.id),
            'reference_externe': 'RET-PROJ-TEST',
            'articles[]': [str(self.article.id)],
            'quantites[]': ['1'],
            'lots[]': ['LOT-RET-01'],
            'peremptions[]': ['2030-01-01'],
        }
        res = self.client.post(reverse('liste_retours_services'), post_data, follow=True)
        self.assertEqual(res.status_code, 200)

        bon = BonMouvement.objects.filter(projet=self.projet, type_bon='RETOUR_PROJET').first()
        self.assertIsNotNone(bon)
        self.assertEqual(bon.fournisseur, self.fournisseur)

        # Vérification vue PDF
        res_pdf = self.client.get(reverse('imprimer_bon_multi_lignes', args=[bon.id]))
        self.assertEqual(res_pdf.status_code, 200)

        # Rendu template HTML PDF
        pdf_config, _ = get_pdf_config(bon.magasin, 'BR', None)
        html = render_to_string('stock/pdf/bon_retour.html', {'bon': bon, 'service': None, 'pdf_config': pdf_config})
        self.assertIn('ORIGINE (PROJET)', html)
        self.assertIn(self.projet.nom, html)
        self.assertIn('ENTREPRISE EN CHARGE :', html)
        self.assertIn(self.fournisseur.raison_sociale, html)

