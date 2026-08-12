# -*- coding: utf-8 -*-
"""
Tests de la recherche insensible aux accents.

Régression : « paracetamol » doit trouver « Paracétamol 500mg »,
sur toutes les pages de liste (articles, état du stock, commandes…).
"""

from django.test import TestCase
from django.contrib.auth import get_user_model

from stock.models import (
    Magasin, Article, StockItem, FamilleArticle, Fournisseur, Commande,
    LigneCommande,
)
from stock.views.common_views import normaliser_texte, filtrer_texte

User = get_user_model()


class NormalisationTexteTest(TestCase):
    """Le helper de normalisation enlève les accents."""

    def test_normalisation_accents(self):
        self.assertEqual(normaliser_texte('Paracétamol'), 'paracetamol')
        self.assertEqual(normaliser_texte('Sérum physiologique'), 'serum physiologique')
        self.assertEqual(normaliser_texte('DÉPÔT'), 'depot')
        self.assertEqual(normaliser_texte('Côte d\'Ivoire'), 'cote divoire')


class RechercheArticlesAccentsTest(TestCase):
    """La liste des articles trouve un article écrit avec accents via une recherche sans accent."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser(
            username='admin', email='admin@chu.ci', password='admin123'
        )
        cls.user.profil.doit_changer_mdp = False
        cls.user.profil.save(update_fields=['doit_changer_mdp'])
        cls.magasin = Magasin.objects.create(nom='Pharmacie Centrale')
        cls.famille = FamilleArticle.objects.create(code='MED', intitule='Médicaments')
        cls.article = Article.objects.create(
            designation='Paracétamol 500mg',
            reference='PARA500',
            famille=cls.famille,
            seuil_minimum=20,
            seuil_critique=10,
            cree_par=cls.user,
        )

    def test_recherche_sans_accent_trouve_article_accentue(self):
        self.client.force_login(self.user)
        session = self.client.session
        session['magasin_actif_id'] = str(self.magasin.id)
        session.save()

        resp = self.client.get('/articles/', {'q': 'paracetamol'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Paracétamol 500mg')

    def test_recherche_avec_accent_trouve_aussi(self):
        self.client.force_login(self.user)
        session = self.client.session
        session['magasin_actif_id'] = str(self.magasin.id)
        session.save()

        resp = self.client.get('/articles/', {'q': 'Paracétamol'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Paracétamol 500mg')

    def test_recherche_inexistante_retourne_vide(self):
        self.client.force_login(self.user)
        session = self.client.session
        session['magasin_actif_id'] = str(self.magasin.id)
        session.save()

        resp = self.client.get('/articles/', {'q': 'zzzz_inexistant'})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Aucun article')


class RechercheCommandesAccentsTest(TestCase):
    """La recherche de commandes ignore aussi les accents (fournisseur)."""

    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_superuser(
            username='admin2', email='admin2@chu.ci', password='admin123'
        )
        cls.user.profil.doit_changer_mdp = False
        cls.user.profil.save(update_fields=['doit_changer_mdp'])
        cls.magasin = Magasin.objects.create(nom='Magasin Test')
        cls.fournisseur = Fournisseur.objects.create(
            raison_sociale='Laboratoire Pharmaceutique d\'Abidjan'
        )
        cls.commande = Commande.objects.create(
            numero_commande='CMD-ACC-001',
            fournisseur=cls.fournisseur,
            magasin=cls.magasin,
            cree_par=cls.user,
        )

    def test_filtrer_texte_helper_sur_fournisseur(self):
        qs = Commande.objects.all()
        resultats = filtrer_texte(qs, 'pharmaceutique dabidjan', ['fournisseur__raison_sociale'])
        self.assertEqual(len(resultats), 1)

    def test_filtrer_texte_ignore_les_accents(self):
        qs = Commande.objects.all()
        resultats = filtrer_texte(qs, 'abidjan', ['fournisseur__raison_sociale'])
        self.assertEqual(len(resultats), 1)
        resultats = filtrer_texte(qs, 'zzz', ['fournisseur__raison_sociale'])
        self.assertEqual(len(resultats), 0)
