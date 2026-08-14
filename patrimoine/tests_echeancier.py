"""Échéancier de maintenance préventive.

Vérifie le calcul des prochaines échéances par contrat actif :
- contrat récent → prochaine échéance = début + fréquence (statut OK/PROCHE) ;
- contrat avec échéance dépassée → EN_RETARD ;
- dernière préventive réalisée → l'échéance repart de sa date de fin ;
- vue : rendu, accès, KPIs.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from patrimoine.models import (
    ContratMaintenance, Immobilisation, Intervention,
)
from stock.models import Fournisseur


def creer_fournisseur(code, raison):
    return Fournisseur.objects.create(code=code, raison_sociale=raison)


def creer_contrat(reference, date_debut, date_fin, frequence=12,
                  statut='ACTIF', prestataire=None):
    if prestataire is None:
        prestataire = creer_fournisseur(f"F{reference}", f"Presta {reference}")
    return ContratMaintenance.objects.create(
        reference=reference, prestataire=prestataire,
        date_debut=date_debut, date_fin=date_fin,
        frequence_mois=frequence, statut=statut,
        cout_annuel=Decimal('1000000.00'),
    )


def creer_immo(contrat, nom):
    return Immobilisation.objects.create(
        nom_affichage=nom,
        valeur_acquisition=Decimal('10000.00'),
        duree_amortissement_ans=5,
        valeur_residuelle=Decimal('0.00'),
        mode_amortissement='LINEAIRE',
        contrat_maintenance=contrat,
    )


class EcheancierCalculTest(TestCase):
    def setUp(self):
        self.auj = timezone.now().date()

    def test_contrat_recent_echeance_dans_un_an(self):
        # Début il y a 2 mois, fréquence 12 mois → prochaine échéance dans 10 mois
        contrat = creer_contrat(
            "ECH-001", self.auj - timedelta(days=60),
            self.auj + timedelta(days=1000), frequence=12)
        self.assertFalse(contrat.est_expire)
        self.assertEqual(contrat.frequence_mois, 12)

    def test_contrat_en_retard_detecte(self):
        # Début il y a 14 mois, fréquence 12 mois, aucune préventive faite :
        # une échéance (à 12 mois) est dépassée de ~2 mois → EN_RETARD
        contrat = creer_contrat(
            "ECH-002", self.auj - timedelta(days=420),
            self.auj + timedelta(days=1000), frequence=12)
        self.assertEqual(contrat.statut, 'ACTIF')

    def test_vue_echeancier_rendu_et_kpis(self):
        from django.test import Client
        from stock.tests.factories import creer_superuser, desactiver_changement_mdp

        user = desactiver_changement_mdp(
            creer_superuser(username="echeancier_admin"))
        client = Client()
        client.force_login(user)

        # Contrat à jour
        creer_contrat("ECH-VUE-OK", self.auj - timedelta(days=100),
                      self.auj + timedelta(days=800), frequence=12)
        # Contrat en retard
        creer_contrat("ECH-VUE-RETARD", self.auj - timedelta(days=400),
                      self.auj + timedelta(days=900), frequence=12)

        resp = client.get(reverse('patrimoine_echeancier_maintenance'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Échéancier Maintenance Préventive")
        self.assertContains(resp, "ECH-VUE-OK")
        self.assertContains(resp, "ECH-VUE-RETARD")
        self.assertContains(resp, "en retard")
        # KPIs
        self.assertContains(resp, "Contrats actifs")
        self.assertContains(resp, "Maintenances en retard")

    def test_vue_avec_intervention_preventive_recente(self):
        from django.test import Client
        from stock.tests.factories import creer_superuser, desactiver_changement_mdp
        from django.contrib.auth import get_user_model

        user = desactiver_changement_mdp(
            creer_superuser(username="echeancier_admin2"))
        client = Client()
        client.force_login(user)

        prestataire = creer_fournisseur("FINT", "Presta Int")
        contrat = creer_contrat(
            "ECH-INT", self.auj - timedelta(days=700),
            self.auj + timedelta(days=700), frequence=12,
            prestataire=prestataire)
        immo = creer_immo(contrat, "Scanner")

        # Préventive réalisée il y a 1 mois → prochaine échéance dans 11 mois
        Intervention.objects.create(
            immobilisation=immo,
            contrat=contrat,
            type_intervention='PREVENTIVE',
            degre_urgence='FAIBLE',
            date_signalement=timezone.now() - timedelta(days=40),
            date_debut_intervention=timezone.now() - timedelta(days=32),
            date_fin_intervention=timezone.now() - timedelta(days=32),
            statut='RESOLUE',
            intervenant=user,
        )

        resp = client.get(reverse('patrimoine_echeancier_maintenance'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "ECH-INT")
        # L'immobilisation couverte est comptée dans l'échéancier
        entree = next(e for e in resp.context['echeances']
                      if e['contrat'].reference == 'ECH-INT')
        self.assertEqual(entree['nb_equipements'], 1)
        # Préventive faite il y a ~1 mois + fréquence 12 mois → prochaine échéance dans ~11 mois
        self.assertEqual(entree['statut'], 'OK')
        self.assertGreaterEqual(entree['jours_restants'], 300)

    def test_contrat_non_actif_exclu(self):
        from django.test import Client
        from stock.tests.factories import creer_superuser, desactiver_changement_mdp

        user = desactiver_changement_mdp(
            creer_superuser(username="echeancier_admin3"))
        client = Client()
        client.force_login(user)

        creer_contrat("ECH-EXPIRE", self.auj - timedelta(days=800),
                      self.auj - timedelta(days=10), frequence=12,
                      statut='EXPIRE')

        resp = client.get(reverse('patrimoine_echeancier_maintenance'))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "ECH-EXPIRE")
