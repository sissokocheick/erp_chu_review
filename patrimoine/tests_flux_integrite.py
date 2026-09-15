# -*- coding: utf-8 -*-
import datetime
from decimal import Decimal
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from django.urls import reverse
from django.core.exceptions import ValidationError
from django.utils import timezone

from core.models import Service
from stock.models import Fournisseur
from patrimoine.models import (
    Batiment, Etage, Bureau, CategoriePatrimoine, TypeEquipement,
    Immobilisation, Intervention, Vehicule, DemandeVehicule,
    ReservationSalle, SalleConference, ContratMaintenance, MouvementPatrimoine,
    Marque, Modele, TypeContrat
)

User = get_user_model()


class PatrimoineFluxIntegriteTestCase(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_superuser(
            username="admin_patrimoine",
            password="adminpassword123",
            email="admin@chu.ci"
        )
        if hasattr(self.user, 'profil'):
            self.user.profil.doit_changer_mdp = False
            self.user.profil.save()
        self.client.force_login(self.user)

        self.service = Service.objects.create(code="CARDIO", nom="Cardiologie")
        self.service_urg = Service.objects.create(code="URG", nom="Urgences")
        self.fournisseur = Fournisseur.objects.create(raison_sociale="Fournisseur Test", code="FTEST")

        self.batiment = Batiment.objects.create(nom="Bâtiment A", code="BAT-A")
        self.etage = Etage.objects.create(nom="1er Étage", ordre=1, batiment=self.batiment)
        self.bureau1 = Bureau.objects.create(nom="Bureau 101", etage=self.etage)
        self.bureau2 = Bureau.objects.create(nom="Bureau 102", etage=self.etage)

        self.categorie = CategoriePatrimoine.objects.create(code="INFO", nom="Informatique")
        self.type_eq = TypeEquipement.objects.create(
            categorie=self.categorie,
            nom="Ordinateur Portable",
            code="PC-PORT"
        )

        self.immo = Immobilisation.objects.create(
            type_equipement=self.type_eq,
            nom_affichage="Dell Latitude 5420",
            code_patrimoine="IMM-2026-0001",
            service_affectation=self.service,
            bureau=self.bureau1,
            valeur_acquisition=Decimal("650000.00"),
            statut="ACTIF",
            date_acquisition=timezone.now().date(),
            cree_par=self.user
        )

    def test_detail_intervention_query_and_prefetch(self):
        """Vérifie que detail_intervention ne crash pas sur select_related ou prefetch_related."""
        intervention = Intervention.objects.create(
            immobilisation=self.immo,
            diagnostic="Écran scintille",
            type_intervention="CURATIVE",
            statut="EN_COURS",
            degre_urgence="MOYENNE",
            cree_par=self.user
        )
        url = reverse('detail_intervention', args=[intervention.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Écran scintille")
        self.assertContains(response, "Dell Latitude 5420")

    def test_detail_vehicule_query_and_prefetch(self):
        """Vérifie que detail_vehicule ne crash pas sur le select_related/prefetch_related."""
        type_veh = TypeEquipement.objects.create(
            categorie=self.categorie,
            nom="Véhicule de liaison",
            code="VEH-LIAIS"
        )
        immo_veh = Immobilisation.objects.create(
            type_equipement=type_veh,
            nom_affichage="Toyota Hilux 4x4",
            code_patrimoine="VEH-2026-001",
            valeur_acquisition=Decimal("25000000.00"),
            statut="ACTIF",
            cree_par=self.user
        )
        marque_toyota = Marque.objects.create(nom="Toyota")
        modele_hilux = Modele.objects.create(nom="Hilux", marque=marque_toyota)
        vehicule = Vehicule.objects.create(
            immobilisation=immo_veh,
            immatriculation="1234-AB-01",
            marque=marque_toyota,
            modele=modele_hilux,
            statut="DISPONIBLE",
            kilometrage=50000
        )
        url = reverse('patrimoine_vehicule_detail', args=[vehicule.pk])
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "1234-AB-01")
        self.assertContains(response, "50000")

    def test_flux_demande_vehicule_validation_et_retour(self):
        """Vérifie le cycle de vie d'une demande véhicule : passage à EN_SERVICE puis DISPONIBLE avec MAJ km."""
        type_veh = TypeEquipement.objects.create(
            categorie=self.categorie, nom="Véhicule Service", code="VEH-SERV"
        )
        immo_veh = Immobilisation.objects.create(
            type_equipement=type_veh, nom_affichage="Peugeot Partner",
            code_patrimoine="VEH-2026-002", valeur_acquisition=Decimal("15000000.00"),
            statut="ACTIF", cree_par=self.user
        )
        marque_peugeot = Marque.objects.create(nom="Peugeot")
        modele_partner = Modele.objects.create(nom="Partner", marque=marque_peugeot)
        vehicule = Vehicule.objects.create(
            immobilisation=immo_veh,
            immatriculation="5678-CD-01",
            marque=marque_peugeot,
            modele=modele_partner,
            statut="DISPONIBLE",
            kilometrage=12000
        )
        demande_v = DemandeVehicule.objects.create(
            vehicule=vehicule,
            demandeur=self.user,
            service_demandeur=self.service,
            objet="Mission d'inspection régionale",
            destination="Grand-Bassam",
            date_depart=timezone.now(),
            date_retour_prevue=timezone.now() + datetime.timedelta(hours=6),
            km_depart=12000,
            statut="EN_ATTENTE"
        )

        # 1. Validation de la demande -> véhicule devient EN_SERVICE
        url_valider = reverse('patrimoine_valider_demande_vehicule', args=[demande_v.pk])
        resp1 = self.client.post(url_valider, {
            'action': 'valider',
            'vehicule': vehicule.pk,
            'km_depart': 12000
        }, follow=True)
        self.assertEqual(resp1.status_code, 200)
        demande_v.refresh_from_db()
        vehicule.refresh_from_db()
        self.assertEqual(demande_v.statut, "VALIDEE")
        self.assertEqual(vehicule.statut, "EN_SERVICE")

        # 2. Retour de la mission avec 12250 km -> véhicule redevient DISPONIBLE et kilométrage mis à jour
        resp2 = self.client.post(url_valider, {
            'action': 'retour',
            'km_retour': 12250,
            'observation_retour': 'RAS, véhicule propre'
        }, follow=True)
        self.assertEqual(resp2.status_code, 200)
        demande_v.refresh_from_db()
        vehicule.refresh_from_db()
        self.assertEqual(demande_v.statut, "TERMINEE")
        self.assertEqual(demande_v.km_retour, 12250)
        self.assertEqual(vehicule.statut, "DISPONIBLE")
        self.assertEqual(vehicule.kilometrage, 12250)

    def test_reservation_salle_anti_collision(self):
        """Vérifie qu'une tentative de validation de réservation chevauchante est bloquée."""
        salle = SalleConference.objects.create(
            nom="Salle Amphithéâtre",
            code="AMPHI-1",
            capacite=100,
            statut="DISPONIBLE"
        )
        debut = timezone.now() + datetime.timedelta(days=1, hours=9)
        fin = debut + datetime.timedelta(hours=2)

        # Première réservation confirmée
        res1 = ReservationSalle.objects.create(
            salle=salle,
            demandeur=self.user,
            service_demandeur=self.service,
            objet="Conférence Médicale",
            date_debut=debut,
            date_fin=fin,
            statut="CONFIRMEE"
        )

        # Deuxième réservation en attente sur le même créneau
        res2 = ReservationSalle.objects.create(
            salle=salle,
            demandeur=self.user,
            service_demandeur=self.service_urg,
            objet="Réunion Crise Urgences",
            date_debut=debut + datetime.timedelta(minutes=30),
            date_fin=fin + datetime.timedelta(hours=1),
            statut="EN_ATTENTE"
        )

        # Tenter de valider res2
        url_valider_salle = reverse('patrimoine_reservation_valider', args=[res2.pk])
        resp = self.client.post(url_valider_salle, {'action': 'valider'}, follow=True)
        res2.refresh_from_db()
        # Doit être resté EN_ATTENTE car collision détectée
        self.assertEqual(res2.statut, "EN_ATTENTE")
        self.assertContains(resp, "déjà réservée")

    def test_modifier_immo_cree_mouvement_mutation(self):
        """Vérifie que le changement de bureau/service génère un MouvementPatrimoine de type MUTATION."""
        url_edit = reverse('patrimoine_modifier', args=[self.immo.pk])
        post_data = {
            'nom_affichage': 'Dell Latitude 5420 Modifié',
            'type_equipement': self.type_eq.pk,
            'service': self.service_urg.pk,
            'bureau': self.bureau2.pk,
            'statut': 'ACTIF',
            'valeur_acquisition': '650000.00',
            'motif_modification': 'Mutation suite à réorganisation',
        }
        resp = self.client.post(url_edit, post_data, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.immo.refresh_from_db()
        self.assertEqual(self.immo.service_affectation, self.service_urg)
        self.assertEqual(self.immo.bureau, self.bureau2)

        mvt = MouvementPatrimoine.objects.filter(
            immobilisation=self.immo,
            type_mouvement='MUTATION'
        ).latest('date_mouvement')
        self.assertIsNotNone(mvt)
        self.assertEqual(mvt.service_arrivee, self.service_urg)
        self.assertEqual(mvt.bureau_depart, self.bureau1)
        self.assertEqual(mvt.bureau_arrivee, self.bureau2)

    def test_modifier_immo_statut_reforme_cree_mouvement_reforme(self):
        """Vérifie que changer le statut en REFORME génère un MouvementPatrimoine de type REFORME."""
        url_edit = reverse('patrimoine_modifier', args=[self.immo.pk])
        post_data = {
            'nom_affichage': self.immo.nom_affichage,
            'type_equipement': self.type_eq.pk,
            'service': self.service.pk,
            'bureau': self.bureau1.pk,
            'statut': 'REFORME',
            'valeur_acquisition': '650000.00',
            'motif_modification': 'Équipement hors service irréparable',
        }
        resp = self.client.post(url_edit, post_data, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.immo.refresh_from_db()
        self.assertEqual(self.immo.statut, 'REFORME')

        mvt = MouvementPatrimoine.objects.filter(
            immobilisation=self.immo,
            type_mouvement='REFORME'
        ).first()
        self.assertIsNotNone(mvt)

    def test_contrat_maintenance_date_validation(self):
        """Vérifie qu'un contrat de maintenance avec date_fin < date_debut lève une ValidationError."""
        type_c = TypeContrat.objects.create(nom="Contrat Préventif Test")
        d_debut = timezone.now().date()
        d_fin = d_debut - datetime.timedelta(days=10)
        contrat = ContratMaintenance(
            reference="CTR-2026-ERR",
            prestataire=self.fournisseur,
            type_contrat=type_c,
            date_debut=d_debut,
            date_fin=d_fin,
            cout_annuel=Decimal("100000.00")
        )
        with self.assertRaises(ValidationError):
            contrat.clean()
        with self.assertRaises(ValidationError):
            contrat.save()
