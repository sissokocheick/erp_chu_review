# -*- coding: utf-8 -*-
"""
Tests étendus du module core.

Couvre : le singleton ConfigurationHopital, ses validations, la configuration
PDF, le formulaire d'édition et le modèle Service.
"""
from decimal import Decimal

from django.test import TestCase
from django.core.exceptions import ValidationError

from core.models import ConfigurationHopital, Service
from core.forms import ConfigurationHopitalForm
from accounts.models import ConfigDocument


class ConfigurationHopitalTest(TestCase):

    def test_get_instance_cree_singleton(self):
        obj = ConfigurationHopital.get_instance()
        self.assertIsNotNone(obj.pk)

    def test_get_instance_idempotent(self):
        obj1 = ConfigurationHopital.get_instance()
        obj2 = ConfigurationHopital.get_instance()
        self.assertEqual(obj1.pk, obj2.pk)
        self.assertEqual(ConfigurationHopital.objects.count(), 1)

    def test_nom_par_defaut(self):
        obj = ConfigurationHopital.get_instance()
        self.assertTrue(obj.nom)

    def test_couleur_par_defaut(self):
        obj = ConfigurationHopital.get_instance()
        self.assertEqual(obj.couleur_principale, '#1c5b96')

    def test_str(self):
        obj = ConfigurationHopital.get_instance()
        self.assertEqual(str(obj), obj.nom)

    def test_clean_couleur_valide(self):
        obj = ConfigurationHopital.get_instance()
        obj.couleur_principale = '#A1B2C3'
        obj.full_clean()

    def test_clean_couleur_invalide(self):
        obj = ConfigurationHopital.get_instance()
        obj.couleur_principale = 'rouge'
        with self.assertRaises(ValidationError):
            obj.full_clean()

    def test_clean_couleur_courte_invalide(self):
        obj = ConfigurationHopital.get_instance()
        obj.couleur_principale = '#fff'
        with self.assertRaises(ValidationError):
            obj.full_clean()

    def test_labels_signatures_six(self):
        obj = ConfigurationHopital.get_instance()
        self.assertEqual(len(obj.labels_signatures), 6)

    def test_labels_signatures_defauts(self):
        obj = ConfigurationHopital.get_instance()
        self.assertEqual(obj.labels_signatures[0], "Le Demandeur")

    def test_map_type_doc(self):
        obj = ConfigurationHopital.get_instance()
        self.assertEqual(obj._map_type_doc('BON_SORTIE'), 'BS')
        self.assertEqual(obj._map_type_doc('BON_ENTREE'), 'BE')
        self.assertEqual(obj._map_type_doc('BON_RETOUR'), 'BR')
        self.assertEqual(obj._map_type_doc('BON_HS'), 'BSHS')
        self.assertEqual(obj._map_type_doc('COMMANDE'), 'BC')
        self.assertEqual(obj._map_type_doc('DEMANDE'), 'BDM')
        self.assertEqual(obj._map_type_doc('INCONNU'), 'BS')

    def test_get_pdf_config_retourne_dict(self):
        obj = ConfigurationHopital.get_instance()
        cfg = obj.get_pdf_config('BON_SORTIE')
        self.assertIsInstance(cfg, dict)
        for champ in ('afficher_logo', 'afficher_cachet', 'afficher_signatures',
                      'code_document', 'direction_label', 'couleur_principale',
                      'signataires'):
            self.assertIn(champ, cfg)

    def test_get_pdf_config_valeurs_defaut(self):
        obj = ConfigurationHopital.get_instance()
        cfg = obj.get_pdf_config('BON_SORTIE')
        self.assertTrue(cfg['afficher_logo'])
        self.assertTrue(cfg['afficher_signatures'])
        self.assertEqual(cfg['direction_label'], obj.direction_label)
        self.assertEqual(cfg['couleur_principale'], obj.couleur_principale)

    def test_get_pdf_config_utilise_config_document(self):
        ConfigDocument.objects.get_or_create(
            type_doc='BS', defaults={'code_document': 'ENR-BSM/DAF-001'})
        cd = ConfigDocument.objects.get(type_doc='BS')
        cd.code_document = 'CODE-CUSTOM'
        cd.save()
        obj = ConfigurationHopital.get_instance()
        cfg = obj.get_pdf_config('BON_SORTIE')
        self.assertEqual(cfg['code_document'], 'CODE-CUSTOM')

    def test_creer_configs_documents_par_defaut(self):
        obj = ConfigurationHopital.get_instance()
        obj.creer_configs_documents_par_defaut()
        self.assertEqual(ConfigDocument.objects.count(), 6)

    def test_creer_configs_idempotent(self):
        obj = ConfigurationHopital.get_instance()
        obj.creer_configs_documents_par_defaut()
        obj.creer_configs_documents_par_defaut()
        self.assertEqual(ConfigDocument.objects.count(), 6)

    def test_signataires_config_six_roles(self):
        obj = ConfigurationHopital.get_instance()
        cfg = obj.get_pdf_config('BON_SORTIE')
        self.assertEqual(len(cfg['signataires']), 6)
        self.assertEqual(cfg['signataires'][0]['ordre'], 1)


class ConfigurationHopitalFormTest(TestCase):

    def test_form_valide_enregistre(self):
        config = ConfigurationHopital.get_instance()
        form = ConfigurationHopitalForm({
            'nom': "CHU d'Angré",
            'couleur_principale': '#123456',
            'telephone': '27 22 45 00 00',
            'email_contact': 'contact@chu.ci',
            'cc': 'CC-1', 'ifu': 'IFU-1', 'rccm': 'RCCM-1',
            'ville': 'Abidjan', 'pays': "Côte d'Ivoire",
            'direction_label': 'DIR', 'sous_direction_label': 'SOUS-DIR',
            'service_label': 'SVC', 'pied_page_pdf': 'pied',
            'prefixe_bon_sortie': 'BS', 'prefixe_bon_entree': 'BE',
            'prefixe_bon_retour': 'BR', 'prefixe_bon_hors_stock': 'HS',
            'prefixe_commande': 'BC',
            'label_signataire_1': 'S1', 'label_signataire_2': 'S2',
            'label_signataire_3': 'S3', 'label_signataire_4': 'S4',
            'label_signataire_5': 'S5', 'label_signataire_6': 'S6',
        }, instance=config)
        self.assertTrue(form.is_valid(), form.errors)
        config = form.save()
        self.assertEqual(config.nom, "CHU d'Angré")
        self.assertEqual(config.prefixe_bon_sortie, 'BS')

    def test_form_couleur_invalide(self):
        config = ConfigurationHopital.get_instance()
        form = ConfigurationHopitalForm({
            'nom': "Test", 'couleur_principale': 'bleu',
        }, instance=config)
        self.assertFalse(form.is_valid())

    def test_form_nom_requis(self):
        config = ConfigurationHopital.get_instance()
        form = ConfigurationHopitalForm({'nom': ''}, instance=config)
        self.assertFalse(form.is_valid())
        self.assertIn('nom', form.errors)

    def test_form_champs_presents(self):
        form = ConfigurationHopitalForm()
        for champ in ('nom', 'couleur_principale', 'logo', 'cachet',
                      'telephone', 'email_contact', 'cc', 'ifu', 'rccm',
                      'prefixe_bon_sortie', 'label_signataire_6'):
            self.assertIn(champ, form.fields)


class ServiceModelTest(TestCase):

    def test_creation_service(self):
        service = Service.objects.create(code="URG", nom="Urgences")
        self.assertEqual(str(service), "URG - Urgences")

    def test_service_telephones_optionnels(self):
        service = Service.objects.create(
            code="REA", nom="Réanimation", poste_telephone="200",
            telephone="22 00 00 00", telecopie="22 00 00 01")
        self.assertEqual(service.poste_telephone, "200")
