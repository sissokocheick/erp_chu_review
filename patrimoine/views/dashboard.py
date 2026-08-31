# -*- coding: utf-8 -*-
"""Dashboard patrimoine — KPIs immobilisations, interventions, véhicules, salles."""
from datetime import timedelta
from decimal import Decimal

from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.db.models import Count, Q, Sum

from patrimoine.models import (
    Immobilisation, Intervention, Vehicule, InterventionVehicule,
    SalleConference, ReservationSalle, DemandeVehicule, DemandeSalle,
    ContratMaintenance, CampagneInventairePatrimoine,
)


@login_required(login_url='/auth/login/')
def dashboard_patrimoine(request):
    """Dashboard dédié au Gestionnaire Patrimoine avec KPIs patrimoine."""
    aujourdhui = timezone.now().date()
    il_y_a_30_jours = aujourdhui - timedelta(days=30)
    il_y_a_7_jours = aujourdhui - timedelta(days=7)

    # ══════════════════════════════════════════════════════════════════════
    # KPIs IMMOBILISATIONS
    # ══════════════════════════════════════════════════════════════════════
    immos_par_statut = dict(
        Immobilisation.objects.values_list('statut')
        .annotate(nb=Count('id'))
        .values_list('statut', 'nb')
    )
    nb_immos_total = Immobilisation.objects.count()
    nb_immos_actives = immos_par_statut.get('ACTIF', 0)
    nb_immos_sas = immos_par_statut.get('EN_ATTENTE', 0)
    nb_immos_panne = immos_par_statut.get('EN_PANNE', 0)
    nb_immos_obsoletes = immos_par_statut.get('OBSOLETE', 0)

    valeur_totale = Immobilisation.objects.filter(
        statut='ACTIF'
    ).aggregate(total=Sum('valeur_acquisition'))['total'] or Decimal('0')

    # ══════════════════════════════════════════════════════════════════════
    # KPIs INTERVENTIONS
    # ══════════════════════════════════════════════════════════════════════
    interventions_par_statut = dict(
        Intervention.objects.values_list('statut')
        .annotate(nb=Count('id'))
        .values_list('statut', 'nb')
    )
    nb_interventions_total = Intervention.objects.count()
    nb_interventions_nouvelles = interventions_par_statut.get('NOUVELLE', 0)
    nb_interventions_en_cours = interventions_par_statut.get('EN_COURS', 0)
    nb_interventions_planifiees = interventions_par_statut.get('PLANIFIEE', 0)
    nb_interventions_terminees_30j = Intervention.objects.filter(
        statut='TERMINEE',
        date_fin_intervention__gte=il_y_a_30_jours
    ).count()

    # Interventions récentes
    dernieres_interventions = Intervention.objects.select_related(
        'immobilisation', 'cree_par'
    ).order_by('-date_creation')[:5]

    # ══════════════════════════════════════════════════════════════════════
    # KPIs VÉHICULES
    # ══════════════════════════════════════════════════════════════════════
    vehicules_par_statut = dict(
        Vehicule.objects.values_list('statut')
        .annotate(nb=Count('id'))
        .values_list('statut', 'nb')
    )
    nb_vehicules_total = Vehicule.objects.count()
    nb_vehicules_disponibles = vehicules_par_statut.get('DISPONIBLE', 0)
    nb_vehicules_en_service = vehicules_par_statut.get('EN_SERVICE', 0)
    nb_vehicules_maintenance = vehicules_par_statut.get('EN_MAINTENANCE', 0)

    # Véhicules avec assurance expirée
    vehicules_assurance_expiree = Vehicule.objects.filter(
        assurance_fin__lt=aujourdhui,
        statut__in=['DISPONIBLE', 'EN_SERVICE']
    ).count()

    # ══════════════════════════════════════════════════════════════════════
    # KPIs SALLES
    # ══════════════════════════════════════════════════════════════════════
    salles_par_statut = dict(
        SalleConference.objects.values_list('statut')
        .annotate(nb=Count('id'))
        .values_list('statut', 'nb')
    )
    nb_salles_total = SalleConference.objects.count()
    nb_salles_disponibles = salles_par_statut.get('DISPONIBLE', 0)
    nb_salles_indisponibles = salles_par_statut.get('INDISPONIBLE', 0)

    # Réservations aujourd'hui / cette semaine
    nb_resa_aujourd = ReservationSalle.objects.filter(
        date_debut__date=aujourdhui,
        statut='CONFIRMEE'
    ).count()
    nb_resa_semaine = ReservationSalle.objects.filter(
        date_debut__date__gte=aujourdhui,
        date_debut__date__lte=aujourdhui + timedelta(days=7),
        statut='CONFIRMEE'
    ).count()

    # ══════════════════════════════════════════════════════════════════════
    # DEMANDES EN ATTENTE
    # ══════════════════════════════════════════════════════════════════════
    nb_demandes_vehicule = DemandeVehicule.objects.filter(statut='EN_ATTENTE').count()
    nb_demandes_salle = DemandeSalle.objects.filter(statut='EN_ATTENTE').count()
    nb_demandes_totales = nb_demandes_vehicule + nb_demandes_salle

    # Dernières demandes
    dernieres_demandes_vehicule = DemandeVehicule.objects.select_related(
        'demandeur', 'vehicule'
    ).order_by('-date_creation')[:3]

    dernieres_demandes_salle = DemandeSalle.objects.select_related(
        'demandeur', 'salle_attribuee'
    ).order_by('-date_creation')[:3]

    # ══════════════════════════════════════════════════════════════════════
    # ALERTES
    # ══════════════════════════════════════════════════════════════════════
    alertes = []

    # Contrats expirés
    contrats_expires = ContratMaintenance.objects.filter(
        statut='EXPIRE'
    ).count()
    if contrats_expires > 0:
        alertes.append({
            'type': 'danger',
            'icon': 'fas fa-file-contract',
            'texte': f'{contrats_expires} contrat(s) de maintenance expiré(s)',
            'url': '/patrimoine/contrats/',
        })

    # Véhicules assurance expirée
    if vehicules_assurance_expiree > 0:
        alertes.append({
            'type': 'warning',
            'icon': 'fas fa-shield-alt',
            'texte': f'{vehicules_assurance_expiree} véhicule(s) avec assurance expirée',
            'url': '/patrimoine/vehicules/',
        })

    # Demandes en attente
    if nb_demandes_vehicule > 0:
        alertes.append({
            'type': 'info',
            'icon': 'fas fa-car',
            'texte': f'{nb_demandes_vehicule} demande(s) véhicule en attente',
            'url': '/patrimoine/demandes-vehicule/valider/',
        })
    if nb_demandes_salle > 0:
        alertes.append({
            'type': 'info',
            'icon': 'fas fa-door-open',
            'texte': f'{nb_demandes_salle} demande(s) salle en attente',
            'url': '/patrimoine/demandes-salle/valider/',
        })

    # ══════════════════════════════════════════════════════════════════════
    # INVENTAIRE
    # ══════════════════════════════════════════════════════════════════════
    inventaires_en_cours = CampagneInventairePatrimoine.objects.filter(
        statut__in=['EN_COURS', 'EN_ATTENTE_VALIDATION']
    ).count()

    # ══════════════════════════════════════════════════════════════════════
    # CONTEXT
    # ══════════════════════════════════════════════════════════════════════
    context = {
        # Immobilisations
        'nb_immos_total': nb_immos_total,
        'nb_immos_actives': nb_immos_actives,
        'nb_immos_sas': nb_immos_sas,
        'nb_immos_panne': nb_immos_panne,
        'nb_immos_obsoletes': nb_immos_obsoletes,
        'valeur_totale': valeur_totale,

        # Interventions
        'nb_interventions_total': nb_interventions_total,
        'nb_interventions_nouvelles': nb_interventions_nouvelles,
        'nb_interventions_en_cours': nb_interventions_en_cours,
        'nb_interventions_planifiees': nb_interventions_planifiees,
        'nb_interventions_terminees_30j': nb_interventions_terminees_30j,
        'dernieres_interventions': dernieres_interventions,

        # Véhicules
        'nb_vehicules_total': nb_vehicules_total,
        'nb_vehicules_disponibles': nb_vehicules_disponibles,
        'nb_vehicules_en_service': nb_vehicules_en_service,
        'nb_vehicules_maintenance': nb_vehicules_maintenance,
        'vehicules_assurance_expiree': vehicules_assurance_expiree,

        # Salles
        'nb_salles_total': nb_salles_total,
        'nb_salles_disponibles': nb_salles_disponibles,
        'nb_salles_indisponibles': nb_salles_indisponibles,
        'nb_resa_aujourd': nb_resa_aujourd,
        'nb_resa_semaine': nb_resa_semaine,

        # Demandes
        'nb_demandes_vehicule': nb_demandes_vehicule,
        'nb_demandes_salle': nb_demandes_salle,
        'nb_demandes_totales': nb_demandes_totales,
        'dernieres_demandes_vehicule': dernieres_demandes_vehicule,
        'dernieres_demandes_salle': dernieres_demandes_salle,

        # Alertes
        'alertes': alertes,
        'contrats_expires': contrats_expires,

        # Inventaire
        'inventaires_en_cours': inventaires_en_cours,
    }

    return render(request, 'patrimoine/dashboard.html', context)
