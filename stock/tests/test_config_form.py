# -*- coding: utf-8 -*-
"""
Tests de régression : formulaire « Identité & Cartouche PDF » de la page
Paramètres Administratifs (ex-onglet Entreprise).

Le formulaire avait été cassé par la migration mono-tenant : la vue ne
fournissait ni le formulaire ni l'instance, et le POST n'avait aucun handler.
"""
from django.test import TestCase
from django.urls import reverse

from core.models import ConfigurationHopital
from core.forms import ConfigurationHopitalForm
from accounts.models import ConfigDocument
from stock.tests import factories


class ConfigurationFormTest(TestCase):
    """Vérifie l'affichage et l'enregistrement de la configuration."""

    def setUp(self):
        self.superuser = factories.creer_superuser(username="admin_config")
        factories.desactiver_changement_mdp(self.superuser)
        self.client.force_login(self.superuser)
        self.config = ConfigurationHopital.get_instance()
        self.url = reverse('parametres_administratifs')

    def test_page_accessible_superuser(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200,
                         msg=f"redirect={getattr(response, 'url', None)}")

    def test_contexte_contient_form_config(self):
        response = self.client.get(self.url)
        self.assertIn('form_config', response.context)
        self.assertIsInstance(response.context['form_config'], ConfigurationHopitalForm)

    def test_contexte_contient_config_hopital(self):
        response = self.client.get(self.url)
        self.assertEqual(response.context['config_hopital'], self.config)

    def test_contexte_contient_configs_list(self):
        response = self.client.get(self.url)
        configs = response.context['configs_list']
        self.assertEqual(len(configs), len(ConfigDocument.TYPE_DOC_CHOICES))
        codes = [c['code'] for c in configs]
        for code, _ in ConfigDocument.TYPE_DOC_CHOICES:
            self.assertIn(code, codes)

    def test_contexte_contient_historique(self):
        response = self.client.get(self.url)
        self.assertIn('historique_config', response.context)

    def test_form_config_pre_rempli(self):
        self.config.nom = "CHU d'Angré"
        self.config.save()
        response = self.client.get(self.url)
        form = response.context['form_config']
        self.assertEqual(form['nom'].value(), "CHU d'Angré")

    def test_post_enregistre_config(self):
        response = self.client.post(self.url, {
            'enregistrer_config': '1',
            'nom': "CHU d'Angré",
            'couleur_principale': '#123456',
            'telephone': '27 22 45 00 00',
            'email_contact': 'contact@chu-angre.ci',
            'cc': 'CC-2026',
            'ifu': 'IFU-2026',
            'rccm': 'RCCM-2026',
            'ville': 'Abidjan',
            'pays': "Côte d'Ivoire",
            'direction_label': 'DIRECTION',
            'sous_direction_label': 'SOUS-DIRECTION',
            'service_label': 'SERVICE',
            'pied_page_pdf': 'Pied de page test',
            'prefixe_bon_sortie': 'BSX',
            'prefixe_bon_entree': 'BEX',
            'prefixe_bon_retour': 'BRX',
            'prefixe_bon_hors_stock': 'HSX',
            'prefixe_commande': 'BCX',
            'label_signataire_1': 'S1',
            'label_signataire_2': 'S2',
            'label_signataire_3': 'S3',
            'label_signataire_4': 'S4',
            'label_signataire_5': 'S5',
            'label_signataire_6': 'S6',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        self.config.refresh_from_db()
        self.assertEqual(self.config.nom, "CHU d'Angré")
        self.assertEqual(self.config.ifu, 'IFU-2026')
        self.assertEqual(self.config.prefixe_bon_sortie, 'BSX')
        self.assertEqual(self.config.label_signataire_6, 'S6')

    def test_post_config_invalide_retourne_erreur(self):
        response = self.client.post(self.url, {
            'enregistrer_config': '1',
            'nom': "",
            'couleur_principale': 'pas-une-couleur',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        data = response.json()
        self.assertFalse(data['success'])

    def test_post_config_doc_enregistre(self):
        config_doc, _ = ConfigDocument.objects.get_or_create(
            type_doc='BS', defaults={'code_document': 'ENR-BSM/DAF-001'})
        response = self.client.post(self.url, {
            'enregistrer_config_doc': '1',
            'doc_type': 'BS',
            'code_document_BS': 'ENR-BSM/DAF-099',
            'version_doc_BS': '003',
            'date_creation_doc_BS': '01/01/2026',
            'date_revision_doc_BS': '02/02/2026',
            'ps2_label_BS': 'PS2 TEST',
            'afficher_logo_BS': 'on',
            'afficher_cachet_BS': '',
            'afficher_cc_BS': 'on',
            'afficher_ifu_BS': 'on',
            'afficher_rccm_BS': 'on',
            'afficher_telephone_BS': 'on',
            'afficher_signatures_BS': 'on',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        config_doc.refresh_from_db()
        self.assertEqual(config_doc.code_document, 'ENR-BSM/DAF-099')
        self.assertEqual(config_doc.version_doc, '003')
        self.assertFalse(config_doc.afficher_cachet)

    def test_post_config_doc_type_inconnu(self):
        response = self.client.post(self.url, {
            'enregistrer_config_doc': '1',
            'doc_type': 'ZZ',
        }, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        data = response.json()
        self.assertFalse(data['success'])

    def test_page_redirige_utilisateur_non_autorise(self):
        user = factories.creer_utilisateur(username="simple_user")
        factories.desactiver_changement_mdp(user)
        self.client.force_login(user)
        response = self.client.get(self.url)
        self.assertNotEqual(response.status_code, 200)

    def test_page_redirige_non_connecte(self):
        self.client.logout()
        response = self.client.get(self.url)
        self.assertIn(response.status_code, (301, 302))

    def test_formulaires_des_types_documents_couples(self):
        """Chaque type de doc a ses 7 cases d'affichage."""
        response = self.client.get(self.url)
        for item in response.context['configs_list']:
            cfg = item['config']
            for champ in ('afficher_logo', 'afficher_cachet', 'afficher_cc',
                          'afficher_ifu', 'afficher_rccm', 'afficher_telephone',
                          'afficher_signatures'):
                self.assertIn(champ, cfg)
