# -*- coding: utf-8 -*-
"""Nettoyage des données de test de la base dev.

Supprime UNIQUEMENT les enregistrements vérifiés sans référence métier :
  - Immobilisation 'Nouveau Matériel (Saisie Directe)' sans type/code/service
  - 12 magasins nommés TEST / PDF / MESURE / SIG (0 référence partout)
  - Fournisseur 'Fournisseur PDF Test' (0 bon)
  - Service 'Service PDF Test' (0 bon)
  - Campagnes 'ROTATION TEST TRIMESTRE' EN_COURS + leurs lignes
  - Plan d'inventaire tournant 'Rotation Test Trimestre'
  - Utilisateurs de test (tmp_user, pdftest, smsdest, dbg_ur) — 0 référence

Gardé : Pharmacie Centrale, DBG, MAG REALCFG, fournisseur LIMA ENTREPRISE,
les services réels (Cardiologie…), la campagne validée '01', admin + ahmed.
"""


def main():
    from django.contrib.auth.models import User
    from stock.models import (
        Magasin, Fournisseur, Service, CampagneInventaire,
        PlanInventaireTournant, LigneInventaire,
    )
    from patrimoine.models import Immobilisation

    supprimes = []

    # 1. Campagnes ROTATION TEST + lignes
    for c in CampagneInventaire.objects.filter(titre__icontains='ROTATION TEST'):
        LigneInventaire.objects.filter(campagne=c).delete()
        c.delete()
        supprimes.append(f"campagne #{c.id} {c.titre}")

    # 2. Plan tournant test
    for p in PlanInventaireTournant.objects.filter(titre__icontains='Rotation Test'):
        p.delete()
        supprimes.append(f"plan #{p.id} {p.titre}")

    # 3. Immobilisation sans type (artefact de saisie directe)
    for im in Immobilisation.objects.filter(
            type_equipement__isnull=True,
            code_patrimoine__isnull=True):
        im.delete()
        supprimes.append(f"immo #{im.id} {im.nom_affichage}")

    # 4. Commande du fournisseur PDF Test (BC-2026-002, EN_ATTENTE, 0 bon reçu)
    from stock.models import Commande, LigneCommande
    for cmd in Commande.objects.filter(fournisseur__raison_sociale__icontains='PDF TEST'):
        LigneCommande.objects.filter(commande=cmd).delete()
        cmd.delete()
        supprimes.append(f"commande #{cmd.id} {cmd.numero_commande}")

    # 5. Fournisseur / Service PDF Test
    for f in Fournisseur.objects.filter(raison_sociale__icontains='PDF TEST'):
        f.delete()
        supprimes.append(f"fournisseur #{f.id} {f.raison_sociale}")
    for s in Service.objects.filter(nom__icontains='PDF TEST'):
        s.delete()
        supprimes.append(f"service #{s.id} {s.nom}")

    # 6. Magasins de test (vérifiés sans référence)
    ids_magasins = [5, 6, 7, 8, 9, 10, 11, 12, 14, 21, 22, 23]
    for m in Magasin.objects.filter(id__in=ids_magasins):
        m.delete()
        supprimes.append(f"magasin #{m.id} {m.nom}")

    # 7. Utilisateurs de test (vérifiés sans bons/mouvements/campagnes/ajustements)
    for u in User.objects.filter(username__in=['tmp_user', 'pdftest', 'smsdest', 'dbg_ur']):
        try:
            u.delete()
            supprimes.append(f"utilisateur #{u.id} {u.username}")
        except Exception as e:
            # Si des historiques PROTECT bloquent, on désactive plutôt que de perdre la traçabilité
            u.is_active = False
            u.save(update_fields=['is_active'])
            supprimes.append(f"utilisateur #{u.id} {u.username} (désactivé : {type(e).__name__})")

    print("═══ SUPPRIMÉS ═══")
    for s in supprimes:
        print("  -", s)
    print(f"Total : {len(supprimes)}")


main()
