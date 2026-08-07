# accounts/menus.py — DISPOSITION = SIDEBAR base_ui.html
from collections import OrderedDict

# Structure : Module → liste des liens (comme dans le sidebar)
ARCHITECTURE_MENU = OrderedDict([
    ('🏠 ACCUEIL & DASHBOARD', [
        'menu_accueil',
        'menu_dashboard',
    ]),

    ('🛒 DEMANDES', [
        'menu_demandes',
        'menu_valider_demandes',
    ]),

    ('🏪 OPÉRATIONS FLUX', [
        'menu_guichet',
        'menu_livraisons',
        'menu_entrees',
        'menu_reception_commande',
        'menu_sorties',
        'menu_sorties_hors_stock',
        'menu_retours_services',
    ]),

    ('📦 GESTION DES STOCKS', [
        'menu_stock',
        'menu_peremptions',
        'menu_destructions',
        'menu_ajustements',
        'menu_inventaires',
        'menu_historique',
    ]),

    ('🛍️ ACHATS & CATALOGUE', [
        'menu_commandes',
        'menu_articles',
        'menu_familles',
    ]),

    ('🏢 PATRIMOINE & SAV', [
        'menu_pat_tickets',
        'menu_pat_tech',
        'menu_pat_dispatch',
        'menu_pat_historique',
        'menu_pat_registre',
        'menu_pat_sas',
        'menu_pat_contrats',
        'menu_pat_import',
        'menu_pat_inventaire',
        'menu_pat_rebuts',
        'menu_pat_pertes',
        'menu_pat_parametres',
    ]),

    ('📈 RAPPORTS & EXPORTS', [
        'menu_rapports',
        'menu_stats_demandes',
        'menu_stats_sondages',
    ]),

    ('⚙️ PARAMÈTRES', [
        'menu_parametres',        
        'menu_magasins',
        'menu_services',
        'menu_specialites',
        'menu_fournisseurs',
        'menu_motifs_annulation',
        'menu_param_admin',
        'menu_parametres_doc',
        'menu_fonctions',
    ]),

    ('🛡️ SÉCURITÉ & ACCÈS', [
        'menu_utilisateurs',
        'menu_roles',
        'menu_circuits_validation',
        'menu_securite_mdp',
        'menu_journal_audit',
    ]),
])

# Métadonnées pour l'affichage (icônes + couleurs + labels lisibles)
MENU_ITEMS_META = {
    # Accueil
    'menu_accueil':              {'icon': 'fa-th-large',        'color': '#ffc107', 'label': 'Accueil'},
    'menu_dashboard':            {'icon': 'fa-chart-line',      'color': '#1c5b96', 'label': 'Tableau de bord'},

    # Demandes
    'menu_demandes':             {'icon': 'fa-clipboard-list',  'color': '#17a2b8', 'label': 'Demandes'},
    'menu_valider_demandes':     {'icon': 'fa-clipboard-check',   'color': '#ffc107', 'label': 'Valider Demandes'},

    # Opérations Flux
    'menu_guichet':              {'icon': 'fa-inbox',           'color': '#6f42c1', 'label': 'Traiter les Demandes (Guichet)'},
    'menu_livraisons':           {'icon': 'fa-dolly',           'color': '#cfabff', 'label': 'Livraisons'},
    'menu_entrees':              {'icon': 'fa-arrow-down',      'color': '#7fe799', 'label': 'Entrées en Stock'},
    'menu_reception_commande':   {'icon': 'fa-truck-loading',   'color': '#28a745', 'label': 'Réceptions de commandes'},
    'menu_sorties':              {'icon': 'fa-sign-out-alt',    'color': '#ff9e9e', 'label': 'Bons de Sortie'},
    'menu_sorties_hors_stock':   {'icon': 'fa-file-export',     'color': '#ffc58a', 'label': 'Sorties Hors Stock'},
    'menu_retours_services':     {'icon': 'fa-undo-alt',        'color': '#8be0ee', 'label': 'Retours Services'},

    # Gestion des Stocks
    'menu_stock':                {'icon': 'fa-search-location', 'color': '#1c5b96', 'label': 'État du Stock'},
    'menu_peremptions':          {'icon': 'fa-exclamation-triangle', 'color': '#ffda6a', 'label': 'Suivi Péremptions'},
    'menu_destructions':         {'icon': 'fa-trash-alt',       'color': '#ff9e9e', 'label': 'Destructions'},
    'menu_ajustements':          {'icon': 'fa-balance-scale',   'color': '#6f42c1', 'label': 'Ajustements Manuels'},
    'menu_inventaires':          {'icon': 'fa-clipboard-check', 'color': '#28a745', 'label': 'Campagnes Inventaires'},
    'menu_historique':           {'icon': 'fa-history',         'color': '#b6c2c9', 'label': 'Historique Mouvements'},

    # Achats & Catalogue
    'menu_commandes':            {'icon': 'fa-file-invoice-dollar', 'color': '#e83e8c', 'label': 'Commandes Fourn.'},
    'menu_articles':             {'icon': 'fa-list',            'color': '#0d47a1', 'label': 'Catalogue Articles'},
    'menu_familles':             {'icon': 'fa-tags',            'color': '#fd7e14', 'label': "Familles d'Articles"},

    # Patrimoine
    'menu_pat_tickets':          {'icon': 'fa-ticket-alt',      'color': '#20c997', 'label': 'Mes Tickets SAV'},
    'menu_pat_tech':             {'icon': 'fa-clipboard-list',  'color': '#6f42c1', 'label': 'Mon Espace Tech'},
    'menu_pat_dispatch':         {'icon': 'fa-satellite-dish',  'color': '#fd7e14', 'label': 'Dispatch Pannes'},
    'menu_pat_historique':       {'icon': 'fa-history',         'color': '#b6c2c9', 'label': 'Historique Global'},
    'menu_pat_registre':         {'icon': 'fa-layer-group',     'color': '#1c5b96', 'label': 'Registre Matériel'},
    'menu_pat_sas':              {'icon': 'fa-clock',           'color': '#ffc107', 'label': 'Sas Immatriculation'},
    'menu_pat_contrats':         {'icon': 'fa-file-contract',   'color': '#17a2b8', 'label': 'Contrats'},
    'menu_pat_import':           {'icon': 'fa-file-import',     'color': '#28a745', 'label': 'Import Excel'},
    'menu_pat_inventaire':       {'icon': 'fa-barcode',         'color': '#28a745', 'label': 'Inventaire du Parc'},
    'menu_pat_rebuts':           {'icon': 'fa-trash-alt',       'color': '#ef4444', 'label': 'Registre des Rebuts'},
    'menu_pat_pertes':           {'icon': 'fa-search-minus',    'color': '#f59e0b', 'label': 'Équipements Perdus'},
    'menu_pat_parametres':       {'icon': 'fa-sliders-h',       'color': '#ffda6a', 'label': 'Paramètres'},

    # Rapports
    'menu_rapports':             {'icon': 'fa-file-export',     'color': '#28a745', 'label': 'Exports CSV / PDF'},
    'menu_stats_demandes':       {'icon': 'fa-chart-bar',       'color': '#0d6efd', 'label': 'Stats Demandes'},
    'menu_stats_sondages':       {'icon': 'fa-smile',           'color': '#198754', 'label': 'Stats Sondages'},
    'menu_stats_satisfaction':   {'icon': 'fa-star-half-alt',     'color': '#6f42c1', 'label': 'Stats Satisfaction'},

    # Paramètres
    'menu_parametres':           {'icon': 'fa-cogs',            'color': '#6c757d', 'label': 'Configuration Système'},
    'menu_magasins':             {'icon': 'fa-store',           'color': '#ffc107', 'label': 'Magasins'},
    'menu_services':             {'icon': 'fa-hospital',        'color': '#28a745', 'label': 'Services'},
    'menu_specialites':          {'icon': 'fa-user-md',         'color': '#17a2b8', 'label': 'Spécialités'},
    'menu_fournisseurs':         {'icon': 'fa-truck-loading',   'color': '#fd7e14', 'label': 'Fournisseurs'},
    'menu_motifs_annulation':    {'icon': 'fa-ban',             'color': '#dc3545', 'label': 'Motifs Annulation'},
    'menu_modeles_pdf':          {'icon': 'fa-file-pdf',        'color': '#dc3545', 'label': 'Modèles de documents PDF'},
    'menu_param_admin':          {'icon': 'fa-building',        'color': '#6c757d', 'label': 'Config. Entreprise'},
    'menu_param_logistique':     {'icon': 'fa-users',           'color': '#6f42c1', 'label': 'Bénéficiaires (Destinataires Hors Stock)'},

    # Sécurité
    'menu_utilisateurs':         {'icon': 'fa-users',           'color': '#1c5b96', 'label': 'Utilisateurs'},
    'menu_roles':                {'icon': 'fa-user-shield',     'color': '#0d47a1', 'label': 'Rôles & Permissions'},
    'menu_circuits_validation':  {'icon': 'fa-project-diagram', 'color': '#6f42c1', 'label': 'Circuits Validation'},
    'menu_journal_audit':        {'icon': 'fa-user-secret',     'color': '#dc3545', 'label': 'Journal & Audit'},

}

# Icônes des modules (comme les module-title du sidebar)
MODULE_ICONS = {
    '🏠 ACCUEIL & DASHBOARD': 'fa-th-large',
    '🛒 DEMANDES': 'fa-clipboard-list',
    '🏪 OPÉRATIONS FLUX': 'fa-exchange-alt',
    '📦 GESTION DES STOCKS': 'fa-boxes',
    '🛍️ ACHATS & CATALOGUE': 'fa-shopping-cart',
    '🏢 PATRIMOINE & SAV': 'fa-building',
    '📈 RAPPORTS & EXPORTS': 'fa-chart-pie',
    '⚙️ PARAMÈTRES': 'fa-cogs',
    '🛡️ SÉCURITÉ & ACCÈS': 'fa-shield-alt',
}

# ==========================================================
# 🎯 STRUCTURE pour la modale Rôles (reflète le sidebar)
# ==========================================================
ROLE_ARCHITECTURE_MENU = OrderedDict([
    ('🏠 ACCUEIL & DASHBOARD', ['menu_accueil', 'menu_dashboard']),
    ('🛒 DEMANDES', ['menu_demandes', 'menu_valider_demandes']),
    ('🏪 OPÉRATIONS FLUX', ['menu_guichet', 'menu_livraisons', 'menu_entrees', 'menu_reception_commande', 'menu_sorties', 'menu_sorties_hors_stock', 'menu_retours_services']),
    ('📦 GESTION DES STOCKS', ['menu_stock', 'menu_peremptions', 'menu_lots', 'menu_destructions', 'menu_ajustements', 'menu_inventaires', 'menu_historique']),
    ('🛍️ ACHATS & CATALOGUE', ['menu_commandes', 'menu_articles', 'menu_familles']),
    ('🏢 PATRIMOINE & SAV', OrderedDict([
        ('SAV', ['menu_pat_tickets', 'menu_pat_tech', 'menu_pat_dispatch', 'menu_pat_historique']),
        ('Gestion du Parc', [
            'menu_pat_registre', 'menu_pat_sas', 'menu_pat_contrats', 'menu_pat_import',
            'menu_pat_inventaire', 'menu_pat_rebuts', 'menu_pat_pertes', 'menu_pat_parametres',
            'menu_pat_fiche_detail', 'menu_pat_modifier_immo', 'menu_pat_mouvements',
            'menu_pat_eclatement', 'menu_pat_immatriculation', 'menu_pat_qr_codes',
            'menu_pat_export_registre', 'menu_pat_contrat_detail', 'menu_pat_assigner_equipements',
            'menu_pat_interventions', 'menu_pat_intervention_detail', 'menu_pat_signaler_panne',
            'menu_pat_creer_intervention', 'menu_pat_valider_intervention', 'menu_pat_portail_prestataire',
            'menu_pat_schema_maintenance', 'menu_pat_types_equipements', 'menu_pat_mes_tickets',
            'menu_pat_suivi_ticket', 'menu_pat_bon_sortie_reparation', 'menu_pat_campagnes_inventaire',
            'menu_pat_detail_campagne', 'menu_pat_reconciliation', 'menu_pat_audit_scan',
            'menu_pat_fiche_comptage'
        ]),
    ])),
    ('📈 RAPPORTS & EXPORTS', ['menu_rapports', 'menu_stats_demandes', 'menu_stats_sondages']),
    ('⚙️ PARAMÈTRES', OrderedDict([
        ('Administratifs', ['menu_param_admin', 'menu_services', 'menu_specialites', 'menu_fonctions', 'menu_parametres']),
        ('Logistique', ['menu_param_logistique', 'menu_magasins', 'menu_fournisseurs', 'menu_beneficiaires', 'menu_motifs_annulation', 'menu_modeles_pdf', 'menu_parametres_doc']),
        ('Stock', ['menu_lots']),
    ])),
    ('🛡️ SÉCURITÉ & ACCÈS', ['menu_utilisateurs', 'menu_roles', 'menu_circuits_validation', 'menu_securite_mdp', 'menu_journal_audit']),
])


def flatten_role_permissions(role_architecture):
    """Aplatit ROLE_ARCHITECTURE_MENU en liste simple de codenames."""
    result = []
    for perms in role_architecture.values():
        if isinstance(perms, dict):
            for sublist in perms.values():
                result.extend(sublist)
        else:
            result.extend(perms)
    return result
