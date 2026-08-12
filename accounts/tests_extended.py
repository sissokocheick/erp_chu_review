# -*- coding: utf-8 -*-
"""
Tests étendus du module accounts.

Couvre : politique de mot de passe, génération de mots de passe, sécurité du
login (brute-force, compte inactif), MenuAccess / permissions, signal de
création de profil, middlewares.
"""
from datetime import timedelta
from unittest import mock

from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth import get_user_model

from accounts.models import (
    MenuAccess, ConfigSecurite, AuditConnexion, Profil, MENU_ACCESS_PERMISSIONS,
)
from accounts.utils import valider_mot_de_passe, generer_mot_de_passe_aleatoire
from stock.tests import factories
from stock.models import Magasin

User = get_user_model()


# ════════════════════════════════════════════════════════════════
# Politique de mot de passe
# ════════════════════════════════════════════════════════════════
class PolitiqueMdpTest(TestCase):
    """Validation de mots de passe (chaque cas = un test)."""


# (mot_de_passe, attendu_valide, contexte)
MDP_CASES = [
    ("Passw0rd", True, 'default'),
    ("Motdepasse1", True, 'default'),
    ("ABcd1234", True, 'default'),
    ("X9kL2mN8", True, 'profil'),
    ("Azerty12", True, 'obligatoire'),
    ("Qwerty123", True, 'admin_reset'),
    ("abcdefgh", False, 'default'),        # pas de majuscule ni chiffre
    ("ABCDEFGH", False, 'default'),        # pas de minuscule ni chiffre
    ("12345678", False, 'default'),        # pas de lettre
    ("short", False, 'default'),           # trop court
    ("", False, 'default'),                # vide
    ("123456A", False, 'default'),         # trop court (7)
    ("12345678A", True, 'default'),        # 9 caractères, chiffres + maj
    ("Mot2Passe", True, 'default'),
    ("motdepasse1", False, 'default'),     # pas de majuscule
    ("MOTDEPASSE1", True, 'default'),      # majuscules + chiffre (pas de minuscule)
    ("abCD12ef", True, 'default'),
    ("p@ssW0rd", True, 'default'),
    ("a", False, 'default'),
    ("A1", False, 'default'),
    ("A1b2C3d4", True, 'default'),
    ("x" * 8, False, 'default'),           # que des minuscules
    ("X" * 8 + "1", True, 'default'),
    ("Passw0rd!", True, 'default'),
    ("  Passw0rd  ", True, 'default'),
    ("MotdePasse", False, 'default'),      # pas de chiffre
    ("MotdePasse99", True, 'default'),
    ("Zz9" * 3, True, 'default'),          # Zz9Zz9Zz9
    ("azAZ09az", True, 'default'),
    ("AZ09azAZ", True, 'default'),
    ("a1B2c3D4", True, 'default'),
    ("Motdepasse1", True, 'profil'),
    ("Motdepasse2", True, 'obligatoire'),
    ("Motdepasse3", True, 'admin_reset'),
    ("P4ssw0rdP4ssw0rd", True, 'default'),
    ("nouveau mot de passe", False, 'default'),  # espaces seulement, pas de maj/chiffre
    ("1234567890", False, 'default'),      # chiffres uniquement
    ("abcdefghij", False, 'default'),      # minuscules uniquement
    ("ABCDEFGHIJ", False, 'default'),      # majuscules uniquement
    ("a1b2c3d4e5", False, 'default'),      # trop de minuscules, pas de majuscule
    ("AB12cd34", True, 'default'),
    ("V3rY$3cur3", True, 'default'),
    ("Mot2Passe2026", True, 'default'),
    ("uN1que!mdp", True, 'default'),
    ("", False, 'profil'),
    ("", False, 'obligatoire'),
]


def _make_mdp_case(mdp, valide, contexte):
    def test(self):
        erreurs = valider_mot_de_passe(mdp, contexte)
        if valide:
            self.assertEqual(erreurs, [], f"attendu valide: {mdp} -> {erreurs}")
        else:
            self.assertTrue(len(erreurs) > 0, f"attendu invalide: {mdp}")
    return test


for _i, (mdp, valide, contexte) in enumerate(MDP_CASES):
    setattr(PolitiqueMdpTest, f'test_mdp_{_i:03d}', _make_mdp_case(mdp, valide, contexte))


class GenerationMdpTest(TestCase):

    def test_longueur_minimale(self):
        mdp = generer_mot_de_passe_aleatoire(8)
        self.assertEqual(len(mdp), 8)

    def test_longueur_par_defaut(self):
        mdp = generer_mot_de_passe_aleatoire()
        self.assertEqual(len(mdp), 12)

    def test_conforme_politique(self):
        for _ in range(20):
            mdp = generer_mot_de_passe_aleatoire()
            self.assertEqual(valider_mot_de_passe(mdp), [])

    def test_longueur_inferieure_forcee_a_8(self):
        mdp = generer_mot_de_passe_aleatoire(3)
        self.assertEqual(len(mdp), 8)

    def test_contenu_varié(self):
        mots = {generer_mot_de_passe_aleatoire() for _ in range(30)}
        self.assertGreaterEqual(len(mots), 20)


class ConfigSecuriteTest(TestCase):

    def test_get_solo_cree(self):
        obj = ConfigSecurite.get_solo()
        self.assertEqual(obj.pk, 1)

    def test_get_solo_idempotent(self):
        ConfigSecurite.get_solo()
        ConfigSecurite.get_solo()
        self.assertEqual(ConfigSecurite.objects.count(), 1)

    def test_save_force_pk_1(self):
        obj = ConfigSecurite.objects.create()
        self.assertEqual(obj.pk, 1)
        self.assertEqual(ConfigSecurite.objects.count(), 1)

    def test_delete_impossible(self):
        obj = ConfigSecurite.get_solo()
        obj.delete()
        self.assertTrue(ConfigSecurite.objects.filter(pk=1).exists())


# ════════════════════════════════════════════════════════════════
# Sécurité du login
# ════════════════════════════════════════════════════════════════
class LoginSecuriteTest(TestCase):

    def setUp(self):
        self.client = Client()
        self.user = factories.creer_utilisateur(username="lucie", password="Motdepasse1")
        factories.desactiver_changement_mdp(self.user)
        self.url = reverse('accounts:custom_login')

    def test_login_succes_redirige(self):
        response = self.client.post(self.url, {
            'username': 'lucie', 'password': 'Motdepasse1'})
        self.assertIn(response.status_code, (301, 302))

    def test_login_mauvais_mdp(self):
        response = self.client.post(self.url, {
            'username': 'lucie', 'password': 'Mauvais123'})
        self.assertEqual(response.status_code, 200)

    def test_login_username_inconnu(self):
        response = self.client.post(self.url, {
            'username': 'inconnu', 'password': 'Motdepasse1'})
        self.assertEqual(response.status_code, 200)

    def test_echec_enregistre_en_audit(self):
        self.client.post(self.url, {
            'username': 'lucie', 'password': 'Mauvais123'})
        self.assertTrue(AuditConnexion.objects.filter(
            type_action='ECHEC').exists())

    def test_login_insensible_a_la_casse_username(self):
        response = self.client.post(self.url, {
            'username': 'LUCie', 'password': 'Motdepasse1'})
        self.assertIn(response.status_code, (301, 302))

    def test_login_utilisateur_inactif_refuse(self):
        self.user.is_active = False
        self.user.save()
        response = self.client.post(self.url, {
            'username': 'lucie', 'password': 'Motdepasse1'})
        self.assertEqual(response.status_code, 200)

    def test_blocage_apres_5_echecs(self):
        for _ in range(5):
            self.client.post(self.url, {
                'username': 'lucie', 'password': 'Mauvais123'})
        # Même avec le bon mot de passe : bloqué
        response = self.client.post(self.url, {
            'username': 'lucie', 'password': 'Motdepasse1'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "bloqu")

    def test_pas_de_blocage_avant_5_echecs(self):
        for _ in range(4):
            self.client.post(self.url, {
                'username': 'lucie', 'password': 'Mauvais123'})
        response = self.client.post(self.url, {
            'username': 'lucie', 'password': 'Motdepasse1'})
        self.assertIn(response.status_code, (301, 302))

    def test_verification_mdp_factice_pour_username_inconnu(self):
        # Ne doit pas planter et doit garder un timing neutre (appel du hash)
        with mock.patch('django.contrib.auth.hashers.check_password') as m:
            self.client.post(self.url, {
                'username': 'personne', 'password': 'Motdepasse1'})
            self.assertTrue(m.called)


# ════════════════════════════════════════════════════════════════
# MenuAccess / permissions
# ════════════════════════════════════════════════════════════════
class MenuAccessTest(TestCase):

    def test_codes_uniques(self):
        codes = [c for c, _ in MENU_ACCESS_PERMISSIONS]
        self.assertEqual(len(codes), len(set(codes)))

    def test_au_moins_75_permissions(self):
        self.assertGreaterEqual(len(MENU_ACCESS_PERMISSIONS), 75)

    def test_codes_sans_espace(self):
        for code, _ in MENU_ACCESS_PERMISSIONS:
            self.assertNotIn(' ', code)

    def test_labels_non_vides(self):
        for code, label in MENU_ACCESS_PERMISSIONS:
            self.assertTrue(label.strip(), f"label vide pour {code}")

    def test_creer_menu_access(self):
        menu = MenuAccess.objects.create(nom="Registre", code="menu_registre_test")
        self.assertEqual(str(menu), "Registre")

    def test_code_unique_modele(self):
        MenuAccess.objects.create(nom="A", code="menu_uniq_a")
        with self.assertRaises(Exception):
            MenuAccess.objects.create(nom="B", code="menu_uniq_a")

    def test_toutes_les_permissions_declarees_sur_le_modele(self):
        codes_modele = [p[0] for p in MenuAccess._meta.permissions]
        for code, _ in MENU_ACCESS_PERMISSIONS:
            self.assertIn(code, codes_modele)


# Génère un test par permission menu_* (couvre les ~90 codes)
for _i, (code, _label) in enumerate(MENU_ACCESS_PERMISSIONS):
    def _make(code):
        def test(self):
            self.assertIn(code, [c for c, _ in MENU_ACCESS_PERMISSIONS])
            self.assertTrue(code.startswith('menu_'))
        return test
    setattr(MenuAccessTest, f'test_permission_{_i:03d}_{code[:30]}', _make(code))


# ════════════════════════════════════════════════════════════════
# Signal de création de profil
# ════════════════════════════════════════════════════════════════
class ProfilSignalTest(TestCase):

    def test_profil_auto_cree(self):
        user = factories.creer_utilisateur(username="signal_test")
        self.assertTrue(Profil.objects.filter(user=user).exists())

    def test_profil_doit_changer_mdp_par_defaut(self):
        user = factories.creer_utilisateur(username="signal_mdp")
        self.assertTrue(user.profil.doit_changer_mdp)

    def test_profil_theme_par_defaut(self):
        user = factories.creer_utilisateur(username="signal_theme")
        self.assertEqual(user.profil.theme_preference, 'light')

    def test_profil_unique(self):
        user = factories.creer_utilisateur(username="signal_unique")
        self.assertEqual(Profil.objects.filter(user=user).count(), 1)


# ════════════════════════════════════════════════════════════════
# Middlewares
# ════════════════════════════════════════════════════════════════
class PasswordChangeMiddlewareTest(TestCase):

    def setUp(self):
        self.client = Client()

    def test_redirige_si_mdp_obligatoire(self):
        user = factories.creer_utilisateur(username="pdc_test")
        self.client.force_login(user)
        response = self.client.get('/parametres/administratifs/')
        self.assertIn(response.status_code, (301, 302))
        self.assertIn('forcer-mdp', response.url)

    def test_acces_autorise_sans_obligation(self):
        user = factories.creer_superuser(username="pdc_ok")
        factories.desactiver_changement_mdp(user)
        self.client.force_login(user)
        response = self.client.get(reverse('parametres_administratifs'))
        self.assertEqual(response.status_code, 200)

    def test_page_changement_accessible(self):
        user = factories.creer_utilisateur(username="pdc_page")
        self.client.force_login(user)
        response = self.client.get(reverse('accounts:changer_mdp_obligatoire'))
        self.assertEqual(response.status_code, 200)


class MagasinAutoSelectMiddlewareTest(TestCase):

    def test_selection_auto_magasin_unique(self):
        magasin = Magasin.objects.create(nom="Unique")
        user = factories.creer_superuser(username="mas_super")
        factories.desactiver_changement_mdp(user)
        self.client.force_login(user)
        self.client.get('/accueil/')
        session = self.client.session
        self.assertEqual(session.get('magasin_actif_id'), str(magasin.id))

    def test_pas_de_selection_si_plusieurs(self):
        Magasin.objects.create(nom="M1")
        Magasin.objects.create(nom="M2")
        user = factories.creer_superuser(username="mas_multi")
        factories.desactiver_changement_mdp(user)
        self.client.force_login(user)
        self.client.get('/accueil/')
        session = self.client.session
        self.assertNotIn('magasin_actif_id', session)
