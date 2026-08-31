"""
Management command: initialise les roles/groups avec les bonnes permissions.
Usage: python manage.py init_roles
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, Permission

ROLE_DEFS = {
    'Administrateur': {
        'description': 'Tous les droits',
        'perms': ['menu_'],  # all menu_ permissions
    },
    'Magasinier': {
        'description': 'Gestion du stock quotidien',
        'perms': [
            'menu_accueil', 'menu_dashboard',
            'menu_demandes', 'menu_guichet',
            'menu_entrees', 'menu_reception_commande',
            'menu_sorties', 'menu_sorties_hors_stock',
            'menu_retours_services', 'menu_retours_fournisseurs',
            'menu_transferts', 'menu_livraisons',
            'menu_stock', 'menu_peremptions', 'menu_destructions',
            'menu_ajustements', 'menu_inventaires', 'menu_historique',
            'menu_articles', 'menu_familles', 'menu_fournisseurs',
            'menu_beneficiaires', 'menu_lots',
            'menu_motifs_annulation',
        ],
    },
    'Responsable Stock': {
        'description': 'Validation et suivi du stock',
        'perms': [
            'menu_accueil', 'menu_dashboard',
            'menu_valider_demandes', 'menu_commandes',
            'menu_stock', 'menu_ajustements', 'menu_inventaires',
            'menu_historique', 'menu_peremptions',
            'menu_rapports', 'menu_stats_demandes', 'menu_stats_sondages',
            'menu_stats_satisfaction',
            'menu_lots',
        ],
    },    'Directeur': {
        'description': 'Direction, audit, rapports, validation véhicules/salles',
        'perms': [
            'menu_accueil', 'menu_dashboard', 'menu_stock', 'menu_historique',
            'menu_rapports', 'menu_stats_demandes', 'menu_stats_sondages', 'menu_stats_satisfaction',
            'menu_journal_audit', 'menu_pat_registre', 'menu_pat_historique', 'menu_pat_contrats',
            'menu_param_admin', 'menu_parametres',
            'menu_pat_vehicules', 'menu_pat_vehicules_valider',
            'menu_pat_salles', 'menu_pat_salles_valider', 'menu_pat_salles_calendrier',
        ],
    },    'Technicien SAV': {
        'description': 'Maintenance et interventions terrain',
        'perms': [
            'menu_accueil', 'menu_dashboard', 'menu_pat_tickets', 'menu_pat_mes_tickets',
            'menu_pat_tech', 'menu_pat_dispatch', 'menu_pat_interventions', 'menu_pat_intervention_detail',
            'menu_pat_signaler_panne', 'menu_pat_creer_intervention', 'menu_pat_suivi_ticket', 'menu_pat_bon_sortie_reparation',
            'menu_pat_inventaire', 'menu_pat_fiche_comptage', 'menu_pat_qr_codes', 'menu_pat_portail_prestataire',
            'menu_pat_valider_intervention', 'menu_pat_vehicules', 'menu_pat_vehicules_interventions',
        ],
    },
    'Gestionnaire Patrimoine': {
        'description': 'Registre, contrats, inventaires, vehicules, salles, parametres',
        'perms': ['menu_accueil', 'menu_dashboard', 'menu_pat_'],
    },
    'Comptable': {
        'description': 'Registre immobilisations, amortissements, exports',
        'perms': [
            'menu_accueil', 'menu_dashboard',
            'menu_pat_registre', 'menu_pat_fiche_detail',
            'menu_pat_modifier_immo', 'menu_pat_mouvements',
            'menu_pat_eclatement', 'menu_pat_immatriculation',
            'menu_pat_export_registre', 'menu_pat_import',
            'menu_pat_contrats', 'menu_pat_contrat_detail',
            'menu_pat_historique',
        ],
    },
    'Auditeur': {
        'description': 'Consultation, audits, historique',
        'perms': [
            'menu_accueil', 'menu_dashboard',
            'menu_pat_registre', 'menu_pat_historique',
            'menu_stock', 'menu_historique',
            'menu_rapports', 'menu_stats_demandes', 'menu_journal_audit',
        ],
    },
}


class Command(BaseCommand):
    help = 'Initialise les roles standard avec leurs permissions'

    def add_arguments(self, parser):
        parser.add_argument('--fix-test', action='store_true',
                            help='Complete aussi le groupe TEST avec toutes les perms')

    def handle(self, *args, **options):
        all_menu = Permission.objects.filter(codename__startswith='menu_')

        for name, def_ in ROLE_DEFS.items():
            group, created = Group.objects.get_or_create(name=name)
            perms_to_add = []
            for prefix in def_['perms']:
                if prefix == 'menu_':
                    perms_to_add.extend(all_menu)
                else:
                    perms_to_add.extend(all_menu.filter(codename__startswith=prefix))
            group.permissions.add(*perms_to_add)
            count = group.permissions.filter(codename__startswith='menu_').count()
            tag = 'CREATED' if created else 'UPDATED'
            self.stdout.write(self.style.SUCCESS(
                f'[{tag}] {name}: {count} menu perms ({", ".join(def_["perms"][:4])}...)'
            ))

        if options['fix_test']:
            test = Group.objects.get(name='TEST')
            test.permissions.add(*all_menu)
            self.stdout.write('[FIX] TEST: toutes les perms ajoutees')

        self.stdout.write(f'\n{len(ROLE_DEFS)} roles synchronises.')
