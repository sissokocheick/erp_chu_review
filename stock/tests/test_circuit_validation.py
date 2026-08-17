# -*- coding: utf-8 -*-
"""
Tests du comportement unifié du circuit de validation.

Règles métier vérifiées :
1. Circuit ACTIF → le document est créé en attente (BROUILLON/ATTENTE) et
   l'action (mouvement de stock) n'est PAS exécutée tant que les validateurs
   désignés dans le circuit n'ont pas validé.
2. Circuit INACTIF ou ABSENT → validation directe : le document est VALIDE à
   la création et l'action est exécutée immédiatement.
3. Seuls les validateurs désignés (ou superuser) peuvent valider ; les autres
   sont refusés.
4. Après validation, l'opération agit sur le stock.
"""
from decimal import Decimal

from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from stock.models import (
    Article, Ajustement, BonMouvement, CircuitValidation, Commande,
    Fournisseur, LigneCommande, Magasin, StockItem,
)
from stock.tests import factories


class BaseCircuitTest(TestCase):
    def setUp(self):
        self.user = factories.creer_utilisateur(username='magasinier')
        self.user.profil.doit_changer_mdp = False
        self.user.profil.save(update_fields=['doit_changer_mdp'])

        self.validateur = factories.creer_utilisateur(username='validateur')
        self.validateur.profil.doit_changer_mdp = False
        self.validateur.profil.save(update_fields=['doit_changer_mdp'])

        self.magasin = factories.creer_magasin(nom='Magasin Circuit')
        self.user.profil.magasins_autorises.add(self.magasin)
        self.validateur.profil.magasins_autorises.add(self.magasin)

        self.famille = factories.creer_famille(code='FCIRC', intitule='Famille Circuit')
        self.article = factories.creer_article(
            famille=self.famille, designation='Article Circuit',
            reference='ART-CIRC', prix_reference=Decimal('1000.00'))
        self.stock_item = StockItem.objects.create(
            article=self.article, magasin=self.magasin,
            quantite_physique=100, valeur_cmup=Decimal('500.00'))

        self.fournisseur = Fournisseur.objects.create(
            code='FOURC', raison_sociale='Fournisseur Circuit')

    def _donner_permission(self, user, codename):
        """Donne une permission menu_* (pattern des validateurs réels : ils ont
        l'accès au module + sont désignés dans le circuit)."""
        perm = Permission.objects.get(
            codename=codename, content_type__app_label='accounts')
        user.user_permissions.add(perm)
        return user

    def _login(self, user):
        self.client.force_login(user)
        session = self.client.session
        session['magasin_actif_id'] = str(self.magasin.id)
        session.save()

    def _creer_commande(self, statut_validation):
        commande = Commande.objects.create(
            fournisseur=self.fournisseur, magasin=self.magasin,
            famille=self.famille, cree_par=self.user)
        commande.statut_validation = statut_validation
        commande.save(update_fields=['statut_validation'])
        LigneCommande.objects.create(
            commande=commande, article=self.article,
            quantite_demandee=10, quantite_recue=0,
            prix_unitaire=Decimal('1000.00'))
        return commande

    def _receptionner(self, commande):
        """POST de réception avec une ligne complète (quantité + lot)."""
        ligne = commande.lignes_commande.first()
        return self.client.post(
            reverse('receptionner_commande', args=[commande.id]),
            {'magasin': self.magasin.id,
             'ligne_ids[]': [ligne.id],
             'quantites[]': ['10'],
             'lots[]': [''],
             'peremptions[]': [''],
             'prix_unitaires[]': ['1000.00'],
             'reference_externe': 'BL-1'})


# ════════════════════════════════════════════════════════════════════
# COMMANDES — règle 2 (auto-VALIDE sans circuit) et règle 1 (BROUILLON)
# ════════════════════════════════════════════════════════════════════
class CommandeCircuitTest(BaseCircuitTest):
    def test_commande_sans_circuit_auto_valide(self):
        """Règle 2 : pas de circuit COMMANDE configuré → validation directe."""
        commande = Commande.objects.create(
            fournisseur=self.fournisseur, magasin=self.magasin,
            famille=self.famille, cree_par=self.user)
        commande.refresh_from_db()
        self.assertEqual(commande.statut_validation, 'VALIDE')

    def test_commande_circuit_inactif_auto_valide(self):
        """Règle 2 : circuit COMMANDE inactif → validation directe."""
        CircuitValidation.objects.create(
            type_document='COMMANDE', est_actif=False)
        commande = Commande.objects.create(
            fournisseur=self.fournisseur, magasin=self.magasin,
            famille=self.famille, cree_par=self.user)
        commande.refresh_from_db()
        self.assertEqual(commande.statut_validation, 'VALIDE')

    def test_commande_circuit_actif_brouillon(self):
        """Règle 1 : circuit COMMANDE actif → commande en BROUILLON."""
        circuit = CircuitValidation.objects.create(
            type_document='COMMANDE', est_actif=True)
        circuit.valideurs.add(self.validateur)

        commande = Commande.objects.create(
            fournisseur=self.fournisseur, magasin=self.magasin,
            famille=self.famille, cree_par=self.user)
        commande.refresh_from_db()
        self.assertEqual(commande.statut_validation, 'BROUILLON')

    def test_valider_commande_par_validateur(self):
        """Règle 3+4 : le validateur du circuit peut approuver la commande."""
        circuit = CircuitValidation.objects.create(
            type_document='COMMANDE', est_actif=True)
        circuit.valideurs.add(self.validateur)
        self._donner_permission(self.validateur, 'menu_commandes')
        commande = self._creer_commande('BROUILLON')

        self._login(self.validateur)
        resp = self.client.get(reverse('valider_commande', args=[commande.id]))
        self.assertEqual(resp.status_code, 302)

        commande.refresh_from_db()
        self.assertEqual(commande.statut_validation, 'VALIDE')
        self.assertEqual(commande.valide_par, self.validateur)

    def test_valider_commande_non_validateur_refuse(self):
        """Règle 3 : un utilisateur hors circuit ne peut pas valider."""
        circuit = CircuitValidation.objects.create(
            type_document='COMMANDE', est_actif=True)
        circuit.valideurs.add(self.validateur)
        commande = self._creer_commande('BROUILLON')

        self._login(self.user)
        resp = self.client.get(reverse('valider_commande', args=[commande.id]))
        self.assertEqual(resp.status_code, 302)

        commande.refresh_from_db()
        self.assertEqual(commande.statut_validation, 'BROUILLON')

    def test_reception_bloquee_si_commande_non_validee(self):
        """Règle 1 : une commande non approuvée ne peut pas être réceptionnée."""
        circuit = CircuitValidation.objects.create(
            type_document='COMMANDE', est_actif=True)
        circuit.valideurs.add(self.validateur)
        commande = self._creer_commande('BROUILLON')
        self._donner_permission(self.user, 'menu_reception_commande')

        self._login(self.user)
        resp = self.client.post(
            reverse('receptionner_commande', args=[commande.id]),
            {'magasin': self.magasin.id})
        self.assertEqual(resp.status_code, 302)
        # Aucun bon d'entrée créé : l'action est bloquée tant que non validée
        self.assertFalse(BonMouvement.objects.filter(
            type_bon='ENTREE', commande_liee=commande).exists())

    def test_reception_autorisee_apres_validation(self):
        """Règle 4 : après validation, la réception est possible."""
        CircuitValidation.objects.create(
            type_document='COMMANDE', est_actif=False)
        commande = self._creer_commande('VALIDE')
        self._donner_permission(self.user, 'menu_reception_commande')

        self._login(self.user)
        resp = self._receptionner(commande)
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(BonMouvement.objects.filter(
            type_bon='ENTREE', commande_liee=commande).exists())


# ════════════════════════════════════════════════════════════════════
# AJUSTEMENTS — règle 1 (ATTENTE sans mouvement) et règle 3/4
# ════════════════════════════════════════════════════════════════════
class AjustementCircuitTest(BaseCircuitTest):
    def setUp(self):
        super().setUp()
        self._donner_permission(self.user, 'menu_ajustements')
        self._donner_permission(self.validateur, 'menu_ajustements')

    def _creer_via_vue(self, user):
        """Crée un ajustement via la vraie vue (qui applique la logique du
        circuit), comme le ferait un utilisateur réel."""
        self._login(user)
        resp = self.client.post(reverse('liste_ajustements'), {
            'article': self.article.id,
            'magasin': self.magasin.id,
            'motif': 'AJOUT',
            'quantite': '10',
            'commentaire': 'Test circuit',
        })
        self.assertEqual(resp.status_code, 302)
        return Ajustement.objects.get(article=self.article, magasin=self.magasin)

    def test_ajustement_sans_circuit_applique_immediatement(self):
        """Règle 2 : pas de circuit AJUSTEMENT → stock ajusté immédiatement."""
        ajustement = self._creer_via_vue(self.user)
        ajustement.refresh_from_db()
        self.assertEqual(ajustement.statut_validation, 'VALIDE')
        self.stock_item.refresh_from_db()
        self.assertEqual(self.stock_item.quantite_physique, 110)

    def test_ajustement_circuit_actif_attente_sans_mouvement(self):
        """Règle 1 : circuit actif → ATTENTE, aucun mouvement de stock."""
        circuit = CircuitValidation.objects.create(
            type_document='AJUSTEMENT', est_actif=True)
        circuit.valideurs.add(self.validateur)

        ajustement = self._creer_via_vue(self.user)
        ajustement.refresh_from_db()
        self.assertEqual(ajustement.statut_validation, 'ATTENTE')
        self.stock_item.refresh_from_db()
        self.assertEqual(self.stock_item.quantite_physique, 100)

    def test_valider_ajustement_par_validateur_applique_le_stock(self):
        """Règle 3+4 : le validateur valide → l'ajustement agit sur le stock."""
        circuit = CircuitValidation.objects.create(
            type_document='AJUSTEMENT', est_actif=True)
        circuit.valideurs.add(self.validateur)
        ajustement = self._creer_via_vue(self.user)
        self.assertEqual(ajustement.statut_validation, 'ATTENTE')

        self._login(self.validateur)
        resp = self.client.post(
            reverse('valider_ajustement', args=[ajustement.id]))
        self.assertEqual(resp.status_code, 302)

        ajustement.refresh_from_db()
        self.assertEqual(ajustement.statut_validation, 'VALIDE')
        self.stock_item.refresh_from_db()
        self.assertEqual(self.stock_item.quantite_physique, 110)

    def test_valider_ajustement_non_validateur_refuse(self):
        """Règle 3 : un utilisateur hors circuit ne peut pas valider."""
        circuit = CircuitValidation.objects.create(
            type_document='AJUSTEMENT', est_actif=True)
        circuit.valideurs.add(self.validateur)
        ajustement = self._creer_via_vue(self.user)

        self._login(self.user)
        resp = self.client.post(
            reverse('valider_ajustement', args=[ajustement.id]))
        self.assertEqual(resp.status_code, 302)

        ajustement.refresh_from_db()
        self.assertEqual(ajustement.statut_validation, 'ATTENTE')
        self.stock_item.refresh_from_db()
        self.assertEqual(self.stock_item.quantite_physique, 100)
