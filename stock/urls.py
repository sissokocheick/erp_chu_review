from django.urls import path, include, reverse_lazy
from django.views.generic import RedirectView


from .views import (
    dashboard, catalogue, commandes, demandes, parametres, rapports, api,
)
from .views.entrees import (
    liste_entrees, annuler_entree, apercu_bon_entree,
    remplacer_scan_entree,
)
from .views.sorties import (
    liste_sorties, annuler_sortie, valider_bon_sortie,
    remplacer_scan_sortie,
)
from .views.retours import (
    liste_retours_services, apercu_bon_retour,
)
from .views.hors_stock import (
    liste_bons_hors_stock, annuler_bon_hors_stock,
    apercu_bon_hors_stock,
)
from .views.ajustements import (
    liste_ajustements, rejeter_ajustement, valider_ajustement,
)
from .views.validation_bons import valider_bon
from .views.inventaires import (
    liste_inventaires, saisir_inventaire,
    api_sauvegarder_ligne_inventaire,
    liste_plans_inventaire_tournant,
    generer_campagne_tournante,
    basculer_statut_plan,
)
from .views.livraisons import liste_livraisons, detail_livraisons_demande
from .views.peremptions import (
    controle_peremptions, retirer_lot_perime,
)
from .views.stock import etat_stock
from .views.historique import journal_historique
from .views.lots import api_lots_disponibles
from .views.utils import changer_magasin

# ═════════════════════════════════════════════════════════════════════════════
# VUES D'IMPRESSION PDF — CENTRALISÉES dans pdf_views.py
# ═════════════════════════════════════════════════════════════════════════════
from .views.pdf_views import (
    imprimer_bon_multi_lignes,
    bon_entree_pdf,
    imprimer_commande,
    imprimer_bon_demande,
    imprimer_ajustement,
    imprimer_etat_stock,
    imprimer_historique_article,
    imprimer_fiche_comptage,
    imprimer_resultat_inventaire,
    rapport_consommation_pdf,
    imprimer_bon_hors_stock,
)


urlpatterns = [

    # ═══════════════════════════════════════════════════════════════════════
    # DASHBOARD
    # ═══════════════════════════════════════════════════════════════════════
    path('', dashboard.dashboard_directeur, name='dashboard_directeur'),

    # ═══════════════════════════════════════════════════════════════════════
    # CATALOGUE
    # ═══════════════════════════════════════════════════════════════════════
    path('articles/', catalogue.liste_articles, name='liste_articles'),
    path('articles/<int:article_id>/historique/', catalogue.historique_article, name='historique_article'),
    path('api/verifier-article/', catalogue.verifier_article, name='verifier_article'),
    path('familles/', catalogue.liste_familles, name='liste_familles'),

    # ═══════════════════════════════════════════════════════════════════════
    # ENTRÉES
    # ═══════════════════════════════════════════════════════════════════════
    path('entrees/', liste_entrees, name='liste_entrees'),
    path('entrees/<int:bon_id>/annuler/', annuler_entree, name='annuler_entree'),
    path('entrees/apercu/<int:bon_id>/', apercu_bon_entree, name='apercu_bon_entree'),
    path('entrees/<int:bon_id>/pdf/', bon_entree_pdf, name='bon_entree_pdf'),
    path('entrees/<int:bon_id>/remplacer-scan/', remplacer_scan_entree, name='remplacer_scan_entree'),

    # ═══════════════════════════════════════════════════════════════════════
    # SORTIES
    # ═══════════════════════════════════════════════════════════════════════
    path('sorties/', liste_sorties, name='liste_sorties'),
    path('sorties/<int:bon_id>/annuler/', annuler_sortie, name='annuler_sortie'),
    path('sorties/valider/<int:bon_id>/', valider_bon_sortie, name='valider_bon_sortie'),
    path('sorties/<int:bon_id>/scan/', remplacer_scan_sortie, name='remplacer_scan_sortie'),
    # Validation générique pour tous les types de bons
    path('bons/<int:bon_id>/valider/', valider_bon, name='valider_bon'),

    # ═══════════════════════════════════════════════════════════════════════
    # IMPRESSION MULTI-TYPES (BS, BE, BR, BSHS)
    # ═══════════════════════════════════════════════════════════════════════
    path('bon/<int:bon_id>/imprimer/', imprimer_bon_multi_lignes, name='imprimer_bon_multi_lignes'),

    # ═══════════════════════════════════════════════════════════════════════
    # RETOURS SERVICES
    # ═══════════════════════════════════════════════════════════════════════
    path('stock/retours-services/', liste_retours_services, name='liste_retours_services'),
    path('retours-services/apercu/<int:bon_id>/', apercu_bon_retour, name='apercu_bon_retour'),
    path('stock/retours-services/imprimer/<int:bon_id>/', imprimer_bon_multi_lignes, name='imprimer_bon_retour'),

    # ═══════════════════════════════════════════════════════════════════════
    # AJUSTEMENTS
    # ═══════════════════════════════════════════════════════════════════════
    path('ajustements/', liste_ajustements, name='liste_ajustements'),
    path('ajustements/imprimer/<int:ajustement_id>/', imprimer_ajustement, name='imprimer_ajustement'),
    path('ajustements/<int:ajustement_id>/valider/', valider_ajustement, name='valider_ajustement'),
    path('ajustements/<int:ajustement_id>/rejeter/', rejeter_ajustement, name='rejeter_ajustement'),

    # ═══════════════════════════════════════════════════════════════════════
    # INVENTAIRES
    # ═══════════════════════════════════════════════════════════════════════
    path('inventaires/', liste_inventaires, name='liste_inventaires'),
    path('inventaires/<int:campagne_id>/fiche/', imprimer_fiche_comptage, name='imprimer_fiche_comptage_stock'),
    path('inventaires/<int:campagne_id>/resultat/', imprimer_resultat_inventaire, name='imprimer_resultat_inventaire'),
    path('inventaires/<int:campagne_id>/saisir/', saisir_inventaire, name='saisir_inventaire'),
    # API AJAX inventaire (sauvegarde ligne par ligne)
    path('inventaire/<int:campagne_id>/api/sauvegarder-ligne/', api_sauvegarder_ligne_inventaire, name='api_sauvegarder_ligne_inventaire'),
    # Inventaire tournant (rotation par famille/zone)
    path('inventaires/tournants/', liste_plans_inventaire_tournant, name='liste_plans_inventaire_tournant'),
    path('inventaires/tournants/<int:plan_id>/generer/', generer_campagne_tournante, name='generer_campagne_tournante'),
    path('inventaires/tournants/<int:plan_id>/statut/', basculer_statut_plan, name='basculer_statut_plan'),

    # ═══════════════════════════════════════════════════════════════════════
    # ÉTAT DU STOCK
    # ═══════════════════════════════════════════════════════════════════════
    path('etat-stock/', etat_stock, name='etat_stock'),
    path('etat-stock/imprimer/', imprimer_etat_stock, name='imprimer_etat_stock'),
    path('article/<int:article_id>/imprimer/', imprimer_historique_article, name='imprimer_historique_article'),

    # ═══════════════════════════════════════════════════════════════════════
    # HISTORIQUE
    # ═══════════════════════════════════════════════════════════════════════
    path('administration/historique/', journal_historique, name='journal_historique'),

    # ═══════════════════════════════════════════════════════════════════════
    # BONS HORS STOCK
    # ═══════════════════════════════════════════════════════════════════════
    path('bons/hors-stock/', liste_bons_hors_stock, name='liste_bons_hors_stock'),
    path('bons/hors-stock/<int:bon_id>/apercu/', apercu_bon_hors_stock, name='apercu_bon_hors_stock'),
    path('bons/hors-stock/<int:bon_id>/imprimer/', imprimer_bon_hors_stock, name='imprimer_bon_hors_stock'),
    path('bons/hors-stock/<int:bon_id>/annuler/', annuler_bon_hors_stock, name='annuler_bon_hors_stock'),

    # ═══════════════════════════════════════════════════════════════════════
    # PÉREMPTIONS & DESTRUCTIONS
    # ═══════════════════════════════════════════════════════════════════════
    path('stock/peremptions/', controle_peremptions, name='controle_peremptions'),
    path('stock/peremptions/retirer/<int:mouvement_id>/', retirer_lot_perime, name='retirer_lot_perime'),
    path('stock/peremptions/historique/', RedirectView.as_view(url='/stock/peremptions/?onglet=destruction', permanent=False), name='historique_destructions'),

    # ═══════════════════════════════════════════════════════════════════════
    # LIVRAISONS
    # ═══════════════════════════════════════════════════════════════════════
    path('livraisons/', liste_livraisons, name='liste_livraisons'),
    path('demandes/<int:demande_id>/livraisons/', detail_livraisons_demande, name='detail_livraisons_demande'),

    # ═══════════════════════════════════════════════════════════════════════
    # LOTS
    # ═══════════════════════════════════════════════════════════════════════
    path('lots/', RedirectView.as_view(url='/stock/peremptions/?onglet=lots', permanent=False), name='liste_lots'),
    path('api/lots/<int:article_id>/<int:magasin_id>/', api_lots_disponibles, name='api_lots_disponibles'),

    # ═══════════════════════════════════════════════════════════════════════
    # UTILITAIRES
    # ═══════════════════════════════════════════════════════════════════════
    path('changer-magasin/', changer_magasin, name='changer_magasin'),

    # ═══════════════════════════════════════════════════════════════════════
    # COMMANDES
    # ═══════════════════════════════════════════════════════════════════════
    path('commandes/', commandes.liste_commandes, name='liste_commandes'),
    path('commande/<int:commande_id>/imprimer/', imprimer_commande, name='imprimer_commande'),
    path('commande/<int:commande_id>/receptionner/', commandes.receptionner_commande, name='receptionner_commande'),
    path('commande/<int:commande_id>/valider/', commandes.valider_commande, name='valider_commande'),
    path('commandes/<int:commande_id>/supprimer/', commandes.supprimer_commande, name='supprimer_commande'),
    path('commandes/<int:commande_id>/solder/', commandes.solder_commande, name='solder_commande'),
    path('commandes/<int:commande_id>/modifier/', commandes.modifier_commande, name='modifier_commande'),
    path('receptions/', commandes.liste_receptions, name='liste_receptions'),
    path('receptions/joindre/<int:commande_id>/', commandes.joindre_bon_livraison, name='joindre_bon_livraison'),
    path('receptions/remplacer-bl/<int:bon_id>/', commandes.remplacer_bon_livraison, name='remplacer_bon_livraison'),
    path('voir-bon-livraison/<int:bon_id>/', commandes.voir_bon_livraison, name='voir_bon_livraison'),

    # ═══════════════════════════════════════════════════════════════════════
    # DEMANDES
    # ═══════════════════════════════════════════════════════════════════════
    path('mes-demandes/', demandes.mes_demandes, name='mes_demandes'),
    path('demande/<int:demande_id>/pdf/', imprimer_bon_demande, name='imprimer_bon_demande'),
    path('mes-demandes/annuler/<int:demande_id>/', demandes.annuler_demande, name='annuler_demande'),
    path('gestion-demandes/', demandes.gestion_demandes, name='gestion_demandes'),
    path('gestion-demandes/valider/<int:demande_id>/', demandes.valider_traitement_demande, name='valider_traitement_demande'),
    path('demandes/<int:demande_id>/statut/', demandes.api_statut_demande, name='api_statut_demande'),
    path('demandes/<int:demande_id>/cloturer/', demandes.cloturer_demande, name='cloturer_demande'),
    path('accuses/<int:accuse_id>/signer/', demandes.signer_accuse_reception, name='signer_accuse_reception'),
    path('valider-demandes/', demandes.demandes_a_valider, name='demandes_a_valider'),

    # ═══════════════════════════════════════════════════════════════════════
    # PARAMÈTRES
    # ═══════════════════════════════════════════════════════════════════════
    path('parametres/logistique/', parametres.parametres_logistique, name='parametres_logistique'),
    path('parametres/administratifs/', parametres.parametres_administratifs, name='parametres_administratifs'),
    path('parametres/notifications/', parametres.parametres_notifications, name='parametres_notifications'),
    path('parametres/supprimer/<str:type_entite>/<int:id_entite>/', parametres.supprimer_parametre, name='supprimer_parametre'),
    # NB: motifs d'annulation, circuits de validation et journal d'audit sont gérés
    # respectivement dans parametres_logistique et dans accounts (menu Sécurité & Accès).
    path('magasins/<int:magasin_id>/parametres/', parametres.parametres_magasin, name='parametres_magasin'),

    # ═══════════════════════════════════════════════════════════════════════
    # RAPPORTS & STATS
    # ═══════════════════════════════════════════════════════════════════════
    path('rapports/', rapports.page_rapports, name='page_rapports'),
    path('stock/rapports/consommation/pdf/', rapport_consommation_pdf, name='rapport_consommation_pdf'),
    path('rapports/export-stock/', rapports.export_stock_excel, name='export_stock_excel'),
    path('rapports/export-commandes/', rapports.export_commandes_excel, name='export_commandes_excel'),
    path('stats/demandes/', rapports.stats_demandes, name='stats_demandes'),
    path('stats/sondages/', rapports.stats_sondages, name='stats_sondages'),
    path('api-details-stats/', rapports.api_details_stats, name='api_details_stats'),
    path('api-detail-demande/<int:demande_id>/', rapports.api_detail_demande, name='api_detail_demande'),
    path('api-details-sondages/', rapports.api_details_sondages, name='api_details_sondages'),
    path('export/sondages/csv/', rapports.export_sondages_csv, name='export_sondages_csv'),
    path('export-mouvements/', rapports.export_mouvements_excel, name='export_mouvements_excel'),
    path('export-articles/', rapports.export_articles_excel, name='export_articles_excel'),

    # ═══════════════════════════════════════════════════════════════════════
    # NOUVEAU : Satisfaction par Service
    # ═══════════════════════════════════════════════════════════════════════
    path('stats/satisfaction-services/', rapports.stats_satisfaction_services, name='stats_satisfaction_services'),

    # ═══════════════════════════════════════════════════════════════════════
    # API / NOTIFICATIONS / UPLOAD
    # ═══════════════════════════════════════════════════════════════════════
    path('notifications/', api.liste_notifications, name='liste_notifications'),
    path('notifications/api/', api.api_notifications, name='api_notifications'),
    path('notifications/<int:notif_id>/lue/', api.marquer_notification_lue, name='marquer_notification_lue'),
    path('notifications/<int:notif_id>/supprimer/', api.supprimer_notification, name='supprimer_notification'),
    path('notifications/tout-effacer/', api.tout_effacer_notifications, name='tout_effacer_notifications'),
    path('upload/<str:app_label>/<str:model_name>/<int:obj_id>/<str:field_name>/', api.upload_fichier_generique, name='upload_fichier_generique'),
    # API liste articles (pour inventaire personnalisé)
    path('api/articles/', api.api_articles_json, name='api_articles_json'),

    # ═══════════════════════════════════════════════════════════════════════
    # SÉCURITÉ / AUDIT
    # ═══════════════════════════════════════════════════════════════════════


    # ═══════════════════════════════════════════════════════════════════════
    # ALIAS D'URLS ACCOUNTS (compatibilité templates stock sans namespace)
    # ═══════════════════════════════════════════════════════════════════════
    path('accueil/', RedirectView.as_view(url=reverse_lazy('accounts:accueil_personnalise')), name='accueil_personnalise'),

    path('', include('stock.urls_pdf_config')),
]
