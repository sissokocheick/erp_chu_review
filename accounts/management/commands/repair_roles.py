# accounts/management/commands/repair_roles.py
from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group
from accounts.models import Entreprise, RoleEntreprise

class Command(BaseCommand):
    help = "Répare les RoleEntreprise manquants"

    def handle(self, *args, **options):
        for grp in Group.objects.all():
            if '@' in grp.name:
                slug = grp.name.split('@')[-1]
                entreprise = Entreprise.objects.filter(slug__iexact=slug).first()
                if entreprise and not hasattr(grp, 'roleentreprise'):
                    RoleEntreprise.objects.create(groupe=grp, entreprise=entreprise)
                    self.stdout.write(self.style.SUCCESS(f"Réparé : {grp.name}"))