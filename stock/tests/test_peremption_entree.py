"""Règle sanitaire : un lot déjà périmé ne peut pas entrer en stock.

Couverture : helper _verifier_peremption (formats, dates), service
creer_bon_entree (blocage avant écriture) et vue de saisie d'entrée.
"""
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from stock.models import BonMouvement, Fournisseur, StockItem
from stock.services.bon_service import BonService
from stock.tests.factories import (
    creer_article, creer_famille, creer_magasin,
    creer_utilisateur, desactiver_changement_mdp,
)


class VerifierPeremptionTest(TestCase):
    """Tests unitaires du helper de blocage."""

    def setUp(self):
        self.famille = creer_famille()
        self.article = creer_article(famille=self.famille, reference="PER-001")

    def test_date_passee_yyyy_mm_dd_bloque(self):
        hier = (date.today() - timedelta(days=1)).isoformat()
        self.assertIn(
            "déjà périmé",
            BonService._verifier_peremption(self.article, hier),
        )

    def test_date_passee_jj_mm_aaaa_bloque(self):
        hier = (date.today() - timedelta(days=1)).strftime('%d/%m/%Y')
        self.assertIn(
            "déjà périmé",
            BonService._verifier_peremption(self.article, hier),
        )

    def test_date_future_acceptee(self):
        demain = (date.today() + timedelta(days=1)).isoformat()
        self.assertIsNone(BonService._verifier_peremption(self.article, demain))

    def test_date_du_jour_acceptee(self):
        self.assertIsNone(BonService._verifier_peremption(self.article, date.today().isoformat()))

    def test_date_absente_acceptee(self):
        self.assertIsNone(BonService._verifier_peremption(self.article, None))
        self.assertIsNone(BonService._verifier_peremption(self.article, ''))

    def test_format_invalide_accepte(self):
        # Format illisible : la validation du modèle s'en chargera
        self.assertIsNone(BonService._verifier_peremption(self.article, 'pas-une-date'))

    def test_article_inconnu_message_generique(self):
        hier = (date.today() - timedelta(days=1)).isoformat()
        self.assertIn("cet article", BonService._verifier_peremption(None, hier))


class CreerBonEntreePeremptionTest(TestCase):
    """Le service refuse l'entrée d'un lot périmé AVANT toute écriture."""

    @classmethod
    def setUpTestData(cls):
        cls.user = desactiver_changement_mdp(
            creer_utilisateur(username="magasinier_peremp")
        )
        cls.magasin = creer_magasin(nom="Magasin Péremption")
        cls.famille = creer_famille()
        cls.article = creer_article(
            famille=cls.famille, reference="PER-002",
            designation="Sérum Périmable", gere_lots_peremption=True,
        )
        cls.stock = StockItem.objects.create(
            article=cls.article, magasin=cls.magasin,
            quantite_physique=0, valeur_cmup=Decimal('0.00'),
        )

    def _lignes(self, peremp):
        return [{
            'article_id': self.article.id,
            'quantite': 10,
            'numero_lot': 'LOT-PER',
            'date_peremption': peremp,
            'prix_unitaire': Decimal('5.00'),
        }]

    def test_lot_perime_est_refuse(self):
        hier = (date.today() - timedelta(days=1)).isoformat()
        with self.assertRaises(ValidationError) as ctx:
            BonService.creer_bon_entree(
                lignes=self._lignes(hier),
                utilisateur=self.user, magasin=self.magasin,
            )
        self.assertIn('périmé', str(ctx.exception))
        # Aucune écriture : ni bon, ni mouvement, ni stock
        self.assertEqual(BonMouvement.objects.count(), 0)
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantite_physique, 0)

    def test_lot_futur_accepte(self):
        demain = (date.today() + timedelta(days=1)).isoformat()
        bon = BonService.creer_bon_entree(
            lignes=self._lignes(demain),
            utilisateur=self.user, magasin=self.magasin,
        )
        self.assertEqual(BonMouvement.objects.count(), 1)
        self.assertEqual(bon.lignes_bon.get().date_peremption.isoformat(), demain)
        # Le stock est suivi par lot : le StockItem du batch a été crédité
        lot_item = StockItem.objects.get(
            article=self.article, magasin=self.magasin, batch_number='LOT-PER')
        self.assertEqual(lot_item.quantite_physique, 10)
        # Le stock générique (sans lot) n'est pas touché
        self.stock.refresh_from_db()
        self.assertEqual(self.stock.quantite_physique, 0)

    def test_sans_date_accepte(self):
        lignes = self._lignes(None)
        lignes[0]['numero_lot'] = None
        BonService.creer_bon_entree(
            lignes=lignes, utilisateur=self.user, magasin=self.magasin,
        )
        self.assertEqual(BonMouvement.objects.count(), 1)


class VueEntreePeremptionTest(TestCase):
    """La page de saisie d'entrée refuse un lot périmé avec message clair."""

    @classmethod
    def setUpTestData(cls):
        cls.user = desactiver_changement_mdp(
            creer_utilisateur(username="agent_entree_peremp", is_superuser=True)
        )
        cls.magasin = creer_magasin(nom="Magasin Entrée")
        cls.famille = creer_famille()
        cls.article = creer_article(
            famille=cls.famille, reference="PER-003",
            designation="Paracétamol Périmable",
        )
        cls.fournisseur = Fournisseur.objects.create(
            code="F-PER", raison_sociale="Fournisseur Péremption")

    def setUp(self):
        self.client.force_login(self.user)
        s = self.client.session
        s['magasin_actif_id'] = str(self.magasin.id)
        s.save()

    def _poster(self, peremp):
        fichier = SimpleUploadedFile(
            'scan_test.pdf', b'%PDF-1.4 test', content_type='application/pdf')
        return self.client.post(reverse('liste_entrees'), {
            'magasin': str(self.magasin.id),
            'fournisseur': str(self.fournisseur.id),
            'articles[]': [str(self.article.id)],
            'quantites[]': ['10'],
            'lots[]': ['LOT-X'],
            'peremptions[]': [peremp],
            'prix_unitaires[]': ['100'],
            'document_scan': fichier,
        })

    def test_entree_lot_perime_refusee(self):
        hier = (date.today() - timedelta(days=1)).isoformat()
        resp = self._poster(hier)
        self.assertRedirects(resp, reverse('liste_entrees'))
        self.assertEqual(BonMouvement.objects.count(), 0)
        # Le message d'erreur est affiché sur la page suivante
        suivi = self.client.get(reverse('liste_entrees'))
        self.assertContains(suivi, "périmé")

    def test_entree_lot_valide_acceptee(self):
        demain = (date.today() + timedelta(days=1)).isoformat()
        resp = self._poster(demain)
        self.assertEqual(resp.status_code, 302)  # redirige vers ?print_bon=…
        self.assertEqual(BonMouvement.objects.count(), 1)
