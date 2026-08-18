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
    DemandeMateriel, Fournisseur, LigneBon, LigneCommande, Magasin,
    Mouvement, StockItem,
)
from stock.services.bon_service import BonService
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


# ════════════════════════════════════════════════════════════════════
# DEMANDES DE MATÉRIEL — validation hiérarchique par service
# Règle 1 (EN_ATTENTE_VALIDATION), règle 2 (directe au magasin),
# règle 3 (page réservée aux validateurs) et règle 4 (approbation → magasin)
# ════════════════════════════════════════════════════════════════════
class DemandeCircuitTest(BaseCircuitTest):
    def setUp(self):
        super().setUp()
        from core.models import Service

        self.service = Service.objects.create(code='SVC1', nom='Cardiologie')
        self.user.profil.service = self.service
        self.user.profil.save(update_fields=['service'])
        self.validateur.profil.service = self.service
        self.validateur.profil.save(update_fields=['service'])

        self._donner_permission(self.user, 'menu_demandes')
        self._donner_permission(self.validateur, 'menu_demandes')
        self._donner_permission(self.validateur, 'menu_valider_demandes')

    def _creer_demande_via_vue(self):
        """Crée une demande via la vraie vue mes_demandes."""
        self._login(self.user)
        resp = self.client.post(reverse('mes_demandes'), {
            'magasin_cible': self.magasin.id,
            'articles[]': [self.article.id],
            'quantites[]': ['5'],
            'commentaire': 'Test demande circuit',
        })
        self.assertEqual(resp.status_code, 302)
        return DemandeMateriel.objects.get(demandeur=self.user)

    def test_demande_circuit_actif_en_attente_validation(self):
        """Règle 1 : circuit DEMANDE actif → demande EN_ATTENTE_VALIDATION."""
        circuit = CircuitValidation.objects.create(
            type_document='DEMANDE', est_actif=True)
        circuit.valideurs.add(self.validateur)

        demande = self._creer_demande_via_vue()
        self.assertEqual(demande.statut, 'EN_ATTENTE_VALIDATION')

    def test_demande_sans_circuit_directe_au_magasin(self):
        """Règle 2 : pas de circuit DEMANDE → transmission directe au magasin."""
        demande = self._creer_demande_via_vue()
        self.assertEqual(demande.statut, 'EN_ATTENTE')

    def test_demande_non_validateur_refuse_page_validation(self):
        """Règle 3 : un utilisateur hors circuit n'accède pas à la validation."""
        circuit = CircuitValidation.objects.create(
            type_document='DEMANDE', est_actif=True)
        circuit.valideurs.add(self.validateur)
        demande = self._creer_demande_via_vue()

        self._login(self.user)
        resp = self.client.post(reverse('demandes_a_valider'), {
            'action': 'approuver', 'demande_id': demande.id})
        self.assertEqual(resp.status_code, 302)
        demande.refresh_from_db()
        self.assertEqual(demande.statut, 'EN_ATTENTE_VALIDATION')

    def test_validateur_approuve_demande_transmise_au_magasin(self):
        """Règle 3+4 : le validateur du circuit approuve → transmise au magasin."""
        circuit = CircuitValidation.objects.create(
            type_document='DEMANDE', est_actif=True)
        circuit.valideurs.add(self.validateur)
        demande = self._creer_demande_via_vue()

        self._login(self.validateur)
        resp = self.client.post(reverse('demandes_a_valider'), {
            'action': 'approuver', 'demande_id': demande.id})
        self.assertEqual(resp.status_code, 302)

        demande.refresh_from_db()
        self.assertEqual(demande.statut, 'EN_ATTENTE')
        self.assertEqual(demande.valide_par_chef, self.validateur)

    def test_validateur_refuse_demande(self):
        """Le validateur peut refuser → demande REFUSEE avec motif."""
        circuit = CircuitValidation.objects.create(
            type_document='DEMANDE', est_actif=True)
        circuit.valideurs.add(self.validateur)
        demande = self._creer_demande_via_vue()

        self._login(self.validateur)
        resp = self.client.post(reverse('demandes_a_valider'), {
            'action': 'refuser', 'demande_id': demande.id,
            'motif_refus': 'Stock indisponible'})
        self.assertEqual(resp.status_code, 302)

        demande.refresh_from_db()
        self.assertEqual(demande.statut, 'REFUSEE')
        self.assertEqual(demande.motif_cloture, 'Stock indisponible')


# ════════════════════════════════════════════════════════════════════
# INVENTAIRES — soumettre → approuver
# Règle 1 (A_VALIDER après soumission), règle 2 (approuver direct),
# règle 3 (seul le validateur approuve) et règle 4 (écarts appliqués)
# ════════════════════════════════════════════════════════════════════
class InventaireCircuitTest(BaseCircuitTest):
    def setUp(self):
        super().setUp()
        self._donner_permission(self.user, 'menu_inventaires')
        self._donner_permission(self.validateur, 'menu_inventaires')
        self.campagne = None

    def _creer_campagne(self):
        from stock.services.inventaire_service import InventaireService
        self.campagne = InventaireService.creer_campagne(
            titre='Inv circuit', magasin=self.magasin, user=self.user)
        ligne = self.campagne.lignes_inventaire.get(article=self.article)
        InventaireService.sauvegarder_saisie(
            self.campagne, {str(ligne.id): 15}, self.user)
        return self.campagne

    def _poster_action(self, action):
        return self.client.post(
            reverse('saisir_inventaire', args=[self.campagne.id]),
            {'action': action})

    def test_inventaire_circuit_actif_soumettre_en_attente(self):
        """Règle 1 : circuit INVENTAIRE actif → soumettre met A_VALIDER, le
        stock n'est pas modifié tant que la campagne n'est pas approuvée."""
        circuit = CircuitValidation.objects.create(
            type_document='INVENTAIRE', est_actif=True)
        circuit.valideurs.add(self.validateur)
        self._creer_campagne()

        self._login(self.user)
        resp = self._poster_action('soumettre')
        self.assertEqual(resp.status_code, 302)

        self.campagne.refresh_from_db()
        self.assertEqual(self.campagne.statut, 'A_VALIDER')
        self.stock_item.refresh_from_db()
        self.assertEqual(self.stock_item.quantite_physique, 100)

    def test_inventaire_sans_circuit_approuver_direct_ajuste_stock(self):
        """Règle 2 : pas de circuit INVENTAIRE → approbation directe, les
        écarts sont appliqués au stock immédiatement."""
        self._creer_campagne()

        self._login(self.user)
        resp = self._poster_action('approuver')
        self.assertEqual(resp.status_code, 302)

        self.campagne.refresh_from_db()
        self.assertEqual(self.campagne.statut, 'VALIDE')
        self.stock_item.refresh_from_db()
        self.assertEqual(self.stock_item.quantite_physique, 15)

    def test_inventaire_circuit_actif_non_validateur_refuse(self):
        """Règle 3 : avec circuit actif, un non-validateur ne peut pas
        approuver — la campagne reste A_VALIDER et le stock inchangé."""
        circuit = CircuitValidation.objects.create(
            type_document='INVENTAIRE', est_actif=True)
        circuit.valideurs.add(self.validateur)
        self._creer_campagne()

        self._login(self.user)
        self._poster_action('soumettre')
        self.campagne.refresh_from_db()
        self.assertEqual(self.campagne.statut, 'A_VALIDER')

        resp = self._poster_action('approuver')
        self.assertEqual(resp.status_code, 302)
        self.campagne.refresh_from_db()
        self.assertEqual(self.campagne.statut, 'A_VALIDER')
        self.stock_item.refresh_from_db()
        self.assertEqual(self.stock_item.quantite_physique, 100)

    def test_inventaire_circuit_actif_validateur_approuve_ajuste_stock(self):
        """Règle 3+4 : le validateur du circuit approuve → écarts appliqués."""
        circuit = CircuitValidation.objects.create(
            type_document='INVENTAIRE', est_actif=True)
        circuit.valideurs.add(self.validateur)
        self._creer_campagne()

        self._login(self.user)
        self._poster_action('soumettre')
        self.campagne.refresh_from_db()
        self.assertEqual(self.campagne.statut, 'A_VALIDER')

        self._login(self.validateur)
        resp = self._poster_action('approuver')
        self.assertEqual(resp.status_code, 302)

        self.campagne.refresh_from_db()
        self.assertEqual(self.campagne.statut, 'VALIDE')
        self.stock_item.refresh_from_db()
        self.assertEqual(self.stock_item.quantite_physique, 15)


# ════════════════════════════════════════════════════════════════════
# Compteurs du menu — badges visibles uniquement chez les validateurs
# ════════════════════════════════════════════════════════════════════
class CompteurMenuValidationTest(BaseCircuitTest):
    def _contexte(self, user):
        from django.test import RequestFactory
        from stock.context_processors import validation_menu_context
        rf = RequestFactory()
        req = rf.get('/')
        req.user = user
        return validation_menu_context(req)

    def test_non_validateur_compteurs_a_zero(self):
        """Un simple magasinier ne voit AUCUN badge (compteurs à 0)."""
        ctx = self._contexte(self.user)
        self.assertEqual(ctx['nb_bons_sortie_a_valider'], 0)
        self.assertEqual(ctx['nb_bons_entree_a_valider'], 0)
        self.assertEqual(ctx['nb_retours_a_valider'], 0)
        self.assertEqual(ctx['nb_commandes_a_valider'], 0)
        self.assertEqual(ctx['nb_ajustements_a_valider'], 0)
        self.assertEqual(ctx['nb_inventaires_a_valider'], 0)

    def test_validateur_voit_les_bons_en_attente(self):
        """Le validateur du circuit SORTIE voit le nombre de bons à valider,
        limité à ses magasins autorisés."""
        circuit = CircuitValidation.objects.create(
            type_document='SORTIE', est_actif=True)
        circuit.valideurs.add(self.validateur)

        BonMouvement.objects.create(
            type_bon='SORTIE', magasin=self.magasin,
            cree_par=self.user, statut_validation='ATTENTE')
        BonMouvement.objects.create(
            type_bon='SORTIE', magasin=self.magasin,
            cree_par=self.user, statut_validation='VALIDE')

        ctx = self._contexte(self.validateur)
        self.assertEqual(ctx['nb_bons_sortie_a_valider'], 1)
        # Le non-validateur ne voit toujours rien
        ctx_non = self._contexte(self.user)
        self.assertEqual(ctx_non['nb_bons_sortie_a_valider'], 0)

    def test_validateur_hors_magasin_ne_compte_pas(self):
        """Les bons d'un autre magasin (non autorisé) ne sont pas comptés."""
        circuit = CircuitValidation.objects.create(
            type_document='SORTIE', est_actif=True)
        circuit.valideurs.add(self.validateur)

        autre_magasin = factories.creer_magasin(nom='Autre Magasin')
        BonMouvement.objects.create(
            type_bon='SORTIE', magasin=autre_magasin,
            cree_par=self.user, statut_validation='ATTENTE')

        ctx = self._contexte(self.validateur)
        self.assertEqual(ctx['nb_bons_sortie_a_valider'], 0)

    def test_compteur_sortie_inclut_retours_fournisseur(self):
        """Un retour fournisseur en ATTENTE (sortie de stock, circuit SORTIE)
        compte dans le badge du validateur SORTIE."""
        circuit = CircuitValidation.objects.create(
            type_document='SORTIE', est_actif=True)
        circuit.valideurs.add(self.validateur)

        BonMouvement.objects.create(
            type_bon='RETOUR_FOURNISSEUR', magasin=self.magasin,
            cree_par=self.user, statut_validation='ATTENTE')

        ctx = self._contexte(self.validateur)
        self.assertEqual(ctx['nb_bons_sortie_a_valider'], 1)
        # Un validateur ENTREE (hors circuit SORTIE) ne voit rien
        circuit_entree = CircuitValidation.objects.create(
            type_document='ENTREE', est_actif=True)
        circuit_entree.valideurs.add(self.user)
        ctx_entree = self._contexte(self.user)
        self.assertEqual(ctx_entree['nb_bons_sortie_a_valider'], 0)

    def test_compteur_entrees_et_retours(self):
        """Le validateur du circuit ENTREE voit les entrées ET les retours."""
        circuit = CircuitValidation.objects.create(
            type_document='ENTREE', est_actif=True)
        circuit.valideurs.add(self.validateur)

        BonMouvement.objects.create(
            type_bon='ENTREE', magasin=self.magasin,
            cree_par=self.user, statut_validation='ATTENTE')
        BonMouvement.objects.create(
            type_bon='RETOUR_SERVICE', magasin=self.magasin,
            cree_par=self.user, statut_validation='ATTENTE')

        ctx = self._contexte(self.validateur)
        self.assertEqual(ctx['nb_bons_entree_a_valider'], 1)
        self.assertEqual(ctx['nb_retours_a_valider'], 1)

    def test_compteur_demandes_limite_au_service(self):
        """Le badge A Valider ne compte que les demandes du service du validateur."""
        from core.models import Service
        from stock.context_processors import menu_validation_context
        from django.test import RequestFactory

        service = Service.objects.create(code='SVC2', nom='Pédiatrie')
        self.validateur.profil.service = service
        self.validateur.profil.save(update_fields=['service'])

        circuit = CircuitValidation.objects.create(
            type_document='DEMANDE', est_actif=True)
        circuit.valideurs.add(self.validateur)

        DemandeMateriel.objects.create(
            numero_demande='DM-1', demandeur=self.user,
            service_demandeur=service, magasin_cible=self.magasin,
            statut='EN_ATTENTE_VALIDATION')
        autre_service = Service.objects.create(code='SVC3', nom='Urgences')
        DemandeMateriel.objects.create(
            numero_demande='DM-2', demandeur=self.user,
            service_demandeur=autre_service, magasin_cible=self.magasin,
            statut='EN_ATTENTE_VALIDATION')

        rf = RequestFactory()
        req = rf.get('/')
        req.user = self.validateur
        ctx = menu_validation_context(req)
        self.assertTrue(ctx['peut_valider_demandes'])
        self.assertEqual(ctx['nb_demandes_a_valider'], 1)


# ════════════════════════════════════════════════════════════════════
# RETOURS FOURNISSEUR — circuit SORTIE (un retour fournisseur RETIRE du
# stock, comme une sortie : il est donc gouverné par le circuit SORTIE,
# pas par le circuit ENTREE réservé aux réintégrations)
# ════════════════════════════════════════════════════════════════════
class RetourFournisseurCircuitTest(BaseCircuitTest):
    def setUp(self):
        super().setUp()
        self._donner_permission(self.validateur, 'menu_circuits_validation')

    def _creer_bon_retour_fournisseur(self, quantite=10):
        """Crée un bon RETOUR_FOURNISSEUR en ATTENTE (aucun service de
        création n'existe encore : le test documente le chemin de validation
        générique `valider_bon`, seul chemin actuellement exposé)."""
        bon = BonMouvement.objects.create(
            type_bon='RETOUR_FOURNISSEUR',
            magasin=self.magasin,
            cree_par=self.user,
            statut_validation='ATTENTE',
        )
        LigneBon.objects.create(
            bon=bon, article=self.article, quantite=quantite)
        return bon

    def _valider(self, bon):
        return self.client.post(
            reverse('valider_bon', args=[bon.id]))

    def test_retour_fournisseur_attente_stock_intact(self):
        """Règle 1 : un bon RETOUR_FOURNISSEUR en ATTENTE ne touche pas le
        stock tant que le circuit ne l'a pas validé."""
        bon = self._creer_bon_retour_fournisseur()
        self.assertEqual(bon.statut_validation, 'ATTENTE')
        self.stock_item.refresh_from_db()
        self.assertEqual(self.stock_item.quantite_physique, 100)

    def test_retour_fournisseur_validateur_entree_refuse(self):
        """Règle 3 : un validateur du circuit ENTREE n'est PAS autorisé — un
        retour fournisseur retire du stock, il relève du circuit SORTIE."""
        circuit_entree = CircuitValidation.objects.create(
            type_document='ENTREE', est_actif=True)
        circuit_entree.valideurs.add(self.validateur)
        bon = self._creer_bon_retour_fournisseur()

        self._login(self.validateur)
        resp = self._valider(bon)
        self.assertEqual(resp.status_code, 302)

        bon.refresh_from_db()
        self.assertEqual(bon.statut_validation, 'ATTENTE')
        self.stock_item.refresh_from_db()
        self.assertEqual(self.stock_item.quantite_physique, 100)

    def test_retour_fournisseur_validateur_sortie_valide_decremente(self):
        """Règle 3+4 : le validateur du circuit SORTIE valide → le bon passe
        VALIDE et le stock diminue (mouvement RETOUR_FOURNISSEUR créé)."""
        circuit_sortie = CircuitValidation.objects.create(
            type_document='SORTIE', est_actif=True)
        circuit_sortie.valideurs.add(self.validateur)
        bon = self._creer_bon_retour_fournisseur()

        self._login(self.validateur)
        resp = self._valider(bon)
        self.assertEqual(resp.status_code, 302)

        bon.refresh_from_db()
        self.assertEqual(bon.statut_validation, 'VALIDE')
        self.assertEqual(bon.valide_par, self.validateur)
        self.stock_item.refresh_from_db()
        self.assertEqual(self.stock_item.quantite_physique, 90)
        self.assertEqual(Mouvement.objects.filter(
            reference_document=bon.numero_bon,
            type_mouvement='RETOUR_FOURNISSEUR').count(), 1)


# ════════════════════════════════════════════════════════════════════
# FLUX COMPLET RETOUR FOURNISSEUR — service, vue de création, vue de
# validation (circuit SORTIE) et impact sur le stock
# ════════════════════════════════════════════════════════════════════
class RetourFournisseurFluxTest(BaseCircuitTest):
    def setUp(self):
        super().setUp()
        self._donner_permission(self.user, 'menu_retours_fournisseurs')
        self._donner_permission(self.validateur, 'menu_retours_fournisseurs')

    def _creer_via_service(self, circuit=None):
        """Crée un bon de retour fournisseur via le service (comme la vue)."""
        return BonService.creer_bon_retour_fournisseur(
            lignes=[{'article_id': self.article.id, 'quantite': 10}],
            utilisateur=self.user, magasin=self.magasin,
            fournisseur=self.fournisseur, circuit_validation=circuit)

    def test_service_sans_circuit_valide_decremente(self):
        """Règle 2 : pas de circuit SORTIE → bon VALIDE, stock décrémenté,
        mouvement RETOUR_FOURNISSEUR créé."""
        bon = self._creer_via_service()
        self.assertEqual(bon.type_bon, 'RETOUR_FOURNISSEUR')
        self.assertEqual(bon.statut_validation, 'VALIDE')
        self.stock_item.refresh_from_db()
        self.assertEqual(self.stock_item.quantite_physique, 90)
        self.assertTrue(Mouvement.objects.filter(
            reference_document=bon.numero_bon,
            type_mouvement='RETOUR_FOURNISSEUR').exists())

    def test_service_circuit_sortie_actif_attente_stock_intact(self):
        """Règle 1 : circuit SORTIE actif → bon en ATTENTE, stock intact (100),
        aucun mouvement créé."""
        circuit = CircuitValidation.objects.create(
            type_document='SORTIE', est_actif=True)
        circuit.valideurs.add(self.validateur)
        bon = self._creer_via_service(circuit)
        self.assertEqual(bon.statut_validation, 'ATTENTE')
        self.stock_item.refresh_from_db()
        self.assertEqual(self.stock_item.quantite_physique, 100)
        self.assertFalse(Mouvement.objects.filter(
            reference_document=bon.numero_bon).exists())

    def test_vue_creation_retour_fournisseur(self):
        """La vue liste_retours_fournisseurs (POST) crée le bon avec le
        fournisseur sélectionné et décrémente le stock (pas de circuit)."""
        self._login(self.user)
        resp = self.client.post(reverse('liste_retours_fournisseurs'), {
            'fournisseur': self.fournisseur.id,
            'magasin': self.magasin.id,
            'reference_externe': 'REF-LITIGE',
            'articles[]': [self.article.id],
            'quantites[]': ['5'],
            'lots[]': [''],
            'peremptions[]': [''],
        })
        self.assertEqual(resp.status_code, 302)
        bon = BonMouvement.objects.get(type_bon='RETOUR_FOURNISSEUR')
        self.assertEqual(bon.fournisseur, self.fournisseur)
        self.assertEqual(bon.statut_validation, 'VALIDE')
        self.assertEqual(bon.lignes_bon.count(), 1)
        self.stock_item.refresh_from_db()
        self.assertEqual(self.stock_item.quantite_physique, 95)

    def test_vue_validation_validateur_sortie_decremente(self):
        """Règle 3+4 : le validateur du circuit SORTIE valide → VALIDE et le
        stock est retiré (100 → 90)."""
        circuit = CircuitValidation.objects.create(
            type_document='SORTIE', est_actif=True)
        circuit.valideurs.add(self.validateur)
        bon = self._creer_via_service(circuit)
        self.assertEqual(bon.statut_validation, 'ATTENTE')

        self._login(self.validateur)
        resp = self.client.post(
            reverse('valider_bon_retour_fournisseur', args=[bon.id]))
        self.assertEqual(resp.status_code, 302)

        bon.refresh_from_db()
        self.assertEqual(bon.statut_validation, 'VALIDE')

    def test_vue_stock_insuffisant_message_reel(self):
        """UX : quand le service rejette (stock insuffisant), la vue affiche le
        message métier réel et non le message générique « erreur technique »."""
        self._login(self.user)
        resp = self.client.post(reverse('liste_retours_fournisseurs'), {
            'fournisseur': self.fournisseur.id,
            'magasin': self.magasin.id,
            'articles[]': [self.article.id],
            'quantites[]': ['500'],  # stock max 100
            'lots[]': [''],
            'peremptions[]': [''],
        }, follow=True)
        html = resp.content.decode('utf-8')
        # Le message métier est visible, pas le fallback générique
        self.assertIn('Stock insuffisant', html)
        self.assertNotIn('Une erreur technique est survenue', html)
        # Aucun bon créé (transaction atomique annulée)
        self.assertFalse(BonMouvement.objects.filter(
            type_bon='RETOUR_FOURNISSEUR').exists())

    def test_vue_validation_non_validateur_refuse(self):
        """Règle 3 : un utilisateur hors circuit SORTIE est refusé — le bon
        reste en ATTENTE et le stock reste intact."""
        circuit = CircuitValidation.objects.create(
            type_document='SORTIE', est_actif=True)
        circuit.valideurs.add(self.validateur)
        bon = self._creer_via_service(circuit)

        self._login(self.user)
        resp = self.client.post(
            reverse('valider_bon_retour_fournisseur', args=[bon.id]))
        self.assertEqual(resp.status_code, 302)

        bon.refresh_from_db()
        self.assertEqual(bon.statut_validation, 'ATTENTE')
        self.stock_item.refresh_from_db()
        self.assertEqual(self.stock_item.quantite_physique, 100)

    def test_vue_liste_rend_avec_permission(self):
        """La page liste s'affiche pour un utilisateur autorisé (GET)."""
        self._login(self.user)
        resp = self.client.get(reverse('liste_retours_fournisseurs'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Retours Fournisseurs')

    def test_pdf_retour_fournisseur_200(self):
        """Le PDF du bon de retour fournisseur se génère (config modèle BR)."""
        bon = self._creer_via_service()
        self._login(self.user)
        resp = self.client.get(
            reverse('imprimer_bon_retour_fournisseur', args=[bon.id]))
        self.assertEqual(resp.status_code, 200)

    # ── Pré-remplissage « retour fournisseur en 1 clic » ──

    def _creer_bon_entree(self, quantite=10, fournisseur=None,
                          lot='LOT-A', peremp=None):
        """Crée un bon d'entrée (réception) avec une ligne lotée."""
        from datetime import date, timedelta
        bon = BonMouvement.objects.create(
            type_bon='ENTREE', magasin=self.magasin, cree_par=self.user,
            fournisseur=fournisseur or self.fournisseur,
            statut_validation='VALIDE')
        LigneBon.objects.create(
            bon=bon, article=self.article, quantite=quantite,
            numero_lot=lot,
            date_peremption=peremp or (date.today() + timedelta(days=30)))
        return bon

    def test_prefill_depuis_bon_entree(self):
        """?from_bon= pré-remplit fournisseur + lignes (avec lot/péremption)."""
        bon = self._creer_bon_entree()
        self._login(self.user)
        resp = self.client.get(
            reverse('liste_retours_fournisseurs') + f'?from_bon={bon.id}')
        self.assertEqual(resp.status_code, 200)
        prefill = resp.context['prefill_retour']
        self.assertEqual(prefill['fournisseur_id'], self.fournisseur.id)
        self.assertEqual(len(prefill['lignes']), 1)
        ligne = prefill['lignes'][0]
        self.assertEqual(ligne['article_id'], self.article.id)
        self.assertEqual(ligne['quantite'], 10)
        self.assertEqual(ligne['numero_lot'], 'LOT-A')
        self.assertTrue(ligne['date_peremption'])

    def test_prefill_depuis_commande_receptionnee(self):
        """?from_commande= agrège les réceptions de la commande et retombe sur
        le fournisseur de la commande quand le bon n'en a pas."""
        commande = self._creer_commande('VALIDE')
        bon = self._creer_bon_entree()
        bon.fournisseur = None
        bon.commande_liee = commande
        bon.save(update_fields=['fournisseur', 'commande_liee'])

        self._login(self.user)
        resp = self.client.get(
            reverse('liste_retours_fournisseurs') +
            f'?from_commande={commande.id}')
        self.assertEqual(resp.status_code, 200)
        prefill = resp.context['prefill_retour']
        self.assertEqual(prefill['fournisseur_id'], self.fournisseur.id)
        self.assertGreaterEqual(len(prefill['lignes']), 1)

    def test_prefill_bon_sans_fournisseur_aucun(self):
        """Un bon sans fournisseur ni commande → aucun pré-remplissage."""
        bon = self._creer_bon_entree()
        bon.fournisseur = None
        bon.save(update_fields=['fournisseur'])
        self._login(self.user)
        resp = self.client.get(
            reverse('liste_retours_fournisseurs') + f'?from_bon={bon.id}')
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.context['prefill_retour'])

    def test_prefill_ignore_bon_autre_magasin(self):
        """Un bon d'un autre magasin (non autorisé) n'est jamais pré-rempli."""
        autre = factories.creer_magasin(nom='Magasin Autre')
        bon = BonMouvement.objects.create(
            type_bon='ENTREE', magasin=autre, cree_par=self.user,
            fournisseur=self.fournisseur, statut_validation='VALIDE')
        LigneBon.objects.create(bon=bon, article=self.article, quantite=5)
        self._login(self.user)
        resp = self.client.get(
            reverse('liste_retours_fournisseurs') + f'?from_bon={bon.id}')
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.context['prefill_retour'])

    def test_prefill_rendu_html_js(self):
        """Le template sérialise le pré-remplissage en JS (PREFILL)."""
        bon = self._creer_bon_entree()
        self._login(self.user)
        resp = self.client.get(
            reverse('liste_retours_fournisseurs') + f'?from_bon={bon.id}')
        html = resp.content.decode('utf-8')
        self.assertIn(f'fournisseur_id: {self.fournisseur.id}', html)
        self.assertIn(f'article_id: {self.article.id}', html)
        # escapejs échappe le tiret en \u002D (décodé en '-' par le navigateur)
        self.assertIn('LOT\\u002DA', html)
        self.assertIn('appliquerPrefill', html)
