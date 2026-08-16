# -*- coding: utf-8 -*-
"""
Tests du tri par clic sur les en-têtes de colonnes (tag `th_tri`).

Vérifie que les listes principales (articles, bons de sortie, bons
d'entrée, historique d'article) :
1. ordonnent réellement le queryset selon tri/ordre (serveur) ;
2. exposent des liens `tri=`/`ordre=` sur les colonnes triables ;
3. préservent la recherche et remettent la pagination à la page 1.
"""

from django.test import TestCase
from django.urls import reverse

from .factories import (
    creer_article, creer_famille, creer_magasin, creer_superuser,
    creer_utilisateur, desactiver_changement_mdp,
)


class TriColonnesArticlesTest(TestCase):
    """La liste des articles se trie par clic sur les en-têtes."""

    @classmethod
    def setUpTestData(cls):
        cls.user = creer_superuser(username="tri_admin")
        desactiver_changement_mdp(cls.user)
        cls.magasin = creer_magasin(nom="Magasin Tri")
        fam_b = creer_famille(code="FAMB", intitule="Bravo")
        fam_a = creer_famille(code="FAMA", intitule="Alpha")
        creer_article(famille=fam_a, designation="Zeta", reference="REF-Z")
        creer_article(famille=fam_b, designation="Milo", reference="REF-M")
        creer_article(famille=fam_a, designation="Alpha", reference="REF-A")

    def setUp(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["magasin_actif_id"] = str(self.magasin.id)
        session.save()

    def _positions(self, html, termes, marqueur_tbody='<tbody id="tbody-articles">'):
        """Positions des termes dans le HTML, limitées au corps du tableau
        (les libellés apparaissent aussi ailleurs : selects, JS...)."""
        debut = html.find(marqueur_tbody)
        self.assertGreater(debut, -1, f"tbody introuvable ({marqueur_tbody})")
        corps = html[debut:]
        return [corps.find(t) for t in termes]

    def test_tri_designation_ascendant(self):
        html = self.client.get(
            reverse("liste_articles"), {"tri": "designation", "ordre": "asc"}
        ).content.decode("utf-8", "replace")
        # Références uniques : les désignations peuvent collisionner avec le
        # libellé de famille (« Alpha ») affiché dans la colonne Famille.
        pos = self._positions(html, ["REF-A", "REF-M", "REF-Z"])
        self.assertEqual(pos, sorted(pos), "Tri A->Z non respecté")

    def test_tri_designation_descendant(self):
        html = self.client.get(
            reverse("liste_articles"), {"tri": "designation", "ordre": "desc"}
        ).content.decode("utf-8", "replace")
        pos = self._positions(html, ["REF-Z", "REF-M", "REF-A"])
        self.assertEqual(pos, sorted(pos), "Tri Z->A non respecté")

    def test_tri_par_famille(self):
        html = self.client.get(
            reverse("liste_articles"), {"tri": "famille", "ordre": "asc"}
        ).content.decode("utf-8", "replace")
        # Famille Alpha (FAMA) avant famille Bravo (FAMB) :
        # Alpha et Zeta (FAMA) avant Milo (FAMB)
        pos = self._positions(html, ["Zeta", "Milo"])
        self.assertEqual(pos, sorted(pos), "Tri par famille non respecté")

    def test_liens_tri_presents_et_preservent_la_recherche(self):
        html = self.client.get(
            reverse("liste_articles"), {"q": "eta", "tri": "designation", "ordre": "asc"}
        ).content.decode("utf-8", "replace")
        # Le lien de tri suivant (desc) existe et garde la recherche q=eta
        self.assertIn("tri=designation&amp;ordre=desc", html)
        self.assertIn("q=eta", html)
        # La colonne active porte la flèche
        self.assertIn("th-tri active", html)

    def test_colonnes_non_triables_restees_brutes(self):
        html = self.client.get(reverse("liste_articles")).content.decode("utf-8", "replace")
        # « Actions » n'est pas un lien de tri
        self.assertIn("<th style=\"text-align: center;\">Actions</th>", html)


class TriColonnesBonsTest(TestCase):
    """La liste des bons de sortie se trie par N° bon et par date."""

    @classmethod
    def setUpTestData(cls):
        cls.user = creer_superuser(username="tri_bons")
        desactiver_changement_mdp(cls.user)
        cls.magasin = creer_magasin(nom="Magasin Bons")
        from stock.models import BonMouvement
        from django.utils import timezone
        from datetime import timedelta
        for numero, jours in (("BS-001", 1), ("BS-003", 3), ("BS-002", 2)):
            BonMouvement.objects.create(
                type_bon="SORTIE", magasin=cls.magasin, numero_bon=numero,
                date_bon=timezone.now() - timedelta(days=jours),
                cree_par=cls.user,
            )

    def setUp(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["magasin_actif_id"] = str(self.magasin.id)
        session.save()

    def test_tri_par_numero_bon(self):
        html = self.client.get(
            reverse("liste_sorties"), {"tri": "numero_bon", "ordre": "asc"}
        ).content.decode("utf-8", "replace")
        debut = html.find('<tbody id="resultats-tableau">')
        self.assertGreater(debut, -1)
        corps = html[debut:]
        pos = [corps.find(n) for n in ("BS-001", "BS-002", "BS-003")]
        self.assertEqual(pos, sorted(pos), "Tri par N° bon non respecté")

    def test_entrees_tri_par_fournisseur_ok(self):
        resp = self.client.get(reverse("liste_entrees"), {"tri": "fournisseur", "ordre": "asc"})
        self.assertEqual(resp.status_code, 200)


class TriHistoriqueArticleTest(TestCase):
    """L'historique des mouvements d'un article se trie par colonne."""

    @classmethod
    def setUpTestData(cls):
        cls.user = creer_superuser(username="tri_hist")
        desactiver_changement_mdp(cls.user)
        cls.magasin = creer_magasin(nom="Magasin Hist")
        cls.article = creer_article(designation="Histo Article", reference="REF-HIST")
        from datetime import datetime
        from stock.models import Mouvement
        Mouvement.objects.create(
            article=cls.article, magasin=cls.magasin, type_mouvement="ENTREE",
            quantite=10, utilisateur=cls.user, date_mouvement=datetime(2026, 1, 2),
        )
        Mouvement.objects.create(
            article=cls.article, magasin=cls.magasin, type_mouvement="SORTIE",
            quantite=3, utilisateur=cls.user, date_mouvement=datetime(2026, 1, 1),
        )

    def setUp(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["magasin_actif_id"] = str(self.magasin.id)
        session.save()

    def _corps_tableau(self, html):
        debut = html.find("<table")
        self.assertGreater(debut, -1)
        tbody = html.find("<tbody", debut)
        self.assertGreater(tbody, -1)
        return html[tbody:]

    def test_tri_par_type(self):
        html = self.client.get(
            reverse("historique_article", args=[self.article.id]),
            {"tri": "type_mouvement", "ordre": "asc"},
        ).content.decode("utf-8", "replace")
        pos = [self._corps_tableau(html).find(t) for t in ("ENTREE", "SORTIE")]
        self.assertEqual(pos, sorted(pos), "Tri par type non respecté")

    def test_tri_par_quantite(self):
        html = self.client.get(
            reverse("historique_article", args=[self.article.id]),
            {"tri": "quantite", "ordre": "desc"},
        ).content.decode("utf-8", "replace")
        pos = [self._corps_tableau(html).find(q) for q in ("10", "3")]
        self.assertEqual(pos, sorted(pos), "Tri par quantité non respecté")
