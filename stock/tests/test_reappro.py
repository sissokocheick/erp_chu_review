# -*- coding: utf-8 -*-
"""
Tests de la boucle de réapprovisionnement.

Couvre la page de suggestions (calcul des quantités recommandées, tri par
urgence, filtres) et la conversion en un clic des suggestions sélectionnées
en commandes fournisseur (une commande par famille).
"""
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from stock.models import (
    Article, StockItem, Commande, LigneCommande, Fournisseur,
)
from stock.tests import factories


class BaseReapproTest(TestCase):
    def setUp(self):
        self.user = factories.creer_superuser(username='reapro_admin')
        self.user.profil.doit_changer_mdp = False
        self.user.profil.save(update_fields=['doit_changer_mdp'])
        self.magasin = factories.creer_magasin(nom='Magasin Réappro')
        self.user.profil.magasins_autorises.add(self.magasin)

        self.famille_med = factories.creer_famille(
            code='MEDR', intitule='Médicaments')
        self.famille_mat = factories.creer_famille(
            code='MATR', intitule='Matériel')

        self.fournisseur = Fournisseur.objects.create(
            code='FOURR', raison_sociale='Distrib Santé CI')

        self.client.force_login(self.user)
        session = self.client.session
        session['magasin_actif_id'] = self.magasin.id
        session.save()

    def _creer_article(self, famille, designation, reference, seuil_min,
                       seuil_crit=None, seuil_max=None, stock=0,
                       prix_reference='1000.00'):
        art = Article.objects.create(
            famille=famille, designation=designation, reference=reference,
            seuil_minimum=seuil_min, seuil_critique=seuil_crit,
            seuil_maximum=seuil_max, prix_reference=Decimal(prix_reference))
        StockItem.objects.create(
            article=art, magasin=self.magasin, quantite_physique=stock,
            valeur_cmup=Decimal('500.00'))
        return art

    def _get_suggestions(self, **params):
        url = reverse('suggestions_reappro')
        if params:
            url += '?' + '&'.join(f'{k}={v}' for k, v in params.items())
        return self.client.get(url)


class SuggestionsGETTest(BaseReapproTest):

    def test_page_rendue_avec_suggestions(self):
        self._creer_article(self.famille_med, 'Paracétamol', 'MED-1',
                            seuil_min=10, seuil_crit=5, seuil_max=50, stock=3)
        resp = self._get_suggestions()
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Paracétamol')
        self.assertEqual(resp.context['nb_suggestions'], 1)
        self.assertEqual(resp.context['nb_critiques'], 1)  # 3 <= 5

    def test_quantite_recommandee_avec_seuil_max(self):
        art = self._creer_article(self.famille_med, 'Amox', 'MED-2',
                                  seuil_min=10, seuil_max=50, stock=5)
        resp = self._get_suggestions()
        sugg = resp.context['suggestions'][0]
        self.assertEqual(sugg['article'].id, art.id)
        # cible = seuil_max (50) - stock (5) = 45
        self.assertEqual(sugg['qte_recommandee'], 45)
        self.assertEqual(sugg['statut'], 'ALERTE')  # 5 <= 10, > seuil_crit None

    def test_quantite_recommandee_sans_seuil_max(self):
        art = self._creer_article(self.famille_mat, 'Gants', 'MAT-1',
                                  seuil_min=10, stock=4)
        resp = self._get_suggestions()
        sugg = resp.context['suggestions'][0]
        self.assertEqual(sugg['article'].id, art.id)
        # cible = seuil_min * 2 (20) - stock (4) = 16
        self.assertEqual(sugg['qte_recommandee'], 16)

    def test_pas_de_suggestion_si_stock_au_dessus_du_seuil(self):
        self._creer_article(self.famille_med, 'Sérum', 'MED-3',
                            seuil_min=10, stock=25)
        resp = self._get_suggestions()
        self.assertEqual(resp.context['nb_suggestions'], 0)

    def test_tri_critiques_avant_alertes(self):
        self._creer_article(self.famille_mat, 'Compresses', 'MAT-2',
                            seuil_min=20, seuil_crit=5, stock=10)  # ALERTE
        self._creer_article(self.famille_med, 'Insuline', 'MED-4',
                            seuil_min=20, seuil_crit=5, stock=2)   # CRITIQUE
        resp = self._get_suggestions()
        statuts = [s['statut'] for s in resp.context['suggestions']]
        self.assertEqual(statuts, ['CRITIQUE', 'ALERTE'])

    def test_filtre_par_famille(self):
        self._creer_article(self.famille_med, 'Doliprane', 'MED-5',
                            seuil_min=10, stock=2)
        self._creer_article(self.famille_mat, 'Seringue', 'MAT-3',
                            seuil_min=10, stock=3)
        resp = self._get_suggestions(famille=self.famille_mat.id)
        refs = [s['article'].reference for s in resp.context['suggestions']]
        self.assertEqual(refs, ['MAT-3'])

    def test_recherche_par_texte(self):
        self._creer_article(self.famille_med, 'Vitamine C', 'MED-6',
                            seuil_min=10, stock=1)
        self._creer_article(self.famille_mat, 'Coton', 'MAT-4',
                            seuil_min=10, stock=1)
        resp = self._get_suggestions(q='Vitamine')
        refs = [s['article'].reference for s in resp.context['suggestions']]
        self.assertEqual(refs, ['MED-6'])

    def test_valeur_estimee_prix_reference(self):
        self._creer_article(self.famille_med, 'Antibio', 'MED-7',
                            seuil_min=10, stock=5, prix_reference='2000.00')
        resp = self._get_suggestions()
        sugg = resp.context['suggestions'][0]
        # qte rec = 20 - 5 = 15 ; valeur = 15 * 2000 = 30000
        self.assertEqual(sugg['valeur_estimee'], Decimal('30000.00'))

    def test_page_vide_sans_article_sous_seuil(self):
        resp = self._get_suggestions()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context['nb_suggestions'], 0)


class ConversionPOSTTest(BaseReapproTest):

    def _post_conversion(self, articles_quantites, **extra):
        """articles_quantites: list[(article_id, quantite)]"""
        return self.client.post(reverse('suggestions_reappro'), {
            'fournisseur': self.fournisseur.id,
            'articles[]': [str(a) for a, _ in articles_quantites],
            'quantites[]': [str(q) for _, q in articles_quantites],
            'objet': 'Réappro urgente',
            **extra,
        })

    def test_creation_une_commande_par_famille(self):
        a1 = self._creer_article(self.famille_med, 'Paracétamol', 'MED-8',
                                 seuil_min=10, stock=2, prix_reference='500.00')
        a2 = self._creer_article(self.famille_med, 'Amoxicilline', 'MED-9',
                                 seuil_min=10, stock=3, prix_reference='800.00')
        a3 = self._creer_article(self.famille_mat, 'Gants', 'MAT-5',
                                 seuil_min=10, stock=1, prix_reference='300.00')
        resp = self._post_conversion([(a1.id, 8), (a2.id, 7), (a3.id, 9)])
        # Redirection vers la liste des commandes
        self.assertRedirects(resp, reverse('liste_commandes'))
        # 2 familles → 2 commandes
        self.assertEqual(Commande.objects.count(), 2)
        cmd_med = Commande.objects.get(famille=self.famille_med)
        cmd_mat = Commande.objects.get(famille=self.famille_mat)
        self.assertEqual(cmd_med.fournisseur, self.fournisseur)
        self.assertEqual(cmd_med.magasin, self.magasin)
        self.assertEqual(cmd_med.cree_par, self.user)
        self.assertEqual(
            cmd_med.lignes_commande.count(), 2)
        self.assertEqual(
            cmd_mat.lignes_commande.count(), 1)
        # Quantités respectées
        qtes = {
            l.article_id: l.quantite_demandee
            for l in cmd_med.lignes_commande.all()
        }
        self.assertEqual(qtes, {a1.id: 8, a2.id: 7})
        # Prix unitaire = prix de référence
        ligne = cmd_med.lignes_commande.get(article=a1)
        self.assertEqual(ligne.prix_unitaire, Decimal('500.00'))

    def test_creation_sans_fournisseur_refusee(self):
        a = self._creer_article(self.famille_med, 'Sérum', 'MED-10',
                                seuil_min=10, stock=1)
        resp = self.client.post(reverse('suggestions_reappro'), {
            'articles[]': [str(a.id)], 'quantites[]': ['10'],
        })
        self.assertRedirects(resp, reverse('suggestions_reappro'))
        self.assertEqual(Commande.objects.count(), 0)

    def test_creation_sans_article_refusee(self):
        resp = self.client.post(reverse('suggestions_reappro'), {
            'fournisseur': self.fournisseur.id,
        })
        self.assertRedirects(resp, reverse('suggestions_reappro'))
        self.assertEqual(Commande.objects.count(), 0)

    def test_quantite_invalide_ignoree(self):
        a1 = self._creer_article(self.famille_med, 'Med A', 'MED-11',
                                 seuil_min=10, stock=1)
        a2 = self._creer_article(self.famille_med, 'Med B', 'MED-12',
                                 seuil_min=10, stock=1)
        resp = self._post_conversion([(a1.id, 5), (a2.id, 0)])
        self.assertRedirects(resp, reverse('liste_commandes'))
        cmd = Commande.objects.get()
        self.assertEqual(cmd.lignes_commande.count(), 1)
        self.assertEqual(cmd.lignes_commande.get().article_id, a1.id)

    def test_numero_commande_genere_et_lignes_reliquat(self):
        a = self._creer_article(self.famille_med, 'Med C', 'MED-13',
                                seuil_min=10, stock=1)
        self._post_conversion([(a.id, 12)])
        cmd = Commande.objects.get()
        self.assertTrue(cmd.numero_commande.startswith('BC-'))
        ligne = cmd.lignes_commande.get()
        self.assertEqual(ligne.reliquat, 12)  # rien de reçu

    def test_objet_par_defaut_par_famille(self):
        a = self._creer_article(self.famille_med, 'Med D', 'MED-14',
                                seuil_min=10, stock=1)
        self._post_conversion([(a.id, 4)], objet='')
        cmd = Commande.objects.get()
        self.assertIn('Médicaments', cmd.objet)
