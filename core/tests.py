from core.models import ConfigDocument, TypeDocument
from django.test import TestCase
from core.pdf_pagination import paginer_bon_sortie


class PDFPaginationTest(TestCase):
    """Tests de pagination PDF."""

    def test_single_page(self):
        """≤ 28 lignes = page unique."""
        lignes = [{'designation': 'Article ' + str(i)} for i in range(28)]
        config = {}
        result = paginer_bon_sortie(lignes, config)
        self.assertFalse(result.est_multi_page)
        self.assertEqual(len(result.pages), 1)

    def test_multi_page(self):
        """> 28 lignes = multi-page."""
        lignes = [{'designation': 'Article ' + str(i)} for i in range(50)]
        config = {}
        result = paginer_bon_sortie(lignes, config)
        self.assertTrue(result.est_multi_page)
        self.assertGreater(len(result.pages), 1)

    def test_last_page_not_empty(self):
        """Dernière page a toujours ≥ 5 lignes."""
        lignes = [{'designation': 'Article ' + str(i)} for i in range(33)]
        config = {}
        result = paginer_bon_sortie(lignes, config)
        last_page = result.pages[-1]
        self.assertGreaterEqual(len(last_page.lignes), 5)


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
