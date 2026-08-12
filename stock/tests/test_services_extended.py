# -*- coding: utf-8 -*-
"""
Tests étendus des services du module stock.

Couvre : BonService (entrée/sortie/retour/hors stock + annulations),
CompteurDocumentService, InventaireService, IsolationService.
"""
from decimal import Decimal

from django.test import TestCase
from django.core.exceptions import ValidationError, PermissionDenied
from django.utils import timezone

from stock.models import (
    StockItem, BonMouvement, Mouvement, MotifAnnulation, Beneficiaire,
    CampagneInventaire, LigneInventaire, Magasin,
    DemandeMateriel, LigneDemande, LivraisonPartielle, LivraisonLigne,
    AccuseReception,
)
from stock.services.compteur_service import CompteurDocumentService
from stock.services.bon_service import BonService
from stock.services.stock_transaction_service import StockTransactionService
from stock.services.inventaire_service import InventaireService
from stock.services.isolation_service import (
    get_magasins_autorises, verifier_acces_magasin, filtrer_par_magasins,
)
from stock.tests import factories


class BaseServiceTest(TestCase):
    def setUp(self):
        self.user = factories.creer_utilisateur()
        self.famille = factories.creer_famille(code="FAMSVC", intitule="Services")
        self.magasin = factories.creer_magasin(nom="Magasin Services")
        self.magasin2 = factories.creer_magasin(nom="Magasin Secondaire")
        self.article = factories.creer_article(
            famille=self.famille, designation="Article Service", reference="SVC-1")
        self.article2 = factories.creer_article(
            famille=self.famille, designation="Article Service 2", reference="SVC-2")
        self.motif = MotifAnnulation.objects.create(libelle="Erreur de saisie")


# ════════════════════════════════════════════════════════════════
# CompteurDocumentService — formats de numérotation
# ════════════════════════════════════════════════════════════════
class CompteurServiceTest(BaseServiceTest):
    """Formats et unicité des numéros générés (cas générés)."""


# (méthode, type_bon, préfixe attendu)
NUMEROTATION_CASES = [
    ('generer_numero_bon', 'ENTREE', 'BE'),
    ('generer_numero_bon', 'SORTIE', 'BS'),
    ('generer_numero_bon', 'RETOUR_SERVICE', 'BR'),
    ('generer_numero_bon', 'SORTIE_HORS_STOCK', 'BSHS'),
    ('generer_numero_commande', None, 'BC'),
    ('generer_numero_demande', None, 'BDM'),
]


def _make_numero_case(methode, type_bon, prefixe):
    def test(self):
        if methode == 'generer_numero_bon':
            numero = getattr(CompteurDocumentService, methode)(type_bon)
        else:
            numero = getattr(CompteurDocumentService, methode)()
        self.assertTrue(numero.startswith(f"{prefixe}-"))
        annee = str(timezone.now().year)
        self.assertIn(annee, numero)
    return test


for _i, (methode, type_bon, prefixe) in enumerate(NUMEROTATION_CASES):
    setattr(CompteurServiceTest, f'test_format_{methode}_{type_bon or "sans"}', _make_numero_case(methode, type_bon, prefixe))


class CompteurServiceUniciteTest(BaseServiceTest):

    def test_numero_bon_uniques_consecutifs(self):
        n1 = CompteurDocumentService.generer_numero_bon('ENTREE')
        n2 = CompteurDocumentService.generer_numero_bon('ENTREE')
        self.assertNotEqual(n1, n2)

    def test_prefixes_differents_par_type(self):
        n_entree = CompteurDocumentService.generer_numero_bon('ENTREE')
        n_sortie = CompteurDocumentService.generer_numero_bon('SORTIE')
        self.assertTrue(n_entree.startswith('BE-'))
        self.assertTrue(n_sortie.startswith('BS-'))

    def test_commande_et_demande_distincts(self):
        n_c = CompteurDocumentService.generer_numero_commande()
        n_d = CompteurDocumentService.generer_numero_demande()
        self.assertTrue(n_c.startswith('BC-'))
        self.assertTrue(n_d.startswith('BDM-'))

    def test_format_annee_sequence(self):
        numero = CompteurDocumentService.generer_numero_bon('SORTIE')
        parts = numero.split('-')
        self.assertEqual(len(parts), 3)
        self.assertEqual(parts[0], 'BS')


# ════════════════════════════════════════════════════════════════
# BonService — création de bons
# ════════════════════════════════════════════════════════════════
class BonServiceCreationTest(BaseServiceTest):

    def test_bon_entree_augmente_le_stock(self):
        BonService.creer_bon_entree(
            lignes=[{'article_id': self.article.id, 'quantite': 30,
                     'prix_unitaire': Decimal('100')}],
            utilisateur=self.user, magasin=self.magasin)
        stock = StockItem.objects.get(article=self.article, magasin=self.magasin)
        self.assertEqual(stock.quantite_physique, 30)
        self.assertEqual(stock.valeur_cmup, Decimal('100.00'))

    def test_bon_entree_cree_les_mouvements(self):
        BonService.creer_bon_entree(
            lignes=[{'article_id': self.article.id, 'quantite': 10,
                     'prix_unitaire': Decimal('50')}],
            utilisateur=self.user, magasin=self.magasin)
        self.assertTrue(Mouvement.objects.filter(
            article=self.article, type_mouvement='ENTREE').exists())

    def test_bon_entree_avec_lot(self):
        BonService.creer_bon_entree(
            lignes=[{'article_id': self.article.id, 'quantite': 5,
                     'prix_unitaire': Decimal('80'), 'numero_lot': 'LOT-X'}],
            utilisateur=self.user, magasin=self.magasin)
        stock = StockItem.objects.get(article=self.article, magasin=self.magasin,
                                      batch_number='LOT-X')
        self.assertEqual(stock.quantite_physique, 5)

    def test_bon_entree_sans_prix(self):
        BonService.creer_bon_entree(
            lignes=[{'article_id': self.article.id, 'quantite': 7}],
            utilisateur=self.user, magasin=self.magasin)
        stock = StockItem.objects.get(article=self.article, magasin=self.magasin)
        self.assertEqual(stock.quantite_physique, 7)

    def test_bon_sortie_diminue_le_stock(self):
        factories.creer_stock(self.article, self.magasin, quantite=50,
                              valeur_cmup=Decimal('10'))
        BonService.creer_bon_sortie(
            lignes=[{'article_id': self.article.id, 'quantite': 20}],
            utilisateur=self.user, magasin=self.magasin)
        stock = StockItem.objects.get(article=self.article, magasin=self.magasin)
        self.assertEqual(stock.quantite_physique, 30)

    def test_bon_sortie_sans_stock_leve_erreur(self):
        with self.assertRaises(ValidationError):
            BonService.creer_bon_sortie(
                lignes=[{'article_id': self.article.id, 'quantite': 5}],
                utilisateur=self.user, magasin=self.magasin)

    def test_bon_sortie_stock_insuffisant(self):
        factories.creer_stock(self.article, self.magasin, quantite=3)
        with self.assertRaises(ValidationError):
            BonService.creer_bon_sortie(
                lignes=[{'article_id': self.article.id, 'quantite': 5}],
                utilisateur=self.user, magasin=self.magasin)

    def test_bon_sortie_genere_bon_valide(self):
        factories.creer_stock(self.article, self.magasin, quantite=10)
        bon = BonService.creer_bon_sortie(
            lignes=[{'article_id': self.article.id, 'quantite': 4}],
            utilisateur=self.user, magasin=self.magasin)
        self.assertEqual(bon.type_bon, 'SORTIE')
        self.assertEqual(bon.statut_validation, 'VALIDE')
        self.assertTrue(bon.numero_bon.startswith('BS-'))

    def test_bon_retour_augmente_le_stock(self):
        BonService.creer_bon_retour(
            lignes=[{'article_id': self.article.id, 'quantite': 12}],
            utilisateur=self.user, magasin=self.magasin)
        stock = StockItem.objects.get(article=self.article, magasin=self.magasin)
        self.assertEqual(stock.quantite_physique, 12)

    def test_bon_hors_stock_ne_touche_pas_le_stock(self):
        destinataire = Beneficiaire.objects.create(nom_complet="Service Pediatrie")
        BonService.creer_bon_hors_stock(
            lignes=[{'article_id': self.article.id, 'quantite': 5}],
            utilisateur=self.user, magasin=self.magasin,
            destinataire=destinataire)
        self.assertFalse(StockItem.objects.filter(
            article=self.article, magasin=self.magasin).exists())
        bon = BonMouvement.objects.get(type_bon='SORTIE_HORS_STOCK')
        self.assertEqual(bon.destinataire, destinataire)

    def test_utilisateur_inactif_refuse(self):
        self.user.is_active = False
        self.user.save()
        with self.assertRaises(PermissionDenied):
            BonService.creer_bon_entree(
                lignes=[{'article_id': self.article.id, 'quantite': 5}],
                utilisateur=self.user, magasin=self.magasin)


# ════════════════════════════════════════════════════════════════
# BonService — annulations
# ════════════════════════════════════════════════════════════════
class BonServiceAnnulationTest(BaseServiceTest):

    def test_annuler_bon_entree_remet_le_stock(self):
        bon = BonService.creer_bon_entree(
            lignes=[{'article_id': self.article.id, 'quantite': 30,
                     'prix_unitaire': Decimal('100')}],
            utilisateur=self.user, magasin=self.magasin)
        BonService.annuler_bon_entree(bon, self.motif, self.user)
        stock = StockItem.objects.get(article=self.article, magasin=self.magasin)
        self.assertEqual(stock.quantite_physique, 0)
        bon.refresh_from_db()
        self.assertTrue(bon.est_annule)

    def test_annuler_deux_fois_refuse(self):
        bon = BonService.creer_bon_entree(
            lignes=[{'article_id': self.article.id, 'quantite': 10}],
            utilisateur=self.user, magasin=self.magasin)
        BonService.annuler_bon_entree(bon, self.motif, self.user)
        with self.assertRaises(ValueError):
            BonService.annuler_bon_entree(bon, self.motif, self.user)

    def test_annuler_bon_sortie_restaure_le_stock(self):
        factories.creer_stock(self.article, self.magasin, quantite=50)
        bon = BonService.creer_bon_sortie(
            lignes=[{'article_id': self.article.id, 'quantite': 20}],
            utilisateur=self.user, magasin=self.magasin)
        BonService.annuler_bon_sortie(bon, self.motif, self.user)
        stock = StockItem.objects.get(article=self.article, magasin=self.magasin)
        self.assertEqual(stock.quantite_physique, 50)
        bon.refresh_from_db()
        self.assertTrue(bon.est_annule)

    def test_annuler_bon_hors_stock(self):
        bon = BonService.creer_bon_hors_stock(
            lignes=[{'article_id': self.article.id, 'quantite': 5}],
            utilisateur=self.user, magasin=self.magasin)
        BonService.annuler_bon_hors_stock(bon, self.motif, self.user)
        bon.refresh_from_db()
        self.assertTrue(bon.est_annule)

    def test_annulation_motif_string_accepte(self):
        bon = BonService.creer_bon_entree(
            lignes=[{'article_id': self.article.id, 'quantite': 5}],
            utilisateur=self.user, magasin=self.magasin)
        BonService.annuler_bon_entree(bon, "Erreur saisie", self.user)
        bon.refresh_from_db()
        self.assertTrue(bon.est_annule)


# ════════════════════════════════════════════════════════════════
# StockTransactionService — contre-mouvements
# ════════════════════════════════════════════════════════════════
class StockTransactionServiceTest(BaseServiceTest):

    def test_contre_mouvement_entree(self):
        mvt = factories.creer_mouvement(
            self.article, self.magasin, self.user, 'ENTREE', 10,
            prix_unitaire=Decimal('100'))
        StockTransactionService.annuler_par_contre_mouvement(mvt, self.user)
        stock = StockItem.objects.get(article=self.article, magasin=self.magasin)
        self.assertEqual(stock.quantite_physique, 0)
        mvt.refresh_from_db()
        self.assertTrue(mvt.est_annule)

    def test_contre_mouvement_sortie(self):
        factories.creer_stock(self.article, self.magasin, quantite=20)
        mvt = factories.creer_mouvement(self.article, self.magasin, self.user, 'SORTIE', 8)
        StockTransactionService.annuler_par_contre_mouvement(mvt, self.user)
        stock = StockItem.objects.get(article=self.article, magasin=self.magasin)
        self.assertEqual(stock.quantite_physique, 20)


# ════════════════════════════════════════════════════════════════
# InventaireService — cycle de vie d'une campagne
# ════════════════════════════════════════════════════════════════
class InventaireServiceTest(BaseServiceTest):

    def test_creer_campagne_cree_une_ligne_par_article(self):
        campagne = InventaireService.creer_campagne(
            titre="Inventaire decembre", magasin=self.magasin, user=self.user)
        self.assertEqual(campagne.titre, "INVENTAIRE DECEMBRE")
        self.assertEqual(campagne.lignes_inventaire.count(), 2)

    def test_creer_campagne_quantite_theorique(self):
        factories.creer_stock(self.article, self.magasin, quantite=15)
        campagne = InventaireService.creer_campagne(
            titre="Inv test", magasin=self.magasin, user=self.user)
        ligne = campagne.lignes_inventaire.get(article=self.article)
        self.assertEqual(ligne.quantite_theorique, 15)

    def test_sauvegarder_saisie_brouillon(self):
        campagne = InventaireService.creer_campagne(
            titre="Inv test", magasin=self.magasin, user=self.user)
        ligne = campagne.lignes_inventaire.get(article=self.article)
        InventaireService.sauvegarder_saisie(
            campagne, {str(ligne.id): 12}, self.user)
        ligne.refresh_from_db()
        self.assertEqual(ligne.quantite_physique, 12)

    def test_sauvegarder_saisie_campagne_terminee_refuse(self):
        campagne = InventaireService.creer_campagne(
            titre="Inv test", magasin=self.magasin, user=self.user)
        campagne.statut = 'VALIDE'
        campagne.save()
        ligne = campagne.lignes_inventaire.get(article=self.article)
        with self.assertRaises(ValidationError):
            InventaireService.sauvegarder_saisie(
                campagne, {str(ligne.id): 5}, self.user)

    def test_valider_campagne_ajuste_le_stock(self):
        factories.creer_stock(self.article, self.magasin, quantite=10,
                              valeur_cmup=Decimal('50'))
        campagne = InventaireService.creer_campagne(
            titre="Inv test", magasin=self.magasin, user=self.user)
        ligne = campagne.lignes_inventaire.get(article=self.article)
        InventaireService.sauvegarder_saisie(
            campagne, {str(ligne.id): 25}, self.user)
        InventaireService.valider_campagne(campagne, self.user)
        stock = StockItem.objects.get(article=self.article, magasin=self.magasin)
        self.assertEqual(stock.quantite_physique, 25)


# ════════════════════════════════════════════════════════════════
# IsolationService — règles d'accès aux magasins
# ════════════════════════════════════════════════════════════════
class IsolationServiceTest(BaseServiceTest):

    def _request(self, user):
        from django.test import RequestFactory
        req = RequestFactory().get('/')
        req.user = user
        return req

    def test_superuser_acces_a_tous(self):
        su = factories.creer_superuser()
        req = self._request(su)
        self.assertEqual(get_magasins_autorises(req).count(), 2)

    def test_utilisateur_sans_profil_acces_vide(self):
        from django.contrib.auth import get_user_model
        user = get_user_model().objects.create_user(username="no_profil")
        req = self._request(user)
        self.assertEqual(get_magasins_autorises(req).count(), 0)

    def test_utilisateur_avec_magasin_autorise(self):
        self.user.profil.magasins_autorises.add(self.magasin)
        req = self._request(self.user)
        self.assertEqual(list(get_magasins_autorises(req)), [self.magasin])

    def test_verifier_acces_vrai(self):
        self.user.profil.magasins_autorises.add(self.magasin)
        req = self._request(self.user)
        self.assertTrue(verifier_acces_magasin(req, self.magasin.id))

    def test_verifier_acces_faux(self):
        self.user.profil.magasins_autorises.add(self.magasin)
        req = self._request(self.user)
        self.assertFalse(verifier_acces_magasin(req, self.magasin2.id))

    def test_filtrer_par_magasins(self):
        self.user.profil.magasins_autorises.add(self.magasin)
        req = self._request(self.user)
        qs = BonMouvement.objects.all()
        self.assertEqual(filtrer_par_magasins(qs, req).count(), 0)


# ════════════════════════════════════════════════════════════════
# Traçabilité Livraison — module Livraisons alimenté par les deux
# parcours de création de sortie (guichet « Traiter » et sortie
# directe liée à une demande).
# ════════════════════════════════════════════════════════════════
class LivraisonTracabiliteTest(TestCase):
    """Le module Livraisons n'est pas redondant : il trace chaque
    livraison de demande (LivraisonPartielle) + accusé de réception,
    et doit être alimenté dès qu'une sortie est liée à une demande."""

    @classmethod
    def setUpTestData(cls):
        from django.contrib.auth import get_user_model
        from core.models import Service
        from stock.models import (
            DemandeMateriel, LigneDemande, LivraisonPartielle,
            AccuseReception, LivraisonLigne,
        )
        cls.User = get_user_model()

        cls.magasin = Magasin.objects.create(nom='Magasin Livraison')
        cls.famille = factories.creer_famille(code='FLIV', intitule='Livraisons')
        cls.article = factories.creer_article(
            famille=cls.famille, designation='Article Livraison', reference='LIV-1')
        cls.article2 = factories.creer_article(
            famille=cls.famille, designation='Article Livraison 2', reference='LIV-2')
        factories.creer_stock(cls.article, cls.magasin, quantite=100)
        factories.creer_stock(cls.article2, cls.magasin, quantite=100)

        cls.user = cls.User.objects.create_superuser(
            username='admin_livraison', password='admin123')
        cls.user.profil.doit_changer_mdp = False
        cls.user.profil.save(update_fields=['doit_changer_mdp'])

        cls.service = Service.objects.create(code='S-LIV', nom='Service Livraison')
        cls.demande = DemandeMateriel.objects.create(
            numero_demande='BDM-LIV-001',
            demandeur=cls.user,
            service_demandeur=cls.service,
            magasin_cible=cls.magasin,
            statut='EN_ATTENTE',
        )
        LigneDemande.objects.create(
            demande=cls.demande, article=cls.article, quantite_demandee=10)
        LigneDemande.objects.create(
            demande=cls.demande, article=cls.article2, quantite_demandee=5)

    def test_sortie_avec_demande_cree_livraison_et_accuse(self):
        """Une sortie liée à une demande alimente le module Livraisons."""
        bon = BonService.creer_bon_sortie(
            lignes=[{'article_id': self.article.id, 'quantite': 6},
                    {'article_id': self.article2.id, 'quantite': 5}],
            utilisateur=self.user,
            magasin=self.magasin,
            demande=self.demande,
        )
        self.demande.refresh_from_db()
        self.assertEqual(self.demande.bon_sortie_lie, bon)

        liv = LivraisonPartielle.objects.get(demande=self.demande, bon_sortie=bon)
        self.assertEqual(liv.quantite_livree, 11)
        self.assertTrue(liv.est_partielle)  # 6/10 → reste 4
        self.assertTrue(AccuseReception.objects.filter(livraison=liv, est_signe=False).exists())

        lignes = LivraisonLigne.objects.filter(livraison=liv)
        self.assertEqual(lignes.count(), 2)
        ligne_art1 = lignes.get(article=self.article)
        self.assertEqual(ligne_art1.quantite_livree, 6)
        self.assertEqual(ligne_art1.reste, 4)  # 10 - 6
        ligne_art2 = lignes.get(article=self.article2)
        self.assertEqual(ligne_art2.reste, 0)  # livraison complète

    def test_sortie_sans_demande_pas_de_livraison(self):
        """Une sortie directe (hors demande) ne crée pas de livraison."""
        bon = BonService.creer_bon_sortie(
            lignes=[{'article_id': self.article.id, 'quantite': 2}],
            utilisateur=self.user,
            magasin=self.magasin,
        )
        self.assertFalse(LivraisonPartielle.objects.filter(bon_sortie=bon).exists())

    def test_stock_decremente_et_mouvement_cree(self):
        """La sortie liée à une demande décrémente le stock et journalise."""
        bon = BonService.creer_bon_sortie(
            lignes=[{'article_id': self.article.id, 'quantite': 3}],
            utilisateur=self.user,
            magasin=self.magasin,
            demande=self.demande,
        )
        stock = StockItem.objects.get(article=self.article, magasin=self.magasin)
        self.assertEqual(stock.quantite_physique, 97)
        self.assertTrue(Mouvement.objects.filter(
            reference_document=bon.numero_bon, type_mouvement='SORTIE').exists())

    def test_liste_livraisons_affiche_la_livraison(self):
        """La page Livraisons liste bien les livraisons de demandes."""
        BonService.creer_bon_sortie(
            lignes=[{'article_id': self.article.id, 'quantite': 4}],
            utilisateur=self.user,
            magasin=self.magasin,
            demande=self.demande,
        )
        session = self.client.session
        session['magasin_actif_id'] = str(self.magasin.id)
        session.save()
        self.client.force_login(self.user)
        resp = self.client.get('/livraisons/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'BDM-LIV-001')
        self.assertContains(resp, 'Service Livraison')
