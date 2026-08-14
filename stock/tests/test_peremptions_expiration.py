"""Onglet « À expirer » du contrôle des péremptions.

Vérifie que les lots dont la péremption tombe dans les prochains jours
(seuil 30/60/90) sont listés avec leur quantité restante et leurs jours
restants, et que le seuil est bien respecté.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from stock.models import StockItem
from stock.services.stock_service import StockService
from stock.tests.factories import (
    creer_article, creer_famille, creer_magasin, creer_superuser,
    desactiver_changement_mdp,
)


class PeremptionsAExpirerTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = desactiver_changement_mdp(
            creer_superuser(username="expiration_admin"))
        cls.magasin = creer_magasin(nom="Magasin Péremption")
        cls.famille = creer_famille()
        cls.article = creer_article(
            famille=cls.famille, reference="EXP-001",
            designation="Sérum", gere_lots_peremption=True)
        StockItem.objects.create(
            article=cls.article, magasin=cls.magasin,
            quantite_physique=0, valeur_cmup=Decimal('0.00'))

    def setUp(self):
        self.client.force_login(self.user)
        session = self.client.session
        session['magasin_actif_id'] = str(self.magasin.id)
        session.save()

    def _entree(self, lot, peremption, quantite=10):
        return StockService.appliquer_mouvement_entree(
            article=self.article,
            magasin=self.magasin,
            quantite=quantite,
            utilisateur=self.user,
            reference_document=f"ENT-{lot}",
            numero_lot=lot,
            date_peremption=peremption,
        )

    def test_lot_expirant_dans_30_jours_liste(self):
        self._entree("LOT-30", date.today() + timedelta(days=30), 10)
        resp = self.client.get(
            reverse('controle_peremptions') + '?onglet=a_expirer&seuil=30')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "LOT-30")
        self.assertContains(resp, "Sérum")

    def test_lot_lointain_exclu_du_seuil_30(self):
        self._entree("LOT-300", date.today() + timedelta(days=300), 10)
        resp = self.client.get(
            reverse('controle_peremptions') + '?onglet=a_expirer&seuil=30')
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "LOT-300")

    def test_seuil_90_inclut_les_60_jours(self):
        self._entree("LOT-60", date.today() + timedelta(days=60), 10)
        # Seuil 30 : exclu
        resp30 = self.client.get(
            reverse('controle_peremptions') + '?onglet=a_expirer&seuil=30')
        self.assertNotContains(resp30, "LOT-60")
        # Seuil 90 : inclus
        resp90 = self.client.get(
            reverse('controle_peremptions') + '?onglet=a_expirer&seuil=90')
        self.assertContains(resp90, "LOT-60")

    def test_lot_perime_exclu(self):
        self._entree("LOT-VIEUX", date.today() - timedelta(days=5), 10)
        resp = self.client.get(
            reverse('controle_peremptions') + '?onglet=a_expirer&seuil=90')
        self.assertNotContains(resp, "LOT-VIEUX")

    def test_quantite_restante_apres_sortie(self):
        self._entree("LOT-QTE", date.today() + timedelta(days=20), 10)
        StockService.appliquer_mouvement_sortie(
            article=self.article,
            magasin=self.magasin,
            quantite=4,
            utilisateur=self.user,
            reference_document="SORTIE-1",
            numero_lot="LOT-QTE",
        )
        resp = self.client.get(
            reverse('controle_peremptions') + '?onglet=a_expirer&seuil=30')
        self.assertContains(resp, "LOT-QTE")
        # 10 - 4 = 6 restants
        self.assertContains(resp, "6")

    def test_seuil_invalide_replie_sur_30(self):
        self._entree("LOT-45", date.today() + timedelta(days=45), 10)
        resp = self.client.get(
            reverse('controle_peremptions') + '?onglet=a_expirer&seuil=abc')
        self.assertEqual(resp.status_code, 200)
        # Seuil replié à 30 : le lot à 45 j est exclu
        self.assertNotContains(resp, "LOT-45")
