# -*- coding: utf-8 -*-
"""Traçabilité du routeur CRUD des paramètres patrimoine.

Vérifie que les créations, modifications et suppressions de référentiels
(ici : catégories) via la route `patrimoine_parametres` — ainsi que
`patrimoine_editer_schema` et `creer_type_equipement` — écrivent bien des
entrées JournalAudit avec le bon utilisateur.
"""
from django.test import TestCase
from django.urls import reverse

from accounts.models import JournalAudit
from patrimoine.models import (CategoriePatrimoine, TypeEquipement,
                                Immobilisation, Intervention)
from stock.tests.factories import creer_superuser, desactiver_changement_mdp


class AuditParametresCRUDTest(TestCase):
    """Le routeur CRUD écrit une entrée JournalAudit par mutation."""

    @classmethod
    def setUpTestData(cls):
        cls.user = desactiver_changement_mdp(
            creer_superuser(username="audit_params_admin"))

    def _post_parametres(self, **data):
        return self.client.post(reverse('patrimoine_parametres'), data)

    def test_crud_categorie_journalise_create_update_delete(self):
        """Création + modification + suppression d'une catégorie via la route
        écrivent trois lignes JournalAudit (CREATE/UPDATE/DELETE)."""
        self.client.force_login(self.user)

        # Création
        resp = self._post_parametres(
            action='save_categorie', nom='CAT-AUDIT', code='CA1')
        self.assertEqual(resp.status_code, 302)
        cat = CategoriePatrimoine.objects.get(code='CA1')
        self.assertEqual(cat.nom, 'CAT-AUDIT')

        # Modification
        resp = self._post_parametres(
            action='save_categorie', item_id=cat.pk,
            nom='CAT-AUDIT-2', code='CA2')
        self.assertEqual(resp.status_code, 302)
        cat.refresh_from_db()
        self.assertEqual(cat.nom, 'CAT-AUDIT-2')

        # Suppression
        resp = self._post_parametres(
            action='delete_categorie', item_id=cat.pk)
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(
            CategoriePatrimoine.objects.filter(pk=cat.pk).exists())

        # Trois lignes JournalAudit, avec le bon utilisateur et la bonne action
        lignes = list(JournalAudit.objects.filter(
            utilisateur=self.user, modele_concerne='CategoriePatrimoine')
            .order_by('pk'))
        self.assertEqual(len(lignes), 3)
        self.assertEqual(
            [l.type_action for l in lignes], ['CREATE', 'UPDATE', 'DELETE'])
        self.assertTrue(all(l.utilisateur == self.user for l in lignes))
        self.assertTrue(all(l.id_objet == cat.pk for l in lignes))

    def test_creer_type_equipement_journalise_creation(self):
        """La création d'un type d'équipement via la route dédiée est tracée."""
        self.client.force_login(self.user)
        cat = CategoriePatrimoine.objects.create(nom='Cat Type', code='CTY')
        resp = self.client.post(reverse('creer_type_equipement'), {
            'nom': 'Type Audit', 'code': 'TA1', 'categorie': cat.pk,
            'duree_amortissement_defaut': 5,
            'specs_schema_cache': '[]',
        })
        self.assertEqual(resp.status_code, 302)
        te = TypeEquipement.objects.get(code='TA1')
        ligne = JournalAudit.objects.filter(
            utilisateur=self.user, modele_concerne='TypeEquipement',
            type_action='CREATE').first()
        self.assertIsNotNone(ligne, "la création doit être journalisée")
        self.assertEqual(ligne.id_objet, te.pk)

    def test_editer_schema_journalise_modification(self):
        """La mise à jour du schéma d'un type d'équipement est tracée."""
        self.client.force_login(self.user)
        cat = CategoriePatrimoine.objects.create(nom='Cat Schéma', code='CS1')
        te = TypeEquipement.objects.create(
            nom='Type Schéma', code='TS1', categorie=cat, cree_par=self.user)
        resp = self.client.post(
            reverse('patrimoine_editer_schema', args=[te.pk]),
            {'specs_schema': '[{"key": "serie", "label": "N° série"}]'})
        self.assertEqual(resp.status_code, 302)
        ligne = JournalAudit.objects.filter(
            utilisateur=self.user, modele_concerne='TypeEquipement',
            type_action='UPDATE').first()
        self.assertIsNotNone(ligne, "la modification doit être journalisée")
        self.assertEqual(ligne.id_objet, te.pk)

class AuditCreerInterventionTest(TestCase):
    """La création d'une intervention via la route est tracée au JournalAudit."""

    @classmethod
    def setUpTestData(cls):
        cls.user = desactiver_changement_mdp(
            creer_superuser(username="audit_inter_admin"))

    def test_creer_intervention_journalise_create(self):
        """POST sur patrimoine_creer_intervention → ligne JournalAudit CREATE."""
        self.client.force_login(self.user)
        immo = Immobilisation.objects.create(nom_affichage="Immo Audit Test")
        resp = self.client.post(
            reverse('patrimoine_creer_intervention', args=[immo.pk]),
            {'type_intervention': 'CURATIVE', 'contrat': '',
             'description_probleme': 'Panne playtest',
             'actions_effectuees': '', 'cout_mo': 0, 'cout_pieces': 0,
             'cout_deplacement': 0})
        self.assertEqual(resp.status_code, 302)
        inter = Intervention.objects.get(immobilisation=immo)
        ligne = JournalAudit.objects.filter(
            utilisateur=self.user, modele_concerne='Intervention',
            type_action='CREATE').first()
        self.assertIsNotNone(
            ligne, "la création d'intervention doit être journalisée")
        self.assertEqual(ligne.id_objet, inter.pk)
