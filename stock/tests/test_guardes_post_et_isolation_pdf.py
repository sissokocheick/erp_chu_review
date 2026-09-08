# -*- coding: utf-8 -*-
"""Régression — durcissement des vues de mutation et isolation des impressions.

1. GET sur `supprimer_commande` et `annuler_demande` → 405 (garde @require_POST)
   sans aucune mutation de l'état.
2. `imprimer_bon_hors_stock` refuse l'impression d'un bon appartenant à un
   magasin non autorisé (même règle qu'`imprimer_bon_multi_lignes`) et
   l'autorise pour un magasin autorisé.
"""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from stock.models import (
    Ajustement, BonMouvement, CampagneInventaire, Commande, DemandeMateriel,
    Fournisseur, LigneBon, LigneCommande, LigneDemande, Magasin, Service,
)
from stock.tests.factories import (
    creer_article, creer_famille, desactiver_changement_mdp,
)

User = get_user_model()


class BaseAgentTest(TestCase):
    """Utilisateur standard limité au « magasin A », connecté par défaut."""

    @classmethod
    def setUpTestData(cls):
        cls.magasin = Magasin.objects.create(nom='Magasin A')
        cls.user = User.objects.create_user(
            username='agent_a', password='testpass123')
        cls.user.profil.magasins_autorises.add(cls.magasin)
        desactiver_changement_mdp(cls.user)

    def setUp(self):
        self.client.force_login(self.user)
        session = self.client.session
        session['magasin_actif_id'] = str(self.magasin.id)
        session.save()

    def _donner_permission(self, codename):
        """Grant d'une permission `accounts.menu_*` (pattern des tests existants)."""
        perm = Permission.objects.get(
            codename=codename, content_type__app_label='accounts')
        self.user.user_permissions.add(perm)


class MutationsGetRefuseesTest(BaseAgentTest):
    """GET sur les actions de mutation → 405, sans effet de bord."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.famille = creer_famille(code='FAM-405', intitule='Famille 405')
        cls.fournisseur = Fournisseur.objects.create(
            code='F405', raison_sociale='Fournisseur 405')
        cls.service = Service.objects.create(code='SVC-405', nom='Urgences')

    def _creer_commande_brouillon(self):
        commande = Commande.objects.create(
            fournisseur=self.fournisseur, magasin=self.magasin,
            famille=self.famille, cree_par=self.user)
        commande.statut_validation = 'BROUILLON'
        commande.save(update_fields=['statut_validation'])
        return commande

    def test_supprimer_commande_en_get_renvoie_405_sans_supprimer(self):
        """Un GET sur supprimer_commande ne doit pas supprimer le brouillon."""
        self._donner_permission('menu_commandes')
        commande = self._creer_commande_brouillon()

        resp = self.client.get(
            reverse('supprimer_commande', args=[commande.pk]))

        self.assertEqual(resp.status_code, 405)
        commande.refresh_from_db()
        self.assertTrue(
            Commande.objects.filter(pk=commande.pk).exists(),
            'la commande ne doit pas être supprimée par un GET')
        self.assertEqual(commande.statut_validation, 'BROUILLON')

    def test_supprimer_commande_en_post_supprime_toujours(self):
        """Le POST (seul chemin légitime) supprime toujours le brouillon."""
        self._donner_permission('menu_commandes')
        commande = self._creer_commande_brouillon()

        resp = self.client.post(
            reverse('supprimer_commande', args=[commande.pk]))

        self.assertEqual(resp.status_code, 302)
        self.assertFalse(
            Commande.objects.filter(pk=commande.pk).exists(),
            'le POST doit supprimer la commande brouillon')

    def test_annuler_demande_en_get_renvoie_405_sans_annuler(self):
        """Un GET sur annuler_demande ne doit pas changer le statut."""
        demande = DemandeMateriel.objects.create(
            numero_demande='DM-405-001', demandeur=self.user,
            service_demandeur=self.service, magasin_cible=self.magasin,
            statut='EN_ATTENTE')

        resp = self.client.get(reverse('annuler_demande', args=[demande.pk]))

        self.assertEqual(resp.status_code, 405)
        demande.refresh_from_db()
        self.assertEqual(
            demande.statut, 'EN_ATTENTE',
            'le GET ne doit ni annuler ni clôturer la demande')

    def test_annuler_demande_en_post_annule_toujours(self):
        """Le POST (seul chemin légitime) annule bien la demande."""
        demande = DemandeMateriel.objects.create(
            numero_demande='DM-405-002', demandeur=self.user,
            service_demandeur=self.service, magasin_cible=self.magasin,
            statut='EN_ATTENTE')

        resp = self.client.post(reverse('annuler_demande', args=[demande.pk]))

        self.assertEqual(resp.status_code, 302)
        demande.refresh_from_db()
        self.assertEqual(demande.statut, 'ANNULEE')


class ImpressionHorsStockIsolationTest(BaseAgentTest):
    """imprimer_bon_hors_stock : isolation par magasins autorisés."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.magasin_b = Magasin.objects.create(nom='Magasin B (non autorisé)')
        cls.famille = creer_famille(code='FAM-HS', intitule='Famille HS')
        cls.article = creer_article(
            famille=cls.famille, reference='ART-HS',
            designation='Article Hors Stock')

        # Un bon hors stock dans chaque magasin
        cls.hs_a = BonMouvement.objects.create(
            type_bon='SORTIE_HORS_STOCK', magasin=cls.magasin,
            statut_validation='VALIDE', numero_bon='HS-A-405')
        cls.hs_b = BonMouvement.objects.create(
            type_bon='SORTIE_HORS_STOCK', magasin=cls.magasin_b,
            statut_validation='VALIDE', numero_bon='HS-B-405')

    def test_impression_bon_magasin_non_autorise_refusee(self):
        """Un agent du magasin A ne peut pas imprimer un bon du magasin B."""
        self._donner_permission('menu_sorties_hors_stock')

        resp = self.client.get(
            reverse('imprimer_bon_hors_stock', args=[self.hs_b.pk]))

        self.assertEqual(
            resp.status_code, 302,
            'l\'impression d\'un bon d\'un magasin non autorisé doit être refusée')
        self.assertRedirects(
            resp, reverse('liste_bons_hors_stock'), fetch_redirect_response=False)
        # Le message d'accès refusé doit être émis (stockage de messages)
        from django.contrib.messages import get_messages
        msgs = [str(m) for m in get_messages(resp.wsgi_request)]
        self.assertTrue(
            any("accès au magasin" in m for m in msgs),
            f"message d'accès refusé absent : {msgs}")

    def test_impression_bon_magasin_autorise_acceptee(self):
        """Un agent du magasin A peut imprimer un bon de SON magasin."""
        self._donner_permission('menu_sorties_hors_stock')

        resp = self.client.get(
            reverse('imprimer_bon_hors_stock', args=[self.hs_a.pk]))

        self.assertEqual(resp.status_code, 200)
        self.assertNotEqual(resp.get('Content-Type', '').split(';')[0].lower(),
                            'text/html', 'le PDF doit être généré (pas un refus)')

    def test_impression_sans_permission_refusee(self):
        """Sans la permission, même un bon du magasin autorisé est refusé."""
        resp = self.client.get(
            reverse('imprimer_bon_hors_stock', args=[self.hs_a.pk]))

        # Permission refusée → redirection vers la liste des bons hors stock
        self.assertEqual(resp.status_code, 302)
        self.assertRedirects(
            resp, reverse('liste_bons_hors_stock'), fetch_redirect_response=False)

class ImpressionPdfAutresDocumentsIsolationTest(BaseAgentTest):
    """Isolation magasin sur les autres vues PDF à identifiant de document
    (commande, demande, ajustement, fiche/resultat d'inventaire, retour
    fournisseur) : refus d'un document d'un magasin non autorisé + impression
    autorisée pour le magasin de l'agent.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.magasin_b = Magasin.objects.create(nom='Magasin B (non autorisé)')
        cls.famille = creer_famille(code='FAM-PDF', intitule='Famille PDF')
        cls.article = creer_article(
            famille=cls.famille, reference='ART-PDF',
            designation='Article PDF')
        cls.fournisseur = Fournisseur.objects.create(
            code='FPDF', raison_sociale='Fournisseur PDF')
        cls.service = Service.objects.create(code='SVC-PDF', nom='Service PDF')

        # Commande dans chaque magasin (avec une ligne)
        cls.commande_a = Commande.objects.create(
            fournisseur=cls.fournisseur, magasin=cls.magasin,
            cree_par=cls.user)
        cls.commande_b = Commande.objects.create(
            fournisseur=cls.fournisseur, magasin=cls.magasin_b,
            cree_par=cls.user)
        for c in (cls.commande_a, cls.commande_b):
            LigneCommande.objects.create(
                commande=c, article=cls.article, quantite_demandee=2)

        # Demande de matériel dans chaque magasin cible (avec une ligne)
        cls.demande_a = DemandeMateriel.objects.create(
            numero_demande='DM-PDF-A', demandeur=cls.user,
            service_demandeur=cls.service, magasin_cible=cls.magasin,
            statut='EN_ATTENTE')
        cls.demande_b = DemandeMateriel.objects.create(
            numero_demande='DM-PDF-B', demandeur=cls.user,
            service_demandeur=cls.service, magasin_cible=cls.magasin_b,
            statut='EN_ATTENTE')
        for d in (cls.demande_a, cls.demande_b):
            LigneDemande.objects.create(
                demande=d, article=cls.article, quantite_demandee=3)

        # Ajustement dans chaque magasin
        cls.ajustement_a = Ajustement.objects.create(
            article=cls.article, magasin=cls.magasin, quantite=2,
            motif='CASSE', cree_par=cls.user)
        cls.ajustement_b = Ajustement.objects.create(
            article=cls.article, magasin=cls.magasin_b, quantite=2,
            motif='CASSE', cree_par=cls.user)

        # Campagnes d'inventaire dans chaque magasin
        cls.campagne_a = CampagneInventaire.objects.create(
            titre='Inventaire PDF A', magasin=cls.magasin)
        cls.campagne_b = CampagneInventaire.objects.create(
            titre='Inventaire PDF B', magasin=cls.magasin_b)

        # Bon de retour fournisseur dans chaque magasin (avec une ligne)
        cls.retour_a = BonMouvement.objects.create(
            type_bon='RETOUR_FOURNISSEUR', magasin=cls.magasin,
            fournisseur=cls.fournisseur, statut_validation='VALIDE',
            numero_bon='RF-A-PDF')
        cls.retour_b = BonMouvement.objects.create(
            type_bon='RETOUR_FOURNISSEUR', magasin=cls.magasin_b,
            fournisseur=cls.fournisseur, statut_validation='VALIDE',
            numero_bon='RF-B-PDF')
        for b in (cls.retour_a, cls.retour_b):
            LigneBon.objects.create(bon=b, article=cls.article, quantite=1)

    def _verifier_refus(self, url_name, doc_id, redirect_name, permission):
        """Un document du magasin B (non autorisé) est refusé avec message."""
        self._donner_permission(permission)
        resp = self.client.get(reverse(url_name, args=[doc_id]))
        self.assertEqual(
            resp.status_code, 302,
            f"{url_name} doit refuser un document d'un magasin non autorisé")
        self.assertRedirects(
            resp, reverse(redirect_name), fetch_redirect_response=False)
        from django.contrib.messages import get_messages
        msgs = [str(m) for m in get_messages(resp.wsgi_request)]
        self.assertTrue(
            any("accès au magasin" in m for m in msgs),
            f"message d'accès refusé absent : {msgs}")

    def _verifier_accepte(self, url_name, doc_id, permission):
        """Un document du magasin de l'agent (A) s'imprime normalement."""
        self._donner_permission(permission)
        resp = self.client.get(reverse(url_name, args=[doc_id]))
        self.assertEqual(
            resp.status_code, 200,
            f'{url_name} doit imprimer un document du magasin autorisé')
        self.assertNotEqual(
            resp.get('Content-Type', '').split(';')[0].lower(), 'text/html',
            'le PDF doit être généré (pas un refus)')

    def test_commande_pdf_isolee(self):
        self._verifier_refus('imprimer_commande', self.commande_b.pk,
                             'liste_commandes', 'menu_commandes')
        self._verifier_accepte('imprimer_commande', self.commande_a.pk,
                               'menu_commandes')

    def test_bon_demande_pdf_isole(self):
        self._verifier_refus('imprimer_bon_demande', self.demande_b.pk,
                             'mes_demandes', 'menu_demandes')
        self._verifier_accepte('imprimer_bon_demande', self.demande_a.pk,
                               'menu_demandes')

    def test_ajustement_pdf_isole(self):
        self._verifier_refus('imprimer_ajustement', self.ajustement_b.pk,
                             'liste_ajustements', 'menu_ajustements')
        self._verifier_accepte('imprimer_ajustement', self.ajustement_a.pk,
                               'menu_ajustements')

    def test_fiche_comptage_pdf_isolee(self):
        self._verifier_refus('imprimer_fiche_comptage_stock',
                             self.campagne_b.pk, 'liste_inventaires',
                             'menu_inventaires')
        self._verifier_accepte('imprimer_fiche_comptage_stock',
                               self.campagne_a.pk, 'menu_inventaires')

    def test_resultat_inventaire_pdf_isole(self):
        self._verifier_refus('imprimer_resultat_inventaire',
                             self.campagne_b.pk, 'liste_inventaires',
                             'menu_inventaires')
        self._verifier_accepte('imprimer_resultat_inventaire',
                               self.campagne_a.pk, 'menu_inventaires')

    def test_retour_fournisseur_pdf_isole(self):
        self._verifier_refus('imprimer_bon_retour_fournisseur',
                             self.retour_b.pk, 'liste_retours_fournisseurs',
                             'menu_retours_fournisseurs')
        self._verifier_accepte('imprimer_bon_retour_fournisseur',
                               self.retour_a.pk, 'menu_retours_fournisseurs')

class ApercuBonEntreeIsolationTest(BaseAgentTest):
    """apercu_bon_entree : même isolation fail-closed par magasins autorisés
    que les autres aperçus et les vues PDF de stock — refus d'un bon d'entrée
    d'un magasin non autorisé, aperçu OK pour le magasin de l'agent.
    """

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.magasin_b = Magasin.objects.create(nom='Magasin B (non autorisé)')
        cls.famille = creer_famille(code='FAM-AP', intitule='Famille Aperçu')
        cls.article = creer_article(
            famille=cls.famille, reference='ART-AP',
            designation='Article Aperçu')
        cls.fournisseur = Fournisseur.objects.create(
            code='FAP', raison_sociale='Fournisseur Aperçu')
        cls.service = Service.objects.create(code='SVC-AP', nom='Service Aperçu')
        cls.entree_a = BonMouvement.objects.create(
            type_bon='ENTREE', magasin=cls.magasin,
            fournisseur=cls.fournisseur, service_demandeur=cls.service,
            cree_par=cls.user, numero_bon='BE-A-AP')
        cls.entree_b = BonMouvement.objects.create(
            type_bon='ENTREE', magasin=cls.magasin_b,
            fournisseur=cls.fournisseur, service_demandeur=cls.service,
            cree_par=cls.user, numero_bon='BE-B-AP')
        for b in (cls.entree_a, cls.entree_b):
            LigneBon.objects.create(bon=b, article=cls.article, quantite=3)

    def test_apercu_bon_entree_magasin_non_autorise_refuse(self):
        """Un aperçu d'un bon d'entrée d'un magasin non autorisé est refusé."""
        self._donner_permission('menu_entrees')
        resp = self.client.get(
            reverse('apercu_bon_entree', args=[self.entree_b.pk]))
        self.assertEqual(
            resp.status_code, 302,
            "l'aperçu d'un bon d'un magasin non autorisé doit être refusé")
        self.assertRedirects(
            resp, reverse('liste_entrees'), fetch_redirect_response=False)
        from django.contrib.messages import get_messages
        msgs = [str(m) for m in get_messages(resp.wsgi_request)]
        self.assertTrue(
            any("accès au magasin" in m for m in msgs),
            f"message d'accès refusé absent : {msgs}")

    def test_apercu_bon_entree_magasin_autorise_accepte(self):
        """L'aperçu d'un bon d'entrée du magasin de l'agent est autorisé."""
        self._donner_permission('menu_entrees')
        resp = self.client.get(
            reverse('apercu_bon_entree', args=[self.entree_a.pk]))
        self.assertEqual(
            resp.status_code, 200,
            "l'aperçu d'un bon du magasin autorisé doit être rendu")
        self.assertTemplateUsed(resp, 'stock/pdf/bon_entree.html')

