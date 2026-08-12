# accounts/migrations/0002_menuaccess_permissions.py
# Generated manually to add menu_* permissions to MenuAccess

from django.db import migrations


def create_menu_permissions(apps, schema_editor):
    """Crée toutes les permissions menu_* en base."""
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')

    ct, _ = ContentType.objects.get_or_create(
        app_label='accounts',
        model='menuaccess'
    )

    MENU_ACCESS_PERMISSIONS = [
        ('menu_accueil', 'Accueil'),
        ('menu_dashboard', 'Tableau de bord'),
        ('menu_demandes', 'Demandes'),
        ('menu_valider_demandes', 'Valider Demandes'),
        ('menu_guichet', 'Guichet'),
        ('menu_livraisons', 'Livraisons'),
        ('menu_entrees', 'Entrées en Stock'),
        ('menu_reception_commande', 'Réceptions de commandes'),
        ('menu_sorties', 'Bons de Sortie'),
        ('menu_sorties_hors_stock', 'Sorties Hors Stock'),
        ('menu_retours_services', 'Retours Services'),
        ('menu_stock', 'État du Stock'),
        ('menu_peremptions', 'Péremptions'),
        ('menu_destructions', 'Destructions'),
        ('menu_ajustements', 'Ajustements'),
        ('menu_inventaires', 'Inventaires'),
        ('menu_historique', 'Historique'),
        ('menu_commandes', 'Commandes'),
        ('menu_articles', 'Articles'),
        ('menu_familles', 'Familles'),
        ('menu_fournisseurs', 'Fournisseurs'),
        ('menu_beneficiaires', 'Bénéficiaires'),
        ('menu_motifs_annulation', 'Motifs Annulation'),
        ('menu_magasins', 'Magasins'),
        ('menu_rapports', 'Rapports'),
        ('menu_stats_demandes', 'Stats Demandes'),
        ('menu_stats_sondages', 'Stats Sondages'),
        ('menu_pat_registre', 'Registre Patrimoine'),
        ('menu_pat_sas', "SAS (Zone d'attente)"),
        ('menu_pat_fiche_detail', 'Fiches Détaillées'),
        ('menu_pat_modifier_immo', 'Modifier Immobilisations'),
        ('menu_pat_mouvements', 'Mouvements Patrimoine'),
        ('menu_pat_eclatement', 'Éclatement Biens'),
        ('menu_pat_immatriculation', 'Immatriculation Directe'),
        ('menu_pat_qr_codes', 'Gestion QR Codes'),
        ('menu_pat_export_registre', 'Export Registre Excel'),
        ('menu_pat_import', 'Import Excel Patrimoine'),
        ('menu_pat_contrats', 'Contrats'),
        ('menu_pat_contrat_detail', 'Détail Contrats'),
        ('menu_pat_assigner_equipements', 'Assigner Équipements aux Contrats'),
        ('menu_pat_interventions', 'Interventions'),
        ('menu_pat_intervention_detail', 'Détail Interventions'),
        ('menu_pat_signaler_panne', 'Signaler Panne'),
        ('menu_pat_creer_intervention', 'Créer Intervention'),
        ('menu_pat_valider_intervention', 'Valider Intervention'),
        ('menu_pat_portail_prestataire', 'Portail Prestataire'),
        ('menu_pat_schema_maintenance', 'Schémas Maintenance'),
        ('menu_pat_types_equipements', "Types d'Équipements"),
        ('menu_pat_tickets', 'Tickets SAV'),
        ('menu_pat_mes_tickets', 'Mes Tickets'),
        ('menu_pat_dispatch', 'Dispatch Interventions'),
        ('menu_pat_tech', 'Espace Technicien'),
        ('menu_pat_suivi_ticket', 'Suivi Ticket'),
        ('menu_pat_bon_sortie_reparation', 'Bon Sortie Réparation'),
        ('menu_pat_inventaire', 'Inventaire Parc'),
        ('menu_pat_campagnes_inventaire', 'Campagnes Inventaire'),
        ('menu_pat_detail_campagne', 'Détail Campagne'),
        ('menu_pat_reconciliation', 'Réconciliation Inventaire'),
        ('menu_pat_audit_scan', 'Audit Scan Inventaire'),
        ('menu_pat_fiche_comptage', 'Fiche Comptage'),
        ('menu_pat_rebuts', 'Rebuts'),
        ('menu_pat_pertes', 'Pertes'),
        ('menu_pat_parametres', 'Paramètres Patrimoine'),
        ('menu_pat_historique', 'Historique Patrimoine'),
        ('menu_utilisateurs', 'Utilisateurs'),
        ('menu_roles', 'Rôles'),
        ('menu_param_admin', 'Paramètres Admin'),
        ('menu_param_logistique', 'Paramètres Logistique'),
        ('menu_circuits_validation', 'Circuits Validation'),
        ('menu_securite_mdp', 'Sécurité MDP'),
        ('menu_journal_audit', 'Journal Audit'),
        ('menu_parametres', 'Paramètres Système'),
        ('menu_services', 'Services'),
        ('menu_specialites', 'Spécialités'),
        ('menu_fonctions', 'Fonctions & Titres'),
        ('menu_modeles_pdf', 'Modèles de documents PDF'),
        ('menu_parametres_doc', 'Configuration Documents PDF'),
        ('menu_lots', 'Gestion des Lots'),
        ('menu_stats_satisfaction', 'Stats Satisfaction'),
    ]

    for code, label in MENU_ACCESS_PERMISSIONS:
        Permission.objects.get_or_create(
            content_type=ct,
            codename=code,
            defaults={'name': label}
        )


def remove_menu_permissions(apps, schema_editor):
    """Supprime les permissions menu_*."""
    Permission = apps.get_model('auth', 'Permission')
    ContentType = apps.get_model('contenttypes', 'ContentType')

    try:
        ct = ContentType.objects.get(app_label='accounts', model='menuaccess')
        Permission.objects.filter(content_type=ct, codename__startswith='menu_').delete()
    except ContentType.DoesNotExist:
        pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
        ('auth', '0012_alter_user_first_name_max_length'),
    ]

    operations = [
        migrations.RunPython(create_menu_permissions, remove_menu_permissions),
    ]
