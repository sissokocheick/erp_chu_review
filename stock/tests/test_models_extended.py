# -*- coding: utf-8 -*-
"""
Tests étendus des modèles du module stock.

Couvre : CMUP, mouvements (entrée/sortie/annulation), StockItem,
validations métier, numérotation auto des articles.
Les cas répétitifs sont générés dynamiquement (chaque cas = un test).
"""
from decimal import Decimal

from django.test import TestCase
from django.core.exceptions import ValidationError
from django.db import IntegrityError

from stock.models import (
    Magasin, Article, FamilleArticle, StockItem, Mouvement, LigneBon,
    BonMouvement,
)
from stock.tests import factories


class BaseStockTest(TestCase):
    def setUp(self):
        self.user = factories.creer_utilisateur()
        self.famille = factories.creer_famille(code="FAM001", intitule="Médicaments")
        self.magasin = factories.creer_magasin(nom="Pharmacie Centrale")
        self.article = factories.creer_article(
            famille=self.famille, designation="Paracétamol 500mg",
            reference="ART-1001",
        )


# ════════════════════════════════════════════════════════════════
# CMUP — calcul du coût moyen unitaire pondéré
# ════════════════════════════════════════════════════════════════
class CMUPCasesTest(BaseStockTest):
    """Cas de calcul CMUP (chaque cas = un test généré)."""


# (entrees [(quantite, prix)], quantite_attendu, cmup_attendu)
CMUP_CASES = [
    ([(10, '100')], 10, '100.00'),
    ([(20, '100')], 20, '100.00'),
    ([(10, '100'), (20, '100')], 30, '100.00'),
    ([(10, '100'), (10, '200')], 20, '150.00'),
    ([(10, '100'), (20, '200')], 30, '166.67'),
    ([(5, '50'), (5, '150')], 10, '100.00'),
    ([(100, '250'), (100, '350')], 200, '300.00'),
    ([(1, '1000'), (3, '2000')], 4, '1750.00'),
    ([(10, '0'), (10, '200')], 20, '100.00'),
    ([(10, '200'), (10, '0')], 20, '200.00'),  # entrée à prix 0 : CMUP inchangé
    ([(7, '70'), (3, '130')], 10, '88.00'),
    ([(25, '400'), (75, '800')], 100, '700.00'),
    ([(2, '150'), (3, '250'), (5, '350')], 10, '280.00'),
    ([(10, '10.50'), (10, '11.50')], 20, '11.00'),
    ([(40, '125'), (60, '125')], 100, '125.00'),
    ([(1, '9999.99'), (1, '0.01')], 2, '5000.00'),
    ([(3, '100'), (7, '100'), (10, '300')], 20, '200.00'),
    ([(100, '50'), (50, '200')], 150, '100.00'),
    ([(10, '150'), (5, '150'), (15, '150')], 30, '150.00'),
    ([(8, '250'), (2, '750')], 10, '350.00'),
    ([(60, '300'), (40, '200')], 100, '260.00'),
    ([(1, '500'), (1, '500'), (1, '500')], 3, '500.00'),
    ([(30, '100'), (70, '100'), (100, '100')], 200, '100.00'),
    ([(10, '50'), (10, '50'), (10, '50'), (10, '50')], 40, '50.00'),
    ([(5, '120'), (15, '280')], 20, '240.00'),
    ([(2, '333.33'), (8, '333.33')], 10, '333.33'),
    ([(12, '75'), (18, '125')], 30, '105.00'),
    ([(50, '10'), (50, '30'), (100, '20')], 200, '20.00'),
    ([(1, '1'), (1, '2'), (1, '3'), (1, '4')], 4, '2.50'),
    ([(10, '100'), (10, '100'), (10, '100'), (10, '100'), (10, '100')], 50, '100.00'),
    ([(20, '250'), (20, '250'), (60, '250')], 100, '250.00'),
    ([(9, '111'), (1, '999')], 10, '199.80'),
    ([(14, '200'), (6, '200'), (80, '200')], 100, '200.00'),
    ([(3, '1000'), (1, '1000'), (1, '1000'), (5, '1000')], 10, '1000.00'),
    ([(10, '99.90'), (10, '100.10')], 20, '100.00'),
    ([(4, '1250'), (6, '1250')], 10, '1250.00'),
    ([(25, '80'), (75, '80'), (100, '80')], 200, '80.00'),
    ([(2, '450'), (2, '450'), (2, '450'), (2, '450'), (2, '450')], 10, '450.00'),
    ([(100, '10'), (100, '90')], 200, '50.00'),
    ([(5, '600'), (5, '400')], 10, '500.00'),
    ([(10, '200'), (10, '200'), (80, '200')], 100, '200.00'),
    ([(1, '2500'), (9, '2500')], 10, '2500.00'),
    ([(15, '150'), (5, '350')], 20, '200.00'),
    ([(7, '100'), (3, '100'), (10, '100')], 20, '100.00'),
    ([(50, '500'), (50, '1500')], 100, '1000.00'),
    ([(33, '300'), (67, '300')], 100, '300.00'),
    ([(10, '0'), (10, '0')], 20, '0.00'),
    ([(6, '120'), (14, '120')], 20, '120.00'),
    ([(1, '5'), (1, '5'), (1, '5'), (1, '5'), (1, '5'), (1, '5'), (1, '5'), (1, '5'), (1, '5'), (1, '5')], 10, '5.00'),
    ([(4, '250'), (16, '250')], 20, '250.00'),
    ([(8, '125'), (2, '625')], 10, '225.00'),
    ([(10, '100'), (20, '200'), (30, '300')], 60, '233.34'),  # quantize à chaque entrée
    ([(5, '50'), (15, '150'), (20, '200')], 40, '162.50'),
    ([(1, '10000'), (9, '10000')], 10, '10000.00'),
    ([(2, '999'), (8, '999')], 10, '999.00'),
    ([(10, '1'), (10, '1999')], 20, '1000.00'),
    ([(35, '200'), (65, '200')], 100, '200.00'),
    ([(3, '700'), (7, '300')], 10, '420.00'),
    ([(10, '105'), (10, '95')], 20, '100.00'),
    ([(40, '250'), (10, '500')], 50, '300.00'),
    ([(12, '125'), (8, '125'), (30, '125')], 50, '125.00'),
    ([(1, '1'), (99, '199')], 100, '197.02'),
    ([(5, '100'), (5, '100'), (5, '100'), (5, '100'), (5, '100')], 25, '100.00'),
    ([(50, '600'), (50, '600')], 100, '600.00'),
    ([(9, '100'), (1, '1100')], 10, '200.00'),
    ([(2, '250'), (3, '250'), (5, '250'), (10, '250')], 20, '250.00'),
    ([(11, '90'), (9, '110')], 20, '99.00'),
    ([(4, '500'), (6, '500'), (10, '500')], 20, '500.00'),
    ([(1, '750'), (9, '250')], 10, '300.00'),
    ([(20, '100'), (80, '100')], 100, '100.00'),
    ([(15, '400'), (5, '400')], 20, '400.00'),
    ([(10, '150'), (90, '150')], 100, '150.00'),
    ([(7, '70'), (3, '70'), (10, '70')], 20, '70.00'),
    ([(2, '2000'), (8, '2000')], 10, '2000.00'),
    ([(1, '100'), (2, '100'), (3, '100'), (4, '100')], 10, '100.00'),
    ([(30, '100'), (30, '200'), (40, '300')], 100, '210.00'),
    ([(5, '9999'), (5, '1')], 10, '5000.00'),
    ([(13, '77'), (7, '77')], 20, '77.00'),
    ([(10, '250'), (10, '250'), (80, '250')], 100, '250.00'),
    ([(1, '1'), (1, '3'), (2, '2')], 4, '2.00'),
    ([(50, '20'), (50, '20'), (100, '40')], 200, '30.00'),
    ([(6, '100'), (14, '200')], 20, '170.00'),
    ([(3, '150'), (7, '150')], 10, '150.00'),
    ([(10, '123'), (10, '123')], 20, '123.00'),
    ([(8, '500'), (2, '500'), (10, '500')], 20, '500.00'),
    ([(20, '50'), (30, '100'), (50, '150')], 100, '115.00'),
    ([(1, '1'), (1, '1'), (8, '1')], 10, '1.00'),
    ([(25, '400'), (25, '400'), (50, '400')], 100, '400.00'),
    ([(10, '100'), (10, '900')], 20, '500.00'),
    ([(5, '250'), (15, '250')], 20, '250.00'),
    ([(2, '300'), (8, '300')], 10, '300.00'),
    ([(1, '50'), (1, '50'), (1, '50'), (1, '50'), (1, '50'), (1, '50'), (1, '50'), (1, '50'), (1, '50'), (1, '50')], 10, '50.00'),
    ([(10, '100'), (30, '100'), (60, '100')], 100, '100.00'),
    ([(4, '200'), (16, '300')], 20, '280.00'),
    ([(7, '140'), (3, '140')], 10, '140.00'),
    ([(10, '10'), (10, '10'), (10, '10')], 30, '10.00'),
    ([(1, '1'), (1, '2'), (8, '2')], 10, '1.90'),
    ([(22, '100'), (78, '100')], 100, '100.00'),
    ([(5, '100'), (5, '100'), (5, '100'), (5, '100'), (5, '100'), (5, '100'), (5, '100'), (5, '100'), (5, '100'), (5, '100')], 50, '100.00'),
    ([(3, '333'), (7, '333')], 10, '333.00'),
    ([(10, '200'), (90, '200')], 100, '200.00'),
    ([(6, '150'), (4, '150'), (10, '150')], 20, '150.00'),
    ([(1, '100'), (1, '100'), (1, '100'), (1, '100'), (1, '100'), (1, '100'), (1, '100'), (1, '100'), (1, '100'), (1, '100')], 10, '100.00'),
    ([(50, '10'), (50, '10'), (50, '10'), (50, '10')], 200, '10.00'),
    ([(9, '110'), (1, '10')], 10, '100.00'),
    ([(2, '100'), (8, '100')], 10, '100.00'),
    ([(1, '5000'), (9, '5000')], 10, '5000.00'),
    ([(10, '100'), (10, '100'), (10, '100'), (10, '100'), (10, '100'), (10, '100'), (10, '100'), (10, '100'), (10, '100'), (10, '100')], 100, '100.00'),
    ([(5, '60'), (5, '60'), (10, '180')], 20, '120.00'),
    ([(1, '1'), (9, '199')], 10, '179.20'),
    ([(100, '100'), (100, '100')], 200, '100.00'),
    ([(3, '100'), (3, '100'), (3, '100'), (1, '100')], 10, '100.00'),
]


def _make_cmup_case(entrees, qte_attendu, cmup_attendu):
    def test(self):
        for quantite, prix in entrees:
            factories.creer_mouvement(
                self.article, self.magasin, self.user, 'ENTREE', quantite,
                prix_unitaire=Decimal(prix),
            )
        stock = StockItem.objects.get(article=self.article, magasin=self.magasin)
        self.assertEqual(stock.quantite_physique, qte_attendu)
        self.assertEqual(stock.valeur_cmup, Decimal(cmup_attendu))
    return test


for _i, (entrees, qte, cmup) in enumerate(CMUP_CASES):
    setattr(CMUPCasesTest, f'test_cmup_case_{_i:03d}', _make_cmup_case(entrees, qte, cmup))


# ════════════════════════════════════════════════════════════════
# Mouvements — sorties, annulations, invariants
# ════════════════════════════════════════════════════════════════
class MouvementStockTest(BaseStockTest):

    def test_sortie_reduit_le_stock(self):
        factories.creer_stock(self.article, self.magasin, quantite=50, valeur_cmup=Decimal('10'))
        factories.creer_mouvement(self.article, self.magasin, self.user, 'SORTIE', 20)
        stock = StockItem.objects.get(article=self.article, magasin=self.magasin)
        self.assertEqual(stock.quantite_physique, 30)

    def test_sortie_avec_prix_garde_le_cmup(self):
        factories.creer_stock(self.article, self.magasin, quantite=50, valeur_cmup=Decimal('10'))
        factories.creer_mouvement(self.article, self.magasin, self.user, 'SORTIE', 20)
        stock = StockItem.objects.get(article=self.article, magasin=self.magasin)
        self.assertEqual(stock.valeur_cmup, Decimal('10.00'))

    def test_entree_puis_sortie_puis_entree(self):
        factories.entrer_stock(self.article, self.magasin, self.user, 100, '200')
        factories.creer_mouvement(self.article, self.magasin, self.user, 'SORTIE', 40)
        factories.entrer_stock(self.article, self.magasin, self.user, 20, '100')
        stock = StockItem.objects.get(article=self.article, magasin=self.magasin)
        self.assertEqual(stock.quantite_physique, 80)

    def test_retour_service_ajoute_du_stock(self):
        factories.entrer_stock(self.article, self.magasin, self.user, 30, '150')
        factories.creer_mouvement(self.article, self.magasin, self.user, 'RETOUR_SERVICE', 5)
        stock = StockItem.objects.get(article=self.article, magasin=self.magasin)
        self.assertEqual(stock.quantite_physique, 35)

    def test_ajustement_positif_ajoute(self):
        factories.entrer_stock(self.article, self.magasin, self.user, 10, '100')
        factories.creer_mouvement(self.article, self.magasin, self.user, 'AJUSTEMENT_POS', 7)
        stock = StockItem.objects.get(article=self.article, magasin=self.magasin)
        self.assertEqual(stock.quantite_physique, 17)

    def test_ajustement_negatif_retire(self):
        factories.entrer_stock(self.article, self.magasin, self.user, 10, '100')
        factories.creer_mouvement(self.article, self.magasin, self.user, 'AJUSTEMENT_NEG', 3)
        stock = StockItem.objects.get(article=self.article, magasin=self.magasin)
        self.assertEqual(stock.quantite_physique, 7)

    def test_entree_cree_le_stock_item(self):
        factories.creer_mouvement(self.article, self.magasin, self.user, 'ENTREE', 5,
                                  prix_unitaire=Decimal('10'))
        self.assertTrue(StockItem.objects.filter(article=self.article, magasin=self.magasin).exists())

    def test_sortie_sans_stock_leve_validation_error(self):
        with self.assertRaises(ValidationError):
            factories.creer_mouvement(self.article, self.magasin, self.user, 'SORTIE', 5)

    def test_sortie_superieure_au_stock_leve_erreur(self):
        factories.creer_stock(self.article, self.magasin, quantite=10)
        with self.assertRaises(ValidationError):
            factories.creer_mouvement(self.article, self.magasin, self.user, 'SORTIE', 11)

    def test_sortie_egale_au_stock_ok(self):
        factories.creer_stock(self.article, self.magasin, quantite=10)
        factories.creer_mouvement(self.article, self.magasin, self.user, 'SORTIE', 10)
        stock = StockItem.objects.get(article=self.article, magasin=self.magasin)
        self.assertEqual(stock.quantite_physique, 0)

    def test_ajustement_negatif_superieur_leve_erreur(self):
        factories.creer_stock(self.article, self.magasin, quantite=10)
        with self.assertRaises(ValidationError):
            factories.creer_mouvement(self.article, self.magasin, self.user, 'AJUSTEMENT_NEG', 11)

    def test_mouvement_sans_magasin_leve_erreur(self):
        with self.assertRaises(ValidationError):
            Mouvement.objects.create(
                article=self.article, utilisateur=self.user,
                type_mouvement='ENTREE', quantite=5,
            )

    def test_modification_mouvement_interdite(self):
        mvt = factories.entrer_stock(self.article, self.magasin, self.user, 10, '100')
        mvt.quantite = 99
        with self.assertRaises(ValidationError):
            mvt.save()

    def test_hash_preuve_genere(self):
        mvt = factories.entrer_stock(self.article, self.magasin, self.user, 10, '100')
        self.assertEqual(len(mvt.hash_preuve), 64)

    def test_hash_preuve_deterministe(self):
        # Le hash inclut l'horodatage : on fixe la même date pour les deux
        from django.utils import timezone
        date_fixe = timezone.now()
        m1 = factories.creer_mouvement(
            self.article, self.magasin, self.user, 'ENTREE', 10,
            prix_unitaire=Decimal('100'), date_mouvement=date_fixe)
        m2 = factories.creer_mouvement(
            self.article, self.magasin, self.user, 'ENTREE', 10,
            prix_unitaire=Decimal('100'), date_mouvement=date_fixe)
        self.assertEqual(m1.hash_preuve, m2.hash_preuve)

    def test_hash_preuve_varie_avec_quantite(self):
        m1 = factories.entrer_stock(self.article, self.magasin, self.user, 10, '100')
        m2 = factories.creer_mouvement(
            self.article, self.magasin, self.user, 'ENTREE', 11,
            prix_unitaire=Decimal('100'))
        self.assertNotEqual(m1.hash_preuve, m2.hash_preuve)

    def test_delete_entree_annule_le_stock(self):
        factories.entrer_stock(self.article, self.magasin, self.user, 10, '100')
        mvt = factories.entrer_stock(self.article, self.magasin, self.user, 5, '100')
        mvt.delete()
        stock = StockItem.objects.get(article=self.article, magasin=self.magasin)
        self.assertEqual(stock.quantite_physique, 10)

    def test_delete_sortie_restaure_le_stock(self):
        factories.entrer_stock(self.article, self.magasin, self.user, 10, '100')
        mvt = factories.creer_mouvement(self.article, self.magasin, self.user, 'SORTIE', 4)
        mvt.delete()
        stock = StockItem.objects.get(article=self.article, magasin=self.magasin)
        self.assertEqual(stock.quantite_physique, 10)

    def test_soft_delete_entree_annule_le_stock(self):
        factories.entrer_stock(self.article, self.magasin, self.user, 10, '100')
        mvt = factories.entrer_stock(self.article, self.magasin, self.user, 5, '100')
        mvt.soft_delete(self.user)
        stock = StockItem.objects.get(article=self.article, magasin=self.magasin)
        self.assertEqual(stock.quantite_physique, 10)
        mvt.refresh_from_db()
        self.assertTrue(mvt.is_deleted)
        self.assertEqual(mvt.deleted_by, self.user)

    def test_soft_delete_sortie_restaure(self):
        factories.entrer_stock(self.article, self.magasin, self.user, 10, '100')
        mvt = factories.creer_mouvement(self.article, self.magasin, self.user, 'SORTIE', 4)
        mvt.soft_delete(self.user)
        stock = StockItem.objects.get(article=self.article, magasin=self.magasin)
        self.assertEqual(stock.quantite_physique, 10)

    def test_annulation_entree_recalcule_cmup(self):
        factories.entrer_stock(self.article, self.magasin, self.user, 10, '100')
        mvt = factories.entrer_stock(self.article, self.magasin, self.user, 10, '300')
        mvt.delete()
        stock = StockItem.objects.get(article=self.article, magasin=self.magasin)
        self.assertEqual(stock.quantite_physique, 10)
        self.assertEqual(stock.valeur_cmup, Decimal('100.00'))

    def test_entree_sans_prix_ne_change_pas_cmup(self):
        factories.creer_stock(self.article, self.magasin, quantite=10, valeur_cmup=Decimal('50'))
        factories.creer_mouvement(self.article, self.magasin, self.user, 'ENTREE', 5)
        stock = StockItem.objects.get(article=self.article, magasin=self.magasin)
        self.assertEqual(stock.valeur_cmup, Decimal('50.00'))

    def test_sortie_sans_stock_item_leve_erreur(self):
        with self.assertRaises(ValidationError):
            factories.creer_mouvement(self.article, self.magasin, self.user, 'RETOUR_FOURNISSEUR', 3)

    def test_retour_fournisseur_retire_le_stock(self):
        factories.entrer_stock(self.article, self.magasin, self.user, 20, '100')
        factories.creer_mouvement(self.article, self.magasin, self.user, 'RETOUR_FOURNISSEUR', 8)
        stock = StockItem.objects.get(article=self.article, magasin=self.magasin)
        self.assertEqual(stock.quantite_physique, 12)

    def test_inventaire_pos_ajuste(self):
        factories.entrer_stock(self.article, self.magasin, self.user, 10, '100')
        factories.creer_mouvement(self.article, self.magasin, self.user, 'INVENTAIRE_POS', 3)
        stock = StockItem.objects.get(article=self.article, magasin=self.magasin)
        self.assertEqual(stock.quantite_physique, 13)

    def test_inventaire_neg_ajuste(self):
        factories.entrer_stock(self.article, self.magasin, self.user, 10, '100')
        factories.creer_mouvement(self.article, self.magasin, self.user, 'INVENTAIRE_NEG', 3)
        stock = StockItem.objects.get(article=self.article, magasin=self.magasin)
        self.assertEqual(stock.quantite_physique, 7)

    def test_lot_separe_du_stock_sans_lot(self):
        factories.entrer_stock(self.article, self.magasin, self.user, 10, '100')
        factories.creer_mouvement(
            self.article, self.magasin, self.user, 'ENTREE', 5,
            prix_unitaire=Decimal('200'), numero_lot='LOT-A',
        )
        stock_sans_lot = StockItem.objects.get(
            article=self.article, magasin=self.magasin, batch_number__isnull=True)
        stock_lot = StockItem.objects.get(
            article=self.article, magasin=self.magasin, batch_number='LOT-A')
        self.assertEqual(stock_sans_lot.quantite_physique, 10)
        self.assertEqual(stock_lot.quantite_physique, 5)
        self.assertEqual(stock_lot.valeur_cmup, Decimal('200.00'))


# ════════════════════════════════════════════════════════════════
# Sorties après entrées — invariants CMUP (cas générés)
# ════════════════════════════════════════════════════════════════
class EntreeSortieTest(BaseStockTest):
    """Entrée puis sortie : la quantité restante est correcte."""


ENTREE_SORTIE_CASES = [
    (100, 10, 90), (100, 50, 50), (100, 100, 0), (50, 1, 49),
    (37, 12, 25), (500, 499, 1), (10, 9, 1), (200, 137, 63),
    (75, 75, 0), (3, 1, 2), (1000, 1000, 0), (64, 8, 56),
    (120, 33, 87), (8, 8, 0), (999, 1, 998), (42, 42, 0),
    (17, 16, 1), (60, 60, 0), (13, 7, 6), (250, 125, 125),
    (30, 30, 0), (18, 18, 0), (77, 22, 55), (5, 5, 0),
    (140, 140, 0), (29, 2, 27), (88, 44, 44), (6, 6, 0),
    (210, 10, 200), (15, 15, 0),
]


def _make_entree_sortie(entree, sortie, reste):
    def test(self):
        factories.entrer_stock(self.article, self.magasin, self.user, entree, '100')
        factories.creer_mouvement(self.article, self.magasin, self.user, 'SORTIE', sortie)
        stock = StockItem.objects.get(article=self.article, magasin=self.magasin)
        self.assertEqual(stock.quantite_physique, reste)
        self.assertEqual(stock.valeur_cmup, Decimal('100.00'))
    return test


for _i, (e, s, r) in enumerate(ENTREE_SORTIE_CASES):
    setattr(EntreeSortieTest, f'test_entree_{e}_sortie_{s}', _make_entree_sortie(e, s, r))


# ════════════════════════════════════════════════════════════════
# StockItem — excedent, valeur totale, contraintes
# ════════════════════════════════════════════════════════════════
class StockItemTest(BaseStockTest):

    def test_excedent_zero_sans_seuil(self):
        stock = factories.creer_stock(self.article, self.magasin, quantite=50)
        self.assertEqual(stock.excedent, 0)

    def test_excedent_positif(self):
        self.article.seuil_maximum = 10
        self.article.save()
        stock = factories.creer_stock(self.article, self.magasin, quantite=15)
        self.assertEqual(stock.excedent, 5)

    def test_excedent_negatif_zero(self):
        self.article.seuil_maximum = 10
        self.article.save()
        stock = factories.creer_stock(self.article, self.magasin, quantite=8)
        self.assertEqual(stock.excedent, 0)

    def test_valeur_totale_cmup(self):
        stock = factories.creer_stock(self.article, self.magasin, quantite=10,
                                      valeur_cmup=Decimal('25.00'))
        self.assertEqual(stock.valeur_totale, Decimal('250.00'))

    def test_valeur_totale_fallback_prix_reference(self):
        self.article.prix_reference = Decimal('40.00')
        self.article.save()
        stock = factories.creer_stock(self.article, self.magasin, quantite=5)
        self.assertEqual(stock.valeur_totale, Decimal('200.00'))

    def test_valeur_totale_zero(self):
        stock = factories.creer_stock(self.article, self.magasin, quantite=0)
        self.assertEqual(stock.valeur_totale, Decimal('0'))

    def test_double_stock_sans_lot_interdit(self):
        factories.creer_stock(self.article, self.magasin, quantite=5)
        with self.assertRaises(IntegrityError):
            factories.creer_stock(self.article, self.magasin, quantite=3)

    def test_stock_lots_differents_autorises(self):
        factories.creer_stock(self.article, self.magasin, quantite=5, batch_number='LOT-1')
        factories.creer_stock(self.article, self.magasin, quantite=3, batch_number='LOT-2')
        self.assertEqual(
            StockItem.objects.filter(article=self.article, magasin=self.magasin).count(), 2)

    def test_batch_vide_normalise_a_null(self):
        stock = factories.creer_stock(self.article, self.magasin, quantite=5, batch_number='')
        stock.refresh_from_db()
        self.assertIsNone(stock.batch_number)

    def test_str(self):
        stock = factories.creer_stock(self.article, self.magasin, quantite=7)
        self.assertIn('7', str(stock))


# ════════════════════════════════════════════════════════════════
# Article — numérotation auto, seuils, lots
# ════════════════════════════════════════════════════════════════
class ArticleTest(BaseStockTest):

    def test_reference_auto_generee(self):
        article = factories.creer_article(famille=self.famille, designation="Auto",
                                          reference=None)
        self.assertTrue(article.reference)
        self.assertTrue(article.reference.startswith('FAM001'))

    def test_reference_unique(self):
        factories.creer_article(famille=self.famille, designation="A", reference="REF-X")
        with self.assertRaises(IntegrityError):
            factories.creer_article(famille=self.famille, designation="B", reference="REF-X")

    def test_requiert_lot_par_article(self):
        self.article.gere_lots_peremption = True
        self.article.save()
        self.assertTrue(self.article.requiert_lot_peremption)

    def test_requiert_lot_par_famille(self):
        self.famille.gere_lots_peremption = True
        self.famille.save()
        self.assertTrue(self.article.requiert_lot_peremption)

    def test_pas_de_lot_par_defaut(self):
        self.assertFalse(self.article.requiert_lot_peremption)

    def test_seuil_alerte_egal_seuil_minimum(self):
        self.assertEqual(self.article.seuil_alerte, self.article.seuil_minimum)

    def test_str_avec_reference(self):
        self.assertEqual(str(self.article), "[ART-1001] Paracétamol 500mg")

    def test_prix_reference_negatif_refuse(self):
        article = factories.creer_article(
            famille=self.famille, designation="Neg",
            reference="ART-NEG", prix_reference=Decimal('-5'))
        with self.assertRaises(ValidationError):
            article.full_clean()

    def test_soft_delete_cache_article(self):
        self.article.soft_delete(self.user)
        self.assertFalse(Article.objects.filter(pk=self.article.pk).exists())
        self.assertTrue(Article.all_objects.filter(pk=self.article.pk).exists())


# ════════════════════════════════════════════════════════════════
# LigneBon — montant
# ════════════════════════════════════════════════════════════════
class LigneBonTest(BaseStockTest):

    def _bon(self):
        return BonMouvement.objects.create(
            type_bon='ENTREE', magasin=self.magasin, cree_par=self.user,
        )

    def test_montant_avec_quantite(self):
        bon = self._bon()
        ligne = LigneBon.objects.create(bon=bon, article=self.article,
                                        quantite=10, prix_unitaire=Decimal('50'))
        self.assertEqual(ligne.montant, Decimal('500.00'))

    def test_montant_avec_quantite_servie(self):
        bon = self._bon()
        ligne = LigneBon.objects.create(bon=bon, article=self.article,
                                        quantite=10, quantite_servie=4,
                                        prix_unitaire=Decimal('50'))
        self.assertEqual(ligne.montant, Decimal('200.00'))

    def test_montant_sans_prix(self):
        bon = self._bon()
        ligne = LigneBon.objects.create(bon=bon, article=self.article, quantite=10)
        self.assertIsNone(ligne.montant)

    def test_montant_zero_si_qte_servie_zero(self):
        bon = self._bon()
        ligne = LigneBon.objects.create(bon=bon, article=self.article,
                                        quantite=10, quantite_servie=0,
                                        prix_unitaire=Decimal('50'))
        self.assertIsNone(ligne.montant)

    def test_quantite_zero_refusee(self):
        bon = self._bon()
        with self.assertRaises(IntegrityError):
            LigneBon.objects.create(bon=bon, article=self.article, quantite=0)


# ════════════════════════════════════════════════════════════════
# BonMouvement — numérotation auto, signataires
# ════════════════════════════════════════════════════════════════
class BonMouvementTest(BaseStockTest):

    def test_numero_auto_genere(self):
        bon = BonMouvement.objects.create(
            type_bon='ENTREE', magasin=self.magasin, cree_par=self.user)
        self.assertTrue(bon.numero_bon)
        self.assertTrue(bon.numero_bon.startswith('BE-'))

    def test_numero_unique_consecutif(self):
        b1 = BonMouvement.objects.create(type_bon='ENTREE', magasin=self.magasin,
                                         cree_par=self.user)
        b2 = BonMouvement.objects.create(type_bon='ENTREE', magasin=self.magasin,
                                         cree_par=self.user)
        self.assertNotEqual(b1.numero_bon, b2.numero_bon)

    def test_bon_sans_magasin_refuse(self):
        from django.core.exceptions import ValidationError as VE
        with self.assertRaises(VE):
            BonMouvement.objects.create(type_bon='ENTREE', cree_par=self.user)

    def test_prefixe_sortie(self):
        bon = BonMouvement.objects.create(
            type_bon='SORTIE', magasin=self.magasin, cree_par=self.user)
        self.assertTrue(bon.numero_bon.startswith('BS-'))

    def test_prefixe_hors_stock(self):
        bon = BonMouvement.objects.create(
            type_bon='SORTIE_HORS_STOCK', magasin=self.magasin, cree_par=self.user)
        self.assertTrue(bon.numero_bon.startswith('BSHS-'))

    def test_prefixe_retour(self):
        bon = BonMouvement.objects.create(
            type_bon='RETOUR_SERVICE', magasin=self.magasin, cree_par=self.user)
        self.assertTrue(bon.numero_bon.startswith('BR-'))

    def test_get_signataires_pdf_six_cases(self):
        from core.models import ConfigurationHopital
        config = ConfigurationHopital.get_instance()
        bon = BonMouvement.objects.create(
            type_bon='SORTIE', magasin=self.magasin, cree_par=self.user)
        signataires = bon.get_signataires_pdf(config)
        self.assertEqual(len(signataires), 6)
        for s in signataires:
            self.assertFalse(s['signe'])

    def test_get_signataires_pdf_avec_validations(self):
        from core.models import ConfigurationHopital
        from accounts.models import Profil
        config = ConfigurationHopital.get_instance()
        bon = BonMouvement.objects.create(
            type_bon='SORTIE', magasin=self.magasin, cree_par=self.user)
        profil = self.user.profil
        profil.a_signature = True
        profil.save()
        from stock.models import ValidationDocument
        ValidationDocument.objects.create(bon=bon, ordre=1, valideur=self.user)
        signataires = bon.get_signataires_pdf(config)
        self.assertTrue(signataires[0]['signe'])
        self.assertEqual(signataires[0]['nom'], self.user.username)

    def test_est_completement_valide_sans_circuit(self):
        bon = BonMouvement.objects.create(
            type_bon='SORTIE', magasin=self.magasin, cree_par=self.user)
        self.assertTrue(bon.est_completement_valide)

    def test_soft_delete_cache_le_bon(self):
        bon = BonMouvement.objects.create(
            type_bon='ENTREE', magasin=self.magasin, cree_par=self.user)
        bon.soft_delete(self.user)
        self.assertFalse(BonMouvement.objects.filter(pk=bon.pk).exists())
        self.assertTrue(BonMouvement.all_objects.filter(pk=bon.pk).exists())
