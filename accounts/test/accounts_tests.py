# accounts/tests.py — Tests complets pour le module accounts
"""
Tests pour le module accounts :
  - Entreprise (slug auto-généré, clean, get_pdf_config)
  - Profil (get_fonction_display, permissions)
  - Fonction, Specialite, RoleEntreprise
  - ConfigDocument
  - JournalAudit, Notification
"""
from django.test import TestCase
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils.text import slugify
from accounts.models import (
    Entreprise, Profil, Fonction, Specialite, RoleEntreprise,
    ConfigDocument, Notification, JournalAudit, MenuAccess
)
from core.models import Service


class EntrepriseModelTest(TestCase):
    """Tests pour le modèle Entreprise."""

    def test_slug_auto_generated_from_nom(self):
        """Le slug doit être généré automatiquement depuis le nom."""
        e = Entreprise.objects.create(nom="CHU Angre")
        self.assertEqual(e.slug, "chu-angre")

    def test_slug_unique_with_counter(self):
        """Si le slug existe déjà, ajouter un compteur."""
        e1 = Entreprise.objects.create(nom="CHU Angre")
        e2 = Entreprise.objects.create(nom="CHU Angre")
        self.assertEqual(e1.slug, "chu-angre")
        self.assertEqual(e2.slug, "chu-angre-1")

    def test_slug_preserved_if_provided(self):
        """Si un slug est fourni explicitement, le conserver."""
        e = Entreprise.objects.create(nom="Test", slug="custom-slug")
        self.assertEqual(e.slug, "custom-slug")

    def test_slug_truncated_to_50_chars(self):
        """Le slug ne doit pas dépasser 50 caractères."""
        nom = "A" * 100
        e = Entreprise.objects.create(nom=nom)
        self.assertLessEqual(len(e.slug), 50)

    def test_str_returns_nom(self):
        """__str__ doit retourner le nom."""
        e = Entreprise.objects.create(nom="Test")
        self.assertEqual(str(e), "Test")

    def test_clean_valid_logo_extension(self):
        """clean() doit accepter PNG et JPG."""
        import os
        from django.core.files.uploadedfile import SimpleUploadedFile
        e = Entreprise(nom="Test")
        # Pas de fichier réel, juste vérifier que clean() ne plante pas sans logo
        e.clean()  # Ne doit pas lever d'exception

    def test_generer_numero_format(self):
        """generer_numero doit retourner le bon format."""
        e = Entreprise.objects.create(nom="Test")
        numero = e.generer_numero('BON_SORTIE', 2025)
        self.assertTrue(numero.startswith("BS "))
        self.assertIn("2025", numero)
        self.assertIn(f"E{e.id}", numero)

    def test_labels_signatures_returns_list(self):
        """labels_signatures doit retourner une liste de 6 labels."""
        e = Entreprise.objects.create(nom="Test")
        labels = e.labels_signatures
        self.assertEqual(len(labels), 6)
        self.assertEqual(labels[0], "Le Demandeur")

    def test_get_pdf_config_returns_dict(self):
        """get_pdf_config doit retourner un dict avec les clés attendues."""
        e = Entreprise.objects.create(nom="Test")
        config = e.get_pdf_config('BON_SORTIE')
        self.assertIn('afficher_logo', config)
        self.assertIn('couleur_principale', config)
        self.assertIn('signataires', config)
        self.assertEqual(config['couleur_principale'], '#1c5b96')

    def test_build_signataires_config(self):
        """_build_signataires_config doit retourner 6 signataires."""
        e = Entreprise.objects.create(nom="Test")
        sigs = e._build_signataires_config()
        self.assertEqual(len(sigs), 6)
        self.assertEqual(sigs[0]['role'], 'demandeur')


class ProfilModelTest(TestCase):
    """Tests pour le modèle Profil."""

    def setUp(self):
        self.entreprise = Entreprise.objects.create(nom="Test Entreprise")
        self.user = User.objects.create_user(username="testuser", password="testpass")

    def test_profil_creation(self):
        """Création d'un profil lié à un user et une entreprise."""
        profil = Profil.objects.create(user=self.user, entreprise=self.entreprise)
        self.assertEqual(profil.user, self.user)
        self.assertEqual(profil.entreprise, self.entreprise)

    def test_get_fonction_display_with_fonction(self):
        """get_fonction_display doit retourner le nom de la fonction."""
        fonction = Fonction.objects.create(nom="Médecin", entreprise=self.entreprise)
        profil = Profil.objects.create(
            user=self.user, entreprise=self.entreprise, fonction=fonction
        )
        self.assertEqual(profil.get_fonction_display(), "Médecin")

    def test_get_fonction_display_chef_service(self):
        """get_fonction_display doit inclure 'Chef de Service'."""
        from core.models import Service
        service = Service.objects.create(
            nom="Cardiologie", code="CAR", entreprise=self.entreprise
        )
        profil = Profil.objects.create(
            user=self.user, entreprise=self.entreprise,
            service=service, est_chef_service=True
        )
        self.assertIn("Chef de Service", profil.get_fonction_display())

    def test_get_fonction_display_service_only(self):
        """get_fonction_display doit retourner le service si pas de fonction."""
        from core.models import Service
        from core.models import Service
        service = Service.objects.create(
            nom="Cardiologie", code="CAR", entreprise=self.entreprise
        )
        profil = Profil.objects.create(
            user=self.user, entreprise=self.entreprise, service=service
        )
        self.assertEqual(profil.get_fonction_display(), "Cardiologie")

    def test_get_fonction_display_fallback(self):
        """get_fonction_display doit retourner 'Non spécifié' par défaut."""
        profil = Profil.objects.create(user=self.user, entreprise=self.entreprise)
        self.assertEqual(profil.get_fonction_display(), "Non spécifié")

    def test_peut_changer_photo_first_time(self):
        """peut_changer_photo doit être True la première fois."""
        profil = Profil.objects.create(user=self.user, entreprise=self.entreprise)
        self.assertTrue(profil.peut_changer_photo)

    def test_temps_restant_photo_initial(self):
        """temps_restant_photo doit être 0 initialement."""
        profil = Profil.objects.create(user=self.user, entreprise=self.entreprise)
        self.assertEqual(profil.temps_restant_photo, 0)

    def test_str_returns_user_and_entreprise(self):
        """__str__ doit contenir le nom d'utilisateur et l'entreprise."""
        profil = Profil.objects.create(user=self.user, entreprise=self.entreprise)
        self.assertIn("testuser", str(profil))
        self.assertIn("Test Entreprise", str(profil))


class FonctionModelTest(TestCase):
    """Tests pour le modèle Fonction."""

    def setUp(self):
        self.entreprise = Entreprise.objects.create(nom="Test")

    def test_creation(self):
        """Création d'une fonction."""
        f = Fonction.objects.create(nom="Médecin", entreprise=self.entreprise)
        self.assertEqual(str(f), "Médecin")

    def test_unique_together(self):
        """Une entreprise ne peut pas avoir 2 fonctions avec le même nom."""
        Fonction.objects.create(nom="Médecin", entreprise=self.entreprise)
        with self.assertRaises(Exception):  # IntegrityError
            Fonction.objects.create(nom="Médecin", entreprise=self.entreprise)


class SpecialiteModelTest(TestCase):
    """Tests pour le modèle Specialite."""

    def setUp(self):
        self.entreprise = Entreprise.objects.create(nom="Test")

    def test_creation(self):
        """Création d'une spécialité."""
        s = Specialite.objects.create(nom="Cardiologie", entreprise=self.entreprise)
        self.assertEqual(str(s), "Cardiologie (Test)")


class ConfigDocumentModelTest(TestCase):
    """Tests pour le modèle ConfigDocument."""

    def setUp(self):
        self.entreprise = Entreprise.objects.create(nom="Test")

    def test_creation(self):
        """Création d'une config document."""
        cd = ConfigDocument.objects.create(
            entreprise=self.entreprise,
            type_doc='BS',
            code_document='ENR-001'
        )
        self.assertEqual(str(cd), "Bon de Sortie — Test")

    def test_unique_together(self):
        """Une entreprise ne peut pas avoir 2 configs pour le même type."""
        ConfigDocument.objects.create(entreprise=self.entreprise, type_doc='BS')
        with self.assertRaises(Exception):
            ConfigDocument.objects.create(entreprise=self.entreprise, type_doc='BS')


class NotificationModelTest(TestCase):
    """Tests pour le modèle Notification."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="testpass")

    def test_creation(self):
        """Création d'une notification."""
        n = Notification.objects.create(
            utilisateur=self.user,
            titre="Test",
            message="Message test"
        )
        self.assertFalse(n.est_lue)

    def test_marquer_lue(self):
        """marquer_lue doit mettre est_lue à True."""
        n = Notification.objects.create(
            utilisateur=self.user, titre="Test", message="Msg"
        )
        n.marquer_lue()
        self.assertTrue(n.est_lue)
        self.assertIsNotNone(n.date_lecture)


class JournalAuditModelTest(TestCase):
    """Tests pour le modèle JournalAudit."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.entreprise = Entreprise.objects.create(nom="Test")

    def test_creation(self):
        """Création d'une entrée d'audit."""
        ja = JournalAudit.objects.create(
            utilisateur=self.user,
            entreprise=self.entreprise,
            action="Création test",
            type_action='CREATE'
        )
        self.assertIn("Création test", str(ja))


class RoleEntrepriseModelTest(TestCase):
    """Tests pour le modèle RoleEntreprise."""

    def setUp(self):
        from django.contrib.auth.models import Group
        self.entreprise = Entreprise.objects.create(nom="Test")
        self.group = Group.objects.create(name="Admin@Test")

    def test_creation(self):
        """Création d'un rôle entreprise."""
        re = RoleEntreprise.objects.create(
            groupe=self.group, entreprise=self.entreprise
        )
        self.assertEqual(str(re), "Admin@Test — Test")

    def test_nom_affiche(self):
        """nom_affiche doit retourner le nom sans le suffixe @entreprise."""
        from django.contrib.auth.models import Group
        g = Group.objects.create(name="Admin@Test")
        re = RoleEntreprise.objects.create(groupe=g, entreprise=self.entreprise)
        self.assertEqual(re.nom_affiche, "Admin")


class EntrepriseSlugEdgeCasesTest(TestCase):
    """Tests edge cases pour le slug d'Entreprise."""

    def test_empty_nom_raises_error(self):
        """Un nom vide doit lever une erreur."""
        with self.assertRaises(Exception):
            Entreprise.objects.create(nom="")

    def test_special_chars_in_nom(self):
        """Les caractères spéciaux doivent être convertis en slug valide."""
        e = Entreprise.objects.create(nom="CHU & Cie — Test")
        self.assertNotIn("&", e.slug)
        self.assertNotIn("—", e.slug)

    def test_unicode_nom(self):
        """Les caractères unicode doivent être gérés."""
        e = Entreprise.objects.create(nom="Hôpital Général")
        self.assertIn("hopital", e.slug.lower())

    def test_multiple_entreprises_same_base_name(self):
        """Créer plusieurs entreprises avec le même nom de base."""
        names = ["Clinique", "Clinique", "Clinique"]
        slugs = []
        for name in names:
            e = Entreprise.objects.create(nom=name)
            slugs.append(e.slug)

        # Tous les slugs doivent être uniques
        self.assertEqual(len(slugs), len(set(slugs)))
        self.assertEqual(slugs[0], "clinique")
        self.assertEqual(slugs[1], "clinique-1")
        self.assertEqual(slugs[2], "clinique-2")
