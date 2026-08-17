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


class DetailConsommationTest(BaseConsommationTest):
    """Détail service × article du rapport de consommation."""

    def test_detail_agrege_par_service_et_article(self):
        # 2 mouvements du même article vers le même service → 1 ligne
        self._mouvement(self.article, self.service_a, 10)
        self._mouvement(self.article, self.service_a, 5)
        # Même article vers un autre service → ligne séparée
        self._mouvement(self.article, self.service_b, 3)
        # Autre article vers le même service → ligne séparée
        self._mouvement(self.article2, self.service_a, 2,
                        prix=Decimal('200.00'))

        resp = self._get_rapport()
        self.assertEqual(resp.status_code, 200)
        lignes = list(resp.context['detail_page'])
        self.assertEqual(len(lignes), 3)

        par_cle = {
            (r['service_demandeur__id'], r['article__id']): r
            for r in lignes
        }
        a1 = par_cle[(self.service_a.id, self.article.id)]
        self.assertEqual(a1['quantite'], 15)
        self.assertEqual(a1['valeur'], Decimal('7500.00'))
        self.assertEqual(a1['nb_mouvements'], 2)

        b1 = par_cle[(self.service_b.id, self.article.id)]
        self.assertEqual(b1['quantite'], 3)
        self.assertEqual(b1['valeur'], Decimal('1500.00'))

        a2 = par_cle[(self.service_a.id, self.article2.id)]
        self.assertEqual(a2['quantite'], 2)
        self.assertEqual(a2['valeur'], Decimal('400.00'))

        # Le total du détail doit correspondre au total du rapport
        total_detail = sum(r['quantite'] for r in lignes)
        self.assertEqual(total_detail, resp.context['total_quantite'])

    def test_detail_trie_par_service_puis_valeur(self):
        self._mouvement(self.article, self.service_b, 1)    # Urgences, 500
        self._mouvement(self.article, self.service_a, 10)   # Cardio, 5000
        self._mouvement(self.article2, self.service_a, 9,   # Cardio, 900
                        prix=Decimal('100.00'))
        resp = self._get_rapport()
        lignes = list(resp.context['detail_page'])
        # Cardio (valeur 5000) avant Cardio (900) avant Urgences (500)
        self.assertEqual(lignes[0]['service_demandeur__nom'], 'Cardiologie')
        self.assertEqual(lignes[0]['article__id'], self.article.id)
        self.assertEqual(lignes[1]['service_demandeur__nom'], 'Cardiologie')
        self.assertEqual(lignes[1]['article__id'], self.article2.id)
        self.assertEqual(lignes[2]['service_demandeur__nom'], 'Urgences')

    def test_detail_pagine(self):
        # 25 lignes service × article différentes → pagination 20/page
        for i in range(25):
            art = factories.creer_article(
                famille=self.famille, designation=f'Art {i}',
                reference=f'CONS-D-{i}', prix_reference=Decimal('100.00'))
            self._mouvement(art, self.service_a, 1)
        resp = self._get_rapport()
        page = resp.context['detail_page']
        self.assertEqual(page.paginator.num_pages, 2)
        self.assertEqual(len(list(page.object_list)), 20)
        self.assertEqual(resp.context['detail_total'], 25)

        # Page 2 → 5 lignes restantes
        resp2 = self._get_rapport(page=2)
        page2 = resp2.context['detail_page']
        self.assertEqual(page2.number, 2)
        self.assertEqual(len(list(page2.object_list)), 5)

    def test_detail_filtre_service_et_magasin(self):
        self._mouvement(self.article, self.service_a, 10)
        self._mouvement(self.article2, self.service_b, 8)
        self._mouvement(self.article2, self.service_a, 30,
                        magasin=self.magasin2)
        resp = self._get_rapport(service=self.service_b.id)
        lignes = list(resp.context['detail_page'])
        self.assertEqual(len(lignes), 1)
        self.assertEqual(lignes[0]['service_demandeur__id'],
                         self.service_b.id)
        # L'autre magasin n'apparaît pas
        self.assertEqual(resp.context['detail_total'], 1)

    def test_export_detail_csv_contenu(self):
        self._mouvement(self.article, self.service_a, 10)
        self._mouvement(self.article2, self.service_b, 3)
        self._mouvement(self.article2, self.service_a, 2,
                        prix=Decimal('200.00'))
        resp = self.client.get(reverse('export_consommation_detail_csv'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'text/csv; charset=utf-8')
        contenu = resp.content.decode('utf-8-sig')
        lignes = [l for l in contenu.splitlines() if l.strip()]
        self.assertEqual(
            lignes[0],
            'Service;Code;Article;Référence;Unité;'
            'Quantité (unités);Valeur (FCFA);Nb mouvements;Période')
        # 1 en-tête + 3 lignes service × article
        self.assertEqual(len(lignes), 4)
        self.assertTrue(any('Cardiologie;CAR;Gants;CONS-1' in l
                            for l in lignes))
        self.assertTrue(any('Cardiologie;CAR;Masques;CONS-2' in l
                            for l in lignes))
        self.assertTrue(any('Urgences;URG;Masques;CONS-2' in l
                            for l in lignes))

    def test_export_detail_respecte_filtre_service(self):
        self._mouvement(self.article, self.service_a, 10)
        self._mouvement(self.article2, self.service_b, 3)
        resp = self.client.get(
            reverse('export_consommation_detail_csv'),
            {'service': self.service_b.id})
        contenu = resp.content.decode('utf-8-sig')
        self.assertIn('Urgences', contenu)
        self.assertNotIn('Cardiologie', contenu)

    def test_export_detail_exclut_destructions_et_autre_magasin(self):
        self._mouvement(self.article, self.service_a, 10)
        self._mouvement(self.article2, self.service_rebuts, 40)
        self._mouvement(self.article2, self.service_a, 30,
                        magasin=self.magasin2)
        resp = self.client.get(reverse('export_consommation_detail_csv'))
        contenu = resp.content.decode('utf-8-sig')
        self.assertNotIn('DESTRUCTION', contenu)
        self.assertNotIn(';40;', contenu)
        lignes = [l for l in contenu.splitlines() if l.strip()]
        self.assertEqual(len(lignes), 2)  # en-tête + 1 ligne


class TriConsommationTest(BaseConsommationTest):
    """Tri par clic sur les tableaux du rapport de consommation."""

    def test_tri_resume_par_quantite_asc(self):
        self._mouvement(self.article, self.service_a, 10)   # Cardio 10
        self._mouvement(self.article2, self.service_b, 8)   # Urgences 8
        resp = self._get_rapport(tri='quantite', ordre='asc')
        noms = [r['service_demandeur__nom']
                for r in resp.context['par_service']]
        self.assertEqual(noms, ['Urgences', 'Cardiologie'])

    def test_tri_resume_par_valeur_desc(self):
        self._mouvement(self.article, self.service_a, 10)   # 5000 F
        self._mouvement(self.article2, self.service_b, 8)   # 800 F
        resp = self._get_rapport(tri='valeur', ordre='desc')
        noms = [r['service_demandeur__nom']
                for r in resp.context['par_service']]
        self.assertEqual(noms, ['Cardiologie', 'Urgences'])

    def test_tri_resume_par_nom_service_desc(self):
        self._mouvement(self.article, self.service_a, 1)
        self._mouvement(self.article2, self.service_b, 1)
        resp = self._get_rapport(tri='service', ordre='desc')
        noms = [r['service_demandeur__nom']
                for r in resp.context['par_service']]
        self.assertEqual(noms, ['Urgences', 'Cardiologie'])

    def test_tri_invalide_revient_au_defaut(self):
        self._mouvement(self.article, self.service_a, 1)
        self._mouvement(self.article2, self.service_b, 1)
        resp = self._get_rapport(tri='injection', ordre='asc')
        # défaut : valeur décroissante → Cardiologie en premier
        noms = [r['service_demandeur__nom']
                for r in resp.context['par_service']]
        self.assertEqual(noms, ['Cardiologie', 'Urgences'])

    def test_tri_detail_independant_du_resume(self):
        # Le tri du résumé (tri/ordre) ne doit pas toucher le détail
        self._mouvement(self.article, self.service_a, 10)
        self._mouvement(self.article2, self.service_b, 8)
        resp = self._get_rapport(tri='quantite', ordre='asc')
        self.assertEqual(
            [r['service_demandeur__nom']
             for r in resp.context['par_service']],
            ['Urgences', 'Cardiologie'])
        # détail inchangé : service puis valeur décroissante
        lignes = list(resp.context['detail_page'])
        self.assertEqual(lignes[0]['service_demandeur__nom'],
                         'Cardiologie')

    def test_tri_detail_par_quantite_asc(self):
        self._mouvement(self.article, self.service_a, 10)   # Gants 10
        self._mouvement(self.article2, self.service_b, 8)   # Masques 8
        resp = self._get_rapport(dtri='quantite', dordre='asc')
        lignes = list(resp.context['detail_page'])
        self.assertEqual(lignes[0]['service_demandeur__nom'], 'Urgences')
        self.assertEqual(lignes[0]['quantite'], 8)

    def test_liens_de_tri_dans_le_html(self):
        self._mouvement(self.article, self.service_a, 10)
        resp = self._get_rapport()
        html = resp.content.decode()
        self.assertIn('tri=service', html)
        self.assertIn('tri=quantite', html)
        self.assertIn('tri=valeur', html)
        self.assertIn('dtri=article', html)
        self.assertIn('dtri=valeur', html)
        self.assertIn('dtri=mouvements', html)

    def test_export_resume_respecte_le_tri(self):
        self._mouvement(self.article, self.service_a, 10)
        self._mouvement(self.article2, self.service_b, 8)
        resp = self.client.get(reverse('export_consommation_services_csv'),
                               {'tri': 'quantite', 'ordre': 'asc'})
        contenu = resp.content.decode('utf-8-sig')
        lignes = [l for l in contenu.splitlines() if l.strip()]
        self.assertEqual(len(lignes), 3)
        idx_urg = next(i for i, l in enumerate(lignes) if 'Urgences' in l)
        idx_car = next(i for i, l in enumerate(lignes) if 'Cardiologie' in l)
        self.assertLess(idx_urg, idx_car)  # 8 avant 10 en asc

    def test_export_detail_respecte_le_tri(self):
        self._mouvement(self.article, self.service_a, 10)
        self._mouvement(self.article2, self.service_b, 8)
        resp = self.client.get(reverse('export_consommation_detail_csv'),
                               {'dtri': 'quantite', 'dordre': 'asc'})
        contenu = resp.content.decode('utf-8-sig')
        lignes = [l for l in contenu.splitlines() if l.strip()]
        self.assertEqual(len(lignes), 3)
        idx_urg = next(i for i, l in enumerate(lignes) if 'Urgences' in l)
        idx_car = next(i for i, l in enumerate(lignes) if 'Cardiologie' in l)
        self.assertLess(idx_urg, idx_car)

    def test_top_services_graphique_donnees_serveur(self):
        # Le donut « Top services » doit refléter le top 8 par valeur,
        # indépendamment du tri affiché du tableau (données serveur).
        import json
        self._mouvement(self.article, self.service_a, 10)   # Cardio 5000 F
        self._mouvement(self.article2, self.service_a, 5)   # Cardio +500 F
        self._mouvement(self.article2, self.service_b, 3)   # Urgences 300 F
        resp = self._get_rapport(tri='service', ordre='asc')
        labels = json.loads(resp.context['chart_services_labels'])
        data = json.loads(resp.context['chart_services_data'])
        # Trié par valeur décroissante même si le tableau est trié par nom
        self.assertEqual(labels, ['Cardiologie', 'Urgences'])
        self.assertEqual(data, [5500.0, 300.0])
        # Le HTML embarque les données (plus de parsing DOM)
        html = resp.content.decode()
        self.assertIn('Cardiologie', html)
        self.assertIn('5500.0', html)


class PdfConsommationTest(BaseConsommationTest):
    """Export PDF du rapport de consommation par service."""

    def test_pdf_rendu_complet(self):
        self._mouvement(self.article, self.service_a, 10)
        self._mouvement(self.article2, self.service_b, 8)
        resp = self.client.get(reverse('rapport_consommation_services_pdf'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        self.assertIn('Rapport_Consommation_par_Service.pdf',
                      resp['Content-Disposition'])
        # PDF généré et non vide (le template se rend sans erreur)
        self.assertGreater(len(resp.content), 1000)
        self.assertTrue(resp.content.startswith(b'%PDF'))

    def test_pdf_respecte_filtre_service(self):
        self._mouvement(self.article, self.service_a, 10)
        self._mouvement(self.article2, self.service_b, 8)
        resp = self.client.get(reverse('rapport_consommation_services_pdf'),
                               {'service': self.service_b.id})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        self.assertTrue(resp.content.startswith(b'%PDF'))

    def test_pdf_sans_donnees_rendu_valide(self):
        resp = self.client.get(reverse('rapport_consommation_services_pdf'))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        self.assertTrue(resp.content.startswith(b'%PDF'))

    def test_pdf_respecte_le_tri(self):
        self._mouvement(self.article, self.service_a, 10)
        self._mouvement(self.article2, self.service_b, 8)
        # Tri résumé par quantité asc + détail par quantité asc
        resp = self.client.get(reverse('rapport_consommation_services_pdf'),
                               {'tri': 'quantite', 'ordre': 'asc',
                                'dtri': 'quantite', 'dordre': 'asc'})
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.content.startswith(b'%PDF'))


class ApiDetailDemandeTest(TestCase):
    """L'API de détail d'une demande : 200 pour une demande existante,
    404 (et non 500) pour une demande inexistante, 403 hors magasin."""

    def setUp(self):
        self.user = factories.creer_superuser(username='api_detail_admin')
        self.user.profil.doit_changer_mdp = False
        self.user.profil.save(update_fields=['doit_changer_mdp'])
        self.magasin = factories.creer_magasin(nom='Magasin API')
        self.user.profil.magasins_autorises.add(self.magasin)
        self.client.force_login(self.user)
        session = self.client.session
        session['magasin_actif_id'] = str(self.magasin.id)
        session.save()

    def _demande(self):
        from stock.models import DemandeMateriel, Service
        from stock.tests import factories as f
        service = Service.objects.create(code='API', nom='Service API')
        return DemandeMateriel.objects.create(
            service_demandeur=service,
            demandeur=self.user,
            magasin_cible=self.magasin,
            statut='EN_ATTENTE',
        )

    def test_demande_inexistante_renvoie_404_pas_500(self):
        """Régression : une demande inexistante répondait 500 (Http404 avalé
        par le except Exception) au lieu de 404."""
        resp = self.client.get('/api-detail-demande/999999/')
        self.assertEqual(resp.status_code, 404)

    def test_demande_existante_renvoie_200(self):
        demande = self._demande()
        resp = self.client.get(f'/api-detail-demande/{demande.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['id'], demande.id)

    def test_demande_hors_magasin_renvoie_403(self):
        autre = factories.creer_magasin(nom='Magasin Autre API')
        from stock.models import Service
        service = Service.objects.create(code='API2', nom='Service API 2')
        from stock.models import DemandeMateriel
        demande = DemandeMateriel.objects.create(
            service_demandeur=service, demandeur=self.user,
            magasin_cible=autre, statut='EN_ATTENTE',
        )
        resp = self.client.get(f'/api-detail-demande/{demande.id}/')
        self.assertEqual(resp.status_code, 403)
