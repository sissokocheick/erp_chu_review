# -*- coding: utf-8 -*-
from django.urls import path
from . import views
from . import rapports

urlpatterns = [

    # ─── Registre / Sas ────────────────────────────────────────────────────────
    path('',                                    views.registre,              name='patrimoine_registre'),
    path('sas/',                                views.sas,                   name='patrimoine_sas'),

    # ─── Fiche détail ──────────────────────────────────────────────────────────
    path('<int:pk>/',                           views.fiche_detail,          name='patrimoine_detail'),
    path('<int:pk>/modifier/',                  views.modifier_immo,         name='patrimoine_modifier'),
    path('<int:pk>/valider-sas/',               views.valider_sas,           name='patrimoine_valider_sas'),

    # NB: route patrimoine_mouvement supprimee (15/08/2026) : ligne commentee retiree (404 trompeur)
    # NB: l'historique des mouvements est consultable dans chaque fiche immobilisation
    # (route liste_mouvements retirée : template patrimoine/mouvements.html inexistant)    # ─── Contrats ──────────────────────────────────────────────────────────────
    path('contrats/',                           views.liste_contrats,        name='patrimoine_contrats'),
    path('contrats/<int:pk>/',                  views.detail_contrat,        name='patrimoine_contrat_detail'),
    path('echeancier-maintenance/',             views.echeancier_maintenance, name='patrimoine_echeancier_maintenance'),

    # ─── Interventions ─────────────────────────────────────────────────────────
    path('interventions/',                      views.liste_interventions,   name='patrimoine_interventions'),
    path('<int:immo_pk>/interventions/creer/',  views.creer_intervention,    name='patrimoine_creer_intervention'),
    path('interventions/<int:pk>/valider/',     views.valider_intervention,  name='patrimoine_valider_intervention'),
    path('intervention/<int:intervention_id>/', views.detail_intervention,   name='detail_intervention'),
    
    # Portail QR Code & Signalement
    path('signaler/<int:immo_id>/',             views.signaler_panne,        name='signaler_panne'),
    path('interventions/declarer/',             views.declarer_panne_pc,     name='patrimoine_declarer_panne_pc'),
   
    # ─── Portail prestataire ───────────────────────────────────────────────────
    path('portail/',                            views.portail_prestataire,   name='patrimoine_portail'),

    # ─── Import Excel ──────────────────────────────────────────────────────────
    path('import/',                             views.import_excel,          name='patrimoine_import'),
    path('import/template/<int:type_id>/',      views.telecharger_template,  name='patrimoine_template'),
    path('import/log/<int:pk>/',                views.detail_import_log,     name='patrimoine_import_log'),

    # ─── Paramètres ────────────────────────────────────────────────────────────
    path('parametres/',                         views.parametres,            name='patrimoine_parametres'),
    path('parametres/type/<int:pk>/schema/',    views.editer_schema,         name='patrimoine_editer_schema'),

    # ─── Utils & Outils ────────────────────────────────────────────────────────
    path('export/',                             views.export_registre_excel, name='patrimoine_export'),
    path('<int:pk>/etiquette/',                 views.etiquette_qr,          name='patrimoine_etiquette_qr'),
    path('parametres/type-equipement/nouveau/', views.creer_type_equipement, name='creer_type_equipement'),
    path('api/type-equipement/<int:type_id>/specs/', views.api_type_specs,   name='api_type_specs'),

    path('ajax/eclater-sas/',                   views.eclater_bien_sas,      name='patrimoine_eclater_sas'),
    path('sas/direct/',                         views.creer_immatriculation_directe, name='patrimoine_direct'),
    path('scan/<str:code>/',                    views.scan_mobile,           name='patrimoine_scan'),

    path('mes-tickets/',                        views.mes_tickets,           name='patrimoine_mes_tickets'),
    path('interventions/dispatch/',             views.dispatch_interventions,name='patrimoine_dispatch'),
    path('mes-interventions/',                  views.mes_interventions_tech,name='patrimoine_mes_interventions'),
    path('mes-demandes/ticket/<int:pk>/',       views.suivi_ticket,          name='patrimoine_suivi_ticket'),

    # ─── AJAX ──────────────────────────────────────────────────────────────────
    path('ajax/modeles/',                       views.ajax_modeles,          name='patrimoine_ajax_modeles'),
    path('ajax/specs-schema/',                  views.ajax_specs_schema,     name='patrimoine_ajax_specs'),
    path('ajax/vnc/<int:pk>/',                  views.ajax_vnc,              name='patrimoine_ajax_vnc'),
    path('ajax/quick-edit/<int:pk>/',           views.quick_edit,            name='patrimoine_quick_edit'),
    path('ajax/localisation/',                  views.ajax_localisation,     name='ajax_localisation'), 
    
    path('contrats/<int:contrat_id>/assigner-equipements/', views.assigner_equipements_contrat, name='patrimoine_assigner_equipements_contrat'),

    path('interventions/<int:pk>/bon-sortie/', views.imprimer_bon_sortie_reparation, name='patrimoine_imprimer_bon_sortie'),

    path('rapports/valeur-services/',      rapports.rapport_valeur_services,          name='patrimoine_rapport_valeurs'),
    path('rapports/valeur-services/csv/',  rapports.export_valeur_services_csv,        name='patrimoine_rapport_valeurs_csv'),
    path('rapports/valeur-services/detail-csv/', rapports.export_valeur_services_detail_csv, name='patrimoine_rapport_valeurs_detail_csv'),
    path('rapports/valeur-services/pdf/',  rapports.rapport_valeur_services_pdf,       name='patrimoine_rapport_valeurs_pdf'),
    path('inventaires/', views.patrimoine_campagnes_inventaire, name='patrimoine_campagnes_inventaire'),

path('inventaires/<int:campagne_id>/', views.detail_campagne_inventaire, name='patrimoine_detail_campagne'),

path('inventaires/<int:campagne_id>/scan/', views.audit_scan_inventaire, name='patrimoine_audit_scan'),

path('inventaires/<int:campagne_id>/fiche/', views.imprimer_fiche_comptage, name='imprimer_fiche_comptage'),path('rebuts/', views.registre_rebuts, name='patrimoine_rebuts'),


path('pertes/', views.registre_pertes, name='patrimoine_pertes'),


    # ═══════════════════════════════════════════════════════════
    # GESTION DES VÉHICULES
    # ═══════════════════════════════════════════════════════════
    path('vehicules/',                            views.liste_vehicules,           name='patrimoine_vehicules'),
    path('vehicules/creer/',                      views.creer_vehicule,            name='patrimoine_vehicule_creer'),
    path('vehicules/<int:pk>/',                   views.detail_vehicule,           name='patrimoine_vehicule_detail'),
    path('vehicules/<int:pk>/modifier/',          views.modifier_vehicule,         name='patrimoine_vehicule_modifier'),
    path('vehicules/<int:pk>/supprimer/',         views.supprimer_vehicule,        name='patrimoine_vehicule_supprimer'),
    path('vehicules/<int:vehicule_pk>/interventions/',    views.liste_interventions_vehicule,  name='patrimoine_vehicule_interventions'),
    path('vehicules/<int:vehicule_pk>/interventions/creer/', views.creer_intervention_vehicule, name='patrimoine_vehicule_intervention_creer'),
    path('vehicules/<int:vehicule_pk>/missions/',         views.liste_missions_vehicule,       name='patrimoine_vehicule_missions'),
    path('vehicules/<int:vehicule_pk>/missions/creer/',   views.creer_mission_vehicule,        name='patrimoine_vehicule_mission_creer'),
    path('ajax/vehicules/modeles/',               views.ajax_modeles_vehicule,     name='patrimoine_vehicule_ajax_modeles'),

    # ═══════════════════════════════════════════════════════════
    # GESTION DES SALLES DE CONFÉRENCE
    # ═══════════════════════════════════════════════════════════
    path('salles/',                               views.liste_salles,              name='patrimoine_salles'),
    path('salles/creer/',                         views.creer_salle,               name='patrimoine_salle_creer'),
    path('salles/<int:pk>/',                      views.detail_salle,              name='patrimoine_salle_detail'),
    path('salles/<int:pk>/modifier/',             views.modifier_salle,            name='patrimoine_salle_modifier'),
    path('salles/<int:pk>/supprimer/',            views.supprimer_salle,           name='patrimoine_salle_supprimer'),
    path('salles/calendrier/',                    views.calendrier_reservations,   name='patrimoine_calendrier'),
    path('salles/reservations/',                  views.liste_reservations,        name='patrimoine_reservations'),
    path('salles/reservations/creer/',            views.creer_reservation,         name='patrimoine_reservation_creer'),
    path('salles/reservations/<int:pk>/',         views.detail_reservation,        name='patrimoine_reservation_detail'),
    path('salles/reservations/<int:pk>/valider/',  views.valider_reservation,       name='patrimoine_reservation_valider'),
    path('salles/reservations/<int:pk>/annuler/',  views.annuler_reservation,       name='patrimoine_reservation_annuler'),
    path('ajax/salles/disponibilite/',            views.ajax_disponibilite_salle,  name='patrimoine_salle_ajax_dispo'),
    path('ajax/salles/reservations/',             views.ajax_reservations_salle,   name='patrimoine_salle_ajax_reservations'),
    path('ajax/salles/etages/',                   views.ajax_etages_salle,         name='patrimoine_salle_ajax_etages'),
    path('ajax/salles/bureaux/',                  views.ajax_bureaux_salle,        name='patrimoine_salle_ajax_bureaux'),

    # ═══════════════════════════════════════════════════════════
    # DEMANDES DE VÉHICULES (utilisateurs)
    # ═══════════════════════════════════════════════════════════
    path('demandes-vehicule/',                    views.mes_demandes_vehicule,       name='patrimoine_mes_demandes_vehicule'),
    path('demandes-vehicule/creer/',              views.creer_demande_vehicule,      name='patrimoine_demande_vehicule_creer'),
    path('demandes-vehicule/<int:pk>/',           views.detail_demande_vehicule,     name='patrimoine_detail_demande_vehicule'),
    path('demandes-vehicule/<int:pk>/annuler/',   views.annuler_demande_vehicule,    name='patrimoine_annuler_demande_vehicule'),
    path('demandes-vehicule/valider/',            views.demandes_vehicule_a_valider, name='patrimoine_demandes_vehicule_valider'),
    path('demandes-vehicule/<int:pk>/valider/',   views.valider_demande_vehicule,    name='patrimoine_valider_demande_vehicule'),

    # ═══════════════════════════════════════════════════════════
    # DEMANDES DE SALLES (utilisateurs)
    # ═══════════════════════════════════════════════════════════
    path('demandes-salle/',                       views.mes_demandes_salle,          name='patrimoine_mes_demandes_salle'),
    path('demandes-salle/creer/',                 views.creer_demande_salle,         name='patrimoine_demande_salle_creer'),
    path('demandes-salle/<int:pk>/',              views.detail_demande_salle,        name='patrimoine_detail_demande_salle'),
    path('demandes-salle/<int:pk>/annuler/',      views.annuler_demande_salle,       name='patrimoine_annuler_demande_salle'),
    path('demandes-salle/valider/',               views.demandes_salle_a_valider,    name='patrimoine_demandes_salle_valider'),
    path('demandes-salle/<int:pk>/valider/',      views.valider_demande_salle,       name='patrimoine_valider_demande_salle'),
]