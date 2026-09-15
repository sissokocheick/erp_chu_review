# -*- coding: utf-8 -*-
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone

from core.models import Service
from stock.models import (
    Magasin, Fournisseur, Article, FamilleArticle, StockItem,
    BonMouvement, DemandeMateriel, LigneDemande
)
from stock.services.bon_service import BonService
from patrimoine.models import (
    CategoriePatrimoine, TypeEquipement, Immobilisation,
    MouvementPatrimoine, Intervention
)

User = get_user_model()


class FluxStockPatrimoineIntegrationTestCase(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            username="gestionnaire_stock",
            password="testpassword123",
            email="stock@chu.ci"
        )
        if hasattr(self.user, 'profil'):
            self.user.profil.doit_changer_mdp = False
            self.user.profil.save()

        self.service = Service.objects.create(code="CARDIO", nom="Cardiologie")
        self.fournisseur = Fournisseur.objects.create(code="F01", raison_sociale="Fournisseur Médical")
        self.magasin = Magasin.objects.create(nom="Pharmacie Centrale")

        self.famille_immo = FamilleArticle.objects.create(
            code="FAM-EQUIP",
            intitule="Équipements Biomédicaux",
            type_famille="MED",
            est_immobilisable=True
        )
        self.article_immo = Article.objects.create(
            famille=self.famille_immo,
            reference="ART-ECG-01",
            designation="Électrocardiographe 12 pistes",
            unite_distribution="UNITE",
            prix_reference=Decimal("1500000.00"),
            est_immobilisable=True
        )

        self.categorie_pat = CategoriePatrimoine.objects.create(
            code="MED",
            nom="Matériel Médical"
        )
        self.type_eq = TypeEquipement.objects.create(
            categorie=self.categorie_pat,
            nom=self.article_immo.designation,
            code="ECG-12P",
            est_actif=True
        )

    def test_flux_entree_puis_sortie_vers_sas_patrimoine(self):
        """
        Vérifie le cycle complet :
        1. Entrée en stock de 2 ECG -> mise à jour stock & CMUP
        2. Sortie de stock de 2 ECG pour le service Cardio
        3. Détection automatique et création de 2 biens dans le Sas Patrimoine
        """
        # 1. Entrée en stock de 2 unités à 1 500 000 FCFA chacune
        bon_entree = BonService.creer_bon_entree(
            lignes=[{
                'article_id': self.article_immo.id,
                'quantite': 2,
                'prix_unitaire': Decimal("1500000.00")
            }],
            utilisateur=self.user,
            magasin=self.magasin,
            fournisseur=self.fournisseur,
            commentaire="Réception commande ECG"
        )
        self.assertEqual(bon_entree.statut_validation, "VALIDE")

        stock_item = StockItem.objects.get(article=self.article_immo, magasin=self.magasin)
        self.assertEqual(stock_item.quantite_physique, 2)
        self.assertEqual(stock_item.valeur_cmup, Decimal("1500000.00"))

        # Aucune immobilisation créée à l'entrée
        self.assertEqual(Immobilisation.objects.filter(article_stock=self.article_immo).count(), 0)

        # 2. Sortie de stock de 2 unités pour la Cardiologie
        bon_sortie = BonService.creer_bon_sortie(
            lignes=[{
                'article_id': self.article_immo.id,
                'quantite': 2,
                'prix_unitaire': Decimal("1500000.00")
            }],
            utilisateur=self.user,
            magasin=self.magasin,
            service_demandeur=self.service,
            commentaire="Dotation service Cardiologie"
        )
        self.assertEqual(bon_sortie.statut_validation, "VALIDE")

        # Le stock physique doit être tombé à 0
        stock_item.refresh_from_db()
        self.assertEqual(stock_item.quantite_physique, 0)

        # 3. Le signal doit avoir créé exactement 2 immobilisations dans le SAS
        immos_sas = Immobilisation.objects.filter(bon_sortie_origine=bon_sortie)
        self.assertEqual(immos_sas.count(), 2)

        for immo in immos_sas:
            self.assertEqual(immo.statut, 'EN_ATTENTE')
            self.assertEqual(immo.service_affectation, self.service)
            self.assertEqual(immo.valeur_acquisition, Decimal("1500000.00"))
            self.assertEqual(immo.article_stock, self.article_immo)
            self.assertEqual(immo.nom_affichage, self.article_immo.designation)

    def test_annulation_bon_sortie_nettoie_le_sas_si_en_attente(self):
        """
        Vérifie que l'annulation d'un bon de sortie dont les biens sont encore dans le Sas
        nettoie proprement le Sas (supprime les enregistrements en attente) et restitue le stock.
        """
        BonService.creer_bon_entree(
            lignes=[{'article_id': self.article_immo.id, 'quantite': 1, 'prix_unitaire': Decimal("1500000.00")}],
            utilisateur=self.user, magasin=self.magasin, fournisseur=self.fournisseur
        )
        bon_sortie = BonService.creer_bon_sortie(
            lignes=[{'article_id': self.article_immo.id, 'quantite': 1, 'prix_unitaire': Decimal("1500000.00")}],
            utilisateur=self.user, magasin=self.magasin, service_demandeur=self.service
        )
        # Vérifier présence dans le Sas
        self.assertEqual(Immobilisation.objects.filter(bon_sortie_origine=bon_sortie, statut='EN_ATTENTE').count(), 1)

        # Annulation du bon de sortie
        BonService.annuler_bon_sortie(bon_sortie, "Erreur de destination", self.user)

        # Bon annulé
        bon_sortie.refresh_from_db()
        self.assertTrue(bon_sortie.est_annule)

        # Stock réintégré
        stock_item = StockItem.objects.get(article=self.article_immo, magasin=self.magasin)
        self.assertEqual(stock_item.quantite_physique, 1)

        # Le Sas a été purgé : 0 immobilisation orpheline restante
        self.assertEqual(Immobilisation.objects.filter(bon_sortie_origine=bon_sortie).count(), 0)

    def test_annulation_bloquee_si_bien_deja_actif_dans_patrimoine(self):
        """
        Garde-fou critique : si un équipement issu d'un bon de sortie a déjà été immatriculé
        et activé dans le patrimoine, l'annulation du bon de sortie DOIT être bloquée.
        """
        BonService.creer_bon_entree(
            lignes=[{'article_id': self.article_immo.id, 'quantite': 1, 'prix_unitaire': Decimal("1500000.00")}],
            utilisateur=self.user, magasin=self.magasin, fournisseur=self.fournisseur
        )
        bon_sortie = BonService.creer_bon_sortie(
            lignes=[{'article_id': self.article_immo.id, 'quantite': 1, 'prix_unitaire': Decimal("1500000.00")}],
            utilisateur=self.user, magasin=self.magasin, service_demandeur=self.service
        )
        immo = Immobilisation.objects.filter(bon_sortie_origine=bon_sortie).first()
        self.assertIsNotNone(immo)

        # Validation du bien dans le patrimoine (activation)
        immo.statut = 'ACTIF'
        immo.code_patrimoine = '26-MED-00001'
        immo.save()

        # Tentative d'annulation du bon de sortie -> Doit lever ValidationError
        with self.assertRaises(ValidationError) as ctx:
            BonService.annuler_bon_sortie(bon_sortie, "Annulation refusée attendue", self.user)

        self.assertIn("déjà actif dans le patrimoine", str(ctx.exception))

        # Le bon n'est PAS annulé et le bien reste actif
        bon_sortie.refresh_from_db()
        self.assertFalse(bon_sortie.est_annule)
        self.assertEqual(Immobilisation.objects.filter(code_patrimoine='26-MED-00001', statut='ACTIF').count(), 1)

    def test_flux_sortie_hors_stock_vers_sas_et_annulation(self):
        """
        Vérifie le flux de sortie hors stock :
        - Création d'un bon hors-stock pour article immobilisable crée bien l'immo dans le Sas
        - Annulation du bon hors-stock supprime l'immo en attente du Sas
        """
        bon_hs = BonService.creer_bon_hors_stock(
            lignes=[{'article_id': self.article_immo.id, 'quantite': 1, 'prix_unitaire': Decimal("1500000.00")}],
            utilisateur=self.user,
            magasin=self.magasin,
            service_demandeur=self.service,
        )
        self.assertEqual(Immobilisation.objects.filter(bon_sortie_origine=bon_hs, statut='EN_ATTENTE').count(), 1)

        # Annuler le bon hors stock
        BonService.annuler_bon_hors_stock(bon_hs, "Annulation test", self.user)
        bon_hs.refresh_from_db()
        self.assertTrue(bon_hs.est_annule)

        # Sas nettoyé
        self.assertEqual(Immobilisation.objects.filter(bon_sortie_origine=bon_hs).count(), 0)

    def test_liaison_demande_pieces_stock_et_intervention_patrimoine(self):
        """
        Vérifie l'interaction entre une intervention de maintenance dans Patrimoine
        et la demande de pièces détachées dans Stock.
        """
        immo = Immobilisation.objects.create(
            type_equipement=self.type_eq,
            nom_affichage="Appareil ECG Réparé",
            code_patrimoine="IMM-TEST-0099",
            service_affectation=self.service,
            valeur_acquisition=Decimal("1500000.00"),
            statut="ACTIF",
            cree_par=self.user
        )
        intervention = Intervention.objects.create(
            immobilisation=immo,
            diagnostic="Câble patient défectueux",
            type_intervention="CURATIVE",
            statut="EN_ATTENTE_PIECES",
            cree_par=self.user
        )
        demande_stock = DemandeMateriel.objects.create(
            service_demandeur=self.service,
            magasin_cible=self.magasin,
            demandeur=self.user,
            statut="EN_ATTENTE",
            commentaire=f"Pièces pour intervention #{intervention.id}"
        )

        intervention.demandes_pieces.add(demande_stock)

        # Vérifier la double relation ORM
        self.assertIn(demande_stock, intervention.demandes_pieces.all())
        self.assertIn(intervention, demande_stock.intervention_set.all())
