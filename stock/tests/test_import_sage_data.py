# -*- coding: utf-8 -*-
"""
Tests de non-régression des données d'import Sage 100.

Les données d'import (familles, fournisseurs, services, articles) vivent
dans des fichiers CSV (`stock/management/commands/data_sage/`) et sont
chargées au niveau du module `import_sage_data`. Ces tests garantissent :

1. les 4 CSV sont bien lus (en-têtes attendus, contenu non vide) ;
2. les comptages restent stables (15 familles, 25 fournisseurs, 18
   services, 664 articles) — toute modification accidentelle d'un CSV
   (doublon, ligne supprimée, en-tête renommé) fera échouer la CI ;
3. la conversion des articles en tuples (référence, famille, désignation,
   unité, seuil_min, seuil_critique) est correcte ;
4. les codes sont uniques (pas de doublon dans les fichiers).
"""

from django.test import SimpleTestCase

from stock.management.commands.import_sage_data import (
    ARTICLES_DATA,
    FAMILLES_DATA,
    FOURNISSEURS_DATA,
    SERVICES_DATA,
    _lire_csv,
)

# Comptages de référence extraits des PDFs Sage 100 lors de la migration.
COMPTAGES = {
    "familles": 15,
    "fournisseurs": 25,
    "services": 18,
    "articles": 664,
}

EN_TETES = {
    "familles.csv": {"code", "intitule", "type", "methode", "categorie"},
    "fournisseurs.csv": {"code", "raison_sociale", "telephone"},
    "services.csv": {"code", "nom", "poste_telephone"},
    "articles.csv": {
        "reference", "famille_code", "designation", "unite",
        "seuil_min", "seuil_critique",
    },
}


class DataSageStabiliteTest(SimpleTestCase):
    """Les CSV data_sage sont lus et leurs comptages restent stables."""

    def test_comptages_stables(self):
        """15 familles / 25 fournisseurs / 18 services / 664 articles."""
        self.assertEqual(len(FAMILLES_DATA), COMPTAGES["familles"])
        self.assertEqual(len(FOURNISSEURS_DATA), COMPTAGES["fournisseurs"])
        self.assertEqual(len(SERVICES_DATA), COMPTAGES["services"])
        self.assertEqual(len(ARTICLES_DATA), COMPTAGES["articles"])

    def test_en_tetes_csv_attendus(self):
        """Chaque CSV expose exactement les colonnes attendues."""
        for nom_fichier, attendu in EN_TETES.items():
            lignes = _lire_csv(nom_fichier)
            self.assertGreater(len(lignes), 0, f"{nom_fichier} vide")
            self.assertEqual(
                set(lignes[0].keys()), attendu,
                f"en-têtes inattendus dans {nom_fichier}",
            )

    def test_contenu_representatif(self):
        """Échantillons de contenu : codes et libellés de référence."""
        self.assertEqual(FAMILLES_DATA[0]["code"], "AFE")
        self.assertIn("EXPLOITATION", FAMILLES_DATA[0]["intitule"].upper())
        self.assertEqual(FOURNISSEURS_DATA[0]["code"], "401BUR")
        self.assertTrue(FOURNISSEURS_DATA[0]["raison_sociale"].strip())
        self.assertEqual(SERVICES_DATA[0]["code"], "411AGC")
        self.assertTrue(SERVICES_DATA[0]["nom"].strip())
        premier_article = ARTICLES_DATA[0]
        self.assertTrue(premier_article[0].strip())  # référence
        self.assertTrue(premier_article[1].strip())  # famille_code

    def test_articles_convertis_en_tuples(self):
        """Chaque article est un tuple (str, str, str, str, int, int)."""
        for article in ARTICLES_DATA:
            self.assertIsInstance(article, tuple)
            self.assertEqual(len(article), 6)
            reference, famille_code, designation, unite, seuil_min, seuil_critique = article
            self.assertIsInstance(reference, str)
            self.assertIsInstance(famille_code, str)
            self.assertIsInstance(designation, str)
            self.assertIsInstance(unite, str)
            self.assertIsInstance(seuil_min, int)
            self.assertIsInstance(seuil_critique, int)
            self.assertTrue(reference.strip(), "référence d'article vide")
            self.assertTrue(famille_code.strip(), "famille d'article vide")
            self.assertGreaterEqual(seuil_min, 0)
            self.assertGreaterEqual(seuil_critique, 0)

    def test_codes_uniques(self):
        """Pas de doublon de code dans familles, fournisseurs, services
        ni de référence dans les articles."""
        codes_familles = [f["code"] for f in FAMILLES_DATA]
        codes_fournisseurs = [f["code"] for f in FOURNISSEURS_DATA]
        codes_services = [s["code"] for s in SERVICES_DATA]
        references = [a[0] for a in ARTICLES_DATA]
        self.assertEqual(len(codes_familles), len(set(codes_familles)))
        self.assertEqual(len(codes_fournisseurs), len(set(codes_fournisseurs)))
        self.assertEqual(len(codes_services), len(set(codes_services)))
        self.assertEqual(len(references), len(set(references)))
