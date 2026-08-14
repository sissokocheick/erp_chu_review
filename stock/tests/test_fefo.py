# -*- coding: utf-8 -*-
"""
Tests de la politique FEFO (First-Expired-First-Out) à la sortie.

Couvre :
- Le résolveur `StockTransactionService.resoudre_lots_fefo` (ordre de
  consommation, lots périmés bloqués, messages d'erreur).
- `BonService.creer_bon_sortie` : découpage par lot + blocage périmé.
- `BonService.valider_bon_sortie` (circuit de validation) : FEFO au moment
  de la validation.
- `LivraisonService.traiter_demande` (guichet) : FEFO + blocage périmé.
- Annulation d'une sortie par lot : remise en stock sur le bon lot.
"""
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from core.models import Service
from stock.models import (
    StockItem, BonMouvement, Mouvement, MotifAnnulation,
    DemandeMateriel, LigneDemande, CircuitValidation,
)
from stock.services.bon_service import BonService
from stock.services.livraison_service import LivraisonService
from stock.services.stock_transaction_service import StockTransactionService
from stock.tests import factories


class BaseFEFOTest(TestCase):
    def setUp(self):
        self.user = factories.creer_utilisateur()
        self.famille = factories.creer_famille(code="FAMLOT", intitule="Lots")
        self.article = factories.creer_article(
            famille=self.famille, designation="Médicament géré en lot",
            reference="LOT-1", gere_lots_peremption=True)
        self.magasin = factories.creer_magasin(nom="Pharmacie")

    def _creer_lot(self, numero, quantite, jours_avant_peremption):
        """Crée un StockItem par lot avec une date de péremption relative."""
        expiry = timezone.now().date() + timedelta(days=jours_avant_peremption)
        return factories.creer_stock(
            self.article, self.magasin, quantite=quantite,
            batch_number=numero, expiry_date=expiry)

    def _qte_lot(self, numero):
        return StockItem.objects.get(
            article=self.article, magasin=self.magasin,
            batch_number=numero).quantite_physique


# ════════════════════════════════════════════════════════════════
# Résolveur FEFO
# ════════════════════════════════════════════════════════════════
class ResolveurFEFOTest(BaseFEFOTest):

    def test_article_sans_gestion_lots_retourne_vide(self):
        art = factories.creer_article(
            famille=self.famille, reference="NL-1", gere_lots_peremption=False)
        self.assertEqual(
            StockTransactionService.resoudre_lots_fefo(art, self.magasin, 5), [])

    def test_fefo_consomme_le_lot_le_plus_proche_de_peremption(self):
        self._creer_lot("A", 10, 60)
        self._creer_lot("B", 10, 30)
        consos = StockTransactionService.resoudre_lots_fefo(
            self.article, self.magasin, 15)
        self.assertEqual([c['numero_lot'] for c in consos], ['B', 'A'])
        self.assertEqual(consos[0]['quantite'], 10)
        self.assertEqual(consos[1]['quantite'], 5)

    def test_consommation_partielle_d_un_seul_lot(self):
        self._creer_lot("A", 10, 30)
        consos = StockTransactionService.resoudre_lots_fefo(
            self.article, self.magasin, 4)
        self.assertEqual(len(consos), 1)
        self.assertEqual(consos[0]['numero_lot'], 'A')
        self.assertEqual(consos[0]['quantite'], 4)

    def test_lot_perime_seul_est_bloque(self):
        self._creer_lot("PERIME", 10, -5)
        with self.assertRaises(ValidationError) as cm:
            StockTransactionService.resoudre_lots_fefo(
                self.article, self.magasin, 5)
        self.assertIn("périmé", str(cm.exception))

    def test_lot_perime_ignore_si_stock_valide_suffisant(self):
        self._creer_lot("PERIME", 50, -5)
        self._creer_lot("BON", 10, 30)
        consos = StockTransactionService.resoudre_lots_fefo(
            self.article, self.magasin, 8)
        self.assertEqual([c['numero_lot'] for c in consos], ['BON'])
        self.assertEqual(consos[0]['quantite'], 8)

    def test_message_mentionne_les_unites_perimees_bloquees(self):
        self._creer_lot("PERIME", 8, -5)
        self._creer_lot("BON", 5, 30)
        with self.assertRaises(ValidationError) as cm:
            StockTransactionService.resoudre_lots_fefo(
                self.article, self.magasin, 10)
        msg = str(cm.exception)
        self.assertIn("périmé", msg)
        self.assertIn("8", msg)  # quantité périmée bloquée mentionnée

    def test_stock_insuffisant_sans_lots_perimes(self):
        self._creer_lot("A", 5, 30)
        with self.assertRaises(ValidationError) as cm:
            StockTransactionService.resoudre_lots_fefo(
                self.article, self.magasin, 10)
        # Aucun lot périmé en jeu : pas de mention d'unités bloquées
        self.assertNotIn("bloquée(s)", str(cm.exception))

    def test_lot_sans_date_consomme_en_dernier(self):
        self._creer_lot("SANS_DATE", 10, 0)
        StockItem.objects.filter(batch_number="SANS_DATE").update(expiry_date=None)
        self._creer_lot("A", 10, 30)
        consos = StockTransactionService.resoudre_lots_fefo(
            self.article, self.magasin, 15)
        self.assertEqual([c['numero_lot'] for c in consos], ['A', 'SANS_DATE'])


# ════════════════════════════════════════════════════════════════
# BonService.creer_bon_sortie (mode direct, sans circuit)
# ════════════════════════════════════════════════════════════════
class CreerBonSortieFEFOTest(BaseFEFOTest):

    def test_sortie_decoupee_par_lot_fefo(self):
        self._creer_lot("A", 10, 60)
        self._creer_lot("B", 10, 30)
        bon = BonService.creer_bon_sortie(
            lignes=[{'article_id': self.article.id, 'quantite': 15}],
            utilisateur=self.user, magasin=self.magasin)
        mvts = Mouvement.objects.filter(
            reference_document=bon.numero_bon, type_mouvement='SORTIE')
        self.assertEqual(mvts.count(), 2)
        by_lot = {m.numero_lot: m.quantite for m in mvts}
        self.assertEqual(by_lot, {'B': 10, 'A': 5})
        # Stock décrémenté par lot
        self.assertEqual(self._qte_lot('B'), 0)
        self.assertEqual(self._qte_lot('A'), 5)
        # Une ligne de bon par lot, avec lot renseigné (traçabilité PDF)
        lignes = bon.lignes_bon.all()
        self.assertEqual(lignes.count(), 2)
        self.assertTrue(all(l.numero_lot for l in lignes))

    def test_sortie_bloquee_si_stock_uniquement_perime(self):
        self._creer_lot("PERIME", 10, -5)
        with self.assertRaises(ValidationError):
            BonService.creer_bon_sortie(
                lignes=[{'article_id': self.article.id, 'quantite': 5}],
                utilisateur=self.user, magasin=self.magasin)
        # Rollback : aucun bon ni mouvement créé
        self.assertEqual(
            BonMouvement.objects.filter(type_bon='SORTIE').count(), 0)
        self.assertEqual(
            Mouvement.objects.filter(type_mouvement='SORTIE').count(), 0)

    def test_sortie_bloquee_si_perimes_necessaires_pour_couvrir(self):
        self._creer_lot("PERIME", 10, -5)
        self._creer_lot("BON", 3, 30)
        with self.assertRaises(ValidationError) as cm:
            BonService.creer_bon_sortie(
                lignes=[{'article_id': self.article.id, 'quantite': 5}],
                utilisateur=self.user, magasin=self.magasin)
        self.assertIn("périmé", str(cm.exception))
        self.assertEqual(
            BonMouvement.objects.filter(type_bon='SORTIE').count(), 0)

    def test_article_sans_lots_comportement_inchange(self):
        art = factories.creer_article(
            famille=self.famille, designation="Sans lot",
            reference="NL-2", gere_lots_peremption=False)
        factories.creer_stock(art, self.magasin, quantite=10)
        bon = BonService.creer_bon_sortie(
            lignes=[{'article_id': art.id, 'quantite': 6}],
            utilisateur=self.user, magasin=self.magasin)
        mvt = Mouvement.objects.get(
            reference_document=bon.numero_bon, type_mouvement='SORTIE')
        self.assertIsNone(mvt.numero_lot)
        self.assertEqual(
            StockItem.objects.get(
                article=art, magasin=self.magasin,
                batch_number__isnull=True).quantite_physique, 4)

    def test_annulation_remet_le_stock_sur_le_bon_lot(self):
        self._creer_lot("A", 10, 60)
        bon = BonService.creer_bon_sortie(
            lignes=[{'article_id': self.article.id, 'quantite': 6}],
            utilisateur=self.user, magasin=self.magasin)
        self.assertEqual(self._qte_lot('A'), 4)
        motif = MotifAnnulation.objects.create(libelle="Erreur de saisie")
        BonService.annuler_bon_sortie(bon, motif, self.user)
        self.assertEqual(self._qte_lot('A'), 10)


# ════════════════════════════════════════════════════════════════
# BonService.valider_bon_sortie (circuit de validation)
# ════════════════════════════════════════════════════════════════
class ValiderBonSortieFEFOTest(BaseFEFOTest):

    def setUp(self):
        super().setUp()
        self.circuit = CircuitValidation.objects.create(
            type_document='SORTIE', est_actif=True)
        self.circuit.valideurs.add(self.user)

    def test_validation_decoupe_par_lot_fefo(self):
        self._creer_lot("A", 10, 60)
        self._creer_lot("B", 10, 30)
        bon = BonService.creer_bon_sortie(
            lignes=[{'article_id': self.article.id, 'quantite': 12}],
            utilisateur=self.user, magasin=self.magasin,
            circuit_validation=self.circuit)
        self.assertEqual(bon.statut_validation, 'ATTENTE')
        # Aucun mouvement tant que le bon n'est pas validé
        self.assertEqual(
            Mouvement.objects.filter(
                reference_document=bon.numero_bon).count(), 0)
        BonService.valider_bon_sortie(bon, self.user)
        mvts = Mouvement.objects.filter(
            reference_document=bon.numero_bon, type_mouvement='SORTIE')
        self.assertEqual(mvts.count(), 2)
        by_lot = {m.numero_lot: m.quantite for m in mvts}
        self.assertEqual(by_lot, {'B': 10, 'A': 2})
        self.assertEqual(self._qte_lot('B'), 0)
        self.assertEqual(self._qte_lot('A'), 8)

    def test_validation_bloquee_si_stock_perime_entre_temps(self):
        self._creer_lot("PERIME", 10, -5)
        bon = BonService.creer_bon_sortie(
            lignes=[{'article_id': self.article.id, 'quantite': 5}],
            utilisateur=self.user, magasin=self.magasin,
            circuit_validation=self.circuit)
        with self.assertRaises(ValidationError):
            BonService.valider_bon_sortie(bon, self.user)
        # Le bon reste en attente, aucun stock décompté
        bon.refresh_from_db()
        self.assertEqual(bon.statut_validation, 'ATTENTE')


# ════════════════════════════════════════════════════════════════
# LivraisonService.traiter_demande (guichet)
# ════════════════════════════════════════════════════════════════
class TraiterDemandeFEFOTest(BaseFEFOTest):

    def setUp(self):
        super().setUp()
        self.service = Service.objects.create(code='SRV-FEFO', nom='Cardiologie')

    def _creer_demande(self, quantite):
        demande = DemandeMateriel.objects.create(
            numero_demande='DM-FEFO-1',
            demandeur=self.user,
            service_demandeur=self.service,
            magasin_cible=self.magasin,
            statut='EN_ATTENTE',
        )
        ligne = LigneDemande.objects.create(
            demande=demande, article=self.article,
            quantite_demandee=quantite)
        return demande, ligne

    def test_traitement_decoupe_par_lot_fefo(self):
        self._creer_lot("A", 10, 60)
        self._creer_lot("B", 10, 30)
        demande, ligne = self._creer_demande(quantite=8)
        LivraisonService.traiter_demande(
            demande, self.magasin.id, {ligne.id: 8}, self.user)
        mvts = Mouvement.objects.filter(
            type_mouvement='SORTIE', numero_lot__isnull=False)
        by_lot = {m.numero_lot: m.quantite for m in mvts}
        self.assertEqual(by_lot, {'B': 8})
        self.assertEqual(self._qte_lot('B'), 2)
        self.assertEqual(self._qte_lot('A'), 10)

    def test_traitement_bloque_si_stock_perime(self):
        self._creer_lot("PERIME", 10, -5)
        demande, ligne = self._creer_demande(quantite=5)
        with self.assertRaises(ValidationError) as cm:
            LivraisonService.traiter_demande(
                demande, self.magasin.id, {ligne.id: 5}, self.user)
        self.assertIn("périmé", str(cm.exception))
        # Aucun bon de sortie créé (rollback)
        self.assertEqual(
            BonMouvement.objects.filter(type_bon='SORTIE').count(), 0)
