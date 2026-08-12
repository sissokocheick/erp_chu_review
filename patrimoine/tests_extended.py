# -*- coding: utf-8 -*-
"""
Tests étendus du module patrimoine.

Couvre : amortissement (linéaire et dégressif), modèles (localisation,
contrats), permissions déclarées.
Les cas d'amortissement sont générés dynamiquement (chaque cas = un test).
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from patrimoine.models import (
    Immobilisation, TypeEquipement, CategoriePatrimoine, Batiment, Etage,
    Bureau, ContratMaintenance,
)
from stock.models import Fournisseur


def creer_immobilisation(valeur_acquisition, duree, valeur_residuelle,
                         mode='LINEAIRE', jours_ecoules=0, **kwargs):
    kwargs.setdefault('date_mise_en_service',
                      timezone.now().date() - timedelta(days=jours_ecoules))
    return Immobilisation.objects.create(
        nom_affichage=f"Immo {kwargs.pop('nom', '') or valeur_acquisition}",
        valeur_acquisition=Decimal(str(valeur_acquisition)),
        duree_amortissement_ans=duree,
        valeur_residuelle=Decimal(str(valeur_residuelle)),
        mode_amortissement=mode,
        **kwargs,
    )


def vnc_attendue(case):
    """Calcule la VNC attendue avec la même formule métier (tests de câblage)."""
    acq = Decimal(str(case['acq']))
    res = Decimal(str(case['res']))
    duree = case['duree']
    jours = case['jours']
    mode = case['mode']
    annees = Decimal(str(round(jours / 365, 4)))
    if mode == 'LINEAIRE':
        annual = (acq - res) / Decimal(str(duree)) if duree else Decimal('0')
        return max(res, acq - annual * annees)
    coeff = Decimal('1.5') if duree <= 5 else Decimal('2.0')
    taux = coeff / Decimal(str(duree))
    return max(res, acq * (1 - taux) ** int(annees))


class AmortissementLineaireTest(TestCase):
    """Cas d'amortissement linéaire (chaque cas = un test)."""


# (valeur_acquisition, valeur_residuelle, duree_ans, jours_ecoules, vnc_attendue)
LINEAIRE_CASES = [
    (100000, 0, 5, 0, '100000'),
    (100000, 0, 5, 365, '80000'),
    (100000, 0, 5, 730, '60000'),
    (100000, 0, 5, 1095, '40000'),
    (100000, 0, 5, 1460, '20000'),
    (100000, 0, 5, 1825, '0'),
    (100000, 0, 5, 2190, '0'),          # au-delà de la durée
    (120000, 20000, 5, 365, '100000'),
    (120000, 20000, 5, 1825, '20000'),  # plancher = valeur résiduelle
    (60000, 0, 10, 1095, '42000'),
    (60000, 0, 10, 3650, '0'),
    (50000, 5000, 5, 365, '41000'),
    (250000, 0, 5, 730, '150000'),
    (100000, 0, 4, 365, '75000'),
    (100000, 0, 4, 1460, '0'),
    (100000, 100000, 5, 365, '100000'),  # résiduelle = acquisition
    (0, 0, 5, 365, '0'),
    (100000, 0, 1, 365, '0'),
    (300000, 0, 5, 365, '240000'),
    (300000, 0, 5, 730, '180000'),
    (300000, 0, 5, 1095, '120000'),
    (80000, 8000, 4, 730, '44000'),
    (150000, 0, 10, 1825, '75000'),
    (150000, 0, 10, 3650, '0'),
    (45000, 0, 3, 365, '30000'),
    (45000, 0, 3, 730, '15000'),
    (90000, 0, 6, 1095, '45000'),
    (200000, 20000, 5, 1095, '92000'),
    (75000, 0, 5, 365, '60000'),
    (75000, 0, 5, 730, '45000'),
    (55000, 0, 5, 1095, '22000'),
    (55000, 0, 5, 1825, '0'),
    (100000, 0, 8, 365, '87500'),
    (100000, 0, 8, 1460, '50000'),
    (240000, 0, 8, 365, '210000'),
    (240000, 0, 8, 2920, '0'),
    (36000, 3600, 3, 365, '25200'),
    (36000, 3600, 3, 1095, '3600'),
    (180000, 0, 5, 365, '144000'),
    (180000, 0, 5, 730, '108000'),
    (130000, 30000, 5, 730, '90000'),
]


def _make_lineaire(acq, res, duree, jours, vnc):
    def test(self):
        immo = creer_immobilisation(acq, duree, res, 'LINEAIRE', jours)
        self.assertEqual(immo.amortissement_annuel, (Decimal(str(acq)) - Decimal(str(res))) / Decimal(str(duree)))
        self.assertEqual(immo.vnc, Decimal(vnc))
    return test


for _i, (acq, res, duree, jours, vnc) in enumerate(LINEAIRE_CASES):
    setattr(AmortissementLineaireTest, f'test_lin_{_i:03d}_acq{acq}_dur{duree}',
            _make_lineaire(acq, res, duree, jours, vnc))


class AmortissementDegressifTest(TestCase):
    """Cas d'amortissement dégressif (chaque cas = un test)."""


# (valeur_acquisition, valeur_residuelle, duree_ans, jours_ecoules, vnc_attendue)
DEGRESSIF_CASES = [
    (100000, 0, 5, 365, '70000'),    # taux 1.5/5 = 0.30
    (100000, 0, 5, 730, '49000'),
    (100000, 0, 5, 1095, '34300'),
    (100000, 0, 10, 365, '80000'),   # taux 2/10 = 0.20
    (100000, 0, 10, 730, '64000'),
    (100000, 0, 10, 1095, '51200'),
    (100000, 0, 4, 365, '62500'),    # duree<=5 → coeff 1.5, taux 0.375
    (100000, 0, 4, 730, '39062.50'),
    (100000, 0, 3, 365, '50000'),    # taux 1.5/3 = 0.50
    (100000, 0, 3, 730, '25000'),
    (200000, 0, 5, 365, '140000'),
    (200000, 0, 5, 730, '98000'),
    (50000, 0, 5, 365, '35000'),
    (50000, 0, 10, 365, '40000'),
    (100000, 20000, 5, 365, '70000'),
    (100000, 20000, 5, 1095, '34300'),
    (100000, 50000, 5, 1825, '50000'),  # plancher résiduelle
    (300000, 0, 5, 730, '147000'),
    (80000, 0, 4, 365, '50000'),
    (80000, 0, 4, 730, '31250'),
    (150000, 0, 10, 1095, '76800'),
    (120000, 0, 5, 182, '120000'),   # < 1 an : int(annees)=0 → pas d'amortissement

    (120000, 0, 5, 365, '84000'),
    (250000, 0, 10, 730, '160000'),
    (60000, 0, 5, 1095, '20580'),
    (60000, 0, 5, 1460, '14406'),
    (90000, 0, 4, 365, '56250'),
    (100000, 0, 20, 365, '90000'),   # taux 2/20 = 0.10
    (100000, 0, 20, 730, '81000'),
    (400000, 0, 5, 365, '280000'),
]


def _make_degressif(acq, res, duree, jours, vnc):
    def test(self):
        immo = creer_immobilisation(acq, duree, res, 'DEGRESSIF', jours)
        self.assertEqual(immo.vnc, Decimal(vnc))
    return test


for _i, (acq, res, duree, jours, vnc) in enumerate(DEGRESSIF_CASES):
    setattr(AmortissementDegressifTest, f'test_deg_{_i:03d}_acq{acq}_dur{duree}',
            _make_degressif(acq, res, duree, jours, vnc))


class AmortissementGeneriqueTest(TestCase):
    """Propriétés calculées et comportements transverses (cas générés)."""

    def test_taux_amorti_pct(self):
        immo = creer_immobilisation(100000, 5, 0, 'LINEAIRE', 365)
        self.assertEqual(immo.taux_amorti_pct, Decimal('20.0'))

    def test_taux_amorti_zero(self):
        immo = creer_immobilisation(0, 5, 0, 'LINEAIRE', 365)
        self.assertEqual(immo.taux_amorti_pct, Decimal('0'))

    def test_est_totalement_amorti(self):
        immo = creer_immobilisation(100000, 5, 0, 'LINEAIRE', 365 * 6)
        self.assertTrue(immo.est_totalement_amorti)

    def test_pas_totalement_amorti(self):
        immo = creer_immobilisation(100000, 5, 0, 'LINEAIRE', 365)
        self.assertFalse(immo.est_totalement_amorti)

    def test_date_debut_amort_fallback_acquisition(self):
        immo = creer_immobilisation(100000, 5, 0, 'LINEAIRE', 0,
                                    date_mise_en_service=None,
                                    date_acquisition=timezone.now().date())
        self.assertEqual(immo.date_debut_amort, immo.date_acquisition)

    def test_annees_ecoulees_zero_sans_date(self):
        immo = creer_immobilisation(100000, 5, 0, 'LINEAIRE', 0,
                                    date_mise_en_service=None)
        self.assertEqual(immo.annees_ecoulees, Decimal('0'))

    def test_annees_ecoulees_un_an(self):
        immo = creer_immobilisation(100000, 5, 0, 'LINEAIRE', 365)
        self.assertEqual(immo.annees_ecoulees, Decimal('1.0'))


# Cas générés : vérifient le câblage (dates → années → VNC) sur un large
# spectre de valeurs, en miroir de la formule métier.
GENERIC_CASES = [
    {'acq': v, 'res': r, 'duree': d, 'jours': j, 'mode': m}
    for v in (1000, 5000, 10000, 25000, 50000, 100000, 250000, 500000, 1000000)
    for r in (0, 0.1, 0.25)
    for d in (3, 5, 8, 10)
    for j in (0, 30, 182, 365, 730, 1460, 2190)
    for m in ('LINEAIRE', 'DEGRESSIF')
]


def _make_generique(case):
    def test(self):
        res_pct = Decimal(str(case['res']))
        res = (Decimal(str(case['acq'])) * res_pct).quantize(Decimal('1'))
        immo = creer_immobilisation(case['acq'], case['duree'], res,
                                    case['mode'], case['jours'])
        attendue = vnc_attendue({**case, 'res': res})
        self.assertEqual(immo.vnc, attendue)
    return test


for _i, case in enumerate(GENERIC_CASES):
    setattr(AmortissementGeneriqueTest, f'test_gen_{_i:04d}', _make_generique(case))


# ════════════════════════════════════════════════════════════════
# Modèles — TypeEquipement, localisation, contrats
# ════════════════════════════════════════════════════════════════
class ModelesPatrimoineTest(TestCase):

    def test_type_equipement_herite_params(self):
        cat = CategoriePatrimoine.objects.create(code="ELEC", nom="Electrique")
        te = TypeEquipement.objects.create(
            categorie=cat, code="TE-GE", nom="Groupe Electrogene",
            duree_amortissement_defaut=8,
            mode_amortissement='DEGRESSIF',
            valeur_residuelle_pct=Decimal('10.00'),
        )
        immo = Immobilisation.objects.create(
            nom_affichage="GE-01",
            valeur_acquisition=Decimal('100000'),
            type_equipement=te,
        )
        self.assertEqual(immo.duree_amortissement_ans, 8)
        self.assertEqual(immo.mode_amortissement, 'DEGRESSIF')
        self.assertEqual(immo.valeur_residuelle, Decimal('10000.00'))

    def test_type_equipement_sans_heritage(self):
        immo = creer_immobilisation(100000, 5, 0, 'LINEAIRE', 0)
        self.assertEqual(immo.duree_amortissement_ans, 5)

    def test_batiment_etage_bureau_hierarchie(self):
        batiment = Batiment.objects.create(nom="Batiment A")
        etage = Etage.objects.create(batiment=batiment, nom="1er Etage")
        bureau = Bureau.objects.create(etage=etage, nom="Bureau 204")
        self.assertEqual(bureau.batiment, batiment)
        self.assertEqual(etage.batiment, batiment)

    def _contrat(self, jours_relatifs):
        fournisseur = Fournisseur.objects.create(code="F001", raison_sociale="Mainteneur")
        return ContratMaintenance.objects.create(
            reference="CT-001", prestataire=fournisseur,
            date_debut=timezone.now().date() - timedelta(days=100),
            date_fin=timezone.now().date() + timedelta(days=jours_relatifs),
        )

    def test_contrat_expire(self):
        fournisseur = Fournisseur.objects.create(code="F002", raison_sociale="Mainteneur 2")
        contrat = ContratMaintenance.objects.create(
            reference="CT-002", prestataire=fournisseur,
            date_debut=timezone.now().date() - timedelta(days=100),
            date_fin=timezone.now().date() - timedelta(days=5))
        self.assertTrue(contrat.est_expire)

    def test_contrat_non_expire(self):
        self.assertFalse(self._contrat(30).est_expire)

    def test_contrat_jours_restants(self):
        self.assertEqual(self._contrat(12).jours_restants, 12)

    def test_immobilisation_statut_par_defaut(self):
        immo = creer_immobilisation(10000, 5, 0)
        self.assertEqual(immo.statut, 'EN_ATTENTE')

    def test_immobilisation_str(self):
        immo = creer_immobilisation(10000, 5, 0, nom="Ordinateur")
        self.assertIn("Ordinateur", str(immo))


# ════════════════════════════════════════════════════════════════
# Permissions patrimoine
# ════════════════════════════════════════════════════════════════
class PermissionsPatrimoineTest(TestCase):
    """Vérifie que toutes les permissions patrimoine sont déclarées."""

    def test_permissions_declarees(self):
        from accounts.models import MENU_ACCESS_PERMISSIONS
        codes = [c for c, _ in MENU_ACCESS_PERMISSIONS if c.startswith('menu_pat')]
        self.assertGreaterEqual(len(codes), 25)

    def test_permissions_commencent_par_menu_pat(self):
        from accounts.models import MENU_ACCESS_PERMISSIONS
        for code, _ in MENU_ACCESS_PERMISSIONS:
            if code.startswith('menu_pat'):
                self.assertTrue(code.startswith('menu_pat'))

    def test_codes_permissions_uniques(self):
        from accounts.models import MENU_ACCESS_PERMISSIONS
        codes = [c for c, _ in MENU_ACCESS_PERMISSIONS]
        self.assertEqual(len(codes), len(set(codes)))

    def test_labels_permissions_non_vides(self):
        from accounts.models import MENU_ACCESS_PERMISSIONS
        for code, label in MENU_ACCESS_PERMISSIONS:
            if code.startswith('menu_pat'):
                self.assertTrue(label.strip())
