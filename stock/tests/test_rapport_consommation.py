# -*- coding: utf-8 -*-
"""
Tests du rapport mensuel de consommation par service.

Couvre : agrégation par service (quantités, valeurs), évolution mensuelle,
filtres (période, service, magasin actif), exclusion des destructions, et
export CSV du même rapport.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Service
from stock.models import Article, Mouvement, StockItem
from stock.tests import factories


class BaseConsommationTest(TestCase):
    def setUp(self):
        self.user = factories.creer_superuser(username='consom_admin')
        self.user.profil.doit_changer_mdp = False
        self.user.profil.save(update_fields=['doit_changer_mdp'])
        self.magasin = factories.creer_magasin(nom='Magasin Consommation')
        self.magasin2 = factories.creer_magasin(nom='Magasin Autre')
        self.user.profil.magasins_autorises.add(self.magasin, self.magasin2)

        self.famille = factories.creer_famille(code='CONS', intitule='Conso')
        self.article = factories.creer_article(
            famille=self.famille, designation='Gants', reference='CONS-1',
            prix_reference=Decimal('500.00'))
        self.article2 = factories.creer_article(
            famille=self.famille, designation='Masques', reference='CONS-2',
            prix_reference=Decimal('100.00'))

        self.service_a = Service.objects.create(code='CAR', nom='Cardiologie')
        self.service_b = Service.objects.create(code='URG', nom='Urgences')
        self.service_rebuts = Service.objects.create(
            code='REBUTS', nom='DESTRUCTION / PÉREMPTIONS')

        self.client.force_login(self.user)
        session = self.client.session
        session['magasin_actif_id'] = str(self.magasin.id)
        session.save()

    def _mouvement(self, article, service, quantite, prix=None,
                   magasin=None, type_mvt='SORTIE', jours_ecoules=0):
        Mouvement(
            type_mouvement=type_mvt,
            article=article,
            magasin=magasin or self.magasin,
            quantite=quantite,
            prix_unitaire=prix,
            utilisateur=self.user,
            service_demandeur=service,
            date_mouvement=timezone.now() - timedelta(days=jours_ecoules),
            reference_document='CONS-TEST',
        ).save(update_stock=False)

    def _get_rapport(self, **params):
        url = reverse('rapport_consommation_services')
        if params:
            url += '?' + '&'.join(f'{k}={v}' for k, v in params.items())
        return self.client.get(url)


class RapportConsommationTest(BaseConsommationTest):

    def test_page_rendue_avec_agregats_par_service(self):
        self._mouvement(self.article, self.service_a, 10)   # 10 × 500 = 5000
        self._mouvement(self.article2, self.service_a, 5, prix=Decimal('200.00'))  # 5 × 200 = 1000
        self._mouvement(self.article2, self.service_b, 3)   # 3 × 100 = 300
        resp = self._get_rapport()
        self.assertEqual(resp.status_code, 200)
        par_service = {r['service_demandeur__id']: r
                       for r in resp.context['par_service']}
        a = par_service[self.service_a.id]
        b = par_service[self.service_b.id]
        self.assertEqual(a['quantite'], 15)
        self.assertEqual(a['valeur'], Decimal('6000.00'))
        self.assertEqual(a['nb_mouvements'], 2)
        self.assertEqual(b['quantite'], 3)
        self.assertEqual(b['valeur'], Decimal('300.00'))
        self.assertEqual(resp.context['total_quantite'], 18)
        self.assertEqual(resp.context['total_valeur'], Decimal('6300.00'))
        self.assertEqual(resp.context['total_mouvements'], 3)

    def test_evolution_mensuelle_serie_complete(self):
        # 2 mouvements dans le mois courant
        self._mouvement(self.article, self.service_a, 7)
        self._mouvement(self.article2, self.service_a, 3)
        import json
        resp = self._get_rapport(mois='3')
        labels = json.loads(resp.context['chart_labels'])
        qte = json.loads(resp.context['chart_qte'])
        self.assertEqual(len(labels), 3)  # 3 mois consécutifs
        # Le mois courant contient 10 unités
        self.assertEqual(qte[-1], 10)
        # Les mois vides sont à 0
        self.assertEqual(qte[0], 0)

    def test_filtre_par_service(self):
        self._mouvement(self.article, self.service_a, 10)
        self._mouvement(self.article2, self.service_b, 8)
        resp = self._get_rapport(service=self.service_b.id)
        ids = [r['service_demandeur__id']
               for r in resp.context['par_service']]
        self.assertEqual(ids, [self.service_b.id])
        self.assertEqual(resp.context['total_quantite'], 8)

    def test_exclusion_des_destructions(self):
        self._mouvement(self.article, self.service_a, 10)
        self._mouvement(self.article2, self.service_rebuts, 50)
        resp = self._get_rapport()
        ids = [r['service_demandeur__id']
               for r in resp.context['par_service']]
        self.assertNotIn(self.service_rebuts.id, ids)
        self.assertEqual(resp.context['total_quantite'], 10)

    def test_isolation_magasin_actif(self):
        self._mouvement(self.article, self.service_a, 10)
        self._mouvement(self.article2, self.service_a, 99,
                        magasin=self.magasin2)
        resp = self._get_rapport()
        self.assertEqual(resp.context['total_quantite'], 10)

    def test_periode_date_range(self):
        self._mouvement(self.article, self.service_a, 10, jours_ecoules=400)
        resp = self._get_rapport(
            date_range='01/01/2020 - 31/12/2020')
        self.assertEqual(resp.context['total_quantite'], 0)
        self.assertEqual(resp.context['total_mouvements'], 0)

    def test_hors_stock_inclus_dans_la_consommation(self):
        self._mouvement(self.article, self.service_a, 10,
                        type_mvt='SORTIE_HORS_STOCK')
        resp = self._get_rapport()
        self.assertEqual(resp.context['total_quantite'], 10)


class ExportConsommationTest(BaseConsommationTest):

    def test_export_csv_contenu(self):
        self._mouvement(self.article, self.service_a, 10)
        self._mouvement(self.article2, self.service_b, 3)
        resp = self.client.get(reverse('export_consommation_services_csv'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp['Content-Type'], 'text/csv; charset=utf-8')
        contenu = resp.content.decode('utf-8-sig')
        lignes = [l for l in contenu.splitlines() if l.strip()]
        self.assertEqual(
            lignes[0],
            'Service;Code;Quantité (unités);Valeur (FCFA);Nb mouvements;Période')
        self.assertTrue(any('Cardiologie' in l for l in lignes))
        self.assertTrue(any('Urgences' in l for l in lignes))
        # 1 en-tête + 2 services
        self.assertEqual(len(lignes), 3)

    def test_export_respecte_le_filtre_service(self):
        self._mouvement(self.article, self.service_a, 10)
        self._mouvement(self.article2, self.service_b, 3)
        resp = self.client.get(
            reverse('export_consommation_services_csv'),
            {'service': self.service_b.id})
        contenu = resp.content.decode('utf-8-sig')
        lignes = [l for l in contenu.splitlines() if l.strip()]
        self.assertEqual(len(lignes), 2)  # en-tête + Urgences
        self.assertIn('Urgences', contenu)
        self.assertNotIn('Cardiologie', contenu)

    def test_export_exclut_destructions_et_magasin_autre(self):
        self._mouvement(self.article, self.service_a, 10)
        self._mouvement(self.article2, self.service_rebuts, 40)
        self._mouvement(self.article2, self.service_a, 30,
                        magasin=self.magasin2)
        resp = self.client.get(reverse('export_consommation_services_csv'))
        contenu = resp.content.decode('utf-8-sig')
        self.assertNotIn('DESTRUCTION', contenu)
        # Seul le mouvement du magasin actif compte (10), pas 40
        self.assertNotIn(';40;', contenu)
