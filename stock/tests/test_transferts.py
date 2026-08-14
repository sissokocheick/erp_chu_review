"""Transferts inter-magasins : service (mouvements liés) et vues.

Couverture :
- création d'un transfert simple (sans lot) : décrément source,
  incrément destination, bon + lignes tracés ;
- articles gérés en lot : FEFO côté source, lot/péremption conservés ;
- blocage : mêmes magasins, pas de lignes, stock insuffisant ;
- annulation : le stock revient au magasin source ;
- vues : liste, création via POST, annulation, isolation magasins.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse

from stock.models import BonMouvement, Mouvement, StockItem
from stock.services.transfert_service import TransfertService
from stock.tests.factories import (
    creer_article, creer_famille, creer_magasin, creer_stock,
    creer_superuser, desactiver_changement_mdp,
)


class TransfertServiceTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = creer_superuser(username="transfert_admin")
        cls.src = creer_magasin(nom="Magasin Source")
        cls.dst = creer_magasin(nom="Magasin Destination")
        cls.famille = creer_famille()
        cls.article = creer_article(
            famille=cls.famille, reference="TRF-001", designation="Pansement")
        cls.article_lot = creer_article(
            famille=cls.famille, reference="TRF-002",
            designation="Sérum en lot", gere_lots_peremption=True)
        # Stock initial dans le magasin source
        creer_stock(cls.article, cls.src, quantite=50, valeur_cmup=Decimal('10.00'))
        creer_stock(cls.article_lot, cls.src, quantite=100, valeur_cmup=Decimal('5.00'))
        # Lots avec péremptions différentes (FEFO)
        creer_stock(cls.article_lot, cls.src, quantite=40, valeur_cmup=Decimal('5.00'),
                    batch_number="LOT-A", expiry_date=date.today() + timedelta(days=10))
        creer_stock(cls.article_lot, cls.src, quantite=60, valeur_cmup=Decimal('5.00'),
                    batch_number="LOT-B", expiry_date=date.today() + timedelta(days=90))

    def _qte(self, article, magasin, lot=None):
        qs = StockItem.objects.filter(article=article, magasin=magasin)
        if lot is None:
            qs = qs.filter(batch_number__isnull=True)
        else:
            qs = qs.filter(batch_number=lot)
        return qs.first().quantite_physique if qs.exists() else 0

    def test_creation_simple_decale_le_stock(self):
        bon = TransfertService.creer_transfert(
            utilisateur=self.user,
            magasin_source=self.src,
            magasin_destination=self.dst,
            lignes=[{'article': self.article, 'quantite': 10}],
            commentaire="Déplacement vers l'unité de soins",
        )
        self.assertEqual(bon.type_bon, 'TRANSFERT')
        self.assertEqual(self._qte(self.article, self.src), 40)
        self.assertEqual(self._qte(self.article, self.dst), 10)
        # Deux mouvements liés tracés par le numéro de bon
        mouvements = Mouvement.objects.filter(
            reference_document=bon.numero_bon)
        self.assertEqual(
            set(mouvements.values_list('type_mouvement', flat=True)),
            {'TRANSFERT_SORTIE', 'TRANSFERT_ENTREE'})
        self.assertEqual(bon.lignes_bon.count(), 1)
        self.assertEqual(bon.lignes_bon.first().quantite, 10)
        # Le CMUP est conservé à l'entrée
        self.assertEqual(
            self._qte(self.article, self.dst), 10)
        self.assertEqual(
            StockItem.objects.get(article=self.article, magasin=self.dst,
                                  batch_number__isnull=True).valeur_cmup,
            Decimal('10.00'))

    def test_lots_fefo_et_conservation(self):
        bon = TransfertService.creer_transfert(
            utilisateur=self.user,
            magasin_source=self.src,
            magasin_destination=self.dst,
            lignes=[{'article': self.article_lot, 'quantite': 50}],
        )
        # FEFO : LOT-A (10 j) consommé en premier (40), puis LOT-B (10)
        self.assertEqual(self._qte(self.article_lot, self.src, lot="LOT-A"), 0)
        self.assertEqual(self._qte(self.article_lot, self.src, lot="LOT-B"), 50)
        # Destination : 40 sur LOT-A + 10 sur LOT-B, péremptions conservées
        self.assertEqual(self._qte(self.article_lot, self.dst, lot="LOT-A"), 40)
        self.assertEqual(self._qte(self.article_lot, self.dst, lot="LOT-B"), 10)
        item_b = StockItem.objects.get(
            article=self.article_lot, magasin=self.dst, batch_number="LOT-B")
        self.assertEqual(item_b.expiry_date, date.today() + timedelta(days=90))
        # Deux lignes de bon tracées (une par lot)
        self.assertEqual(bon.lignes_bon.count(), 2)

    def test_blocage_lot_perime(self):
        # Un lot périmé est présent dans le magasin source
        creer_stock(self.article_lot, self.src, quantite=20, valeur_cmup=Decimal('5.00'),
                    batch_number="LOT-PERIME",
                    expiry_date=date.today() - timedelta(days=5))
        with self.assertRaises(ValidationError) as ctx:
            TransfertService.creer_transfert(
                utilisateur=self.user,
                magasin_source=self.src,
                magasin_destination=self.dst,
                lignes=[{'article': self.article_lot, 'quantite': 1000}],
            )
        self.assertIn("périmé", str(ctx.exception))

    def test_meme_magasin_refuse(self):
        with self.assertRaises(ValidationError):
            TransfertService.creer_transfert(
                utilisateur=self.user,
                magasin_source=self.src,
                magasin_destination=self.src,
                lignes=[{'article': self.article, 'quantite': 1}],
            )

    def test_pas_de_lignes_refuse(self):
        with self.assertRaises(ValidationError):
            TransfertService.creer_transfert(
                utilisateur=self.user,
                magasin_source=self.src,
                magasin_destination=self.dst,
                lignes=[],
            )

    def test_stock_insuffisant_refuse(self):
        with self.assertRaises(ValidationError) as ctx:
            TransfertService.creer_transfert(
                utilisateur=self.user,
                magasin_source=self.src,
                magasin_destination=self.dst,
                lignes=[{'article': self.article, 'quantite': 9999}],
            )
        self.assertIn("insuffisant", str(ctx.exception))

    def test_annulation_restaure_le_stock_source(self):
        bon = TransfertService.creer_transfert(
            utilisateur=self.user,
            magasin_source=self.src,
            magasin_destination=self.dst,
            lignes=[{'article': self.article, 'quantite': 10}],
        )
        TransfertService.annuler_transfert(bon, self.user, motif="Erreur de saisie")
        bon.refresh_from_db()
        self.assertTrue(bon.est_annule)
        self.assertEqual(self._qte(self.article, self.src), 50)
        self.assertEqual(self._qte(self.article, self.dst), 0)
        # Les mouvements d'origine sont marqués annulés, des contre-mouvements existent
        self.assertTrue(Mouvement.objects.filter(
            reference_document=bon.numero_bon,
            type_mouvement='TRANSFERT_SORTIE').first().est_annule)
        self.assertTrue(Mouvement.objects.filter(
            reference_document=bon.numero_bon,
            type_mouvement='TRANSFERT_ENTREE').first().est_annule)

    def test_annulation_double_refuse(self):
        bon = TransfertService.creer_transfert(
            utilisateur=self.user,
            magasin_source=self.src,
            magasin_destination=self.dst,
            lignes=[{'article': self.article, 'quantite': 5}],
        )
        TransfertService.annuler_transfert(bon, self.user)
        with self.assertRaises(ValidationError):
            TransfertService.annuler_transfert(bon, self.user)


class TransfertVuesTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = desactiver_changement_mdp(
            creer_superuser(username="mag_transfert"))
        cls.src = creer_magasin(nom="Magasin A")
        cls.dst = creer_magasin(nom="Magasin B")
        cls.famille = creer_famille()
        cls.article = creer_article(famille=cls.famille, reference="TRF-VUE")
        creer_stock(cls.article, cls.src, quantite=30, valeur_cmup=Decimal('7.00'))
        cls.article_lot = creer_article(
            famille=cls.famille, reference="TRF-VUE-LOT",
            designation="Sérum en lot", gere_lots_peremption=True)
        creer_stock(cls.article_lot, cls.src, quantite=10, valeur_cmup=Decimal('4.00'),
                    batch_number="LOT-A", expiry_date=date.today() + timedelta(days=10))

    def setUp(self):
        self.client.force_login(self.user)
        session = self.client.session
        session['magasin_actif_id'] = str(self.src.id)
        session.save()

    def test_liste_accessible(self):
        resp = self.client.get(reverse('liste_transferts'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Transferts inter-Magasins")

    def test_creation_via_post(self):
        resp = self.client.post(reverse('liste_transferts'), {
            'magasin_source': self.src.id,
            'magasin_destination': self.dst.id,
            'articles[]': [self.article.id],
            'quantites[]': ['5'],
            'commentaire': 'Test',
        })
        # Redirection vers l'impression du bon créé
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(resp['Location'].startswith('/transferts/?print_bon='))
        self.assertEqual(
            StockItem.objects.get(article=self.article, magasin=self.src,
                                  batch_number__isnull=True).quantite_physique, 25)
        self.assertEqual(
            StockItem.objects.get(article=self.article, magasin=self.dst,
                                  batch_number__isnull=True).quantite_physique, 5)

    def test_creation_meme_magasin_refusee(self):
        resp = self.client.post(reverse('liste_transferts'), {
            'magasin_source': self.src.id,
            'magasin_destination': self.src.id,
            'articles[]': [self.article.id],
            'quantites[]': ['5'],
        })
        self.assertRedirects(resp, reverse('liste_transferts'), fetch_redirect_response=False)
        # Le message d'erreur s'affiche sur la page suivie
        suivie = self.client.get(resp['Location'])
        self.assertContains(suivie, "différent")

    def test_annulation_via_post(self):
        bon = TransfertService.creer_transfert(
            utilisateur=self.user,
            magasin_source=self.src,
            magasin_destination=self.dst,
            lignes=[{'article': self.article, 'quantite': 5}],
        )
        resp = self.client.post(
            reverse('annuler_transfert', args=[bon.id]),
            {'motif': 'Erreur'})
        self.assertRedirects(resp, reverse('liste_transferts'))
        bon.refresh_from_db()
        self.assertTrue(bon.est_annule)
        self.assertEqual(
            StockItem.objects.get(article=self.article, magasin=self.src,
                                  batch_number__isnull=True).quantite_physique, 30)

    def test_impression_bon_transfert(self):
        bon = TransfertService.creer_transfert(
            utilisateur=self.user,
            magasin_source=self.src,
            magasin_destination=self.dst,
            lignes=[{'article': self.article, 'quantite': 3}],
        )
        resp = self.client.get(reverse('imprimer_bon_multi_lignes', args=[bon.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        # Le template dédié au transfert est utilisé (et pas le bon de sortie)
        self.assertTemplateUsed(resp, 'stock/pdf/bon_transfert.html')
        self.assertTemplateNotUsed(resp, 'stock/pdf/bon_sortie.html')

    def test_impression_bon_transfert_avec_lots(self):
        """Les colonnes lot/péremption apparaissent quand des lignes ont des lots."""
        bon = TransfertService.creer_transfert(
            utilisateur=self.user,
            magasin_source=self.src,
            magasin_destination=self.dst,
            lignes=[{'article': self.article_lot, 'quantite': 3}],
        )
        # Article géré en lot : le FEFO consomme LOT-A (péremption la plus
        # proche) → la ligne du bon porte le n° de lot
        ligne = bon.lignes_bon.first()
        self.assertIsNotNone(ligne.numero_lot)
        self.assertEqual(ligne.numero_lot, 'LOT-A')
        resp = self.client.get(reverse('imprimer_bon_multi_lignes', args=[bon.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')
