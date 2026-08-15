# -*- coding: utf-8 -*-
"""Régression multi-page des PDF de bons.

Couverture :
- un bon avec plus de 18 lignes est paginé en plusieurs pages ;
- la dernière page porte le bloc de signatures (bloc-bas) ;
- la numérotation « n / total » est rendue (via pymupdf si dispo) ;
- le bon de commande n'a plus le tableau vide (clés de lignes harmonisées) ;
- les aperçus HTML (SweetAlert2) utilisent aussi le multi-page.

Les assertions sur le nombre de pages nécessitent `pymupdf` (import facultatif).
"""
import io
import re

from django.test import TestCase
from django.urls import reverse

from stock.models import BonMouvement, Commande, Fournisseur, LigneBon, LigneCommande, Service
from stock.tests.factories import (
    creer_article, creer_famille, creer_magasin,
    creer_superuser, desactiver_changement_mdp,
)


def _normaliser(texte):
    """Réduit tous les blancs (sauts de ligne d'extraction PDF) à un espace."""
    return re.sub(r"\s+", " ", texte.replace("\u00a0", " "))

try:
    import pymupdf
except ImportError:  # pragma: no cover - dépendance optionnelle
    pymupdf = None


class PdfMultiPageTest(TestCase):
    """Les bons dépassant 18 lignes passent en multi-page avec signatures en bas."""

    NB_LIGNES = 20  # > 18 => doit produire 2 pages

    @classmethod
    def setUpTestData(cls):
        cls.user = desactiver_changement_mdp(
            creer_superuser(username="pdf_multi_page"))
        cls.magasin = creer_magasin(nom="Magasin Multi-Page")
        cls.famille = creer_famille()
        cls.fournisseur = Fournisseur.objects.create(raison_sociale="Fournisseur Multi-Page")
        cls.service = Service.objects.create(nom="Service Multi-Page", code="SMP")
        cls.articles = [
            creer_article(famille=cls.famille, reference=f"MP-{i:02d}",
                          designation=f"Article Multi Page {i}")
            for i in range(cls.NB_LIGNES)
        ]

    def setUp(self):
        self.client.force_login(self.user)
        session = self.client.session
        session['magasin_actif_id'] = str(self.magasin.id)
        session.save()
        self._bon_33 = BonMouvement.objects.create(
            type_bon='SORTIE',
            magasin=self.magasin,
            service_demandeur=self.service,
            cree_par=self.user,
        )

    def _creer_bon(self, type_bon):
        bon = BonMouvement.objects.create(
            type_bon=type_bon,
            magasin=self.magasin,
            fournisseur=self.fournisseur,
            service_demandeur=self.service,
            cree_par=self.user,
        )
        for i, article in enumerate(self.articles, start=1):
            LigneBon.objects.create(bon=bon, article=article, quantite=i)
        return bon

    def _nb_div_pages(self, html):
        return html.count('class="page')

    def test_apercu_entree_multi_page_et_signatures(self):
        bon = self._creer_bon('ENTREE')
        resp = self.client.get(reverse('apercu_bon_entree', args=[bon.id]))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode('utf-8', 'replace')
        self.assertEqual(self._nb_div_pages(html), 2, "20 lignes doivent produire 2 pages")
        self.assertIn("BON D'ENTRÉE", html)
        self.assertIn('bloc-bas', html)
        self.assertIn('signatures-table', html, "le bloc de signatures doit être rendu")
        self.assertNotIn("BON DE SORTIE", html)

    def test_apercu_retour_multi_page_et_signatures(self):
        bon = self._creer_bon('RETOUR_SERVICE')
        resp = self.client.get(reverse('apercu_bon_retour', args=[bon.id]))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode('utf-8', 'replace')
        self.assertEqual(self._nb_div_pages(html), 2, "20 lignes doivent produire 2 pages")
        self.assertIn("BON DE RETOUR", html)
        self.assertIn('bloc-bas', html)
        self.assertIn('signatures-table', html, "le bloc de signatures doit être rendu")

    def test_apercu_hors_stock_multi_page_et_signatures(self):
        bon = self._creer_bon('SORTIE_HORS_STOCK')
        resp = self.client.get(reverse('apercu_bon_hors_stock', args=[bon.id]))
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode('utf-8', 'replace')
        self.assertEqual(self._nb_div_pages(html), 2, "20 lignes doivent produire 2 pages")
        self.assertIn("HORS STOCK", html)
        self.assertIn("DESTINATAIRE", html, "le bloc destinataire doit être rendu")
        self.assertIn('bloc-bas', html)
        self.assertIn('signatures-table', html, "le bloc de signatures doit être rendu")

    def test_commande_pdf_multi_page_tableau_non_vide(self):
        """Régression : le tableau du bon de commande était vide (clés incohérentes)."""
        commande = Commande.objects.create(
            numero_commande='CMD-MP-TEST',
            fournisseur=self.fournisseur,
            magasin=self.magasin,
            cree_par=self.user,
        )
        for i, article in enumerate(self.articles, start=1):
            LigneCommande.objects.create(
                commande=commande, article=article, quantite_demandee=i)

        resp = self.client.get(reverse('imprimer_commande', args=[commande.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        self.assertTemplateUsed(resp, 'stock/pdf/bon_commande.html')

        if pymupdf is None:
            return  # les assertions de contenu nécessitent pymupdf

        doc = pymupdf.open(stream=resp.content, filetype='pdf')
        try:
            self.assertEqual(doc.page_count, 2, "20 lignes doivent produire 2 pages PDF")
            texte = "\n".join(doc[i].get_text() for i in range(doc.page_count))
            # Régression tableau vide : la désignation et la quantité apparaissent
            self.assertIn("Article Multi Page 0", texte)
            self.assertIn("Article Multi Page 19", texte)
            # Numérotation des pages rendue dans le pied de page
            self.assertIn("2 / 2", _normaliser(texte))
        finally:
            doc.close()

    def test_bon_entree_pdf_multi_page_et_numerotation(self):
        bon = self._creer_bon('ENTREE')
        resp = self.client.get(reverse('imprimer_bon_multi_lignes', args=[bon.id]))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'application/pdf')
        self.assertTemplateUsed(resp, 'stock/pdf/bon_entree.html')

        if pymupdf is None:
            return

        doc = pymupdf.open(stream=resp.content, filetype='pdf')
        try:
            self.assertEqual(doc.page_count, 2, "20 lignes doivent produire 2 pages PDF")
            texte = doc[1].get_text()
            self.assertIn("2 / 2", _normaliser(texte),
                          "la numérotation de page doit être rendue")
        finally:
            doc.close()

    def test_signatures_restent_sur_la_derniere_page_contenu(self):
        """Régression : le bloc de signatures (bloc-bas) ne doit pas être rejeté
        sur une page quasi vide à la fin du document. Il doit rester sur la
        dernière page qui contient des lignes de données.

        Avant la correction, la réserve du bloc-bas était mal calculée
        (hauteur_bloc_bas_mm lisait pdf_config comme un objet alors que c'est
        un dict) : la dernière page avec ≥15 lignes débordait et le bloc de
        signatures partait sur une page 3 presque vide.
        """
        if pymupdf is None:
            self.skipTest("pymupdf requis")

        # 33 lignes => 2 pages (18 + 15) ; la page 2 porte la fin du tableau
        # ET le bloc-bas (sondage + signatures), sans page 3 vide.
        for i in range(self.NB_LIGNES, 33):
            LigneBon.objects.create(bon=self._bon_33, article=self.articles[i % self.NB_LIGNES], quantite=i)

        bon = self._bon_33
        resp = self.client.get(reverse('imprimer_bon_multi_lignes', args=[bon.id]))
        self.assertEqual(resp.status_code, 200)
        doc = pymupdf.open(stream=resp.content, filetype='pdf')
        try:
            self.assertEqual(doc.page_count, 2,
                             "33 lignes doivent tenir sur 2 pages (signatures avec le contenu)")
            derniere = doc[-1]
            texte = derniere.get_text().upper()
            # La dernière page contient à la fois des lignes de données ET les signatures.
            self.assertIn('DEMANDEUR', texte,
                          "le bloc de signatures doit être sur la dernière page")
            self.assertIn('MP-', texte,
                          "la dernière page doit contenir des lignes de données")
        finally:
            doc.close()

    def test_page_1_remplie_jusqu_en_bas(self):
        """Régression : le contenu d'une page pleine doit atteindre le bas de la page
        (les lignes sont étirées via une hauteur calculée) et non s'arrêter au milieu.

        On vérifie que la dernière ligne de données de la page 1 est rendue sous
        250mm alors qu'avant la correction elle s'arrêtait vers ~160mm.
        """
        if pymupdf is None:
            self.skipTest("pymupdf requis")

        bon = self._creer_bon('ENTREE')
        resp = self.client.get(reverse('imprimer_bon_multi_lignes', args=[bon.id]))
        self.assertEqual(resp.status_code, 200)
        doc = pymupdf.open(stream=resp.content, filetype='pdf')
        try:
            self.assertEqual(doc.page_count, 2)
            page1 = doc[0]
            # repère le bas de la dernière cellule de données de la page 1
            y_bas = None
            for blk in page1.get_text('dict')['blocks']:
                for line in blk.get('lines', []):
                    for span in line['spans']:
                        if span['text'].strip().startswith('MP-'):
                            y_bas = max(y_bas or 0, span['bbox'][3])
            self.assertIsNotNone(y_bas, "la page 1 doit contenir des lignes de données")
            # 842pt de hauteur, marge basse ~25pt : 250mm ≈ 708pt
            self.assertGreater(y_bas, 700,
                               f"la dernière ligne de la page 1 doit être en bas "
                               f"(y={y_bas:.0f}pt, <250mm attendu)")
        finally:
            doc.close()
