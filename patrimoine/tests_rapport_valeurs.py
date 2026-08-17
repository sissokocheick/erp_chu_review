# -*- coding: utf-8 -*-
"""
Tests du rapport mensuel de valeur des immobilisations par service.

Couvre : agrégation par service (nb, valeur d'acquisition, amortissement,
VNC), détail par service × type d'équipement, filtres (période, service,
exclusion des sortis), tri par clic, exports CSV (résumé + détail) et
génération du PDF.
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from core.models import Service
from patrimoine.models import CategoriePatrimoine, Immobilisation, TypeEquipement
from patrimoine.tests_extended import creer_immobilisation
from stock.tests import factories


class BaseRapportValeursTest(TestCase):
    def setUp(self):
        self.user = factories.creer_superuser(username='pat_rapport')
        self.user.profil.doit_changer_mdp = False
        self.user.profil.save(update_fields=['doit_changer_mdp'])
        self.service_a = Service.objects.create(code='CAR', nom='Cardiologie')
        self.service_b = Service.objects.create(code='URG', nom='Urgences')
        self.cat = CategoriePatrimoine.objects.create(
            code='CAT-R', nom='Catégorie Rapport')
        self.type_pc = TypeEquipement.objects.create(
            code='PC-R', nom='Ordinateur Portable', categorie=self.cat)
        self.type_imp = TypeEquipement.objects.create(
            code='IMP-R', nom='Imprimante', categorie=self.cat)
        self.client.force_login(self.user)

    def _immo(self, valeur, service, type_eq, jours=365, statut='ACTIF',
              date_acq=None, duree=5):
        """Crée un bien : VNC = valeur - (valeur/durée × années écoulées)."""
        return creer_immobilisation(
            valeur, duree, 0, jours_ecoules=jours,
            service_affectation=service, type_equipement=type_eq,
            statut=statut,
            date_acquisition=date_acq or (
                timezone.now().date() - timedelta(days=jours or 1)),
        )

    def _get(self, **params):
        url = reverse('patrimoine_rapport_valeurs')
        if params:
            url += '?' + '&'.join(f'{k}={v}' for k, v in params.items())
        return self.client.get(url)


class RapportValeurServicesTest(BaseRapportValeursTest):

    def test_agregation_par_service(self):
        # Cardio : 2 biens (100000 + 50000), 1 an → amorti 1/5
        self._immo(100000, self.service_a, self.type_pc)
        self._immo(50000, self.service_a, self.type_imp)
        # Urgences : 1 bien
        self._immo(200000, self.service_b, self.type_pc)

        resp = self._get()
        self.assertEqual(resp.status_code, 200)
        par_service = {r['service_demandeur__nom']: r
                       for r in resp.context['par_service']}
        a = par_service['Cardiologie']
        b = par_service['Urgences']
        self.assertEqual(a['nb'], 2)
        self.assertEqual(a['valeur_acq'], Decimal('150000.00'))
        # Amorti 1 an : 100000/5 + 50000/5 = 30000
        self.assertEqual(a['amorti'], Decimal('30000.00'))
        self.assertEqual(a['vnc'], Decimal('120000.00'))
        self.assertEqual(b['nb'], 1)
        self.assertEqual(b['valeur_acq'], Decimal('200000.00'))
        self.assertEqual(b['vnc'], Decimal('160000.00'))
        self.assertEqual(resp.context['total_nb'], 3)
        self.assertEqual(resp.context['total_acq'], Decimal('350000.00'))
        self.assertEqual(resp.context['total_vnc'], Decimal('280000.00'))

    def test_detail_par_service_et_type(self):
        self._immo(100000, self.service_a, self.type_pc)
        self._immo(50000, self.service_a, self.type_imp)
        resp = self._get()
        detail = resp.context['par_svc_type']
        self.assertEqual(len(detail), 2)
        par = {(r['service_demandeur__nom'], r['type__nom']): r for r in detail}
        self.assertEqual(par[('Cardiologie', 'Ordinateur Portable')]['nb'], 1)
        self.assertEqual(par[('Cardiologie', 'Ordinateur Portable')]['valeur_acq'],
                         Decimal('100000.00'))
        self.assertEqual(par[('Cardiologie', 'Imprimante')]['nb'], 1)

    def test_exclusion_des_sortis_par_defaut(self):
        self._immo(100000, self.service_a, self.type_pc)
        self._immo(50000, self.service_a, self.type_pc, statut='REFORME')
        resp = self._get()
        self.assertEqual(resp.context['total_nb'], 1)
        self.assertEqual(resp.context['total_vnc'], Decimal('80000.00'))

    def test_inclure_sortis(self):
        self._immo(100000, self.service_a, self.type_pc)
        self._immo(50000, self.service_a, self.type_pc, statut='CEDE')
        resp = self._get(inclure_sortis='1')
        self.assertEqual(resp.context['total_nb'], 2)

    def test_filtre_par_service(self):
        self._immo(100000, self.service_a, self.type_pc)
        self._immo(200000, self.service_b, self.type_pc)
        resp = self._get(service=self.service_b.id)
        noms = [r['service_demandeur__nom'] for r in resp.context['par_service']]
        self.assertEqual(noms, ['Urgences'])
        self.assertEqual(resp.context['total_nb'], 1)

    def test_evolution_mensuelle_serie_complete(self):
        self._immo(100000, self.service_a, self.type_pc,
                   date_acq=timezone.now().date())
        self._immo(50000, self.service_a, self.type_pc,
                   date_acq=timezone.now().date() - timedelta(days=90))
        import json
        resp = self._get(mois='6')
        labels = json.loads(resp.context['chart_labels'])
        nb = json.loads(resp.context['chart_nb'])
        val = json.loads(resp.context['chart_valeur'])
        self.assertEqual(len(labels), 6)
        self.assertEqual(nb[-1], 1)
        self.assertEqual(float(val[-1]), 100000.0)
        # Le mois ~90 jours en arrière contient le 2e bien
        self.assertEqual(sum(nb), 2)

    def test_tri_par_clic_sur_service(self):
        self._immo(100000, self.service_a, self.type_pc)
        self._immo(50000, self.service_b, self.type_pc)
        resp = self._get(tri='vnc', ordre='asc')
        noms = [r['service_demandeur__nom'] for r in resp.context['par_service']]
        # Urgences (40000 VNC) avant Cardiologie (80000)
        self.assertEqual(noms, ['Urgences', 'Cardiologie'])

    def test_liens_de_tri_dans_html(self):
        self._immo(100000, self.service_a, self.type_pc)
        resp = self._get()
        html = resp.content.decode()
        self.assertIn('tri=service', html)
        self.assertIn('tri=vnc', html)
        self.assertIn('dtri=type', html)
        self.assertIn('dtri=vnc', html)


class ExportValeursTest(BaseRapportValeursTest):

    def test_export_csv_resume(self):
        self._immo(100000, self.service_a, self.type_pc)
        self._immo(50000, self.service_b, self.type_pc)
        resp = self.client.get(reverse('patrimoine_rapport_valeurs_csv'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'text/csv; charset=utf-8')
        contenu = resp.content.decode('utf-8-sig')
        lignes = [l for l in contenu.splitlines() if l.strip()]
        self.assertEqual(
            lignes[0],
            'Service;Nb biens;Valeur d\'acquisition (FCFA);'
            'Amortissement cumulé (FCFA);VNC (FCFA);Période')
        self.assertEqual(len(lignes), 3)  # en-tête + 2 services
        self.assertTrue(any('Cardiologie;1;100000,00' in l for l in lignes))
        self.assertTrue(any('Urgences;1;50000,00' in l for l in lignes))

    def test_export_csv_detail(self):
        self._immo(100000, self.service_a, self.type_pc)
        self._immo(50000, self.service_a, self.type_imp)
        resp = self.client.get(reverse('patrimoine_rapport_valeurs_detail_csv'))
        contenu = resp.content.decode('utf-8-sig')
        lignes = [l for l in contenu.splitlines() if l.strip()]
        self.assertEqual(len(lignes), 3)  # en-tête + 2 types
        self.assertTrue(any('Ordinateur Portable' in l for l in lignes))
        self.assertTrue(any('Imprimante' in l for l in lignes))

    def test_export_respecte_filtre_service_et_exclusions(self):
        self._immo(100000, self.service_a, self.type_pc)
        self._immo(50000, self.service_b, self.type_pc, statut='REFORME')
        resp = self.client.get(
            reverse('patrimoine_rapport_valeurs_csv'),
            {'service': self.service_b.id})
        contenu = resp.content.decode('utf-8-sig')
        self.assertNotIn('Cardiologie', contenu)
        # Le bien réformé est exclu → aucune ligne de données
        lignes = [l for l in contenu.splitlines() if l.strip()]
        self.assertEqual(len(lignes), 1)

    def test_pdf_rendu(self):
        self._immo(100000, self.service_a, self.type_pc)
        self._immo(50000, self.service_b, self.type_pc)
        resp = self.client.get(reverse('patrimoine_rapport_valeurs_pdf'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        self.assertIn('Valeur_Immobilisations_par_Service.pdf',
                      resp['Content-Disposition'])
        self.assertTrue(resp.content.startswith(b'%PDF'))
        self.assertGreater(len(resp.content), 1000)

    def test_pdf_sans_donnees_rendu_valide(self):
        resp = self.client.get(reverse('patrimoine_rapport_valeurs_pdf'))
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.content.startswith(b'%PDF'))
