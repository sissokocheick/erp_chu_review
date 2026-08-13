# -*- coding: utf-8 -*-
"""Tests du tableau de bord stock enrichi.

Vérifie les nouveaux indicateurs : flux entrées/sorties sur 14 jours,
valeur du stock par famille et par magasin, top entrées 30 jours, et
l'isolation par magasin actif (session).
"""
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from stock.models import (
    Magasin, FamilleArticle, Article, StockItem, Mouvement)

User = get_user_model()


class DashboardBase(TestCase):
    """Base : admin + 2 magasins + articles + mouvements variés."""

    def setUp(self):
        self.user = User.objects.create_superuser(
            username='dash_admin', password='dashpass2026',
            email='dash@chu.ci')
        self.user.profil.doit_changer_mdp = False
        self.user.profil.save(update_fields=['doit_changer_mdp'])
        self.client.login(username='dash_admin', password='dashpass2026')

        self.mag_a = Magasin.objects.create(nom='Magasin Principal')
        self.mag_b = Magasin.objects.create(nom='Annexe')

        self.famille_med = FamilleArticle.objects.create(
            code='MED', intitule='Medicaments')
        self.famille_mat = FamilleArticle.objects.create(
            code='MAT', intitule='Materiel')

        self.art_paracetamol = Article.objects.create(
            designation='Paracetamol 500mg', famille=self.famille_med,
            reference='DASH-P-001', prix_reference=Decimal('100'),
            seuil_minimum=10, seuil_critique=5)
        self.art_gants = Article.objects.create(
            designation='Gants chirurgicaux', famille=self.famille_mat,
            reference='DASH-G-001', prix_reference=Decimal('250'),
            seuil_minimum=20, seuil_critique=10)

        # Stock magasin A
        StockItem.objects.create(
            article=self.art_paracetamol, magasin=self.mag_a,
            quantite_physique=50, valeur_cmup=Decimal('95'))
        StockItem.objects.create(
            article=self.art_gants, magasin=self.mag_a,
            quantite_physique=100, valeur_cmup=Decimal('240'))
        # Stock magasin B
        StockItem.objects.create(
            article=self.art_paracetamol, magasin=self.mag_b,
            quantite_physique=2, valeur_cmup=Decimal('95'))

        self.maintenant = timezone.now()
        # Mouvements aujourd'hui (magasin A) : 10 entrées, 7 sorties.
        # update_stock=False : on n'applique pas l'effet sur le stock (les
        # KPIs de valeur doivent rester ceux définis explicitement ci-dessus).
        def _mvt(article, magasin, type_mvt, quantite):
            m = Mouvement(
                article=article, magasin=magasin, type_mouvement=type_mvt,
                quantite=quantite, date_mouvement=self.maintenant,
                utilisateur=self.user)
            m.save(update_stock=False)

        for _ in range(10):
            _mvt(self.art_paracetamol, self.mag_a, 'ENTREE', 5)
        for _ in range(7):
            _mvt(self.art_gants, self.mag_a, 'SORTIE', 2)
        # Mouvement magasin B (doit être exclu quand magasin A actif)
        _mvt(self.art_paracetamol, self.mag_b, 'ENTREE', 99)

    def _url(self):
        return reverse('dashboard_directeur')


class TestDashboardKPIs(DashboardBase):

    def test_page_charge_sans_erreur(self):
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)
        body = resp.content.decode('utf-8')
        self.assertNotIn('Traceback', body)
        self.assertNotIn('Internal Server Error', body)

    def test_page_contient_nouveaux_indicateurs(self):
        resp = self.client.get(self._url())
        body = resp.content.decode('utf-8')
        for marqueur in ('chartFlux', 'chartFamilles', 'chartEntrees',
                         'Valeur du stock par magasin', 'Top 5 Entrées',
                         'Flux entrées / sorties',
                         'Taux de rotation par famille',
                         'Couverture de stock', 'Rotation stock'):
            self.assertIn(marqueur, body, f'Marqueur absent : {marqueur}')

    def test_kpi_entrees_sorties_jour(self):
        resp = self.client.get(self._url())
        ctx = resp.context
        # Sans magasin actif : tous les magasins sont vus
        self.assertEqual(ctx['entrees_jour'], 11)  # 10 A + 1 B
        self.assertEqual(ctx['sorties_jour'], 7)

    def test_valeur_stock_total_cmup(self):
        """Valeur = Σ quantité × (valeur_cmup si > 0 sinon prix_ref)."""
        resp = self.client.get(self._url())
        attendu = 50 * 95 + 100 * 240 + 2 * 95  # = 29590
        self.assertEqual(resp.context['valeur_stock_total'], Decimal(attendu))

    def test_flux_14_jours_series_alignees(self):
        import json
        resp = self.client.get(self._url())
        ctx = resp.context
        labels = json.loads(ctx['flux_labels'])
        entrees = json.loads(ctx['flux_entrees'])
        sorties = json.loads(ctx['flux_sorties'])
        # 14 jours générés
        self.assertEqual(len(labels), 14)
        self.assertEqual(len(entrees), 14)
        self.assertEqual(len(sorties), 14)
        # Le jour d'aujourd'hui porte les quantités cumulées :
        # 10 entrées × 5 (A) + 1 entrée × 99 (B) = 149 ; 7 sorties × 2 = 14
        self.assertEqual(entrees[-1], 149)
        self.assertEqual(sorties[-1], 14)

    def test_valeur_par_famille(self):
        resp = self.client.get(self._url())
        if resp.status_code != 200:
            self.fail(f"Statut {resp.status_code} au lieu de 200 — redirect "
                      f"vers {resp.get('Location', '?')}")
        familles = {
            i['article__famille__intitule']: i['total']
            for i in resp.context['valeur_par_famille']
        }
        self.assertIn('Medicaments', familles)
        self.assertIn('Materiel', familles)
        self.assertEqual(familles['Medicaments'], Decimal(50 * 95 + 2 * 95))
        self.assertEqual(familles['Materiel'], Decimal(100 * 240))

    def test_valeur_par_magasin(self):
        resp = self.client.get(self._url())
        magasins = {
            i['magasin__nom']: i['total']
            for i in resp.context['valeur_par_magasin']
        }
        self.assertIn('Magasin Principal', magasins)
        self.assertIn('Annexe', magasins)
        self.assertEqual(magasins['Magasin Principal'], Decimal(50 * 95 + 100 * 240))
        self.assertEqual(magasins['Annexe'], Decimal(2 * 95))

    def test_rotation_globale_30j(self):
        """Rotation globale = Σ sorties 30j ÷ Σ stock actuel."""
        resp = self.client.get(self._url())
        # Sorties : 7 × 2 (gants) = 14 ; stock total : 50+2+100 = 152
        self.assertEqual(resp.context['rotation_globale_30j'], 0.09)

    def test_rotation_par_famille(self):
        resp = self.client.get(self._url())
        rotations = {
            r['famille']: r for r in resp.context['rotation_par_famille']}
        self.assertIn('Materiel', rotations)
        self.assertIn('Medicaments', rotations)
        # Materiel : 14 sorties / 100 en stock = 0.14× → 214,3 j de couverture
        self.assertEqual(rotations['Materiel']['sorties'], 14)
        self.assertEqual(rotations['Materiel']['stock'], 100)
        self.assertEqual(rotations['Materiel']['taux'], 0.14)
        self.assertEqual(rotations['Materiel']['couverture'], 214.3)
        # Medicaments : aucune sortie → taux 0, pas de couverture
        self.assertEqual(rotations['Medicaments']['taux'], 0)
        self.assertIsNone(rotations['Medicaments']['couverture'])

    def test_rotation_triee_par_taux_decroissant(self):
        resp = self.client.get(self._url())
        familles = [r['famille'] for r in resp.context['rotation_par_famille']]
        # Materiel (0.14×) devant Medicaments (0×)
        self.assertEqual(familles, ['Materiel', 'Medicaments'])

    def test_couverture_triee_par_urgence(self):
        resp = self.client.get(self._url())
        couvertures = [
            r['couverture'] for r in resp.context['rotation_par_couverture']
            if r['couverture'] is not None]
        self.assertEqual(couvertures, sorted(couvertures))

    def test_rotation_stock_epuise(self):
        """Famille avec sorties mais stock à zéro → pas de taux, couverture 0 j."""
        famille_urg = FamilleArticle.objects.create(
            code='URG', intitule='Urgence')
        art = Article.objects.create(
            designation='Seringue 5ml', famille=famille_urg,
            reference='DASH-URG-001')
        StockItem.objects.create(
            article=art, magasin=self.mag_a, quantite_physique=0)
        m = Mouvement(
            article=art, magasin=self.mag_a, type_mouvement='SORTIE',
            quantite=30, date_mouvement=self.maintenant,
            utilisateur=self.user)
        m.save(update_stock=False)  # stock déjà à 0 : on ne touche pas au stock
        resp = self.client.get(self._url())
        urg = next(r for r in resp.context['rotation_par_famille']
                   if r['famille'] == 'Urgence')
        self.assertEqual(urg['sorties'], 30)
        self.assertEqual(urg['stock'], 0)
        self.assertIsNone(urg['taux'])
        self.assertEqual(urg['couverture'], 0)  # épuisé : le plus urgent

    def test_top_entrees_present(self):
        import json
        resp = self.client.get(self._url())
        labels = json.loads(resp.context['chart_entrees_labels'])
        # Top entrées : paracétamol (50 A + 99 B = 149) devant gants (0)
        self.assertEqual(labels, ['Paracetamol 500mg'])

    def test_charts_articles_services_par_defaut(self):
        import json
        resp = self.client.get(self._url())
        # Top sorties : seul les gants ont des sorties (7 × 2)
        self.assertEqual(
            json.loads(resp.context['chart_articles_labels']),
            ['Gants chirurgicaux'])
        # Pas de service demandeur → services vides mais sérialisés
        self.assertEqual(resp.context['chart_services_labels'], '[]')


class TestDashboardIsolationMagasin(DashboardBase):

    def _activer_magasin(self, magasin):
        session = self.client.session
        session['magasin_actif_id'] = str(magasin.id)
        session.save()

    def test_entrees_sorties_scopes_magasin_actif(self):
        self._activer_magasin(self.mag_a)
        resp = self.client.get(self._url())
        self.assertEqual(resp.context['entrees_jour'], 10)
        self.assertEqual(resp.context['sorties_jour'], 7)
        # Le magasin actif est exposé au template
        self.assertEqual(resp.context['magasin_actif'].id, self.mag_a.id)

    def test_valeur_stock_scopee_magasin_actif(self):
        self._activer_magasin(self.mag_b)
        resp = self.client.get(self._url())
        self.assertEqual(resp.context['valeur_stock_total'], Decimal(2 * 95))

    def test_valeur_par_magasin_filtree(self):
        """Avec magasin B actif, la répartition ne montre que B."""
        self._activer_magasin(self.mag_b)
        resp = self.client.get(self._url())
        magasins = [i['magasin__nom'] for i in resp.context['valeur_par_magasin']]
        self.assertEqual(magasins, ['Annexe'])

    def test_flux_scopes_magasin_actif(self):
        import json
        self._activer_magasin(self.mag_b)
        resp = self.client.get(self._url())
        # Magasin B : 1 entrée de 99, aucune sortie
        self.assertEqual(json.loads(resp.context['flux_entrees'])[-1], 99)
        self.assertEqual(json.loads(resp.context['flux_sorties'])[-1], 0)

    def test_rotation_scopee_magasin_actif(self):
        """Magasin B actif : seuls ses stocks/sorties comptent."""
        self._activer_magasin(self.mag_b)
        resp = self.client.get(self._url())
        rotations = {
            r['famille']: r for r in resp.context['rotation_par_famille']}
        self.assertEqual(rotations['Medicaments']['stock'], 2)
        self.assertEqual(rotations['Medicaments']['sorties'], 0)
        self.assertNotIn('Materiel', rotations)
        # Aucune sortie sur le magasin B → rotation globale 0
        self.assertEqual(resp.context['rotation_globale_30j'], 0)


class TestDashboardSansMagasin(DashboardBase):
    """Aucun magasin actif → les données de tous les magasins sont montrées."""

    def test_magasin_actif_absent_du_contexte(self):
        resp = self.client.get(self._url())
        self.assertIsNone(resp.context['magasin_actif'])

    def test_page_sans_donnees_charge(self):
        import json
        # Vide les mouvements et stocks pour vérifier les états vides
        Mouvement.objects.all().delete()
        StockItem.objects.all().delete()
        resp = self.client.get(self._url())
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['valeur_stock_total'], 0)
        self.assertEqual(json.loads(resp.context['flux_entrees'])[-1], 0)
        self.assertEqual(resp.context['chart_familles_labels'], '[]')
        # Rotation : aucun stock → indicateur neutre, tableaux vides
        self.assertIsNone(resp.context['rotation_globale_30j'])
        self.assertEqual(resp.context['rotation_par_famille'], [])
        self.assertEqual(resp.context['rotation_par_couverture'], [])
