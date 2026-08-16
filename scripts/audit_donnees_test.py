# -*- coding: utf-8 -*-
"""Audit des données de test dans la base dev.

Liste les enregistrements suspects (noms contenant TEST / PDF / MESURE / SIG /
ESSAI / DEMO / EXEMPLE / SAMPLE / TEMP) et les orphelins, sans rien modifier.
À lancer via : manage.py shell -c "exec(open('scripts/audit_donnees_test.py').read())"
"""


def main():
    from stock.models import (
        Article, FamilleArticle, Magasin, Fournisseur, Service, Beneficiaire,
        BonMouvement, Commande, DemandeMateriel, CampagneInventaire,
        PlanInventaireTournant, Ajustement, MotifAnnulation,
    )
    from patrimoine.models import (
        Immobilisation, CategoriePatrimoine, TypeEquipement, Batiment, Etage,
        Bureau, Marque, ContratMaintenance, Intervention, ImportPatrimoine,
    )
    from accounts.models import Profil
    from core.models import ConfigurationNotification

    MARKERS = ['test', 'pdf', 'mesure', 'sig', 'essai', 'demo', 'exemple',
               'sample', 'temp', 'rcfg']

    def suspect(v):
        if not v:
            return False
        s = str(v).lower()
        return any(m in s for m in MARKERS)

    def titre_field(model):
        for f in ('nom', 'titre', 'designation', 'intitule', 'raison_sociale',
                  'reference', 'code', 'nom_affichage', 'numero_serie'):
            if hasattr(model, f):
                return f
        return None

    tables = [
        (Magasin, 'Magasin'),
        (FamilleArticle, 'FamilleArticle'),
        (Article, 'Article'),
        (Fournisseur, 'Fournisseur'),
        (Service, 'Service'),
        (Beneficiaire, 'Beneficiaire'),
        (BonMouvement, 'BonMouvement'),
        (Commande, 'Commande'),
        (DemandeMateriel, 'DemandeMateriel'),
        (CampagneInventaire, 'CampagneInventaire'),
        (PlanInventaireTournant, 'PlanInventaireTournant'),
        (Ajustement, 'Ajustement'),
        (MotifAnnulation, 'MotifAnnulation'),
        (Immobilisation, 'Immobilisation'),
        (CategoriePatrimoine, 'CategoriePatrimoine'),
        (TypeEquipement, 'TypeEquipement'),
        (Batiment, 'Batiment'),
        (Etage, 'Etage'),
        (Bureau, 'Bureau'),
        (Marque, 'Marque'),
        (ContratMaintenance, 'ContratMaintenance'),
        (Intervention, 'Intervention'),
        (ImportPatrimoine, 'ImportPatrimoine'),
    ]

    print("═══ ENREGISTREMENTS SUSPECTS (nom contient TEST/PDF/MESURE/SIG/…) ═══")
    for model, label in tables:
        tf = titre_field(model)
        if not tf:
            continue
        suspects = model.objects.all()
        try:
            suspects = [o for o in suspects if suspect(getattr(o, tf, None))]
        except Exception:
            continue
        if suspects:
            print(f"\n--- {label} ({len(suspects)}) ---")
            for o in suspects[:40]:
                print(f"  id={o.id} | {getattr(o, tf)}")

    print("\n═══ ORPHELINS / ANOMALIES ═══")
    print("Immos sans type_equipement :",
          Immobilisation.objects.filter(type_equipement__isnull=True).count())
    print("Immos sans code_patrimoine :",
          Immobilisation.objects.filter(code_patrimoine__isnull=True).count())
    print("Immos sans service :",
          Immobilisation.objects.filter(service_affectation__isnull=True).count())
    print("Articles sans famille :",
          Article.objects.filter(famille__isnull=True).count())
    print("Bons sans magasin :",
          BonMouvement.objects.filter(magasin__isnull=True).count())

    print("\n═══ VOLUMES (repère) ═══")
    for model, label in tables:
        print(f"{label}: {model.objects.count()}")
    print(f"Profil: {Profil.objects.count()}")
    # ConfigurationPdf a été fusionné dans ConfigurationHopital/paramétrage
    print(f"ConfigurationNotification: {ConfigurationNotification.objects.count()}")


main()
