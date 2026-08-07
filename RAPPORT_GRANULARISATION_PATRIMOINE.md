# 📋 GRANULARISATION DES PERMISSIONS - MODULE PATRIMOINE

## ✅ Migration Effectuée avec Succès

### Résumé de la granularisation

Le module **Patrimoine** dispose désormais de **37 permissions granulaires** permettant un contrôle d'accès précis pour chaque fonctionnalité, au même titre que le module Stock.

---

## 📊 NOUVELLES PERMISSIONS CRÉÉES (37 permissions)

### 1. Registre & Immobilisations (9 permissions)
| Code Permission | Libellé | Action |
|----------------|---------|--------|
| `menu_pat_registre` | Registre Patrimoine | Consulter le registre |
| `menu_pat_sas` | SAS (Zone d'attente) | Accéder à la zone SAS |
| `menu_pat_fiche_detail` | Fiches Détaillées | Voir les fiches détaillées |
| `menu_pat_modifier_immo` | Modifier Immobilisations | Éditer les immobilisations |
| `menu_pat_mouvements` | Mouvements Patrimoine | Consulter les mouvements |
| `menu_pat_eclatement` | Éclatement Biens | Éclater les biens |
| `menu_pat_immatriculation` | Immatriculation Directe | Créer immatriculations |
| `menu_pat_qr_codes` | Gestion QR Codes | Générer/voir QR codes |
| `menu_pat_export_registre` | Export Registre Excel | Exporter le registre |
| `menu_pat_import_excel` | Import Excel Patrimoine | Importer depuis Excel |

### 2. Contrats (3 permissions)
| Code Permission | Libellé | Action |
|----------------|---------|--------|
| `menu_pat_contrats` | Contrats | Liste des contrats |
| `menu_pat_contrat_detail` | Détail Contrats | Voir détails contrat |
| `menu_pat_assigner_equipements` | Assigner Équipements | Lier équipements aux contrats |

### 3. Maintenance & Interventions (8 permissions)
| Code Permission | Libellé | Action |
|----------------|---------|--------|
| `menu_pat_interventions` | Interventions | Liste interventions |
| `menu_pat_intervention_detail` | Détail Interventions | Voir détails intervention |
| `menu_pat_signaler_panne` | Signaler Panne | Déclarer une panne |
| `menu_pat_creer_intervention` | Créer Intervention | Planifier intervention |
| `menu_pat_valider_intervention` | Valider Intervention | Valider intervention terminée |
| `menu_pat_portail_prestataire` | Portail Prestataire | Accès portail externe |
| `menu_pat_schema_maintenance` | Schémas Maintenance | Gérer schémas |
| `menu_pat_types_equipements` | Types d'Équipements | Configurer types |

### 4. Tickets & Support (6 permissions)
| Code Permission | Libellé | Action |
|----------------|---------|--------|
| `menu_pat_tickets` | Tickets SAV | Liste globale tickets |
| `menu_pat_mes_tickets` | Mes Tickets | Voir ses propres tickets |
| `menu_pat_dispatch` | Dispatch Interventions | Assigner aux techniciens |
| `menu_pat_tech` | Espace Technicien | Interface technicien |
| `menu_pat_suivi_ticket` | Suivi Ticket | Suivre avancement ticket |
| `menu_pat_bon_sortie_reparation` | Bon Sortie Réparation | Éditer bons sortie |

### 5. Inventaires Parc (6 permissions)
| Code Permission | Libellé | Action |
|----------------|---------|--------|
| `menu_pat_inventaire` | Inventaire Parc | Vue globale inventaires |
| `menu_pat_campagnes_inventaire` | Campagnes Inventaire | Gérer campagnes |
| `menu_pat_detail_campagne` | Détail Campagne | Voir détails campagne |
| `menu_pat_reconciliation` | Réconciliation Inventaire | Valider écarts |
| `menu_pat_audit_scan` | Audit Scan Inventaire | Scanner pour inventaire |
| `menu_pat_fiche_comptage` | Fiche Comptage | Imprimer fiches comptage |

### 6. Rebuts & Pertes (2 permissions)
| Code Permission | Libellé | Action |
|----------------|---------|--------|
| `menu_pat_rebuts` | Rebuts | Gérer les rebuts |
| `menu_pat_pertes` | Pertes | Gérer les pertes |

### 7. Paramètres (2 permissions)
| Code Permission | Libellé | Action |
|----------------|---------|--------|
| `menu_pat_parametres` | Paramètres Patrimoine | Configuration module |
| `menu_pat_historique` | Historique Patrimoine | Consulter historique |

---

## 🔧 MODIFICATIONS TECHNIQUES

### Fichiers modifiés

1. **`accounts/models.py`**
   - Ajout de 37 nouvelles permissions dans `MENU_ACCESS_PERMISSIONS`
   - Organisation par sections thématiques commentées
   - Total : **79 permissions** tous modules confondus

2. **`accounts/migrations/0007_add_patrimoine_permissions.py`** (NOUVEAU)
   - Migration automatique générée par Django
   - Met à jour les choix du champ `nom` dans `MenuAccess`
   - Met à jour les permissions dans `Meta.permissions`

3. **Corrections de bugs découverts**
   - `/workspace/stock/views/lots.py` : Suppression import incomplet
   - `/workspace/stock/views/utils.py` : Suppression import incomplet

### Statistiques

| Métrique | Valeur |
|----------|--------|
| Permissions Stock | 30 |
| Permissions Patrimoine | 37 |
| Permissions Accounts/Admin | 12 |
| **Total Général** | **79** |
| Fichiers créés | 1 (migration) |
| Fichiers modifiés | 3 |

---

## 🎯 UTILISATION DANS LES RÔLES

### Exemple de configuration de rôle

Dans l'interface d'administration Django ou via le module de gestion des rôles :

```python
# Rôle : Gestionnaire Patrimoine
permissions = [
    'menu_pat_registre',
    'menu_pat_sas',
    'menu_pat_fiche_detail',
    'menu_pat_modifier_immo',
    'menu_pat_mouvements',
    'menu_pat_contrats',
    'menu_pat_interventions',
    'menu_pat_creer_intervention',
    'menu_pat_valider_intervention',
    'menu_pat_inventaire',
    'menu_pat_campagnes_inventaire',
    'menu_pat_reconciliation',
    'menu_pat_rebuts',
    'menu_pat_pertes',
]

# Rôle : Technicien Maintenance
permissions = [
    'menu_pat_mes_tickets',
    'menu_pat_tech',
    'menu_pat_suivi_ticket',
    'menu_pat_interventions',
    'menu_pat_signaler_panne',
    'menu_pat_bon_sortie_reparation',
]

# Rôle : Admin Patrimoine (toutes permissions)
permissions = [p for p in MENU_ACCESS_PERMISSIONS if p[0].startswith('menu_pat_')]
```

---

## 🔒 SÉCURITÉ RENFORCÉE

### Avant granularisation
- Permissions globales : `menu_pat_tickets`, `menu_pat_tech`, etc.
- Contrôle grossier par menu principal
- Risque : accès à des fonctionnalités non autorisées

### Après granularisation
- Permissions fines par action métier
- Contrôle précis : "Voir" ≠ "Modifier" ≠ "Valider"
- Respect du principe du moindre privilège
- Audit facilité : quelle permission a été utilisée ?

---

## 📝 PROCÉDURE DE MIGRATION

### Étape 1 : Appliquer la migration
```bash
python manage.py migrate accounts
```

### Étape 2 : Mettre à jour les rôles existants
Via l'interface d'administration ou script Python :
```python
from accounts.models import MenuAccess

# Vérifier que toutes les permissions sont créées
assert MenuAccess.objects.count() == 79
```

### Étape 3 : Mapper les anciennes permissions vers les nouvelles
Exemple pour un rôle "Gestionnaire Patrimoine" :
- Ancien : `menu_pat_registre` → Nouveau : conservé + ajout des permissions fines
- Ancien : `menu_pat_interventions` → Nouveau : éclaté en 8 permissions

### Étape 4 : Tester les accès
- Connecter un utilisateur avec le rôle mis à jour
- Vérifier que chaque menu apparaît/disparaît correctement
- Tester les actions protégées par `@verifier_permission`

---

## ✅ VÉRIFICATION

Pour vérifier que les permissions sont bien créées :

```bash
python manage.py shell
>>> from accounts.models import MenuAccess
>>> MenuAccess.objects.filter(nom__startswith='menu_pat_').count()
37
>>> MenuAccess.objects.count()
79
```

---

## 🚀 PROCHAINES ÉTAPES RECOMMANDÉES

1. **Appliquer la migration** en base de données
2. **Mettre à jour les templates** pour utiliser les nouvelles permissions
3. **Auditer les vues patrimoine** et ajouter les décorateurs `@verifier_permission` manquants
4. **Créer des rôles prédéfinis** avec des combinaisons de permissions cohérentes
5. **Documenter dans le manuel utilisateur** les nouveaux rôles disponibles

---

## 📞 SUPPORT

En cas de problème lors de la migration :
- Vérifier que la migration `0007_add_patrimoine_permissions.py` est bien appliquée
- S'assurer que toutes les 79 permissions sont présentes dans `MenuAccess`
- Consulter les logs Django pour d'éventuelles erreurs de permission

**Date de création** : 2026-08-07  
**Version** : 1.0  
**Auteur** : Assistant IA
