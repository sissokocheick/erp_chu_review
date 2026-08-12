# -*- coding: utf-8 -*-
# accounts/management/commands/repair_roles.py
"""
Commande de maintenance pour réparer/créer les permissions manquantes.
Mono-tenant : les rôles sont des Group Django globaux.
"""
from django.core.management.base import BaseCommand
from django.contrib.auth.models import Permission, Group
from django.contrib.contenttypes.models import ContentType
from accounts.models import MenuAccess, MENU_ACCESS_PERMISSIONS


class Command(BaseCommand):
    help = "Crée les permissions menu_* manquantes en base de données"

    def handle(self, *args, **options):
        ct, _ = ContentType.objects.get_or_create(
            app_label='accounts',
            model='menuaccess'
        )

        created_count = 0
        for code, label in MENU_ACCESS_PERMISSIONS:
            perm, created = Permission.objects.get_or_create(
                content_type=ct,
                codename=code,
                defaults={'name': label}
            )
            if created:
                created_count += 1
                self.stdout.write(self.style.SUCCESS(f"Créée : {code}"))

        self.stdout.write(
            f"\n[OK] {created_count} permission(s) creee(s). "
            f"Total : {len(MENU_ACCESS_PERMISSIONS)} permissions."
        )
