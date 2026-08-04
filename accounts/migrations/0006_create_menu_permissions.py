# Generated manually — creates missing menu_ permissions for django.contrib.auth
from django.db import migrations
from django.contrib.auth.models import Permission
from django.contrib.contenttypes.models import ContentType


MENU_PERMISSIONS = {
    'menu_dashboard': 'Tableau de bord',
    'menu_accueil': 'Accueil',
    'menu_demandes': 'Mes Demandes',
    'menu_guichet': 'Traiter Demandes',
    'menu_entrees': 'Entrées Stock',
    'menu_sorties': 'Bons de Sortie',
    'menu_retours_services': 'Retours Services',
    'menu_sorties_hors_stock': 'Sorties Hors Stock',
    'menu_stock': 'État du Stock',
    'menu_peremptions': 'Péremptions',
    'menu_destructions': 'Destructions',
    'menu_ajustements': 'Ajustements',
    'menu_inventaires': 'Inventaires',
    'menu_articles': 'Catalogue Articles',
    'menu_familles': 'Familles',
    'menu_commandes': 'Commandes',
    'menu_reception_commande': 'Réceptions',
    'menu_livraisons': 'Livraisons',
    'menu_rapports': 'Rapports',
    'menu_historique': 'Historique',
    'menu_magasins': 'Magasins',
    'menu_fournisseurs': 'Fournisseurs',
    'menu_motifs_annulation': 'Motifs Annulation',
    'menu_param_logistique': 'Param. Logistique',
    'menu_services': 'Services',
    'menu_specialites': 'Spécialités',
    'menu_param_admin': 'Param. Admin',
    'menu_fonctions': 'Fonctions',
    'menu_utilisateurs': 'Utilisateurs',
    'menu_roles': 'Rôles & Accès',
    'menu_circuits_validation': 'Circuits Validation',
    'menu_journal_audit': 'Journal Audit',
    'menu_pat_tickets': 'Patrimoine & SAV',
}


def create_menu_permissions(apps, schema_editor):
    """Crée les permissions menu_ manquantes sur le modèle Profil (accounts)."""
    Profil = apps.get_model('accounts', 'Profil')
    ct = ContentType.objects.get_for_model(Profil)

    for codename, label in MENU_PERMISSIONS.items():
        Permission.objects.get_or_create(
            codename=codename,
            content_type=ct,
            defaults={'name': label}
        )


def delete_menu_permissions(apps, schema_editor):
    """Reverse : supprime les permissions menu_ (attention)."""
    Profil = apps.get_model('accounts', 'Profil')
    ct = ContentType.objects.get_for_model(Profil)
    Permission.objects.filter(content_type=ct, codename__startswith='menu_').delete()


class Migration(migrations.Migration):
    dependencies = [
        ('accounts', '0005_configsecurite'),  # ← ADAPTE si ton nom de migration 0001 est différent
    ]

    operations = [
        migrations.RunPython(
            create_menu_permissions,
            reverse_code=delete_menu_permissions,
        ),
    ]
