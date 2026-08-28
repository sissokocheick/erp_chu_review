# -*- coding: utf-8 -*-
"""
Package vues Patrimoine.

Ré-exporte toutes les vues pour la compatibilité avec ``from . import views``
dans urls.py. Chaque module contient un sous-ensemble logique de vues.
"""
from .common import patrimoine_required

from .catalogue import (
    registre, fiche_detail, modifier_immo,
    etiquette_qr, quick_edit, scan_mobile,
    registre_rebuts, registre_pertes,
)

from .sas import (
    sas, valider_sas, eclater_bien_sas,
    creer_immatriculation_directe,
)

from .contrats import (
    liste_contrats, detail_contrat,
    assigner_equipements_contrat, echeancier_maintenance,
)

from .interventions import (
    liste_interventions, detail_intervention,
    signaler_panne, creer_intervention, valider_intervention,
    portail_prestataire, mes_tickets, dispatch_interventions,
    mes_interventions_tech, suivi_ticket,
    declarer_panne_pc, imprimer_bon_sortie_reparation,
)

from .parametres import (
    parametres, editer_schema,
    ajax_modeles, ajax_batiments, ajax_localisation,
    ajax_specs_schema, ajax_vnc,
    creer_type_equipement, api_type_specs,
)

from .exports import (
    export_registre_excel, telecharger_template,
    import_excel, detail_import_log,
)

from .inventaire import (
    patrimoine_campagnes_inventaire, detail_campagne_inventaire,
    appliquer_reconciliation_inventaire, audit_scan_inventaire,
    imprimer_fiche_comptage,
)

from .vehicules import (
    liste_vehicules, detail_vehicule, creer_vehicule, modifier_vehicule, supprimer_vehicule,
    liste_interventions_vehicule, creer_intervention_vehicule,
    liste_missions_vehicule, creer_mission_vehicule,
    ajax_modeles_vehicule,
)

from .salles import (
    liste_salles, detail_salle, creer_salle, modifier_salle, supprimer_salle,
    calendrier_salles, calendrier_reservations, liste_reservations, creer_reservation,
    detail_reservation, valider_reservation, annuler_reservation, supprimer_reservation,
    ajax_etages, ajax_bureaux, ajax_etages_salle, ajax_bureaux_salle,
    ajax_disponibilite_salle, ajax_reservations_salle,
)

from .demandes import (
    mes_demandes_vehicule, creer_demande_vehicule, detail_demande_vehicule, annuler_demande_vehicule,
    demandes_vehicule_a_valider, valider_demande_vehicule,
    mes_demandes_salle, creer_demande_salle, detail_demande_salle, annuler_demande_salle,
    demandes_salle_a_valider, valider_demande_salle,
)
