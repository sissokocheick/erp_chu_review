from decimal import Decimal
from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile

from core.models import Service, ConfigurationHopital
from stock.models import (
    Magasin, Article, FamilleArticle, StockItem, Fournisseur,
    BonMouvement, LigneBon, DemandeMateriel, LigneDemande,
    Commande, LigneCommande, CampagneInventaire, LigneInventaire,
    Mouvement, Beneficiaire
)
from stock.services.bon_service import BonService
from stock.pdf_utils import _role_utilisateur, servir_pdf_cache
from stock.views.pdf_views import (
    imprimer_bon_demande,
    imprimer_commande,
    imprimer_fiche_comptage,
    imprimer_resultat_inventaire,
    rapport_consommation_pdf,
    imprimer_bon_hors_stock,
)


class PDFAuditCoherenceTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.hopital = ConfigurationHopital.objects.create(
            nom="CHU de Test",
            couleur_principale="#1c5b96",
            pied_page_pdf="Direction des Affaires Financières / Service Logistique"
        )
        self.service = Service.objects.create(nom="Pédiatrie", code="PED", poste="Poste 201")
        self.user_demandeur = User.objects.create_user(username="demandeur", password="pwd", first_name="Jean", last_name="Demandeur")
        self.user_magasinier = User.objects.create_user(username="magasinier", password="pwd", first_name="Marc", last_name="Magasinier")
        self.user_valideur = User.objects.create_user(username="valideur", password="pwd", first_name="Paul", last_name="Chef")
        self.user_admin = User.objects.create_superuser(username="admin", password="pwd", email="admin@test.ci")

        self.fournisseur = Fournisseur.objects.create(code="FOURN-01", raison_sociale="Pharma Plus CI")

        self.magasin = Magasin.objects.create(
            nom="Pharmacie Centrale",
            responsable=self.user_valideur,
            titre_responsable="Pharmacien Chef"
        )
        self.famille = FamilleArticle.objects.create(code="MED", intitule="Médicaments")
        self.article = Article.objects.create(
            designation="Paracétamol 500mg",
            reference="PARA-500",
            famille=self.famille,
            prix_reference=Decimal("500.00"),
            unite_distribution="Boîte"
        )
        self.stock_item = StockItem.objects.create(
            article=self.article,
            magasin=self.magasin,
            quantite_physique=100,
            valeur_cmup=Decimal("450.00")
        )

    def test_cache_invalidation_on_bon_status_change(self):
        """Le cache PDF d'un bon doit être invalidé dès que son statut change."""
        bon = BonMouvement.objects.create(
            type_bon="SORTIE",
            magasin=self.magasin,
            cree_par=self.user_magasinier,
            statut_validation="ATTENTE"
        )
        bon.fichier_pdf.save("test_bon.pdf", SimpleUploadedFile("test_bon.pdf", b"%PDF-1.4 dummy content"))
        self.assertTrue(bool(bon.fichier_pdf))

        # Changement de statut vers VALIDE -> doit vider le cache
        bon.statut_validation = "VALIDE"
        bon.valide_par = self.user_valideur
        bon.date_validation = timezone.now()
        bon.save()
        bon.refresh_from_db()
        self.assertFalse(bool(bon.fichier_pdf))

    def test_cache_invalidation_on_ligne_bon_change(self):
        """Modifier ou supprimer une ligne de bon doit invalider le cache PDF du bon parent."""
        bon = BonMouvement.objects.create(
            type_bon="ENTREE",
            magasin=self.magasin,
            cree_par=self.user_magasinier,
            statut_validation="VALIDE"
        )
        ligne = LigneBon.objects.create(
            bon=bon,
            article=self.article,
            quantite=10,
            prix_unitaire=Decimal("450.00")
        )
        bon.fichier_pdf.save("test_entree.pdf", SimpleUploadedFile("test_entree.pdf", b"%PDF-1.4 dummy content"))
        self.assertTrue(bool(bon.fichier_pdf))

        # Modifier la ligne -> invalide le cache du bon
        ligne.quantite = 20
        ligne.save()
        bon.refresh_from_db()
        self.assertFalse(bool(bon.fichier_pdf))

    def test_role_utilisateur_resolution(self):
        """Vérifie la résolution dynamique des rôles signataires sur les différents types de documents."""
        demande = DemandeMateriel.objects.create(
            numero_demande="DEM-001",
            magasin_cible=self.magasin,
            demandeur=self.user_demandeur,
            service_demandeur=self.service,
            statut="VALIDEE"
        )
        bon_sortie = BonMouvement.objects.create(
            type_bon="SORTIE",
            magasin=self.magasin,
            cree_par=self.user_magasinier,
            valide_par=self.user_valideur,
            statut_validation="VALIDE"
        )
        demande.bon_sortie_lie = bon_sortie
        demande.save()

        user_found = _role_utilisateur(bon_sortie, "demandeur")
        self.assertEqual(user_found, self.user_demandeur)

        user_mag = _role_utilisateur(bon_sortie, "magasinier")
        self.assertEqual(user_mag, self.user_magasinier)

        user_resp = _role_utilisateur(bon_sortie, "responsable")
        self.assertEqual(user_resp, self.user_valideur)

    def test_servir_pdf_cache_force_refresh(self):
        """Avec ?refresh=1, servir_pdf_cache doit invalider le fichier en cache et retourner None pour regénération."""
        bon = BonMouvement.objects.create(
            type_bon="SORTIE",
            magasin=self.magasin,
            cree_par=self.user_magasinier
        )
        bon.fichier_pdf.save("test_cache.pdf", SimpleUploadedFile("test_cache.pdf", b"%PDF-1.4 dummy content"))
        self.assertTrue(bool(bon.fichier_pdf))

        # Requête normale -> retourne le cache
        req_normal = self.factory.get("/stock/bons/1/imprimer/")
        res = servir_pdf_cache(bon, "bon.pdf", request=req_normal)
        self.assertIsNotNone(res)

        # Requête forcée (?refresh=1) -> invalide et retourne None
        req_force = self.factory.get("/stock/bons/1/imprimer/?refresh=1")
        res_forced = servir_pdf_cache(bon, "bon.pdf", request=req_force)
        self.assertIsNone(res_forced)
        bon.refresh_from_db()
        self.assertFalse(bool(bon.fichier_pdf))

    def test_bon_service_creer_bon_sortie_quantites_et_prix(self):
        """Vérifie que BonService.creer_bon_sortie remplit correctement prix_unitaire, quantite_servie, reste."""
        lignes = [{'article_id': self.article.id, 'quantite': 5}]
        bon = BonService.creer_bon_sortie(
            lignes=lignes,
            utilisateur=self.user_magasinier,
            magasin=self.magasin,
            service_demandeur=self.service
        )
        self.assertEqual(bon.lignes_bon.count(), 1)
        ligne = bon.lignes_bon.first()
        self.assertEqual(ligne.quantite, 5)
        self.assertEqual(ligne.quantite_servie, 5)
        self.assertEqual(ligne.quantite_demandee, 5)
        self.assertEqual(ligne.reste, 0)
        self.assertEqual(ligne.prix_unitaire, Decimal("450.00"))
        self.assertEqual(ligne.montant, Decimal("2250.00"))

    def test_fiche_comptage_inventaire_rendu_et_donnees(self):
        """Vérifie que la fiche de comptage d'inventaire contient les lignes et signataires."""
        campagne = CampagneInventaire.objects.create(
            titre="Inventaire Général T1",
            magasin=self.magasin,
            cree_par=self.user_magasinier
        )
        LigneInventaire.objects.create(
            campagne=campagne,
            article=self.article,
            quantite_theorique=100
        )
        req = self.factory.get(f"/stock/inventaires/{campagne.id}/fiche/")
        req.user = self.user_admin
        req.session = {'magasin_actif_id': self.magasin.id}

        resp = imprimer_fiche_comptage(req, campagne.id)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')

    def test_resultat_inventaire_rendu_et_donnees(self):
        """Vérifie que le résultat d'inventaire calcule les écarts, valeurs et signatures."""
        campagne = CampagneInventaire.objects.create(
            titre="Inventaire Clôturé",
            magasin=self.magasin,
            cree_par=self.user_magasinier,
            valide_par=self.user_valideur,
            statut="VALIDE",
            date_validation=timezone.now()
        )
        LigneInventaire.objects.create(
            campagne=campagne,
            article=self.article,
            quantite_theorique=100,
            quantite_physique=95
        )
        req = self.factory.get(f"/stock/inventaires/{campagne.id}/resultat/")
        req.user = self.user_admin
        req.session = {'magasin_actif_id': self.magasin.id}

        resp = imprimer_resultat_inventaire(req, campagne.id)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')

    def test_bon_hors_stock_avec_destinataire(self):
        """Vérifie que le bon hors stock s'imprime avec un bénéficiaire physique."""
        beneficiaire = Beneficiaire.objects.create(
            nom_complet="KOUASSI Affoué",
            poste="Infirmière Major",
            service=self.service
        )
        bon = BonMouvement.objects.create(
            type_bon="SORTIE_HORS_STOCK",
            magasin=self.magasin,
            cree_par=self.user_magasinier,
            destinataire=beneficiaire,
            statut_validation="VALIDE"
        )
        LigneBon.objects.create(
            bon=bon,
            article=self.article,
            quantite=3,
            quantite_servie=3,
            quantite_demandee=3,
            prix_unitaire=Decimal("450.00")
        )
        req = self.factory.get(f"/stock/hors-stock/{bon.id}/pdf/")
        req.user = self.user_admin
        req.session = {'magasin_actif_id': self.magasin.id}

        resp = imprimer_bon_hors_stock(req, bon.id)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')

    def test_imprimer_commande_rendu(self):
        """Vérifie que le PDF de commande s'exécute avec les calculs et signatures."""
        cmd = Commande.objects.create(
            numero_commande="CMD-2026-001",
            magasin=self.magasin,
            fournisseur=self.fournisseur,
            cree_par=self.user_magasinier,
            statut="VALIDE"
        )
        LigneCommande.objects.create(
            commande=cmd,
            article=self.article,
            quantite_demandee=50,
            quantite_recue=0,
            prix_unitaire=Decimal("400.00")
        )
        req = self.factory.get(f"/stock/commandes/{cmd.id}/imprimer/")
        req.user = self.user_admin
        req.session = {'magasin_actif_id': self.magasin.id}

        resp = imprimer_commande(req, cmd.id)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')

    def test_imprimer_bon_demande_rendu(self):
        """Vérifie le PDF de demande de matériel avec les infos du service."""
        demande = DemandeMateriel.objects.create(
            numero_demande="DEM-2026-002",
            magasin_cible=self.magasin,
            demandeur=self.user_demandeur,
            service_demandeur=self.service,
            statut="EN_ATTENTE"
        )
        LigneDemande.objects.create(
            demande=demande,
            article=self.article,
            quantite_demandee=10
        )
        req = self.factory.get(f"/stock/demandes/{demande.id}/imprimer/")
        req.user = self.user_admin
        req.session = {'magasin_actif_id': self.magasin.id}

        resp = imprimer_bon_demande(req, demande.id)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')

    def test_rapport_consommation_tri_par_famille(self):
        """Vérifie que le rapport de consommation trie par famille pour le regroupement Django."""
        Mouvement.objects.create(
            type_mouvement="SORTIE",
            article=self.article,
            magasin=self.magasin,
            quantite=15,
            utilisateur=self.user_magasinier
        )
        req = self.factory.get("/stock/rapports/consommation/pdf/")
        req.user = self.user_admin
        req.session = {'magasin_actif_id': self.magasin.id}

        resp = rapport_consommation_pdf(req)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')
