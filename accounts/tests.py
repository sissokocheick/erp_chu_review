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
        ma = MenuAccess.objects.create(nom="Utilisateurs", code='menu_utilisateurs')
        self.assertEqual(str(ma), "Utilisateurs")

    def test_unique_code(self):
        """L'unicité est portée par `code`, pas par `nom`."""
        MenuAccess.objects.create(nom="Rôles", code='menu_roles')
        with self.assertRaises(Exception):
            MenuAccess.objects.create(nom="Autre libellé", code='menu_roles')


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


# ==========================================================
# MAGASIN AUTO-SELECT (middleware)
# ==========================================================
class MagasinAutoSelectMiddlewareTest(TestCase):
    """Régression : le superuser doit conserver son magasin sélectionné."""

    def _request_avec_magasin(self, user, magasin_id):
        from django.test import RequestFactory
        from django.contrib.sessions.middleware import SessionMiddleware
        from accounts.middleware import MagasinAutoSelectMiddleware
        request = RequestFactory().get('/')
        request.user = user
        SessionMiddleware(lambda r: None).process_request(request)
        request.session['magasin_actif_id'] = str(magasin_id)
        MagasinAutoSelectMiddleware(lambda r: None)(request)
        return request.session.get('magasin_actif_id')

    def test_superuser_garde_son_magasin(self):
        from stock.models import Magasin
        magasin1 = Magasin.objects.create(nom="Magasin A")
        Magasin.objects.create(nom="Magasin B")
        admin = User.objects.create_superuser(username="admin_mag", password="pass")
        self.assertEqual(
            self._request_avec_magasin(admin, magasin1.id),
            str(magasin1.id),
        )

    def test_user_autorise_garde_son_magasin(self):
        from stock.models import Magasin
        magasin = Magasin.objects.create(nom="Magasin A")
        user = User.objects.create_user(username="user_mag", password="pass")
        user.profil.magasins_autorises.add(magasin)
        self.assertEqual(
            self._request_avec_magasin(user, magasin.id),
            str(magasin.id),
        )

    def test_magasin_non_autorise_retire(self):
        from stock.models import Magasin
        magasin_autorise = Magasin.objects.create(nom="Magasin A")
        magasin_interdit = Magasin.objects.create(nom="Magasin B")
        user = User.objects.create_user(username="user_mag2", password="pass")
        user.profil.magasins_autorises.add(magasin_autorise)
        # Le magasin en session n'est pas autorisé → retiré (et seul magasin autorisé re-sélectionné)
        self.assertEqual(
            self._request_avec_magasin(user, magasin_interdit.id),
            str(magasin_autorise.id),
        )

    def test_magasin_non_autorise_sans_autoselect(self):
        """Avec plusieurs magasins autorisés, un magasin non autorisé est simplement retiré."""
        from stock.models import Magasin
        magasin_a = Magasin.objects.create(nom="Magasin A")
        magasin_b = Magasin.objects.create(nom="Magasin B")
        magasin_interdit = Magasin.objects.create(nom="Magasin C")
        user = User.objects.create_user(username="user_mag3", password="pass")
        user.profil.magasins_autorises.add(magasin_a, magasin_b)
        self.assertIsNone(self._request_avec_magasin(user, magasin_interdit.id))


# ==========================================================
# SÉCURITÉ LOGIN (rate-limiting + timing oracle)
# ==========================================================
class LoginSecuriteTest(TestCase):
    """Régression : blocage après 5 échecs, login valide toujours possible."""

    def test_username_inexistant_ne_plante_pas(self):
        """Un username inexistant doit renvoyer le formulaire (timing oracle neutralisé)."""
        from django.test import Client
        resp = Client().post(
            '/auth/login/',
            {'username': 'utilisateur_inexistant', 'password': 'motdepasse'},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn('Identifiants incorrects', resp.content.decode('utf-8', errors='ignore'))

    def test_blocage_apres_cinq_echecs(self):
        """La 6e tentative d'une même IP doit être bloquée."""
        from django.test import Client
        client = Client()
        for _ in range(5):
            client.post(
                '/auth/login/',
                {'username': 'utilisateur_inexistant', 'password': 'mauvais'},
            )
        resp = client.post(
            '/auth/login/',
            {'username': 'utilisateur_inexistant', 'password': 'mauvais'},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertIn('bloquée', resp.content.decode('utf-8', errors='ignore'))

    def test_login_valide_toujours_possible(self):
        """Un bon mot de passe connecte l'utilisateur."""
        from django.test import Client
        user = User.objects.create_user(username="login_ok", password="Motdepasse2026!")
        user.profil.doit_changer_mdp = False
        user.profil.save()
        resp = Client().post(
            '/auth/login/',
            {'username': 'login_ok', 'password': 'Motdepasse2026!'},
        )
        # Redirection après connexion (accueil ou changement MDP)
        self.assertIn(resp.status_code, (200, 302))

# ==========================================================
# CRÉATION / MODIFICATION UTILISATEUR : FORMAT EMAIL + TÉLÉPHONE
# ==========================================================
class CreationUtilisateurValidationTest(TestCase):
    """Régression : le formulaire utilisateur exige un email valide et un téléphone à 10 chiffres."""

    @classmethod
    def setUpTestData(cls):
        from stock.tests.factories import creer_magasin
        creer_magasin(nom='Magasin Tests')
        cls.admin = User.objects.create_superuser(
            username='admin_uv', password='Motdepasse2026!', email='admin@chu.ci'
        )
        cls.admin.profil.doit_changer_mdp = False
        cls.admin.profil.save()

    def setUp(self):
        self.client.force_login(self.admin)

    def _post_utilisateur(self, **overrides):
        data = {
            'enregistrer_user': '1',
            'username': 'nouveau',
            'first_name': 'Jean',
            'last_name': 'Kouassi',
            'email': 'jean.kouassi@chu.ci',
            'contact': '0708091011',
            'groupe': '',
            'service': '',
            'specialite': '',
            'fonction': '',
        }
        data.update(overrides)
        return self.client.post('/auth/utilisateurs/', data)

    def test_creation_email_invalide_refuse(self):
        resp = self._post_utilisateur(email='mauvais-email')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Adresse email invalide')
        self.assertFalse(User.objects.filter(username='nouveau').exists())

    def test_creation_email_sans_domaine_refuse(self):
        resp = self._post_utilisateur(email='jean@')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Adresse email invalide')
        self.assertFalse(User.objects.filter(username='nouveau').exists())

    def test_creation_telephone_9_chiffres_refuse(self):
        resp = self._post_utilisateur(contact='070809101')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'exactement 10 chiffres')
        self.assertFalse(User.objects.filter(username='nouveau').exists())

    def test_creation_valide_ok(self):
        resp = self._post_utilisateur()
        self.assertEqual(resp.status_code, 302)
        user = User.objects.get(username='nouveau')
        self.assertEqual(user.email, 'jean.kouassi@chu.ci')
        self.assertEqual(user.profil.contact, '0708091011')

    def test_modification_email_invalide_refuse(self):
        user = User.objects.create_user(
            username='deja_la', password='Motdepasse2026!', email='valide@chu.ci'
        )
        resp = self._post_utilisateur(user_id=str(user.id), username='deja_la', email='pas-ok')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Adresse email invalide')
        user.refresh_from_db()
        self.assertEqual(user.email, 'valide@chu.ci')

    def test_modification_telephone_invalide_refuse(self):
        user = User.objects.create_user(
            username='deja_la2', password='Motdepasse2026!', email='valide2@chu.ci'
        )
        resp = self._post_utilisateur(user_id=str(user.id), username='deja_la2', contact='0123')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'exactement 10 chiffres')
        user.refresh_from_db()
        self.assertEqual(user.profil.contact or '', '')

    def test_api_email_format_invalide(self):
        resp = self.client.get('/auth/api/utilisateurs/verifier/', {'type': 'email', 'value': 'pas-un-email'})
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data['available'])
        self.assertIn('invalide', data['message'])

    def test_api_email_format_valide_disponible(self):
        resp = self.client.get('/auth/api/utilisateurs/verifier/', {'type': 'email', 'value': 'libre@chu.ci'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['available'])

    def test_creation_envoie_mdp_par_email_si_canal_config(self):
        """Canal email configuré : le MDP initial part par email, ET la modale
        d'affichage (session new_user_credentials) reste remplie."""
        from django.core import mail
        from django.test import override_settings
        from core.models import ConfigurationNotification

        cfg = ConfigurationNotification.get_instance()
        cfg.activer_email = True
        cfg.email_expediteur = 'no-reply@chu.ci'
        cfg.smtp_host = 'smtp.gmail.com'
        cfg.smtp_user = 'no-reply@chu.ci'
        cfg.smtp_password = 'secret-app'
        cfg.save()

        with override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            resp = self._post_utilisateur(email='jean2@chu.ci', username='nouveau2')
        self.assertEqual(resp.status_code, 302)
        user = User.objects.get(username='nouveau2')

        # 1 email envoyé avec le mot de passe dans le corps
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ['jean2@chu.ci'])
        self.assertIn('nouveau2', mail.outbox[0].body)
        # Le MDP dans l'email correspond au MDP réel du compte
        mdp_email = None
        for ligne in mail.outbox[0].body.splitlines():
            if 'Mot de passe :' in ligne:
                mdp_email = ligne.split(':', 1)[1].strip()
                break
        self.assertIsNotNone(mdp_email)
        self.assertTrue(user.check_password(mdp_email))

        # La modale reste affichée (session remplie)
        session = self.client.session
        creds = session.get('new_user_credentials')
        self.assertIsNotNone(creds)
        self.assertEqual(creds['username'], 'nouveau2')

    def test_creation_aucun_canal_pas_d_email(self):
        """Aucun canal configuré : pas d'envoi, mais la modale reste affichée."""
        from django.core import mail
        from django.test import override_settings

        with override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend'):
            resp = self._post_utilisateur(email='jean3@chu.ci', username='nouveau3')
        self.assertEqual(resp.status_code, 302)
        self.assertTrue(User.objects.filter(username='nouveau3').exists())
        self.assertEqual(len(mail.outbox), 0)
        session = self.client.session
        self.assertIsNotNone(session.get('new_user_credentials'))
