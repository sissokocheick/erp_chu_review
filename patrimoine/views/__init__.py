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
