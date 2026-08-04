from django.test import TestCase
from core.pdf_pagination import paginer_bon_sortie


class PDFPaginationTest(TestCase):
    """Tests de pagination PDF."""

    def test_single_page(self):
        """≤ 28 lignes = page unique."""
        lignes = [{'designation': 'Article ' + str(i)} for i in range(28)]
        config = {}
        result = paginer_bon_sortie(lignes, config)
        self.assertFalse(result.est_multi_page)
        self.assertEqual(len(result.pages), 1)

    def test_multi_page(self):
        """> 28 lignes = multi-page."""
        lignes = [{'designation': 'Article ' + str(i)} for i in range(50)]
        config = {}
        result = paginer_bon_sortie(lignes, config)
        self.assertTrue(result.est_multi_page)
        self.assertGreater(len(result.pages), 1)

    def test_last_page_not_empty(self):
        """Dernière page a toujours ≥ 5 lignes."""
        lignes = [{'designation': 'Article ' + str(i)} for i in range(33)]
        config = {}
        result = paginer_bon_sortie(lignes, config)
        last_page = result.pages[-1]
        self.assertGreaterEqual(len(last_page.lignes), 5)
