from django.urls import path
from . import views

urlpatterns = [

    # ─── Registre / Sas ────────────────────────────────────────────────────────
    path('',                                    views.registre,              name='patrimoine_registre'),
    path('sas/',                                views.sas,                   name='patrimoine_sas'),

    # ─── Fiche détail ──────────────────────────────────────────────────────────
    path('<int:pk>/',                           views.fiche_detail,          name='patrimoine_detail'),
    path('<int:pk>/modifier/',                  views.modifier_immo,         name='patrimoine_modifier'),
    path('<int:pk>/valider-sas/',               views.valider_sas,           name='patrimoine_valider_sas'),

    # ─── Mouvements ────────────────────────────────────────────────────────────
    path('<int:pk>/mouvement/',                 views.creer_mouvement,       name='patrimoine_mouvement'),
    path('mouvements/',                         views.liste_mouvements,      name='patrimoine_mouvements'),

    # ─── Contrats ──────────────────────────────────────────────────────────────
    path('contrats/',                           views.liste_contrats,        name='patrimoine_contrats'),
    path('contrats/<int:pk>/',                  views.detail_contrat,        name='patrimoine_contrat_detail'),

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
    
    path('contrats/<int:pk>/assigner-equipements/', views.assigner_equipements_contrat, name='patrimoine_assigner_equipements_contrat'),

    path('interventions/<int:pk>/bon-sortie/', views.imprimer_bon_sortie_reparation, name='patrimoine_imprimer_bon_sortie'),


path('inventaires/', views.patrimoine_campagnes_inventaire, name='patrimoine_campagnes_inventaire'),

path('inventaires/<int:campagne_id>/', views.detail_campagne_inventaire, name='patrimoine_detail_campagne'),

path('inventaires/<int:campagne_id>/scan/', views.audit_scan_inventaire, name='patrimoine_audit_scan'),

path('inventaires/<int:campagne_id>/fiche/', views.imprimer_fiche_comptage, name='imprimer_fiche_comptage'),

path('rebuts/', views.registre_rebuts, name='patrimoine_rebuts'),

path('pertes/', views.registre_pertes, name='patrimoine_pertes'),

]