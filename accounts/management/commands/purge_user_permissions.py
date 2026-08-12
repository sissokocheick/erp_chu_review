# -*- coding: utf-8 -*-
"""Commande de maintenance : purge des permissions directes héritées.

Les droits métier viennent UNIQUEMENT des groupes (rôles). Cette commande
supprime les permissions directes (user_permissions) laissées par l'ancien
système, qui provoquaient l'affichage complet du menu pour des rôles restreints.
"""
from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model

User = get_user_model()


class Command(BaseCommand):
    help = "Purge les permissions directes des utilisateurs (droits = groupes uniquement)"

    def add_arguments(self, parser):
        parser.add_argument(
            '--username', '-u',
            help="Ne purger que cet utilisateur (sinon tous)",
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help="Affiche sans supprimer",
        )

    def handle(self, *args, **options):
        qs = User.objects.all()
        if options['username']:
            qs = qs.filter(username=options['username'])

        total = 0
        for u in qs:
            n = u.user_permissions.count()
            if n:
                total += n
                if options['dry_run']:
                    self.stdout.write(f"[DRY] {u.username}: {n} permission(s) directe(s)")
                else:
                    u.user_permissions.clear()
                    self.stdout.write(self.style.SUCCESS(f"[OK] {u.username}: {n} permission(s) directe(s) purgées"))
        self.stdout.write(f"\nTotal : {total} permission(s) directe(s) traitées.")
