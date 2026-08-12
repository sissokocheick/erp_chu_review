# accounts/tests.py — Tests mono-tenant
"""
Tests pour le module accounts (mono-tenant) :
  - Profil (get_fonction_display, peut_changer_photo, doit_changer_mdp, signal)
  - Fonction, Specialite
  - ConfigDocument
  - Notification, JournalAudit, AuditConnexion
  - MenuAccess
"""
from django.test import TestCase
from django.contrib.auth.models import User, Group
from django.utils import timezone
from datetime import timedelta

from accounts.models import (
    Profil, Fonction, Specialite, ConfigDocument,
    Notification, JournalAudit, AuditConnexion, MenuAccess,
)
from core.models import Service


# ==========================================================
# PROFIL
# ==========================================================
class ProfilModelTest(TestCase):
    """Tests pour le modèle Profil (mono-tenant)."""

    def setUp(self):
        self.user = User.objects.create_user(username="testuser", password="testpass")
        # Le signal créer_profil_utilisateur crée déjà le Profil
        self.profil = self.user.profil

    def test_profil_auto_created_by_signal(self):
        """Le signal doit créer automatiquement un Profil à la création d'un User."""
        u = User.objects.create_user(username="auto", password="pass")
        self.assertTrue(hasattr(u, 'profil'))
        self.assertIsInstance(u.profil, Profil)

    def test_doit_changer_mdp_default_true(self):
        """doit_changer_mdp doit être True par défaut (1ère connexion)."""
        self.assertTrue(self.profil.doit_changer_mdp)

    def test_get_fonction_display_with_fonction(self):
        """Priorité 1 : FK Fonction."""
        fonction = Fonction.objects.create(nom="Médecin")
        self.profil.fonction = fonction
        self.profil.save()
        self.assertEqual(self.profil.get_fonction_display(), "Médecin")

    def test_get_fonction_display_chef_service(self):
        """Priorité 2 : Chef de Service + Service."""
        service = Service.objects.create(nom="Cardiologie", code="CAR")
        self.profil.service = service
        self.profil.est_chef_service = True
        self.profil.save()
        self.assertIn("Chef de Service", self.profil.get_fonction_display())
        self.assertIn("Cardiologie", self.profil.get_fonction_display())

    def test_get_fonction_display_service_only(self):
        """Priorité 3 : Service seul."""
        service = Service.objects.create(nom="Cardiologie", code="CAR")
        self.profil.service = service
        self.profil.save()
        self.assertEqual(self.profil.get_fonction_display(), "Cardiologie")

    def test_get_fonction_display_specialite(self):
        """Priorité 4 : Spécialité."""
        specialite = Specialite.objects.create(nom="Anesthésie")
        self.profil.specialite = specialite
        self.profil.save()
        self.assertEqual(self.profil.get_fonction_display(), "Anesthésie")

    def test_get_fonction_display_fallback(self):
        """Fallback : 'Non spécifié'."""
        self.assertEqual(self.profil.get_fonction_display(), "Non spécifié")

    def test_fonction_complete_alias(self):
        """fonction_complete est un alias de get_fonction_display."""
        fonction = Fonction.objects.create(nom="Pharmacien")
        self.profil.fonction = fonction
        self.profil.save()
        self.assertEqual(self.profil.fonction_complete, "Pharmacien")

    def test_peut_changer_photo_first_time(self):
        """peut_changer_photo = True si jamais changé."""
        self.assertTrue(self.profil.peut_changer_photo)

    def test_temps_restant_photo_initial(self):
        """temps_restant_photo = 0 initialement."""
        self.assertEqual(self.profil.temps_restant_photo, 0)

    def test_peut_changer_photo_after_recent_change(self):
        """peut_changer_photo = False juste après un changement."""
        self.profil.date_derniere_photo = timezone.now()
        self.profil.nb_changements_photo = 1
        self.profil.save()
        self.assertFalse(self.profil.peut_changer_photo)
        self.assertGreater(self.profil.temps_restant_photo, 0)

    def test_delai_attente_photo_plafonne(self):
        """Le délai est plafonné à 60 minutes."""
        self.profil.nb_changements_photo = 10  # 10 × 10 = 100 → plafonné à 60
        self.assertEqual(self.profil.delai_attente_photo_minutes, 60)

    def test_str_with_service(self):
        """__str__ contient le service si présent."""
        service = Service.objects.create(nom="Urgences", code="URG")
        self.profil.service = service
        self.profil.save()
        self.assertIn("Urgences", str(self.profil))

    def test_str_without_service(self):
        """__str__ retourne le nom utilisateur sans service."""
        self.assertIn("testuser", str(self.profil))


# ==========================================================
# FONCTION
# ==========================================================
class FonctionModelTest(TestCase):
    def test_creation(self):
        f = Fonction.objects.create(nom="Médecin")
        self.assertEqual(str(f), "Médecin")

    def test_ordering(self):
        Fonction.objects.create(nom="Zebra")
        Fonction.objects.create(nom="Alpha")
        noms = list(Fonction.objects.values_list('nom', flat=True))
        self.assertEqual(noms, sorted(noms))


# ==========================================================
# SPECIALITE
# ==========================================================
class SpecialiteModelTest(TestCase):
    def test_creation(self):
        s = Specialite.objects.create(nom="Cardiologie")
        self.assertEqual(str(s), "Cardiologie")

    def test_with_description(self):
        s = Specialite.objects.create(nom="Pédiatrie", description="Enfants")
        self.assertEqual(s.description, "Enfants")


# ==========================================================
# CONFIG DOCUMENT
# ==========================================================
class ConfigDocumentModelTest(TestCase):
    def test_creation(self):
        cd = ConfigDocument.objects.create(
            type_doc='BS',
            code_document='ENR-001'
        )
        self.assertEqual(str(cd), "Bon de Sortie")
        self.assertTrue(cd.afficher_logo)
        self.assertTrue(cd.afficher_signatures)

    def test_defaults_affichage(self):
        cd = ConfigDocument.objects.create(type_doc='BE')
        self.assertTrue(cd.afficher_logo)
        self.assertTrue(cd.afficher_cachet)
        self.assertTrue(cd.afficher_cc)
        self.assertTrue(cd.afficher_ifu)
        self.assertTrue(cd.afficher_rccm)
        self.assertTrue(cd.afficher_telephone)
        self.assertTrue(cd.afficher_signatures)

    def test_type_doc_choices(self):
        for code, label in ConfigDocument.TYPE_DOC_CHOICES:
            cd = ConfigDocument.objects.create(type_doc=code)
            self.assertEqual(cd.get_type_doc_display(), label)


# ==========================================================
# NOTIFICATION
# ==========================================================
class NotificationModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="notifuser", password="pass")

    def test_creation(self):
        n = Notification.objects.create(
            utilisateur=self.user,
            titre="Test",
            message="Message test"
        )
        self.assertFalse(n.est_lue)
        self.assertEqual(n.type_notif, 'INFO')

    def test_marquer_lue(self):
        n = Notification.objects.create(
            utilisateur=self.user, titre="Test", message="Msg"
        )
        n.marquer_lue()
        n.refresh_from_db()
        self.assertTrue(n.est_lue)
        self.assertIsNotNone(n.date_lecture)

    def test_str(self):
        n = Notification.objects.create(
            utilisateur=self.user, titre="Alerte", message="X", type_notif='WARNING'
        )
        self.assertIn("Alerte", str(n))
        self.assertIn("notifuser", str(n))


# ==========================================================
# JOURNAL AUDIT
# ==========================================================
class JournalAuditModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="audituser", password="pass")

    def test_creation(self):
        ja = JournalAudit.objects.create(
            utilisateur=self.user,
            action="Création test",
            type_action='CREATE'
        )
        self.assertIn("Création test", str(ja))
        self.assertEqual(ja.type_action, 'CREATE')

    def test_with_details_json(self):
        ja = JournalAudit.objects.create(
            utilisateur=self.user,
            action="Modif",
            type_action='UPDATE',
            details={'champ': 'nom', 'avant': 'A', 'apres': 'B'}
        )
        self.assertEqual(ja.details['champ'], 'nom')

    def test_anonymous_allowed(self):
        """utilisateur peut être NULL (actions anonymes / système)."""
        ja = JournalAudit.objects.create(
            utilisateur=None,
            action="Action système",
            type_action='UPDATE'
        )
        self.assertIsNone(ja.utilisateur)


# ==========================================================
# AUDIT CONNEXION
# ==========================================================
class AuditConnexionModelTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="connuser", password="pass")

    def test_creation_connexion(self):
        ac = AuditConnexion.objects.create(
            utilisateur=self.user,
            type_action='CONNEXION',
            description="Login OK",
            adresse_ip="127.0.0.1"
        )
        self.assertEqual(ac.type_action, 'CONNEXION')
        self.assertIn("CONNEXION", str(ac))

    def test_echec_sans_user(self):
        """Échec de connexion peut n'avoir aucun utilisateur."""
        ac = AuditConnexion.objects.create(
            utilisateur=None,
            type_action='ECHEC',
            description="Mauvais mot de passe",
            adresse_ip="10.0.0.1"
        )
        self.assertIsNone(ac.utilisateur)


# ==========================================================
# MENU ACCESS
# ==========================================================
class MenuAccessModelTest(TestCase):
    def test_creation(self):
        ma = MenuAccess.objects.create(nom='menu_utilisateurs')
        self.assertEqual(str(ma), "Utilisateurs")

    def test_unique_nom(self):
        MenuAccess.objects.create(nom='menu_roles')
        with self.assertRaises(Exception):
            MenuAccess.objects.create(nom='menu_roles')


# ==========================================================
# GROUPES (rôles mono-tenant)
# ==========================================================
class GroupRoleTest(TestCase):
    """Les rôles sont des Group Django classiques."""

    def test_create_role(self):
        g = Group.objects.create(name="RESPONSABLE LOGISTIQUE")
        self.assertEqual(g.name, "RESPONSABLE LOGISTIQUE")

    def test_assign_role_to_user(self):
        user = User.objects.create_user(username="roleuser", password="pass")
        g = Group.objects.create(name="VALIDATEUR")
        user.groups.add(g)
        self.assertTrue(user.groups.filter(name="VALIDATEUR").exists())