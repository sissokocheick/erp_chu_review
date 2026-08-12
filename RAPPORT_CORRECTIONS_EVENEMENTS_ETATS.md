# RAPPORT D'AUDIT & CORRECTIONS — Gestion des événements et états

**Projet** : ERP CHU (`C:\Users\hp\Pictures\erp_chu_review\erp_chu_review`)
**Date** : 2026-08-08
**Méthode** : audit par 3 analyses parallèles (stock, patrimoine, comptes/core) + vérification manuelle de chaque constat critique avant correction.

---

## ✅ SYNTHÈSE DES CORRECTIONS APPLIQUÉES

### 🔴 Stock — 10 correctifs critiques

| # | Fichier | Problème corrigé |
|---|---------|------------------|
| 1 | `stock/views/*` (10 fichiers) | `get_magasins_autorises(request.user)` → `get_magasins_autorises(request)` : 17 appels passaient le mauvais argument → `AttributeError` → **toutes les listes/créations/annulations d'entrées, sorties, HS, livraisons, ajustements, inventaires, retours, lots, péremptions étaient cassées** (erreurs masquées par `catch_errors`). |
| 2 | `stock/views/utils.py` | `changer_magasin` : import de `get_magasins_autorises` manquant (`NameError`) + mauvais argument → **le sélecteur de magasin ne fonctionnait jamais**. |
| 3 | `stock/services/stock_transaction_service.py` | Annulation par contre-mouvement : `save(update_fields=['est_annule'])` sans `update_stock=False` → `ValidationError` → **toute annulation de bon échouait systématiquement**. |
| 4 | `stock/services/bon_service.py` | `annuler_bon_hors_stock` : idem → annulation HS impossible. |
| 5 | `stock/models.py` | `Mouvement.soft_delete()`/`restore()` sans `update_stock=False` → soft-delete impossible. |
| 6 | `stock/services/bon_service.py` | `bon.demande_origine = demande` + `save(update_fields=['demande_origine'])` : champ inexistant (relation inverse) → `ValueError` → **création d'un bon de sortie lié à une demande impossible** ; `bon.demande_origine_id` (`AttributeError`) → annulation de bon de sortie toujours en échec. Corrigé via `demande.bon_sortie_lie = bon`. |
| 7 | `stock/services/bon_service.py` | `annuler_bon_entree`/`annuler_bon_sortie` : filtre `reference_document=bon.numero_bon` (égalité stricte) → mouvements de réception (`"{num} (Réf Cmd: ...)"`) jamais retrouvés → **bon annulé sans restitution du stock**. Corrigé en `startswith`. |
| 8 | `stock/services/parametre_service.py` | `update_circuit` : `circuit.valideurs.set()/.clear()` sur M2M avec through explicite `CircuitValidateur` → `ValueError` → **la page circuits de validation plantait en 500**. Corrigé : gestion directe des `CircuitValidateur` avec ordre incrémental. |
| 9 | `stock/services/inventaire_service.py` | `annuler_campagne` : écriture de champs inexistants (`annule_par`, `date_annulation`) sur `CampagneInventaire` → `ValueError`. Corrigé : sauvegarde du statut seul + log. |
| 10 | `stock/services/inventaire_service.py` | `valider_campagne` : une campagne `ANNULEE` pouvait être re-validée → **double application des écarts au stock**. Corrigé : blocage de `VALIDE`/`ANNULE`. |

### 🔴 Stock — cause racine : double source de vérité sur `statut_validation`

| # | Fichier | Problème corrigé |
|---|---------|------------------|
| 11 | `stock/models.py` | `BonMouvement.save()` **écrasait** le `statut_validation` passé explicitement par les services (recalcul selon le circuit en base) → les services exécutaient déjà les mouvements de stock, puis `valider_bon` les ré-exécutait (**stock doublé**), ou le bon restait `BROUILLON` incohérent. Corrigé : suppression du bloc de recalcul — **les services sont désormais l'unique source de vérité** du statut. |
| 12 | `stock/views/commandes.py` | `receptionner_commande` : statut calculé explicitement avant création (ATTENTE si circuit ENTREE actif, sinon VALIDE) — comportement identique à l'ancien calcul `save()` mais sans le conflit. |
| 13 | `stock/services/livraison_service.py` | `destruction_lot_perime` : `statut_validation='VALIDE'` explicite (le mouvement SORTIE est exécuté immédiatement → pas de double sortie à la validation). |

### 🟠 Stock — transitions d'état et gardes

| # | Fichier | Problème corrigé |
|---|---------|------------------|
| 14 | `stock/views/validation_bons.py` | **Garde `est_annule` et `REJETE`** : un bon annulé ou rejeté pouvait être validé → mouvements exécutés. |
| 15 | `stock/views/validation_bons.py` | **`SORTIE_HORS_STOCK` ne crée plus de mouvement `SORTIE`** à la validation (le bon HS n'a pas d'impact stock — la validation décrémentait le stock réel). |
| 16 | `stock/models.py` | `LivraisonPartielle.annuler()` : restituait la quantité du **bon entier** au lieu de celle de **cette livraison** → sur-restitution si plusieurs livraisons. Corrigé : itération sur `lignes_livraison` avec `quantite_livree`. |
| 17 | `stock/models.py` | `DemandeMateriel.actualiser_statut()` : `livraisons.count()` incluait les livraisons annulées → mauvaise transition d'état. Corrigé : `filter(est_annule=False)`. |
| 18 | `stock/views/demandes.py` | Recherche `Q(nom__icontains=q)` : champ inexistant sur `DemandeMateriel` → `FieldError` → 500. Corrigé : `service_demandeur__nom`. |
| 19 | `stock/views/demandes.py` + `livraisons.py` | **Garde `ANNULEE` manquante** dans `valider_traitement_demande`, `cloturer_demande`, `peut_livrer` → une demande annulée restait livrable/traitable. |
| 20 | `stock/services/__init__.py` | `DemandeService.annuler` : les `LivraisonPartielle` liées aux bons annulés n'étaient pas marquées `est_annule` → `reste` faux. |

### 🔴 Patrimoine

| # | Fichier | Problème corrigé |
|---|---------|------------------|
| 21 | `patrimoine/signals.py` | **Le signal ne créait JAMAIS d'immobilisation** : branché sur `post_save` de `BonMouvement`, il se déclenchait AVANT la création des `LigneBon` → `lignes_bon.all()` vide. Corrigé : branché sur `post_save` de `LigneBon` (avec garde `created`, anti-doublon, `transaction.atomic`). **Le pipeline stock→Sas fonctionne désormais.** |
| 22 | `patrimoine/views.py` | `receptionner_demande` : statuts inexistants `REJETEE`/`RECEPTIONNEE` → les demandes réellement terminées (`RECEPTIONNE`, `CLOTUREE`) restaient « restantes » → **l'intervention restait bloquée en `EN_ATTENTE_PIECES`**. Corrigé : `REFUSEE`/`RECEPTIONNE`/`CLOTUREE`. |
| 23 | `patrimoine/views.py` | `resoudre` : idem → des demandes en état terminal (`RECEPTIONNE`/`CLOTUREE`/`REFUSEE`) étaient forcées à `ANNULEE` avec écrasement de `motif_refus` (**corruption de données métier du stock**). |
| 24 | `patrimoine/views.py` | `creer_mouvement` : **CESSION/PERTE/REMPLACEMENT/AFFECTATION ne mettaient pas à jour le statut** → `CEDE`/`DISPARU` inatteignables (un bien cédé/perdu restait `ACTIF`). Corrigé : CESSION→CEDE, PERTE→DISPARU, REMPLACEMENT→REFORME, AFFECTATION→ACTIF. |
| 25 | `patrimoine/views.py` | **Inventaire : les biens `EN_ATTENTE` (Sas, sans code patrimoine) étaient inclus dans les campagnes** → impossibles à scanner → déclarés `MANQUANT` → `DISPARU` + mouvement `PERTE` (**matériel neuf déclaré perdu**). Corrigé : sélection `ACTIF`/`EN_PANNE` uniquement. |
| 26 | `patrimoine/views.py` | `demander_pieces` : `service_demandeur` NULL → `IntegrityError` → **500**. Corrigé : message d'erreur propre + redirect. |

### 🟠 Comptes / Core

| # | Fichier | Problème corrigé |
|---|---------|------------------|
| 27 | `accounts/middleware.py` | URL `'logout'` au lieu de **`'custom_logout'`** → un utilisateur en état « doit changer MDP » **ne pouvait pas se déconnecter** (piégé, chaque requête redirigée). |
| 28 | `accounts/views.py` | **Trou d'audit** : `custom_login` retournait avant `log_audit`/`AuditConnexion` quand `doit_changer_mdp` → les connexions des comptes neufs n'apparaissaient jamais au journal de sécurité. Corrigé : audit juste après `login()` (avant le return anticipé), doublon supprimé. |
| 29 | `accounts/views.py` | **Désactivation d'un compte sans purge des sessions** → l'utilisateur désactivé restait connecté jusqu'à expiration. Corrigé : purge des sessions actives de l'utilisateur désactivé. |
| 30 | `accounts/views.py` | `user.groups.set([groupe_id])` : impossible de retirer le dernier rôle (groupe vide ignoré). Corrigé : `clear()` si `groupe_id` vide. |
| 31 | `accounts/views.py` | `page_roles` : renommage d'un rôle vers un nom existant → `IntegrityError` (**500**) ; `role_id` non numérique → `ValueError` (**500**). Corrigé : contrôle de doublon + conversion `int()` sécurisée. |
| 32 | `config/settings_test.py` | `MIGRATION_MODULES = {'stock': None}` cassait le graphe de migrations (`accounts.0001` dépend de `stock.0001`) → **tous les tests Django étaient impossibles à lancer**. Corrigé : migrations stock actives sur SQLite. |

### 🟠 Accounts — 2e passe (sécurité & audit)

| # | Fichier | Problème corrigé |
|---|---------|------------------|
| 33 | `accounts/views.py` | **Changements de MDP non tracés dans `AuditConnexion`** : seuls CONNEXION/ECHEC/DECONNEXION étaient écrits, jamais `PASSWORD_CHANGE` (pourtant défini dans TYPE_CHOICES) ni `ADMIN`. Corrigé : `changer_mdp_obligatoire` et `profil_utilisateur` écrivent `PASSWORD_CHANGE`, `reinitialiser_mdp` écrit `ADMIN` (avec IP + user-agent). |
| 34 | `accounts/views.py` | **`marquer_notification_lue` ne remplissait pas `date_lecture`** (écriture directe `est_lue=True; save()` au lieu de la méthode modèle). Corrigé : `notif.marquer_lue()` (set `date_lecture`). |
| 35 | `accounts/middleware.py` | **Déconnexion de sécurité AntiSpam non journalisée** : le `logout()` flushait la session sans trace → la dernière connexion restait « en cours » dans l'audit. Corrigé : `log_audit(LOGOUT)` + `AuditConnexion(DECONNEXION)` avant logout (import local pour éviter les cycles). |
| 36 | `accounts/models.py` | **Permission morte `menu_stats_satisfaction`** : utilisée dans les menus et l'API (`MENU_STRUCTURE`, `MENU_ITEMS_META`, `api_verifier_champ_utilisateur`) mais jamais déclarée dans `MENU_ACCESS_PERMISSIONS` → `has_perm` toujours False → **menu « Stats Satisfaction » invisible et non assignable dans les rôles**. Corrigé : déclaration + ajout au parent `menu_rapports` dans `SOUS_PERMISSIONS` (views.py). |
| 37 | `accounts/views.py` | **Menu complet affiché pour un rôle à 1 fonctionnalité** (bug signalé par l'utilisateur) : les permissions `menu_*` étaient stockées DIRECTEMENT sur l'utilisateur (`user_permissions`, reliquat de l'ancien système) en plus du groupe ; Django combine les deux → l'utilisateur gardait tous les menus. Corrigé : purge des permissions directes à chaque affectation de rôle dans `page_utilisateurs` (les droits viennent UNIQUEMENT des groupes) + nouvelle commande `purge_user_permissions` pour nettoyer les données existantes. **Vérifié en base réelle** : ahmed est passé de 79 permissions directes à 0 (seules les 2 de son groupe TEST restent). |
| 38 | `templates/base_ui.html` + 6 templates | **Icônes invisibles** (bug signalé par l'utilisateur) : la CSP `font-src 'self' https://fonts.gstatic.com` **bloquait les webfonts du CDN cdnjs.cloudflare.com** → le CSS FontAwesome se chargeait mais les polices d'icônes ne se téléchargeaient jamais → icônes invisibles. Corrigé : FontAwesome 6.4.0 hébergé en local (`static/vendor/fontawesome/`, CSS + 8 webfonts), tous les templates basculés du CDN vers `{% static %}`. **Vérifié via serveur de dev** : CSS et WOFF2 servis en HTTP 200. |
| 39 | `templates/base_ui.html` + `accounts/urls.py` + `accounts/config_documents_views.py` | **Module PARAMÈTRES : liens manquants** (bug signalé par l'utilisateur) : en donnant tout le module Paramètres à un rôle (12 permissions via `SOUS_PERMISSIONS`), seuls 3 liens apparaissaient dans le sidebar. Corrigé : ① `menu_parametres_doc` (Configuration Documents PDF) → la vue `config_documents_globaux` existait mais n'était **routée nulle part** (route morte) → route ajoutée dans accounts/urls.py + `menu_parametres_doc` ajouté à sa protection ; ② lien « Documents PDF » ajouté au sidebar ; ③ lien « Gestion des Lots » ajouté (`menu_lots`, route `liste_lots`) + `menu_lots` ajouté à la condition d'ouverture du module GESTION DES STOCKS ; ④ lien « Modèles PDF » ne dépend plus de `magasin_actif` (affiché dès que `menu_modeles_pdf` ; la condition magasin ne conditionne plus que l'URL). **Vérifié par tests fonctionnels** (client Django, 3 scénarios) : rôle param_patrimoine seul → seul le lien Paramètres Patrimoine apparaît ; module Paramètres complet → Administratifs + Logistique + Documents PDF ; `menu_modeles_pdf` + magasin → lien Modèles PDF. |
| 40 | `templates/base_ui.html` | **Module PARAMÈTRES : 14 cases cochées mais 2-4 liens affichés** (bug signalé par l'utilisateur) : la page Rôles propose 14 fonctionnalités (Services, Spécialités, Fonctions, Fournisseurs, Magasins, Motifs, Bénéficiaires, Lots, PDF…) mais le menu regroupait tout en 2-4 pages → l'utilisateur ne voyait pas ses choix. Corrigé : sous-menu PARAMÈTRES enrichi avec **un lien par fonctionnalité cochée** (Services, Spécialités, Fonctions → `page_fonctions`, Fournisseurs, Magasins, Motifs Annulation → `parametres_motifs`, Bénéficiaires, Lots, Documents PDF) en plus des pages groupées Administratifs/Logistique ; condition d'ouverture du module élargie aux 14 permissions (`menu_fonctions`, `menu_beneficiaires`, `menu_lots` inclus). **Vérifié par tests fonctionnels** : rôle tout-coché → 10 liens rendus ; `menu_services` seul → uniquement Administratifs + Services ; `menu_fonctions` seul → lien Fonctions seul ; `menu_motifs_annulation` seul → lien Motifs seul. |
| 41 | `accounts/views.py` | **Page Rôles : déploiement « Paramètre global » dupliquant toutes les cases** (bug signalé par l'utilisateur) : `SOUS_PERMISSIONS` contenait des parents (menu_parametres, menu_rapports, menu_utilisateurs, menu_pat_registre, menu_pat_contrats, menu_pat_tech, menu_pat_tickets, menu_pat_inventaire) dont les enfants étaient **déjà listés individuellement** dans `ROLE_ARCHITECTURE_MENU` → chaque module affichait un bloc pliable redondant avec les mêmes cases (ex. « Paramètres » dépliable listant Param. Admin, Logistique, Magasins, Services… en double). Corrigé : suppression de ces 8 entrées redondantes de `SOUS_PERMISSIONS` ; les enfants restent cochables individuellement (vérifié : tous présents dans la structure) et les déploiements CRUD légitimes (Créer/Modifier/Ajouter) sont conservés. **Vérifié par rendu réel** : 26 déploiements avant → 18 après (uniquement CRUD), toutes les cases individuelles présentes, `manage.py check` OK. |
| 42 | `accounts/views.py` + `accounts/menus.py` | **« Les paramètres déjà dans Logistique/Administratifs ne doivent pas être cochables dehors »** (bug signalé par l'utilisateur) : la page Rôles utilisait une **copie locale obsolète de `ROLE_ARCHITECTURE_MENU`** dans views.py (structure plate, PARAMÈTRES sans les 4 nouvelles permissions menu_fonctions/menu_beneficiaires/menu_lots/menu_parametres_doc, GESTION DES STOCKS contenant encore menu_lots) qui écrasait la structure complète de menus.py. Résultat : ① les nouvelles cases n'apparaissaient pas du tout dans la page Rôles (impossibles à cocher) ; ② menu_lots cochable 2× (GESTION DES STOCKS + PARAMÈTRES). Corrigé : suppression des blocs locaux obsolètes (`ROLE_ARCHITECTURE_MENU` + `MODULE_ICONS`) de views.py et **import depuis `accounts.menus`** (une seule source de vérité) ; `MENU_ITEMS_META` local (79 clés, le plus complet) conservé ; `_flatten_role_permissions` corrigé pour gérer les sous-groupes (dicts imbriqués, avant il ignorait tout sauf les listes plates). **Vérifié par rendu réel** : les 4 nouvelles cases visibles (perm 415/412/359/414), sous-groupe Stock rendu, icônes de modules correctes, menu_lots cochable 1 seule fois, création de rôle POST sauvegarde les 4 nouvelles permissions, `compileall` 0 erreur, `manage.py check` no issues. |
| 43 | `accounts/menus.py` + `accounts/views.py` + `templates/base_ui.html` | **Refonte complète de la page Rôles : miroir exact du menu** (demande utilisateur « on reprend la gestion des rôles depuis le début ») : ① `ROLE_ARCHITECTURE_MENU` réécrit = **même arborescence que le sidebar** (9 modules dans le même ordre : ACCUEIL & DASHBOARD, DEMANDES, MOUVEMENTS DE STOCK, GESTION DES STOCKS, ACHATS & CATALOGUE, PATRIMOINE & SAV, RAPPORTS & EXPORTS, PARAMÈTRES, SÉCURITÉ & ACCÈS) avec les mêmes pages dans le même ordre, **chaque page une seule fois** (suppression des sous-groupes artificiels SAV/Gestion du Parc et Administratifs/Logistique/Stock qui n'existaient pas dans le menu, suppression des pages fantômes menu_pat_fiche_detail/menu_pat_mouvements/… qui n'ont aucun lien dans le menu, menu_lots dédoublonné → GESTION DES STOCKS uniquement) ; ② `SOUS_PERMISSIONS` réécrit : **chaque page → ses actions en dessous** (Créer/Modifier/Supprimer : add_*/change_*/delete_* et can_* spécifiques — 40 pages avec actions, ex. menu_entrees → can_add/change/delete_bon_entree, menu_pat_registre → 5 actions, menu_utilisateurs → 5 actions) ; ③ `SOUS_PERM_LABELS` complété avec 72 labels français pour toutes les actions ; ④ lien « Gestion des Lots » retiré en double du menu PARAMÈTRES (base_ui.html) — il reste dans GESTION DES STOCKS (chaque page du menu aussi une seule fois). **Vérifié par rendu réel** : 9 modules dans l'ordre du menu, chaque page 1 seule occurrence (0 doublon), 40 dépliables d'actions, POST création rôle avec page+actions sauvegarde correctement, `compileall` 0 erreur, `manage.py check` no issues. |

---

## 🧪 Vérifications effectuées

- ✅ `compileall` sur toutes les apps : **0 erreur**
- ✅ `manage.py check` : **no issues**
- ✅ Import de tous les modules modifiés (stock + patrimoine + accounts) : OK
- ✅ **5 tests de non-régression fonctionnels passent** (statut explicite préservé, `Mouvement.save(update_stock=False)`, `soft_delete`, `update_circuit` with through model, `annuler_campagne`)

## ⚠️ Problèmes pré-existants NON corrigés (hors périmètre "événements/états" ou nécessitant décision métier)

1. **Tests obsolètes** (`test_services.py`, `test_isolation_magasin.py`, `test_configuration_pdf.py`) : utilisent d'anciens noms de champs (`Magasin(code, adresse)`, `FamilleArticle(nom, code)`...) supprimés des modèles → ils échouaient déjà AVANT mes correctifs. À réécrire sur le schéma actuel.
2. **Double source de vérité MDP** : `ConfigSecurite` (accounts) vs `ConfigurationHopital.type_mot_de_passe` (core) — deux réglages parallèles.
3. **`SECRET_KEY` en dur** + `DEBUG=True` par défaut + `ALLOWED_HOSTS='*'` dans `config/settings.py` — risque de sécurité production.
4. **`BROUILLON`/`ATTENTE` automatiques supprimés** : les bons créés SANS statut explicite passent maintenant à `VALIDE` (défaut du champ). Les 2 seuls créateurs concernés (`receptionner_commande`, `destruction_lot_perime`) ont reçu un statut explicite — mais si un futur code crée un bon sans statut en comptant sur le circuit, il devra le calculer lui-même (comme les services).
5. **Transitions d'interventions non validées côté serveur** (patrimoine `detail_intervention`) : aucune table de transitions — un POST forgé peut faire des transitions incohérentes. À ajouter (garde de sécurité).
6. **Templates patrimoine inexistants** (`mouvement.html`, `mouvements.html`, `import_log.html`, `portail_prestataire.html`...) → 500 sur ces routes. À créer ou retirer les routes.
7. **Amortissement** : défauts du type jamais appliqués dans le flux Sas ; troncature d'année en dégressif — correctifs de calcul à valider avec le métier.
8. **`bon_sortie_lie` sur `demande` non nettoyé à l'annulation** dans certains chemins (corrigé sur le chemin principal via `DemandeService.annuler`).
9. **Faux positifs de l'audit écartés après vérification** : `BDM` est bien dans `TYPE_DOC_CHOICES` (models.py:1377) ; aucun `except Exception: pass` silencieux dans views.py (36 `except` vérifiés, tous avec log/logger/messages).
10. **Pas de verrouillage de compte après échecs répétés** (feature de sécurité absente — ajout à prévoir) et **double source de vérité MDP** (`ConfigSecurite` vs `ConfigurationHopital.type_mot_de_passe`) — nécessitent une décision métier.

---

## 📌 Passe accounts (2e) — points vérifiés supplémentaires

- `api_verifier_champ_utilisateur` : l'API de vérification AJAX (username/email/contact) fonctionne ; les références `menu_stats_*` y sont bien utilisées pour la validation des permissions.
- `repair_roles.py` : commande générique (ne référence aucune permission en dur) — pas de modification nécessaire.
- `AntiSpamMiddleware` : le correctif importe `log_audit`/`AuditConnexion`/`get_client_ip` **en local** (dans le try) pour éviter tout cycle d'import middleware↔views ; vérifié au runtime Django.
- `get_client_ip` est défini dans `accounts/views.py` (pas dans `utils.py`) — l'import du middleware pointe vers la bonne source.

---

*Rapport généré après vérification manuelle de chaque constat critique (lecture du code réel, tests de non-régression).*

---

## Correctif #44 — Ordre des cases de la page Rôles = ordre exact du menu (toute l'application)

**Signalement utilisateur** : « c'est pas toujours bon, c'est pas respecté dans parametre » → « l'arborescence du menu doit être respectée dans les rôles, pour toute l'application ».

**Cause racine** : dans `accounts/templates/accounts/roles.html`, les cases de chaque module étaient itérées via `{% for perm in perms_disponibles %}` — une liste de permissions **triée par codename** (`order_by('codename', 'id')`). Résultat : les pages d'un module apparaissaient en **ordre alphabétique** (ex. PARAMÈTRES : Beneficiaires, Fonctions, Fournisseurs, Magasins…) au lieu de l'ordre du menu (Admin, Logistique, Services, Specialites, Fonctions…).

**Correction** (`fix_ordre_tpl.py`) : les 2 boucles (module avec sous-groupes + module plat) réécrites pour itérer **l'ordre de la structure** (`{% for codename in sous_codenames %}` / `{% for codename in codenames %}`), chaque case résolue via `perms_by_codename|get_item:codename`. L'ordre affiché suit désormais exactement `ROLE_ARCHITECTURE_MENU` (= miroir du menu).

**Vérifications (rendu réel, superuser temporaire)** :
- 9 modules, ordre = ordre du menu : ACCUEIL & DASHBOARD, DEMANDES, MOUVEMENTS DE STOCK, GESTION DES STOCKS, ACHATS & CATALOGUE, PATRIMOINE & SAV, RAPPORTS & EXPORTS, PARAMÈTRES, SÉCURITÉ & ACCÈS ✅
- Chaque module : pages dans l'ordre EXACT des liens du menu (comparaison base_ui.html vs rendu) ✅
  - DEMANDES : demandes, guichet, valider ✅
  - MOUVEMENTS : entrees, sorties, hors_stock, retours, livraisons, reception ✅
  - GESTION DES STOCKS : stock, ajustements, inventaires, lots, peremptions, historique ✅
  - ACHATS : commandes, articles, familles ✅
  - PATRIMOINE : 12 pages dans l'ordre du menu ✅
  - RAPPORTS : rapports, stats_demandes, stats_sondages, stats_satisfaction ✅
  - PARAMÈTRES : param_admin, param_logistique, services, specialites, fonctions, fournisseurs, magasins, motifs_annulation, beneficiaires, modeles_pdf, parametres_doc ✅
  - SÉCURITÉ : utilisateurs, roles, circuits_validation, journal_audit ✅
- 0 doublon de case maître (51 pages, 1 occurrence chacune) ✅
- 40 pages dépliables avec actions, actions exactes par page (menu_entrees → can_add/change/delete_bon_entree, menu_sorties → bon_sortie, menu_retours_services → bon_retour, menu_reception_commande → accusereception…) ✅
- POST création de rôle (page + actions) : sauvegarde correcte des 4 permissions ✅
- `compileall` : 0 erreur ; `manage.py check` : no issues ✅

**Fichiers modifiés** :
- `accounts/templates/accounts/roles.html` (2 boucles de rendu des modules)

---

---

## Correctif #45 — PARAMÈTRES : pages regroupées en sous-groupes (miroir du menu réel)

**Signalement utilisateur** : « PARAMÈTRES : Admin, Logistique, Services, Specialites… ne respecte pas — il y a seulement des pages, et ils sont regroupés dans Admin et Logistique, et les autres pages ».

**Cause** : au correctif #43, le module PARAMÈTRES avait été rendu **plat** (11 cases à la suite). Or le menu réel (`base_ui.html`) regroupe ces pages : **Services / Specialites / Fonctions sont des sections de la page "Administratifs"** (même URL `/parametres/administratifs/`), et **Fournisseurs / Magasins / Motifs / Beneficiaires sont des sections de la page "Logistique"** (`/parametres/logistique/`). Seuls Modeles PDF et Documents PDF sont des pages autonomes.

**Correction** (`fix_param_sousgroupes.py`) : dans `accounts/menus.py`, `ROLE_ARCHITECTURE_MENU['⚙️ PARAMÈTRES']` est passé de liste plate à **`OrderedDict` imbriqué** (le template gère déjà ce format) :
- **Administratifs** : menu_param_admin, menu_services, menu_specialites, menu_fonctions
- **Logistique** : menu_param_logistique, menu_fournisseurs, menu_magasins, menu_motifs_annulation, menu_beneficiaires
- **Documents** : menu_modeles_pdf, menu_parametres_doc

**Vérifications (rendu réel, superuser temporaire)** :
- 3 bandeaux de sous-groupes affichés (Administratifs / Logistique / Documents) ✅
- 11 pages dans l'ordre exact de chaque groupe ✅
- 0 doublon de case maître (51 pages au total) ✅
- 40 bodies d'actions intacts, actions correctes par page (menu_services → add/change/delete_service, menu_fournisseurs → add/change/delete_fournisseur, menu_modeles_pdf → can_configurer_modeles_pdf + CRUD modèle…) ✅
- POST création de rôle avec des pages des 3 sous-groupes : sauvegarde correcte ✅
- `compileall` : 0 erreur ; `manage.py check` : no issues ✅

**Fichier modifié** : `accounts/menus.py` (module PARAMÈTRES de ROLE_ARCHITECTURE_MENU)

---

---

## Correctif #46 — (ANNULE) Menu latéral PARAMÈTRES : liens regroupés en sous-groupes visuels

**Signalement utilisateur** : « ce que tu as mis ici est bon (ADMINISTRATIFS / LOGISTIQUE / DOCUMENTS) mais dans l'application ce n'est pas regroupé, ils ont toujours externe » → la page Rôles était corrigée (#45) mais **le menu latéral** (`base_ui.html`) affichait encore les 11 liens PARAMÈTRES à plat.

**Correction** (`fix_menu_param_groupes2.py`) : le bloc du sous-menu `menu-parametres` dans `templates/base_ui.html` est restructuré avec 3 **en-têtes de groupe** (`<div class="menu-group-label">`) :
- **Administratifs** : Admin, Services, Specialites, Fonctions
- **Logistique** : Logistique, Fournisseurs, Magasins, Motifs, Beneficiaires
- **Documents** : Modeles PDF, Documents PDF

Chaque en-tête n'apparaît que si au moins une permission de son groupe est accordée (conditions `{% if %}` conservées par groupe) ; les liens individuels gardent leurs conditions d'origine.

**Vérifications (rendu réel)** :
- Superuser : 3 bandeaux + liens dans l'ordre exact (Admin, Services, Specialites, Fonctions / Logistique, Fournisseurs, Magasins, Motifs, Beneficiaires / Docs PDF) ✅
- Cas partiels (bandeau jamais vide) :
  - user avec `menu_services` seul → bandeau **Administratifs** + liens Admin, Services ✅
  - user avec `menu_fournisseurs` seul → bandeau **Logistique** + liens Logistique, Fournisseurs ✅
  - user avec `menu_parametres_doc` seul → bandeau **Documents** + Docs PDF ✅
- Page Rôles toujours OK (bandeaux Administratifs/Logistique/Documents présents, status 200) ✅
- `manage.py check` : no issues ✅
- Note : le lien « Modeles PDF » reste conditionné à `magasin_actif` (comportement existant — il ne s'affiche que si un magasin est actif).

**Fichier modifié** : `templates/base_ui.html` (sous-menu PARAMÈTRES)

---

---

## Correctif #47 — Page Rôles : PARAMÈTRES = 3 pages cochables avec fonctionnalités en dessous

**Signalement utilisateur** : « tu ne devais pas modifier le menu mais les rôles, pour que seulement les trois pages de paramètres soient cochables avec leurs différentes fonctionnalités en dessous ».

**Actions** :
1. **Annulation du #46** : `templates/base_ui.html` restauré (le sous-menu PARAMÈTRES redevient la liste de liens d'origine, sans en-têtes de groupe). Le menu latéral n'est pas modifié.
2. **Page Rôles restructurée** (la demande réelle) :
   - `accounts/menus.py` : `ROLE_ARCHITECTURE_MENU['⚙️ PARAMÈTRES']` ne contient plus que **3 pages cochables** : `menu_param_admin` (Admin), `menu_param_logistique` (Logistique), `menu_modeles_pdf` (Modeles PDF).
   - `accounts/views.py` : `SOUS_PERMISSIONS` → chaque page cochable a **ses fonctionnalités en dessous** (dépliable) :
     - **Admin** → Services, Specialites, Fonctions + actions CRUD + Modifier configuration
     - **Logistique** → Fournisseurs, Magasins, Motifs, Beneficiaires + actions CRUD + Modifier configuration
     - **Modeles PDF** → Documents PDF + actions documents/config modèle PDF
   - `SOUS_PERM_LABELS` complété : 8 labels de pages enfants ajoutés (Services, Specialites, Fonctions & Titres, Fournisseurs, Magasins, Motifs Annulation, Beneficiaires, Documents PDF).

**Vérifications (rendu réel, superuser temporaire)** :
- 3 bandeaux (Administratifs / Logistique / Documents), **3 cases cochables** dans PARAMÈTRES (menu_param_admin, menu_param_logistique, menu_modeles_pdf) ✅
- 3 bodies dépliables avec les fonctionnalités exactes par page ✅
- Labels français corrects (Services, Specialites, Fonctions & Titres, Fournisseurs, Magasins, Beneficiaires, Documents PDF, Modifier configuration…) ✅
- 0 doublon de case cochable (43 cases au total) ✅
- POST création de rôle (pages + fonctionnalités) : sauvegarde correcte ✅
- Menu latéral restauré : 0 `menu-group-label` ✅
- `compileall` : 0 erreur ; `manage.py check` : no issues ✅

**Fichiers modifiés** : `accounts/menus.py`, `accounts/views.py`, `templates/base_ui.html` (restauration)

---

---

## Correctif #48 — Menu PARAMÈTRES : seules les 3 pages affichées (miroir des 3 cases cochables du rôle)

**Signalement utilisateur** : « dans le menu parametre il doit avoir que les trois pages dans le menu même si tout est coché dans le rôle — afficher les trois seulement à cocher ».

**Demande** : le menu latéral PARAMÈTRES ne doit afficher que les **3 pages** qui correspondent aux 3 cases cochables du rôle (Admin, Logistique, Modeles PDF), même si l'utilisateur possède toutes les permissions (`menu_services`, `menu_specialites`, `menu_fonctions`, `menu_fournisseurs`, `menu_magasins`, `menu_motifs_annulation`, `menu_beneficiaires`, `menu_parametres_doc`).

**Correction** (`fix_menu_3pages.py`) : dans `templates/base_ui.html`, le sous-menu PARAMÈTRES ne contient plus que 3 liens :
1. **Administratifs** → `/parametres/administratifs/` (si `menu_param_admin` ou une fonctionnalité Admin)
2. **Logistique** → `/parametres/logistique/` (si `menu_param_logistique` ou une fonctionnalité Logistique)
3. **Modeles PDF** → config modèle PDF si magasin actif, sinon `/auth/parametres/documents-pdf/` (si `menu_modeles_pdf` ou `menu_parametres_doc`)

Les liens individuels Services / Specialites / Fonctions / Fournisseurs / Magasins / Motifs / Beneficiaires / Documents PDF sont **retirés du menu** — ces fonctionnalités restent accessibles à l'intérieur des pages Administratifs/Logistique (sections) et restent cochables dans la page Rôles sous leur page principale.

**Vérifications (rendu réel)** :
- Superuser (toutes perms) : menu PARAMÈTRES = **3 liens** exactement (Administratifs, Logistique, Modeles PDF) ; aucun lien individuel ✅
- Cas partiels :
  - `menu_services` seul → lien **Administratifs** ✅
  - `menu_magasins` seul → lien **Logistique** ✅
  - `menu_parametres_doc` seul → lien **Modeles PDF** (fallback vers documents PDF) ✅
- 0 `menu-group-label` (aucun résidu du #46) ✅
- `compileall` : 0 erreur ; `manage.py check` : no issues ✅

**Fichier modifié** : `templates/base_ui.html` (sous-menu PARAMÈTRES)

---
