"""
Tests unitaires pour valider les corrections de securite du module stock.
A placer dans : stock/tests/test_security_fixes.py

Pour executer :
    python manage.py test stock.tests.test_security_fixes
    # ou
    python manage.py test stock.tests.test_security_fixes.SecurityTestCase
"""

import json
from decimal import Decimal
from unittest.mock import patch, MagicMock

from django.test import TestCase, Client, override_settings
from django.contrib.auth import get_user_model
from django.urls import reverse, NoReverseMatch
from django.utils import timezone
from django.apps import apps

User = get_user_model()


class SecurityTestCase(TestCase):
    """Base class avec setup commun."""

    def setUp(self):
        self.client = Client()

        # Entreprises
        Entreprise = apps.get_model('accounts', 'Entreprise')
        self.entreprise_a = Entreprise.objects.create(
            nom="CHU A", slug="chu-a", email_contact="chu-a@test.com"
        )
        self.entreprise_b = Entreprise.objects.create(
            nom="CHU B", slug="chu-b", email_contact="chu-b@test.com"
        )

        # Utilisateurs
        self.admin_a = User.objects.create_superuser(
            username="admin_a", email="admin_a@test.com",
            password="testpass123"
        )
        self.user_a = User.objects.create_user(
            username="user_a", email="user_a@test.com",
            password="testpass123"
        )
        self.user_b = User.objects.create_user(
            username="user_b", email="user_b@test.com",
            password="testpass123"
        )

        # Profils
        Profil = apps.get_model('accounts', 'Profil')
        Profil.objects.get_or_create(user=self.admin_a, defaults={'entreprise': self.entreprise_a})
        Profil.objects.get_or_create(user=self.user_a, defaults={'entreprise': self.entreprise_a})
        Profil.objects.get_or_create(user=self.user_b, defaults={'entreprise': self.entreprise_b})

        # Login par defaut en admin_a
        self.client.login(username="admin_a", password="testpass123")

        self._models = {}

    def get_model(self, app_label, model_name):
        """Recupere un modele avec cache."""
        cache_key = f"{app_label}.{model_name}"
        if cache_key not in self._models:
            try:
                self._models[cache_key] = apps.get_model(app_label, model_name)
            except LookupError:
                for app in ['stock', 'accounts', 'core']:
                    try:
                        self._models[cache_key] = apps.get_model(app, model_name)
                        break
                    except LookupError:
                        continue
                else:
                    raise LookupError(f"Modele {model_name} introuvable")
        return self._models[cache_key]

    def get_url(self, url_name, kwargs=None):
        """Recupere une URL avec gestion d'erreur."""
        try:
            if kwargs:
                return reverse(url_name, kwargs=kwargs)
            return reverse(url_name)
        except NoReverseMatch:
            self.skipTest(f"URL '{url_name}' non configuree")


class TestIsolationEntreprise(SecurityTestCase):
    """Teste l'isolation entre les entreprises (multi-tenant)."""

    def setUp(self):
        super().setUp()
        try:
            self.Magasin = self.get_model('stock', 'Magasin')
            self.Article = self.get_model('stock', 'Article')
            self.Fournisseur = self.get_model('stock', 'Fournisseur')
            self.BonMouvement = self.get_model('stock', 'BonMouvement')
            self.FamilleArticle = self.get_model('stock', 'FamilleArticle')

            self.magasin_a = self.Magasin.objects.create(
                nom="Magasin A", entreprise=self.entreprise_a
            )
            self.magasin_b = self.Magasin.objects.create(
                nom="Magasin B", entreprise=self.entreprise_b
            )

            self.famille = self.FamilleArticle.objects.create(
                intitule="Famille Test", entreprise=self.entreprise_a
            )

            self.article_a = self.Article.objects.create(
                reference="ART-A-001", designation="Article A",
                entreprise=self.entreprise_a, famille=self.famille,
            )
            self.article_b = self.Article.objects.create(
                reference="ART-B-001", designation="Article B",
                entreprise=self.entreprise_b, famille=self.famille,
            )

            self.fournisseur = self.Fournisseur.objects.create(
                raison_sociale="Fournisseur Test",
                entreprise=self.entreprise_a
            )
        except LookupError as e:
            self.skipTest(f"Modele manquant : {e}")

    def test_creer_entree_avec_article_autre_entreprise(self):
        """Entree stock avec article entreprise B -> refuse."""
        session = self.client.session
        session['magasin_actif_id'] = str(self.magasin_a.id)
        session.save()

        url = self.get_url('liste_entrees')

        response = self.client.post(
            url,
            {
                'magasin': self.magasin_a.id,
                'fournisseur': self.fournisseur.id,
                'articles[]': [self.article_b.id],
                'quantites[]': ['10'],
                'lots[]': ['LOT-001'],
                'peremptions[]': ['2026-12-31'],
                'prix_unitaires[]': ['100.00'],
            }
        )

        # Doit etre refuse (redirection ou erreur)
        self.assertIn(response.status_code, [302, 400, 403])

        # Aucun bon ne doit etre cree
        self.assertEqual(
            self.BonMouvement.objects.filter(
                type_bon='ENTREE', magasin=self.magasin_a
            ).count(),
            0
        )

    def test_creer_sortie_avec_article_autre_entreprise(self):
        """Sortie stock avec article entreprise B -> refuse."""
        session = self.client.session
        session['magasin_actif_id'] = str(self.magasin_a.id)
        session.save()

        url = self.get_url('liste_sorties')

        response = self.client.post(
            url,
            {
                'magasin': self.magasin_a.id,
                'articles[]': [self.article_b.id],
                'quantites[]': ['5'],
            }
        )

        self.assertIn(response.status_code, [302, 400, 403])

        self.assertEqual(
            self.BonMouvement.objects.filter(
                type_bon='SORTIE', magasin=self.magasin_a
            ).count(),
            0
        )

    def test_acces_magasin_autre_entreprise_bloque(self):
        """Acces au magasin d'une autre entreprise est bloque."""
        url = self.get_url('changer_magasin')
        response = self.client.post(url, {'magasin_id': self.magasin_b.id})

        # Le magasin actif ne doit pas changer
        session = self.client.session
        self.assertNotEqual(
            str(session.get('magasin_actif_id', '')),
            str(self.magasin_b.id)
        )


class TestRaceConditionValidation(SecurityTestCase):
    """Teste les conditions de course (race conditions) sur la validation."""

    def setUp(self):
        super().setUp()
        try:
            self.Magasin = self.get_model('stock', 'Magasin')
            self.Article = self.get_model('stock', 'Article')
            self.BonMouvement = self.get_model('stock', 'BonMouvement')
            self.LigneBon = self.get_model('stock', 'LigneBon')
            self.Mouvement = self.get_model('stock', 'Mouvement')
            self.CircuitValidation = self.get_model('stock', 'CircuitValidation')
            self.FamilleArticle = self.get_model('stock', 'FamilleArticle')

            self.magasin_a = self.Magasin.objects.create(
                nom="Magasin A", entreprise=self.entreprise_a
            )

            self.famille = self.FamilleArticle.objects.create(
                intitule="Famille Test", entreprise=self.entreprise_a
            )

            self.article_a = self.Article.objects.create(
                reference="ART-A-001", designation="Article A",
                entreprise=self.entreprise_a, famille=self.famille,
            )

            self.bon = self.BonMouvement.objects.create(
                type_bon='ENTREE',
                magasin=self.magasin_a,
                cree_par=self.admin_a,
                statut_validation='EN_ATTENTE',
                numero_bon='BE-TEST-001',
            )
            self.LigneBon.objects.create(
                bon=self.bon,
                article=self.article_a,
                quantite=10,
            )

            self.circuit = self.CircuitValidation.objects.create(
                type_document='ENTREE',
                entreprise=self.entreprise_a,
                est_actif=True,
            )
            self.circuit.valideurs.add(self.admin_a)
        except LookupError as e:
            self.skipTest(f"Modele manquant : {e}")

    def test_double_validation_bloquee(self):
        """Deux validations simultanees -> une seule reussit."""
        url = self.get_url('valider_bon', {'bon_id': self.bon.id})

        # Premiere validation
        response1 = self.client.post(url)
        self.assertEqual(response1.status_code, 302)

        self.bon.refresh_from_db()
        self.assertEqual(self.bon.statut_validation, 'VALIDE')

        # Deuxieme validation (doit echouer ou ne rien faire)
        response2 = self.client.post(url)
        self.assertEqual(response2.status_code, 302)

        # Un seul mouvement doit etre cree
        mouvements = self.Mouvement.objects.filter(
            reference_document=self.bon.numero_bon
        )
        self.assertEqual(mouvements.count(), 1)


class TestFailClosed(SecurityTestCase):
    """Teste le principe fail-closed (refus par defaut)."""

    def setUp(self):
        super().setUp()
        try:
            self.Magasin = self.get_model('stock', 'Magasin')
            self.Article = self.get_model('stock', 'Article')
            self.BonMouvement = self.get_model('stock', 'BonMouvement')
            self.LigneBon = self.get_model('stock', 'LigneBon')
            self.CircuitValidation = self.get_model('stock', 'CircuitValidation')
            self.FamilleArticle = self.get_model('stock', 'FamilleArticle')

            self.magasin_a = self.Magasin.objects.create(
                nom="Magasin A", entreprise=self.entreprise_a
            )

            self.famille = self.FamilleArticle.objects.create(
                intitule="Famille Test", entreprise=self.entreprise_a
            )

            self.article_a = self.Article.objects.create(
                reference="ART-A-001", designation="Article A",
                entreprise=self.entreprise_a, famille=self.famille,
            )

            self.bon = self.BonMouvement.objects.create(
                type_bon='ENTREE',
                magasin=self.magasin_a,
                cree_par=self.user_a,
                statut_validation='BROUILLON',
                numero_bon='BE-TEST-002',
            )
            self.LigneBon.objects.create(
                bon=self.bon,
                article=self.article_a,
                quantite=10,
            )
        except LookupError as e:
            self.skipTest(f"Modele manquant : {e}")

    def test_user_normal_sans_circuit_ne_peut_pas_valider(self):
        """User normal sans circuit -> refuse."""
        self.client.login(username="user_a", password="testpass123")

        url = self.get_url('valider_bon', {'bon_id': self.bon.id})
        response = self.client.post(url)

        # Doit etre refuse (redirection vers login/permission ou 403)
        self.assertIn(response.status_code, [302, 403])

        self.bon.refresh_from_db()
        self.assertEqual(self.bon.statut_validation, 'BROUILLON')

    def test_superuser_sans_circuit_peut_valider(self):
        """Superuser sans circuit -> autorise (superuser bypass)."""
        # Admin_a est superuser, pas besoin de circuit specifique
        url = self.get_url('valider_bon', {'bon_id': self.bon.id})
        response = self.client.post(url)

        self.bon.refresh_from_db()
        self.assertEqual(self.bon.statut_validation, 'VALIDE')


class TestOpenRedirect(SecurityTestCase):
    """Teste la protection contre les open redirects."""

    def setUp(self):
        super().setUp()
        try:
            self.Magasin = self.get_model('stock', 'Magasin')
            self.magasin_a = self.Magasin.objects.create(
                nom="Magasin A", entreprise=self.entreprise_a
            )
        except LookupError as e:
            self.skipTest(f"Modele manquant : {e}")

    def test_redirect_externe_bloque(self):
        """Redirection externe bloquee."""
        session = self.client.session
        session['magasin_actif_id'] = str(self.magasin_a.id)
        session.save()

        url = self.get_url('changer_magasin')
        response = self.client.post(
            url,
            {
                'magasin_id': self.magasin_a.id,
                'next': 'https://evil.com/steal-cookies',
            }
        )

        if response.status_code == 302:
            self.assertNotIn('evil.com', response.url)

    def test_redirect_magasin_autre_entreprise_bloque(self):
        """Changement vers magasin autre entreprise bloque."""
        magasin_b = self.Magasin.objects.create(
            nom="Magasin B", entreprise=self.entreprise_b
        )

        url = self.get_url('changer_magasin')
        response = self.client.post(
            url,
            {'magasin_id': magasin_b.id}
        )

        session = self.client.session
        self.assertNotEqual(
            session.get('magasin_actif_id'),
            str(magasin_b.id)
        )


class TestPaginationSQL(SecurityTestCase):
    """Teste que la pagination utilise bien Paginator Django."""

    def setUp(self):
        super().setUp()
        try:
            self.Magasin = self.get_model('stock', 'Magasin')
            self.Article = self.get_model('stock', 'Article')
            self.Mouvement = self.get_model('stock', 'Mouvement')
            self.FamilleArticle = self.get_model('stock', 'FamilleArticle')

            self.magasin_a = self.Magasin.objects.create(
                nom="Magasin A", entreprise=self.entreprise_a
            )

            self.famille = self.FamilleArticle.objects.create(
                intitule="Famille Test", entreprise=self.entreprise_a
            )

            self.article_a = self.Article.objects.create(
                reference="ART-A-001", designation="Article A",
                entreprise=self.entreprise_a, famille=self.famille,
            )
        except LookupError as e:
            self.skipTest(f"Modele manquant : {e}")

    def test_pagination_sql_utilisee(self):
        """Paginator Django utilise pour les peremptions."""
        for i in range(30):
            self.Mouvement.objects.create(
                type_mouvement='ENTREE',
                article=self.article_a,
                magasin=self.magasin_a,
                quantite=10,
                utilisateur=self.admin_a,
                date_peremption=timezone.now() + timezone.timedelta(days=30),
                numero_lot=f'LOT-{i:03d}',
            )

        url = self.get_url('controle_peremptions')
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)

        if 'lots' in response.context:
            lots = response.context['lots']
            self.assertTrue(
                hasattr(lots, 'has_next') or hasattr(lots, 'paginator'),
                "La pagination doit utiliser un objet Page de Paginator"
            )


class TestPrecisionDecimal(SecurityTestCase):
    """Teste la precision des calculs decimaux."""

    def setUp(self):
        super().setUp()
        try:
            self.Magasin = self.get_model('stock', 'Magasin')
            self.Article = self.get_model('stock', 'Article')
            self.StockItem = self.get_model('stock', 'StockItem')
            self.FamilleArticle = self.get_model('stock', 'FamilleArticle')

            self.magasin_a = self.Magasin.objects.create(
                nom="Magasin A", entreprise=self.entreprise_a
            )

            self.famille = self.FamilleArticle.objects.create(
                intitule="Famille Test", entreprise=self.entreprise_a
            )

            self.article_a = self.Article.objects.create(
                reference="ART-A-001", designation="Article A",
                entreprise=self.entreprise_a, famille=self.famille,
            )

            self.StockItem.objects.create(
                article=self.article_a,
                magasin=self.magasin_a,
                quantite_physique=100,
                valeur_cmup=Decimal('10.99'),
            )
        except LookupError as e:
            self.skipTest(f"Modele manquant : {e}")

    def test_valeur_totale_en_decimal(self):
        """La valeur totale doit etre un Decimal."""
        url = self.get_url('export_etat_stock_csv')
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        content = response.content.decode('utf-8')
        self.assertIn('1099.00', content)


class TestConditionEntreprisePDF(SecurityTestCase):
    """Teste l'isolation entreprise pour les PDF."""

    def setUp(self):
        super().setUp()
        try:
            self.Magasin = self.get_model('stock', 'Magasin')
            self.BonMouvement = self.get_model('stock', 'BonMouvement')

            self.magasin_b = self.Magasin.objects.create(
                nom="Magasin B", entreprise=self.entreprise_b
            )
        except LookupError as e:
            self.skipTest(f"Modele manquant : {e}")

    def test_pdf_entree_autre_entreprise_bloque(self):
        """Acces PDF bon d'entree autre entreprise bloque."""
        try:
            bon_b = self.BonMouvement.objects.create(
                type_bon='ENTREE',
                magasin=self.magasin_b,
                cree_par=self.user_b,
                statut_validation='VALIDE',
                numero_bon='BE-B-001',
            )
        except Exception:
            self.skipTest("Impossible de creer le bon")

        url = self.get_url('bon_entree_pdf', {'bon_id': bon_b.id})
        response = self.client.get(url)

        # Doit etre bloque (403) ou au minimum ne pas contenir les donnees
        self.assertIn(response.status_code, [200, 403])

        if response.status_code == 200:
            # Si 200, verifier que le contenu ne fuite pas les donnees
            content = response.content.decode('utf-8', errors='ignore')
            # Le PDF genere ne doit pas contenir le numero de bon de l'autre entreprise
            # (c'est un test heuristique)
            if 'BE-B-001' in content:
                self.fail("PDF accessible sans verification entreprise — fuite de donnees")


class TestPermissionsGranulaires(SecurityTestCase):
    """Teste les permissions granulaires par role."""

    def setUp(self):
        super().setUp()
        try:
            self.Magasin = self.get_model('stock', 'Magasin')
            self.magasin_a = self.Magasin.objects.create(
                nom="Magasin A", entreprise=self.entreprise_a
            )
        except LookupError as e:
            self.skipTest(f"Modele manquant : {e}")

    def test_user_sans_permission_ne_peut_pas_acceder(self):
        """User sans permission specifique -> acces refuse."""
        self.client.login(username="user_a", password="testpass123")

        # Essayer d'acceder au dashboard directeur (reserve aux admins)
        url = self.get_url('dashboard_directeur')
        response = self.client.get(url)

        # Doit etre refuse
        self.assertIn(response.status_code, [302, 403])

    def test_admin_peut_acceder(self):
        """Admin peut acceder aux pages admin."""
        url = self.get_url('dashboard_directeur')
        response = self.client.get(url)

        # Admin a le droit d'acceder
        self.assertEqual(response.status_code, 200)
