# -*- coding: utf-8 -*-
"""Supprime les préférences individuelles email/SMS du Profil.

Depuis la refonte des notifications, la décision d'envoyer par email ou SMS
est une configuration GLOBALE faite par l'administrateur (Paramètres →
Notifications). Les champs notif_email / notif_sms du Profil sont supprimés.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0005_alter_menuaccess_options_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='profil',
            name='notif_email',
        ),
        migrations.RemoveField(
            model_name='profil',
            name='notif_sms',
        ),
    ]
