# -*- coding: utf-8 -*-
"""Audit d'intégrité des données — à lancer via `manage.py shell < scripts/audit_integrity.py`."""


def main():
    from django.db.models import Sum

    from stock.models import (
        Article, BonMouvement, LigneBon, Mouvement,
        CampagneInventaire, LigneInventaire, StockItem,
    )
    from patrimoine.models import Immobilisation

    checks = [
        ("Articles sans famille", Article.objects.filter(famille__isnull=True).count()),
        ("Bons sans magasin", BonMouvement.objects.filter(magasin__isnull=True).count()),
        ("Lignes bon sans article", LigneBon.objects.filter(article__isnull=True).count()),
        ("Mouvements sans article", Mouvement.objects.filter(article__isnull=True).count()),
        ("Campagnes sans magasin", CampagneInventaire.objects.filter(magasin__isnull=True).count()),
        ("Lignes inventaire sans article", LigneInventaire.objects.filter(article__isnull=True).count()),
        ("Immos sans type equipement", Immobilisation.objects.filter(type_equipement__isnull=True).count()),
    ]
    for label, n in checks:
        print(f"{label} : {n}")

    print("--- Stocks négatifs (StockItem) ---")
    neg = [s for s in StockItem.objects.all() if (s.quantite_physique or 0) < 0]
    print("StockItem négatifs :", len(neg))

    print("--- StockItem > 0 sans aucun mouvement ---")
    incoherents = 0
    for s in StockItem.objects.select_related("article", "magasin")[:500]:
        somme = Mouvement.objects.filter(
            article=s.article, magasin=s.magasin, est_annule=False,
        ).aggregate(total=Sum("quantite"))["total"] or 0
        if (s.quantite_physique or 0) > 0 and somme == 0:
            incoherents += 1
    print("StockItem > 0 sans aucun mouvement :", incoherents)

    print("--- Données de référence ---")
    print("Articles:", Article.objects.count())
    print("Bons:", BonMouvement.objects.count())
    print("Mouvements:", Mouvement.objects.count())
    print("Immos:", Immobilisation.objects.count())
    print("Campagnes inventaire:", CampagneInventaire.objects.count())


main()
