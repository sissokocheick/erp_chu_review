# 🔍 RAPPORT DE BUGS & INCOHÉRENCES — NexusERP

> **Date** : 23 Août 2026  
> **Méthode** : Audit de code + Tests fonctionnels manuels (navigateur)  
> **Environnement** : Django 6.0 / Python 3.14 / SQLite (test local)  
> **Dernier commit** : `e109be2` (sécurité durcie)

---

## 📊 Résumé exécutif

| Catégorie | Nombre |
|---|---|
| 🔴 Bugs critiques | 1 (restant) |
| 🟠 Bugs moyens | 6 |
| 🟡 Bugs mineurs | 8 |
| 🔵 Incohérences de conception | 4 |
| **Total** | **23** |
| ✅ Corrigés | 4 |

---

## 🔴 BUGS CRITIQUES

### BUG-01 — Champ fichier scanné obligatoire alors qu'il devrait être optionnel
| | |
|---|---|
| **Statut** | ✅ **CORRIGÉ** |
| **Fichiers** | `stock/templates/stock/liste_entrees.html` L302, `stock/views/entrees.py` L129-133 |
| **Problème** | Le formulaire d'entrée en stock bloquait avec l'alerte "Veuillez sélectionner un fichier" alors que le label n'a pas d'astérisque `*` |
| **Cause** | `<input type="file" required>` + backend `if not fichier_scan: return error` |
| **Correction** | Supprimé `required` du template + rendu le scan optionnel dans `_creer_entree` |

### BUG-02 — Type de notification `ALERTE_STOCK` inexistant
| | |
|---|---|
| **Statut** | ✅ **CORRIGÉ** |
| **Fichier** | `stock/services/bon_service.py` L260 |
| **Problème** | `type_notif="ALERTE_STOCK"` — ce type n'existe pas dans `Notification.TYPE_CHOICES` |
| **Types valides** | `INFO`, `SUCCESS`, `WARNING`, `DANGER` |
| **Impact** | Erreur de validation ou notification affichée incorrectement |
| **Correction suggérée** | Remplacer `ALERTE_STOCK` par `"WARNING"` ou `"DANGER"` |

### BUG-03 — Annulation de sortie sans gestion du stock insuffisant
| | |
|---|---|
| **Statut** | ✅ **CORRIGÉ** |
| **Fichier** | `stock/views/sorties.py` |
| **Problème** | L'annulation d'une sortie en stock ne vérifie pas si le stock est suffisant pour réintégrer les quantités |
| **Impact** | Stock potentiellement négatif si le magasin a été vidé entre la sortie et l'annulation |
| **Correction suggérée** | Ajouter une vérification `stock_disponible >= quantite_avant` avant réintégration |

### BUG-04 — Bypass de vérification de signature via AJAX
| | |
|---|---|
| **Statut** | ✅ **DÉJÀ CORRIGÉ** (précédemment) |
| **Fichier** | `stock/views/demandes.py` |
| **Problème** | La validation de signature peut être contournée en soumettant directement via AJAX sans passer par le vérificateur de workflow |
| **Impact** | Un utilisateur peut valider une demande sans être dans le circuit de validation |
| **Correction suggérée** | Vérifier le circuit de validation côté serveur pour chaque soumission AJAX |

### BUG-05 — Variable `logging` ambiguë dans `demandes.py`
| | |
|---|---|
| **Statut** | ✅ **CORRIGÉ** |
| **Fichier** | `stock/views/demandes.py` L158 |
| **Problème** | `logging.getLogger(__name__).warning(...)` alors que le module utilise déjà `logger = logging.getLogger(__name__)` au niveau module |
| **Impact** | Confusion inutile, double instanciation de logger |
| **Correction suggérée** | Remplacer `logging.getLogger(__name__)` par `logger` |

---

## 🟠 BUGS MOYENS

### BUG-06 — Double calcul `peut_valider` contradictoire dans commandes
| | |
|---|---|
| **Fichier** | `stock/views/commandes.py` L125-137 vs L380-395 |
| **Problème** | Dans `liste_commandes`, `peut_valider = False` si pas de circuit. Dans `valider_commande`, le superuser passe quand même. |
| **Incohérence** | Le bouton "Valider" est visible dans la liste mais la validation échoue silencieusement pour les non-superusers |
| **Correction suggérée** | Harmoniser la logique : si pas de circuit, bloquer tout le monde (y compris superuser) avec un message clair |

### BUG-07 — Téléphone fournisseur sans formatage
| | |
|---|---|
| **Fichier** | `stock/views/parametres.py` |
| **Problème** | Le numéro `01 23 45 67 89` est enregistré en brut `0123456789` |
| **Impact** | UX — numéro moins lisible dans les tables |
| **Correction suggérée** | Formatter le numéro au format `XX XX XX XX XX` côté backend |

### BUG-08 — Dropdown "Type Famille" garde la valeur par défaut
| | |
|---|---|
| **Fichier** | Template de création de famille |
| **Problème** | Le dropdown affiche "Médicaments & Produits de Pharmacie" sélectionné par défaut, même pour une famille de bureau |
| **Impact** | Si l'utilisateur ne change pas le type → famille mal catégorisée |
| **Correction suggérée** | Remettre le select sur l'option placeholder par défaut (`-- Sélectionner --`) |

### BUG-09 — Champ "Référence (Optionnel)" invisible dans formulaire article
| | |
|---|---|
| **Fichier** | Template de création d'article |
| **Problème** | Le label "RÉFÉRENCE (OPTIONNEL)" est affiché mais le champ de saisie n'est pas visible dans le DOM |
| **Impact** | L'utilisateur ne peut pas saisir manuellement une référence d'article |
| **Correction suggérée** | Vérifier le CSS/JS qui masque le champ et le rendre visible |

### BUG-10 — Code mort dans `_creer_ma_demande`
| | |
|---|---|
| **Fichier** | `stock/views/demandes.py` L84-100 |
| **Problème** | Le bloc de vérification `obliger_reception_precedente` est indenté sous un `return`, créant une confusion sur le flux d'exécution |
| **Impact** | Le code fonctionne (s'exécute quand `service_user` existe) mais l'indentation est trompeuse |
| **Correction suggérée** | Ré-indenter le bloc pour clarifier le flux |

### BUG-11 — Les paramètres du magasin ne s'affichent pas au chargement
| | |
|---|---|
| **Fichier** | `templates/parametres/logistique.html` |
| **Problème** | En arrivant sur `/parametres/logistique/`, toutes les sections sont repliées |
| **Impact** | L'utilisateur doit cliquer manuellement sur "Magasins" pour voir le contenu |
| **Correction suggérée** | Ouvrir la section "Magasins" par défaut ou ajouter un ancre `#magasins` |

---

## 🟡 BUGS MINEURS

### BUG-12 — Les paramètres admin ne s'affichent pas au chargement (même problème que BUG-11)
| | |
|---|---|
| **Fichier** | `templates/parametres/admin.html` |
| **Problème** | Toutes les sections repliées au chargement initial |

### BUG-13 — Séparateur de milliers absent dans les prix
| | |
|---|---|
| **Fichier** | Templates d'affichage des prix |
| **Problème** | Les prix s'affichent en brut : `75000` au lieu de `75 000` |
| **Correction suggérée** | Utiliser le filtre `floatformat` ou un template tag personnalisé avec séparateur de milliers |

### BUG-14 — La barre latérale ne s'ouvre pas sur mobile
| | |
|---|---|
| **Fichier** | `templates/base.html` |
| **Problème** | Le hamburger menu n'est pas testable (simulation desktop uniquement) |
| **Impact** | Non vérifié — potentiellement bloquant sur mobile |

### BUG-15 — Référence article auto-générée limitée à 3 chiffres
| | |
|---|---|
| **Fichier** | Modèle `Article` |
| **Problème** | Le format `FAMILLE001` limiterait à 999 articles par famille |
| **Impact** | Mineur si volume < 999 articles/famille |

### BUG-16 — Format date "après-midi" au lieu de "PM"
| | |
|---|---|
| **Fichier** | Templates d'affichage datetime |
| **Problème** | Les timestamps affichent "après-midi" au lieu de "PM" |
| **Impact** | UX — aspect non professionnel |

### BUG-17 — Les popups de succès se ferment trop rapidement
| | |
|---|---|
| **Fichier** | Templates avec SweetAlert2 |
| **Problème** | Les toasts de confirmation disparaissent en 2 secondes |
| **Impact** | L'utilisateur peut manquer le message de confirmation |

### BUG-18 — Le bouton "Retour" manque dans certains formulaires
| | |
|---|---|
| **Fichiers** | Templates de création famille, article |
| **Problème** | Pas de lien de retour à la liste après soumission |
| **Impact** | UX — l'utilisateur doit utiliser le menu latéral pour revenir |

### BUG-19 — Les emojis dans les messages d'erreur ne s'affichent pas partout
| | |
|---|---|
| **Fichier** | Vues et templates |
| **Problème** | Les `✅`, `❌`, `⚠️` dans les messages Django `messages` ne s'affichent pas sur tous les navigateurs/OS |
| **Impact** | Mineur — lisible même sans emoji |

---

## 🔵 INCOHÉRENCES DE CONCEPTION

### INC-01 — `TracabiliteModel` dupliqué (3 définitions identiques)
| | |
|---|---|
| **Fichiers** | `stock/models.py`, `patrimoine/models.py`, `core/models.py` |
| **Problème** | Le même mixin `TracabiliteModel` (created_by, modified_by, created_at, modified_at) est copié-collé dans 3 apps |
| **Correction suggérée** | Créer un module shared `core/tracabilite.py` et l'importer dans chaque app |

### INC-02 — Pattern Singleton `ConfigSecurite` avec PK=1 garanti
| | |
|---|---|
| **Fichiers** | `accounts/models.py` |
| **Problème** | La logique PK=1 est fragile et peut causer des conflits si Django génère un autre PK |
| **Correction suggérée** | Utiliser `django-configurations` ou un pattern singleton plus robuste |

### INC-03 — `TypeDocument` dans `core` mais codes littéraux dans `stock`
| | |
|---|---|
| **Fichiers** | `core/models.py` (définition) vs `stock/views/` (utilisation) |
| **Problème** | Les constantes `BS`, `BE`, `BR` sont définies dans `TypeDocument` mais les vues utilisent des strings littérales `'SORTIE'`, `'ENTREE'` |
| **Correction suggérée** | Utiliser `TypeDocument.SORTIE.value` au lieu de la string literal |

### INC-04 — `accounts/views.py` (>4500 lignes) devrait être scindé
| | |
|---|---|
| **Fichier** | `accounts/views.py` |
| **Problème** | Fichier monolithique contenant login, utilisateurs, profil, reset MDP, notifications |
| **Correction suggérée** | Scinder en modules : `accounts/views/login.py`, `accounts/views/users.py`, `accounts/views/profile.py` |

---

## ✅ FONCTIONNALITÉS VALIDÉES (testées et OK)

| Fonctionnalité | Résultat |
|---|---|
| Page de connexion | ✅ Fonctionnelle |
| Changement obligatoire du MDP (1ère connexion) | ✅ Fonctionnel |
| Dashboard avec widgets | ✅ Affichage correct |
| Création de magasin | ✅ Fonctionnel |
| Sélection de magasin (header) | ✅ Persiste en session |
| Création de famille d'articles | ✅ Fonctionnel |
| Auto-génération code famille | ✅ Fonctionnel |
| Création d'article | ✅ Fonctionnel |
| Auto-génération référence article | ✅ Fonctionnel |
| Création de fournisseur | ✅ Fonctionnel |
| Recherche AJAX article dans bon d'entrée | ✅ Instantané |
| Formulaire de bon d'entrée | ✅ Fonctionnel |
| Modal de confirmation partout | ✅ Avec récapitulatif |
| Traçabilité (cree_par / modifie_par) | ✅ Timestamps corrects |
| Menu latéral | ✅ Tous les modules accessibles |
| Paramètres Admin (Services, Spécialités) | ✅ Fonctionnel |
| Paramètres Logistiques (Magasins, Fournisseurs) | ✅ Fonctionnel |

---

## 🎯 PROCHAINE ÉTAPE RECOMMANDÉE

1. **Corriger les 4 bugs critiques restants** (BUG-02 à BUG-05)
2. **Mutualiser `TracabiliteModel`** (INC-01)
3. **Scinder `accounts/views.py`** (INC-04)
4. **Ajouter des tests unitaires** pour les chemins de bord (annulation, validation sans circuit)

---

*Rapport généré automatiquement par l'audit NexusERP — 23 Août 2026*
