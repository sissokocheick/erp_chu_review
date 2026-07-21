from django.test import TestCase
from django.core.exceptions import PermissionDenied
from core.managers import set_current_tenant, get_current_tenant, TenantManager
from core.models import Service, ConfigurationHopital
from accounts.models import Entreprise

class TenantIsolationTest(TestCase):
    """Tests d'isolation multi-tenant."""
    
    def setUp(self):
        self.entreprise_a = Entreprise.objects.create(nom="Entreprise A")
        self.entreprise_b = Entreprise.objects.create(nom="Entreprise B")
        
    def test_tenant_manager_returns_none_without_tenant(self):
        """Sans tenant, TenantManager doit retourner queryset vide."""
        set_current_tenant(None)
        qs = Service.objects.all()
        self.assertEqual(qs.count(), 0)
        
    def test_tenant_manager_filters_by_tenant(self):
        """Avec tenant, TenantManager filtre correctement."""
        Service.objects.create(entreprise=self.entreprise_a, code="S1", nom="Service 1")
        Service.objects.create(entreprise=self.entreprise_b, code="S2", nom="Service 2")
        
        set_current_tenant(self.entreprise_a)
        qs = Service.objects.all()
        self.assertEqual(qs.count(), 1)
        self.assertEqual(qs.first().code, "S1")
        
    def test_global_manager_returns_all(self):
        """GlobalManager retourne toutes les entreprises."""
        Service.objects.create(entreprise=self.entreprise_a, code="S1", nom="Service 1")
        Service.objects.create(entreprise=self.entreprise_b, code="S2", nom="Service 2")
        
        set_current_tenant(None)
        qs = Service.all_objects.all()
        self.assertEqual(qs.count(), 2)

class PDFPaginationTest(TestCase):
    """Tests de pagination PDF."""
    
    def test_single_page(self):
        """≤ 28 lignes = page unique."""
        from core.pdf_pagination import paginer_bon_sortie
        lignes = [{'designation': 'Article ' + str(i)} for i in range(28)]
        config = {}
        result = paginer_bon_sortie(lignes, config)
        self.assertFalse(result.est_multi_page)
        self.assertEqual(len(result.pages), 1)
        
    def test_multi_page(self):
        """> 28 lignes = multi-page."""
        from core.pdf_pagination import paginer_bon_sortie
        lignes = [{'designation': 'Article ' + str(i)} for i in range(50)]
        config = {}
        result = paginer_bon_sortie(lignes, config)
        self.assertTrue(result.est_multi_page)
        self.assertGreater(len(result.pages), 1)
        
    def test_last_page_not_empty(self):
        """Dernière page a toujours ≥ 5 lignes."""
        from core.pdf_pagination import paginer_bon_sortie
        lignes = [{'designation': 'Article ' + str(i)} for i in range(33)]
        config = {}
        result = paginer_bon_sortie(lignes, config)
        last_page = result.pages[-1]
        self.assertGreaterEqual(len(last_page.lignes), 5)