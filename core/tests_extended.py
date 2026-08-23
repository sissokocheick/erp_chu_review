# -*- coding: utf-8 -*-
"""
Tests étendus du module core.

Couvre : le singleton ConfigurationHopital, ses validations, la configuration
PDF, le formulaire d'édition, le modèle Service et la qualité du code vues.
"""
import ast
import os
from decimal import Decimal

from django.test import TestCase
from django.core.exceptions import ValidationError

from core.models import ConfigurationHopital, Service
from core.forms import ConfigurationHopitalForm
from core.models import TypeDocument


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
        self.assertEqual(obj._map_type_doc(TypeDocument.BS), 'BS')
        self.assertEqual(obj._map_type_doc('BON_ENTREE'), 'BE')
        self.assertEqual(obj._map_type_doc('BON_RETOUR'), 'BR')
        self.assertEqual(obj._map_type_doc('BON_HS'), 'BSHS')
        self.assertEqual(obj._map_type_doc('COMMANDE'), 'BC')
        self.assertEqual(obj._map_type_doc('DEMANDE'), 'BDM')
        self.assertEqual(obj._map_type_doc('INCONNU'), 'BS')

    def test_get_pdf_config_retourne_dict(self):
        obj = ConfigurationHopital.get_instance()
        cfg = obj.get_pdf_config(TypeDocument.BS)
        self.assertIsInstance(cfg, dict)
        for champ in ('afficher_logo', 'afficher_cachet', 'afficher_signatures',
                      'code_document', 'direction_label', 'couleur_principale',
                      'signataires'):
            self.assertIn(champ, cfg)

    def test_get_pdf_config_valeurs_defaut(self):
        obj = ConfigurationHopital.get_instance()
        cfg = obj.get_pdf_config(TypeDocument.BS)
        self.assertTrue(cfg['afficher_logo'])
        self.assertTrue(cfg['afficher_signatures'])
        self.assertEqual(cfg['direction_label'], obj.direction_label)
        self.assertEqual(cfg['couleur_principale'], obj.couleur_principale)

    def test_get_pdf_config_utilise_metadonnees_defaut(self):
        obj = ConfigurationHopital.get_instance()
        cfg = obj.get_pdf_config(TypeDocument.BS)
        self.assertEqual(cfg['code_document'], 'ENR-BSM/DAF-001')

    def test_creer_configs_documents_par_defaut(self):
        obj = ConfigurationHopital.get_instance()
        result = obj.creer_configs_documents_par_defaut()
        self.assertEqual(len(result), 6)

    def test_creer_configs_idempotent(self):
        obj = ConfigurationHopital.get_instance()
        obj.creer_configs_documents_par_defaut()
        result = obj.creer_configs_documents_par_defaut()
        self.assertEqual(len(result), 6)

    def test_signataires_config_six_roles(self):
        obj = ConfigurationHopital.get_instance()
        cfg = obj.get_pdf_config(TypeDocument.BS)
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


# ─── Audit qualité : aucune vue ne contient `except Exception: pass` ────

def _scan_views_for_silent_exception_pass():
    """
    Parcourt toutes les vues (FBV + CBV) et retourne la liste des
    ``except Exception: pass`` sans aucun logger/warning.

    Utilise l'AST pour être invariant au style (indentation, commentaires).
    """
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    view_dirs = [
        os.path.join(base, 'stock', 'views'),
        os.path.join(base, 'patrimoine', 'views'),
    ]
    view_files = [
        os.path.join(base, 'accounts', 'views.py'),
        os.path.join(base, 'core', 'views.py'),
    ]
    for d in view_dirs:
        if not os.path.isdir(d):
            continue
        for root, _, files in os.walk(d):
            for f in files:
                if f.endswith('.py'):
                    view_files.append(os.path.join(root, f))

    violations = []
    for fpath in view_files:
        if not os.path.exists(fpath):
            continue
        try:
            with open(fpath, 'r', encoding='utf-8') as fh:
                source = fh.read()
            tree = ast.parse(source, filename=fpath)
        except SyntaxError:
            continue

        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler) or not node.type:
                continue
            exc_name = getattr(node.type, 'id', None) or getattr(
                node.type, 'attr', None)
            if not exc_name or 'Exception' not in exc_name:
                continue

            # except Exception: pass  (uniquement pass, rien d'autre)
            body = node.body
            is_pass_only = (
                len(body) == 1 and isinstance(body[0], ast.Pass)
            )
            if not is_pass_only:
                continue

            # Vérifier s'il y a un appel de logger / logging / print
            has_log = False
            for child in ast.walk(node):
                if not isinstance(child, ast.Call):
                    continue
                func = child.func
                if isinstance(func, ast.Attribute):
                    if func.attr in (
                        'warning', 'error', 'info', 'debug',
                        'critical', 'log', 'exception',
                    ):
                        has_log = True
                elif isinstance(func, ast.Name):
                    if func.id in ('log', 'debug', 'info', 'warning',
                                   'error', 'critical', 'print'):
                        has_log = True
            if not has_log:
                rel = os.path.relpath(fpath, base)
                violations.append(f'{rel}:{node.lineno}')

    return violations


class TestCodeQualiteVues(TestCase):
    """Vérifie automatiquement que les vues ne contiennent pas de
    ``except Exception: pass`` silencieux (sans logger)."""

    def test_aucun_except_exception_pass_silencieux(self):
        """
        Aucune vue ne doit contenir ``except Exception: pass`` sans
        aucun logging (logger.warning, logger.error, etc.).

        Si ce test échoue, ajoutez un ``logger.warning(…)`` ou
        ``logger.error(…)`` dans le bloc except concerné.
        """
        violations = _scan_views_for_silent_exception_pass()
        if violations:
            msg = (
                f'{len(violations)} except Exception: pass silencieux '
                f'dans les vues:\n' + '\n'.join(
                    f'  - {v}' for v in violations
                ) + '\nAjoutez un logger.warning() ou logger.error() '
                'dans chaque bloc except.'
            )
            self.fail(msg)

    def test_toutes_les_vues_sont_parsables(self):
        """Vérifie qu'aucun fichier de vue ne contient d'erreur de syntaxe."""
        base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        view_dirs = [
            os.path.join(base, 'stock', 'views'),
            os.path.join(base, 'patrimoine', 'views'),
        ]
        view_files = [
            os.path.join(base, 'accounts', 'views.py'),
            os.path.join(base, 'core', 'views.py'),
        ]
        for d in view_dirs:
            if not os.path.isdir(d):
                continue
            for root, _, files in os.walk(d):
                for f in files:
                    if f.endswith('.py'):
                        view_files.append(os.path.join(root, f))

        syntax_errors = []
        for fpath in view_files:
            if not os.path.exists(fpath):
                continue
            try:
                with open(fpath, 'r', encoding='utf-8') as fh:
                    ast.parse(fh.read(), filename=fpath)
            except SyntaxError as e:
                rel = os.path.relpath(fpath, base)
                syntax_errors.append(f'{rel}: {e}')

        if syntax_errors:
            self.fail(
                f'{len(syntax_errors)} fichiers vues avec erreurs de '
                f'syntaxe:\n' + '\n'.join(
                    f'  - {e}' for e in syntax_errors
                )
            )
