# -*- coding: utf-8 -*-
"""
Garde-fous de performance : plafonne le nombre de requêtes SQL par page.

Objectif : détecter immédiatement une régression N+1 (requête par ligne)
sur les pages les plus consultées. Si une vue ajoute une requête par
ligne dans une boucle, le compteur explose et le test échoue.

Valeurs mesurées (300 articles / 3000 mouvements / 100 bons) :
    dashboard           52 requêtes
    etat_stock          14
    liste_articles      14
    liste_sorties       14
    historique          14
    peremptions         14
    liste_commandes     14
Les plafonds laissent une marge de sécurité.
"""
from decimal import Decimal
from random import choice, randint

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection

from core.models import Service
from stock.models import (
    Article, Magasin, StockItem, Mouvement, BonMouvement, LigneBon,
)
from stock.tests import factories

User = get_user_model()


class PerfGuardTest(TestCase):
    """Plafonds de requêtes sur les pages lourdes."""

    def setUp(self):
        self.user = User.objects.create_superuser(
            username='perf', password='perfpass2026')
        self.user.profil.doit_changer_mdp = False
        self.user.profil.save(update_fields=['doit_changer_mdp'])

        self.famille = factories.creer_famille(code='PERF', intitule='Perf')
        self.mag_a = factories.creer_magasin(nom='Perf Mag A')
        self.mag_b = factories.creer_magasin(nom='Perf Mag B')
        self.user.profil.magasins_autorises.add(self.mag_a, self.mag_b)

        articles = [
            Article.objects.create(
                famille=self.famille, designation=f'Art Perf {i:02d}',
                reference=f'PERF-{i:03d}',
                prix_reference=Decimal(f'{randint(100, 9000)}.00'))
            for i in range(30)
        ]
        for art in articles:
            for mag in (self.mag_a, self.mag_b):
                StockItem.objects.create(
                    article=art, magasin=mag,
                    quantite_physique=randint(0, 200),
                    valeur_cmup=Decimal(f'{randint(50, 5000)}.00'))

        services = [
            Service.objects.create(code=f'SRV-{i}', nom=f'Service Perf {i}')
            for i in range(5)
        ]
        for i in range(200):
            Mouvement(
                type_mouvement=choice(
                    ['ENTREE', 'SORTIE', 'SORTIE_HORS_STOCK',
                     'RETOUR_SERVICE', 'AJUSTEMENT_POS', 'AJUSTEMENT_NEG']),
                article=choice(articles), magasin=choice([self.mag_a, self.mag_b]),
                quantite=randint(1, 50),
                utilisateur=self.user,
                service_demandeur=choice(services),
                reference_document=f'PM-{i:04d}',
            ).save(update_stock=False)

        for i in range(10):
            bon = BonMouvement.objects.create(
                type_bon='SORTIE', magasin=self.mag_a,
                service_demandeur=choice(services),
                cree_par=self.user)
            for _ in range(3):
                LigneBon.objects.create(
                    bon=bon, article=choice(articles),
                    quantite=randint(1, 20))

        self.client.force_login(self.user)
        session = self.client.session
        session['magasin_actif_id'] = self.mag_a.id
        session.save()

    def _assert_nb_queries(self, url, plafond, label):
        with CaptureQueriesContext(connection) as ctx:
            resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200, f'{label} : {resp.status_code}')
        nb = len(ctx.captured_queries)
        self.assertLessEqual(
            nb, plafond,
            f'{label} : {nb} requêtes SQL (plafond {plafond}) — '
            f'régression N+1 probable')

    def test_dashboard_requetes_plafonnees(self):
        self._assert_nb_queries('/', 65, 'dashboard /')

    def test_etat_stock_requetes_plafonnees(self):
        self._assert_nb_queries('/etat-stock/', 25, 'etat_stock')

    def test_liste_articles_requetes_plafonnees(self):
        self._assert_nb_queries('/articles/?q=Perf', 25, 'liste_articles')

    def test_liste_sorties_requetes_plafonnees(self):
        self._assert_nb_queries('/sorties/', 25, 'liste_sorties')

    def test_historique_requetes_plafonnees(self):
        self._assert_nb_queries('/administration/historique/', 25,
                                'historique mouvements')

    def test_peremptions_requetes_plafonnees(self):
        self._assert_nb_queries('/stock/peremptions/', 25, 'peremptions')
