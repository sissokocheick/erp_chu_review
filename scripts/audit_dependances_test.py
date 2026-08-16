# -*- coding: utf-8 -*-
"""Vérifie les dépendances des données de test avant nettoyage."""

def main():
    from django.contrib.auth.models import User
    from stock.models import (
        Magasin, Fournisseur, Service, BonMouvement, StockItem,
        CampagneInventaire, PlanInventaireTournant, Commande, DemandeMateriel,
        Article, LigneBon, Mouvement, Ajustement,
    )
    from patrimoine.models import Immobilisation

    print("═══ IMMO SANS TYPE ═══")
    for im in Immobilisation.objects.filter(type_equipement__isnull=True):
        print(f"  id={im.id} | nom={im.nom_affichage!r} | code={im.code_patrimoine!r} "
              f"| serie={im.numero_serie!r} | statut={im.statut}")
        print(f"    interventions={im.interventions.count()} "
              f"mouvements={im.mouvements.count()} "
              f"contrat={im.contrat_maintenance_id}")

    print("\n═══ MAGASINS SUSPECTS — RÉFÉRENCES ═══")
    sus_ids = [5, 6, 7, 8, 9, 10, 11, 12, 14, 21, 22, 23]
    for m in Magasin.objects.filter(id__in=sus_ids).order_by('id'):
        bons = BonMouvement.objects.filter(magasin=m).count()
        stocks = StockItem.objects.filter(magasin=m).count()
        camp = CampagneInventaire.objects.filter(magasin=m).count()
        plans = PlanInventaireTournant.objects.filter(magasin=m).count()
        com = Commande.objects.filter(magasin=m).count()
        dem = DemandeMateriel.objects.filter(magasin_cible=m).count()
        mvt = Mouvement.objects.filter(magasin=m).count()
        print(f"  {m.id} {m.nom!r}: bons={bons} stocks={stocks} campagnes={camp} "
              f"plans={plans} commandes={com} demandes={dem} mouvements={mvt}")

    print("\n═══ FOURNISSEUR / SERVICE PDF TEST ═══")
    from stock.models import LigneBon
    for f in Fournisseur.objects.filter(id=2):
        bons = BonMouvement.objects.filter(fournisseur=f).count()
        lignes = LigneBon.objects.filter(bon__fournisseur=f).count()
        print(f"  Fournisseur {f.id} {f.raison_sociale!r}: bons={bons}")
    for s in Service.objects.filter(id=2):
        bons = BonMouvement.objects.filter(service_demandeur=s).count()
        print(f"  Service {s.id} {s.nom!r}: bons={bons}")

    print("\n═══ CAMPAGNES ROTATION TEST ═══")
    for c in CampagneInventaire.objects.filter(id__in=[3, 4, 5]):
        print(f"  campagne id={c.id} {c.titre!r}: lignes={c.lignes_inventaire.count()} "
              f"magasin={c.magasin_id} statut={c.statut}")
    print(f"  plan id=1 {PlanInventaireTournant.objects.filter(id=1).first()!r}")

    print("\n═══ AUTRES TABLES ═══")
    print("  Campagne '01' (id non 3-5):",
          list(CampagneInventaire.objects.exclude(id__in=[3, 4, 5])
               .values_list('id', 'titre', 'magasin__nom')))
    print("  Tous les magasins:",
          list(Magasin.objects.order_by('id').values_list('id', 'nom')))
    print("  Articles:", list(Article.objects.values_list('id', 'designation', 'reference')))
    print("  Bons:", list(BonMouvement.objects.values_list('id', 'numero_bon', 'type_bon',
                                                          'magasin__nom', 'fournisseur__raison_sociale',
                                                          'service_demandeur__nom')[:15]))
    print("  Utilisateurs:", list(User.objects.values_list('id', 'username', 'is_superuser', 'is_active')))


main()
