# -*- coding: utf-8 -*-
"""
Management command : génère les campagnes d'inventaire tournant dont
l'échéance est atteinte (plan ACTIF + prochaine_echeance <= aujourd'hui).

Usage :
    python manage.py generer_inventaires_tournants
    python manage.py generer_inventaires_tournants --dry-run

C'est le mécanisme de planification automatique : branché en tâche
planifiée (cron/Windows Task Scheduler) ou déclenché à la connexion
(voir accounts.views.custom_login -> _generer_tournants_a_echeance).
"""
from django.core.management.base import BaseCommand

from stock.models import PlanInventaireTournant
from stock.services.inventaire_service import InventaireService


class Command(BaseCommand):
    help = "Génère les campagnes d'inventaire tournant dont l'échéance est atteinte."

    def add_arguments(self, parser):
        parser.add_argument(
            '--dry-run', action='store_true',
            help='Affiche les plans échus sans générer de campagne.')

    def handle(self, *args, **options):
        dry_run = options.get('dry_run')
        from django.utils import timezone

        aujourdhui = timezone.now().date()
        plans_echus = PlanInventaireTournant.objects.filter(
            statut='ACTIF',
            prochaine_echeance__lte=aujourdhui,
        ).select_related('magasin')

        generes = 0
        echecs = 0
        for plan in plans_echus:
            if dry_run:
                self.stdout.write(
                    f"  [dry-run] Échu : {plan.titre} (magasin {plan.magasin.nom}, "
                    f"échéance {plan.prochaine_echeance})")
                continue
            try:
                campagne = InventaireService.generer_campagne_tournante(
                    plan, None)
                generes += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  ✅ Campagne '{campagne.titre}' générée "
                        f"({campagne.lignes_inventaire.count()} article(s))."))
            except Exception as e:
                echecs += 1
                self.stderr.write(
                    self.style.ERROR(
                        f"  ❌ Échec pour '{plan.titre}' : {e}"))

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry-run : {plans_echus.count()} plan(s) échu(s) détecté(s)."))
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Terminé : {generes} campagne(s) générée(s), "
                    f"{echecs} échec(s), {plans_echus.count()} plan(s) échu(s)."))
