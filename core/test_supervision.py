# -*- coding: utf-8 -*-
"""Tests du tableau de bord de supervision (vue + helpers)."""
import os
import tempfile
from pathlib import Path
from unittest import mock

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from core.logging_filters import SlowQueryFilter
from core.supervision import (
    _taille_lisible,
    lister_erreurs_logs,
    lister_requetes_lentes,
    lister_sauvegardes,
    taille_base,
    usage_disque,
)


@override_settings(ROOT_URLCONF='config.urls')
class SupervisionViewTest(TestCase):
    def setUp(self):
        self.superuser = User.objects.create_superuser(username='sup', password='x')
        self.user = User.objects.create_user(username='simple', password='x')
        for u in (self.superuser, self.user):
            profil = u.profil
            profil.doit_changer_mdp = False
            profil.save()

    def test_acces_reserve_au_superuser(self):
        self.client.force_login(self.user)
        resp = self.client.get(reverse('supervision'))
        self.assertEqual(resp.status_code, 403)

    def test_anonyme_redirige_vers_login(self):
        resp = self.client.get(reverse('supervision'))
        self.assertEqual(resp.status_code, 302)
        self.assertIn('/auth/login/', resp.url)

    def test_superuser_voit_la_page(self):
        self.client.force_login(self.superuser)
        resp = self.client.get(reverse('supervision'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Tableau de bord de supervision')
        # Statut de santé présent
        self.assertContains(resp, 'BASE')
        self.assertContains(resp, 'Sauvegardes PostgreSQL')
        # Métriques de performance
        self.assertContains(resp, 'Requêtes lentes')
        self.assertContains(resp, 'Espace disque utilisé')
        self.assertContains(resp, 'Taille de la base')

    def test_statut_erreur_base_visible(self):
        self.client.force_login(self.superuser)
        with mock.patch('core.health.check_database',
                        return_value=('error', 'connexion refusée')):
            resp = self.client.get(reverse('supervision'))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'error')
        self.assertContains(resp, 'connexion refusée')


class SupervisionHelpersTest(TestCase):
    def test_lister_sauvegardes_fichiers_reels(self):
        dossier = Path(settings.BASE_DIR) / 'backups'
        dossier.mkdir(parents=True, exist_ok=True)
        # Deux faux backups (noms attendus par backup_db.py)
        for nom, contenu in (('chu_angre_db_20260101.backup', b'x' * 2048),
                             ('chu_angre_db_20260102.backup', b'y' * 1024)):
            (dossier / nom).write_bytes(contenu)
            os.utime(dossier / nom, (1700000000, 1700000000))
        os.utime(dossier / 'chu_angre_db_20260102.backup', (1700000100, 1700000100))
        try:
            resultats = lister_sauvegardes(limit=5)
            self.assertEqual(len(resultats), 2)
            # Le plus récent en premier (date dans le nom 20260102 > 20260101)
            self.assertEqual(resultats[0]['nom'], 'chu_angre_db_20260102.backup')
            self.assertEqual(resultats[0]['taille'], 1024)
            self.assertEqual(resultats[0]['taille_lisible'], '1 Ko')
        finally:
            for nom in ('chu_angre_db_20260101.backup', 'chu_angre_db_20260102.backup'):
                (dossier / nom).unlink(missing_ok=True)

    def test_lister_erreurs_logs(self):
        dossier = Path(settings.BASE_DIR) / 'logs'
        dossier.mkdir(parents=True, exist_ok=True)
        f = dossier / 'test_supervision.log'
        f.write_text(
            '2026-01-01 10:00:00 INFO requete ok\n'
            '2026-01-01 10:00:01 ERROR boom\n'
            '2026-01-01 10:00:02 Traceback (most recent call last):\n'
            '2026-01-01 10:00:03   File "x.py", line 1\n',
            encoding='utf-8',
        )
        try:
            erreurs = lister_erreurs_logs(limit=10)
            # 2 lignes d'erreur (ERROR + Traceback), la plus récente en premier
            self.assertEqual(len(erreurs), 2)
            self.assertEqual(erreurs[0]['fichier'], 'test_supervision.log')
            self.assertIn('Traceback', erreurs[0]['texte'])
            self.assertIn('ERROR boom', erreurs[1]['texte'])
        finally:
            f.unlink(missing_ok=True)

    def test_aucun_dossier_retourne_vide(self):
        with mock.patch.object(settings, 'BASE_DIR', Path(settings.BASE_DIR) / 'inexistant_xyz'):
            self.assertEqual(lister_sauvegardes(), [])
            self.assertEqual(lister_erreurs_logs(), [])

    def test_taille_lisible(self):
        self.assertEqual(_taille_lisible(500), '500 o')
        self.assertEqual(_taille_lisible(2048), '2 Ko')
        self.assertEqual(_taille_lisible(3 * 1024 * 1024), '3.0 Mo')
        self.assertEqual(_taille_lisible(2 * 1024 * 1024 * 1024), '2.0 Go')

    def test_taille_base_sqlite_positive(self):
        octets = taille_base()
        self.assertIsNotNone(octets)
        self.assertGreater(octets, 0)

    def test_usage_disque(self):
        disque = usage_disque()
        self.assertIsNotNone(disque)
        self.assertGreater(disque['total'], 0)
        self.assertGreater(disque['libre'], 0)
        self.assertIn('dossiers', disque)
        self.assertIn('logs', disque['dossiers'])
        self.assertIn('pourcentage', disque)

    def test_lister_requetes_lentes_parse_et_trie(self):
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.log')
        tmp.close()
        f = Path(tmp.name)
        f.write_text(
            '[2026-08-14 10:00:00] DEBUG (0.512) SELECT * FROM articles; args=(1,); alias=default\n'
            '[2026-08-14 10:00:01] DEBUG (0.050) SELECT 1; args=(); alias=default\n'
            '[2026-08-14 10:00:02] DEBUG (1.234) SELECT * FROM mouvements; args=(); alias=default\n',
            encoding='utf-8',
        )
        try:
            resultats = lister_requetes_lentes(limit=10, fichier=f)
            # Toutes les lignes du fichier (le filtre de log fait le seuil à l'écriture)
            self.assertEqual(len(resultats), 3)
            self.assertEqual(resultats[0]['ms'], 1234)   # plus récente en premier
            self.assertEqual(resultats[0]['sql'], 'SELECT * FROM mouvements')
            self.assertNotIn('args=', resultats[0]['sql'])  # données retirées
            self.assertEqual(resultats[2]['ms'], 512)
        finally:
            f.unlink(missing_ok=True)

    def test_aucune_requete_lente_sans_fichier(self):
        self.assertEqual(lister_requetes_lentes(fichier=Path(settings.BASE_DIR) / 'logs' / 'inexistant-xyz.log'), [])


class SlowQueryFilterTest(TestCase):
    def test_garde_seulement_les_lentes(self):
        filtre = SlowQueryFilter(threshold=0.2)
        rapide = type('R', (), {'duration': 0.05})()
        lente = type('R', (), {'duration': 0.5})()
        sans_duree = type('R', (), {})()
        self.assertFalse(filtre.filter(rapide))
        self.assertTrue(filtre.filter(lente))
        self.assertFalse(filtre.filter(sans_duree))

    def test_seuil_par_defaut_200ms(self):
        filtre = SlowQueryFilter()
        self.assertEqual(filtre.threshold, 0.2)
        self.assertTrue(filtre.filter(type('R', (), {'duration': 0.2})()))
