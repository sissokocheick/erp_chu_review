# -*- coding: utf-8 -*-
"""Régression : « Gestion des Lots » doit être accessible avec la seule permission menu_lots."""
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import TestCase
from django.urls import reverse

from accounts.models import Profil
from stock.models import Magasin


class LotsPermissionTest(TestCase):
    def setUp(self):
        self.magasin = Magasin.objects.create(nom="Magasin Central", localisation="Central")
        self.user = get_user_model().objects.create_user(username="lotsuser", password="x12345678")
        self.user.profil.magasins_autorises.set([self.magasin])
        self.user.profil.doit_changer_mdp = False
        self.user.profil.save(update_fields=["doit_changer_mdp"])
        perm = Permission.objects.get(codename="menu_lots")
        self.user.user_permissions.add(perm)

    def test_page_lots_accessible_avec_menu_lots_seul(self):
        self.client.force_login(self.user)
        # la session doit avoir un magasin actif
        session = self.client.session
        session["magasin_actif_id"] = self.magasin.id
        session.save()
        r = self.client.get(reverse("liste_lots"))
        self.assertEqual(r.status_code, 302)
        self.assertIn("onglet=lots", r["Location"])
        r2 = self.client.get(r["Location"])
        self.assertEqual(r2.status_code, 200)
        self.assertContains(r2, "Gestion des Lots")

    def test_onglet_lots_accessible_avec_menu_lots_seul(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["magasin_actif_id"] = self.magasin.id
        session.save()
        r = self.client.get(reverse("controle_peremptions") + "?onglet=lots")
        self.assertEqual(r.status_code, 200)

    def test_sans_permission_redirige(self):
        u2 = get_user_model().objects.create_user(username="sansperm", password="x12345678")
        u2.profil.magasins_autorises.set([self.magasin])
        u2.profil.doit_changer_mdp = False
        u2.profil.save(update_fields=["doit_changer_mdp"])
        self.client.force_login(u2)
        r = self.client.get(reverse("controle_peremptions") + "?onglet=lots")
        self.assertIn(r.status_code, (302, 403))
