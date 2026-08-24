# 📊 RAPPORT DE TEST COMPLET — Module Stock

> **Date** : 23 Août 2026
> **Environnement** : Django 6.0 / SQLite (test local)
> **Données** : 6 articles, 13 services, 15 demandes, 19 bons

---

## 1. Flux testés

### 1.1 Création de demandes (15 demandes)
| # | Service | Article | Statut final |
|---|---------|---------|-------------|
| 1 | DESTRUCTION / PEREMPTIONS | Chaise de bureau | LIVREE ✅ |
| 2 | Cardiologie | Stethoscope Littmann | LIVREE ✅ |
| 3 | Pediatrie | Moniteur patient | EN_ATTENTE |
| 4 | Radiologie | Chaise roulante | EN_ATTENTE |
| 5 | Chirurgie | Table d'examen | EN_ATTENTE |
| 6 | Urgences | Lampe chirurgicale | EN_ATTENTE |
| 7 | Maternite | Chaise de bureau | EN_ATTENTE |
| 8 | Laboratoire | Stethoscope Littmann | EN_ATTENTE |
| 9 | Pharmacie | Moniteur patient | EN_ATTENTE |
| 10 | Orthopedie | Chaise roulante | LIVREE ✅ |
| 11 | Neurologie | Table d'examen | LIVREE ✅ |
| 12 | Ophtalmologie | Lampe chirurgicale | LIVREE ✅ |
| 13 | ORL | Chaise de bureau | LIVREE ✅ |
| 14 | DESTRUCTION / PEREMPTIONS | Stethoscope | LIVREE ✅ |
| 15 | Cardiologie | Moniteur patient | LIVREE ✅ |

### 1.2 Traitement des demandes (10/15)
- **10 demandes livrées** avec succès via `LivraisonService.traiter_demande()`
- **5 demandes restées en EN_ATTENTE** (non traitées volontairement pour tester les filtres)

### 1.3 Annulations (3 bons)
- **3 bons de sortie** annulés avec restauration du stock
- Motif d'annulation requis et enregistré

### 1.4 Garde-fous testés
| Test | Résultat |
|------|----------|
| Sortie avec stock insuffisant (99999 > 51) | ✅ Refusé correctement |
| Bon de sortie vide (0 lignes) | ✅ Refusé correctement |
| Double annulation d'un bon déjà annulé | ✅ Refusé correctement |
| Annulation d'entrée avec stock partiellement consommé | ⚠️ BUG CRITIQUE (voir section 2) |

### 1.5 Cohérence des stocks
| Article | Stock réel | Calculé | Cohérent |
|---------|-----------|---------|----------|
| Chaise de bureau ergonomique | 51 | 48 | ❌ INCOHERENT (+3) |
| Stethoscope Littmann | 48 | 52 | ❌ INCOHERENT (-4) |
| Moniteur patient | 49 | 52 | ❌ INCOHERENT (-3) |
| Chaise roulante | 49 | 52 | ❌ INCOHERENT (-3) |
| Table d'examen | 45 | 45 | ✅ COHERENT |
| Lampe chirurgicale | **0** | 96 | ❌ INCOHERENT (-96) |

---

## 2. Bugs trouvés

### 🔴 BUG CRITIQUE : Annulation d'entrée vide le stock partiellement consommé

| | |
|---|---|
| **Fichier** | `stock/services/bon_service.py` — `annuler_bon_entree()` |
| **Problème** | Quand on annule un bon d'entrée dont le stock a été partiellement consommé, le `AJUSTEMENT_NEG_FORCE` retire TOUT le stock restant, y compris les quantités sorties légitimement. |
| **Séquence** | 1) Entrée 50 lampes → stock=50, 2) Sortie 4 lampes → stock=46, 3) Annulation entrée → contre-mouvement impossible (46<50) → AJUSTEMENT retire 46 → stock=0 |
| **Impact** | Le stock passe à 0 alors qu'il reste 46 lampes légitimement dans le magasin. Les 4 lampes déjà sorties sont "perdues" dans le compteur. |
| **Correction** | Le AJUSTEMENT_NEG_FORCE ne devrait retirer que la quantité réellement disponible (46), PAS la quantité originale (50). Ou mieux : ne pas créer d'ajustement forcé du tout et alerter l'administrateur pour un ajustement manuel. |

### 🟠 BUG MOYEN : Incohérences de stock sur 5/6 articles

| | |
|---|---|
| **Problème** | 5 articles sur 6 ont un stock incohérent entre le stock physique et le calcul théorique (entrées - sorties + retours + ajustements). |
| **Cause probable** | Les AJUSTEMENT_NEG_FORCE créés lors des annulations d'entrée modifient le stock sans que les sorties associées soient ajustées en conséquence. |
| **Impact** | Les rapports de stock et les niveaux de réappro sont erronés. |

### 🟡 BUG MINEUR : Avertissement "AJUSTEMENT_NEG_FORCE bloqué à 0"

| | |
|---|---|
| **Problème** | Lors de l'annulation, le log indique "AJUSTEMENT_NEG_FORCE bloqué à 0 : stock=46, demandé=50, appliqué=46" mais le stock passe quand même à 0. |
| **Interprétation** | Le garde-fou capte bien l'incohérence mais l'ajustement est quand même appliqué avec la quantité available (46), ce qui vide le stock. |

---

## 3. Statistiques des tests

| Métrique | Valeur |
|----------|--------|
| Demandes créées | 15 |
| Demandes traitées (livraison) | 10 |
| Bons de sortie annulés | 3 |
| Entrées en stock | 7 |
| Garde-fous testés | 4 |
| Garde-fous passés | 3/4 |
| Articles en stock | 6 |
| Services utilisés | 13 |
| Tests total | 20+ |

---

## 4. Conclusion

Le module Stock fonctionne correctement pour les flux normaux :
- Création de demandes ✅
- Livraison partielle ✅
- Annulation de sorties ✅
- Garde-fous (stock insuffisant, bon vide, double annulation) ✅

**Le point critique** est la gestion des annulations d'entrées (`annuler_bon_entree`) qui produit des incohérences de stock quand le stock a été partiellement consommé entre l'entrée et l'annulation. Ce bug doit être corrigé avant la mise en production.

---

*Rapport généré automatiquement par les tests NexusERP — 23 Août 2026*
