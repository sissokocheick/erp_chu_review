# 📘 NexusERP — Documentation du fonctionnement de l'application

> Suite de gestion intégrée (ERP) **mono-tenant** pour le Centre Hospitalier et Universitaire (CHU).
> Cette documentation décrit, page par page, le fonctionnement de l'application : qui voit quoi,
> comment chaque fonctionnalité se déclenche, et quels sont les flux métier.

---

## Résumé des fonctionnalités

### Architecture
- **Stack** : Django 6 + Python 3.14, **PostgreSQL** (seule base supportée — production, staging, dev et tests), templates + JS (jQuery, Chart.js, SweetAlert2, Select2), **WeasyPrint** (PDF), Playwright (tests E2E).
- **4 modules** : `accounts` (utilisateurs & sécurité), `stock` (le cœur métier), `patrimoine` (immobilisations), `core` (configuration & supervision).
- **Qualité** : 2441 tests (unitaires + E2E sur PostgreSQL), CI GitHub Actions, filets anti-régression (dépendances, données codées en dur, comptages CSV d'import).

### 👤 Accounts — utilisateurs & sécurité
- **Authentification** : login sécurisé (anti brute-force), logout POST-only, « Mot de passe oublié » **par email OU SMS** (selon le canal configuré), reset par l'admin si les notifications sont désactivées.
- **Comptes** : création avec mot de passe généré (affiché + envoyé par email/SMS si le canal est actif), profils, **rôles & permissions** `menu_*`, circuits de validation.
- **Sécurité** : politique de mots de passe, journal d'audit (JournalAudit, AuditConnexion), purge des sessions à la désactivation, middleware « doit changer le MDP ».

### 📦 Stock — le cœur métier
- **Référentiels** : articles (référence, famille, unité, seuils), familles, magasins, fournisseurs, services/bénéficiaires ; import Sage 100 via **CSV** (15 familles, 25 fournisseurs, 18 services, 664 articles).
- **Mouvements** : bons d'entrée (lots + péremption), de sortie, de retour, **transferts inter-magasins**, sorties hors stock (traçage sans impact stock), ajustements, destructions/rebuts.
- **FEFO** : sortie par date de péremption la plus proche, **blocage des lots périmés**.
- **Commandes & réappro** : commandes fournisseurs, **boucle de réappro fermée** (suggestions depuis les seuils → conversion en commande en 1 clic), réceptions, livraisons, **demandes des services** (création → validation → livraison → accusé de réception).
- **Inventaires** : campagnes complètes (comptage, écarts, validation) + **inventaires tournants** (planification par famille/zone, échéances, génération automatique).
- **Péremptions & lots** : suivi des lots, alertes d'expiration, contrôle/destruction des lots périmés.
- **Pilotage** : dashboard (valeur du stock, alertes de seuil, top mouvements/services, **taux de rotation 30 j**, lots en alerte, graphiques), rapports (consommation par service mensuelle exportable, réappro), exports CSV/Excel.
- **Documents** : **PDF configurables** (logo + entête depuis les paramètres, modèles par type de bon, signatures sur 2 lignes, numérotation des pages, multi-pages, marges basses).

### 🏥 Patrimoine
- **Immobilisations** : catégories, types d'équipement, marques, localisation (bâtiment → étage → bureau).
- **Amortissements** : linéaire et dégressif, valeur nette comptable.
- **Contrats de maintenance** (échéanciers), **interventions** sur équipements, **SAS** (division des lots, modèles auto + manuel).

### 🔔 Notifications
- **Configuration globale par l'admin** : email (SMTP) et/ou **SMS (Twilio API)**.
- Canal actif → notifications, mot de passe de création et de reset envoyés automatiquement ; désactivé → tout en local (reset manuel par l'admin).
- Alertes de santé (uptime) + **alertes CI Slack/webhook**.

### 🚀 Exploitation
- **CI/CD** : GitHub Actions (tests sur PostgreSQL, pip-audit, check --deploy), déploiement staging Ansible.
- **Déploiement** : scripts bash/PowerShell, Gunicorn/waitress, systemd/NSSM, **sauvegardes PostgreSQL automatiques** (pg_dump + rétention), **restauration** (pg_restore, --dry-run), Let's Encrypt (TLS auto), collectstatic.
- **Supervision** : tableau de bord santé, taille de la base, requêtes lentes, usage disque, logs d'erreurs.

---

## Table des matières

1. [Vue d'ensemble](#1-vue-densemble)
2. [Connexion & sécurité](#2-connexion--sécurité)
3. [Navigation & menu](#3-navigation--menu)
4. [Accueil & Tableau de bord](#4-accueil--tableau-de-bord)
5. [Demandes](#5-demandes)
6. [Mouvements de stock](#6-mouvements-de-stock)
7. [Gestion des stocks](#7-gestion-des-stocks)
8. [Achats & catalogue](#8-achats--catalogue)
9. [Patrimoine & SAV](#9-patrimoine--sav)
10. [Rapports & exports](#10-rapports--exports)
11. [Paramètres](#11-paramètres)
12. [Sécurité & accès](#12-sécurité--accès)
13. [Circuits de validation (règle « A Valider »)](#13-circuits-de-validation--règle--a-valider-)
14. [Configuration des PDF](#14-configuration-des-pdf)
15. [Architecture technique & tests](#15-architecture-technique--tests)

---

## 1. Vue d'ensemble

L'application couvre **quatre grands domaines** :

| Domaine | Rôle |
|---|---|
| **Stock & Logistique** | Demandes de matériel, entrées, sorties, retours, hors stock, inventaires, ajustements, commandes fournisseurs |
| **Patrimoine & SAV** | Registre des immobilisations, contrats de maintenance, interventions techniques, tickets SAV, inventaire du parc |
| **Administration** | Utilisateurs, rôles & permissions, circuits de validation, journal d'audit, paramètres |
| **Documents PDF** | Modèles de bons (sortie, entrée, retour, commande, hors stock, demande) entièrement configurables |

**Monoposte d'établissement** : l'application est mono-tenant (un seul établissement : le CHU). Les
références à « magasin » désignent des **dépôts internes** (Pharmacie Centrale, etc.) et non des
établissements distincts. Un sélecteur de magasin actif est disponible en haut de l'écran ; la
plupart des écrans de stock sont filtrés sur ce magasin.

---

## 2. Connexion & sécurité

### Écran de connexion (`/auth/login/`)
- Identification par **nom d'utilisateur + mot de passe**.
- Affichage/masquage du mot de passe.
- **Session de 15 minutes** d'inactivité (session expirée → retour au login).
- Journalisation des tentatives de connexion (réussies et échouées) dans les **événements de connexion** (Journal & Audit).

### Changement de mot de passe obligatoire
- Si l'utilisateur a le drapeau « Doit changer le mot de passe » (première connexion ou après
  réinitialisation par un administrateur), il est **forcé** sur la page `/auth/forcer-mdp/`
  avant tout accès à l'application.

### Mot de passe oublié — self-service (`/auth/mot-de-passe-oublie/`)
L'utilisateur peut **réinitialiser lui-même** son mot de passe depuis la page de connexion
(lien « Mot de passe oublié »), **à condition qu'au moins un canal de notification
(email ou SMS) soit configuré et livrable** (voir §11 Notifications) :

1. **Choix du canal** : l'utilisateur choisit « Par email » (il saisit son email **ou** son
   identifiant) ou « Par SMS » (il saisit son numéro, formats `07XXXXXXXX` ou `+22507XXXXXXXX`
   acceptés).
2. **Canal indisponible** : un canal activé mais non livrable (ex. SMTP incomplet) est
   **grisé et non proposé** — l'autre canal est présélectionné automatiquement avec le champ
   correspondant. Le message reste **neutre** : il ne révèle jamais si un compte existe.
3. **Envoi** : un **jeton à usage unique** (expiration ~24 h) est envoyé sur le canal choisi ;
   si l'envoi échoue sur ce canal, **l'autre canal est tenté automatiquement** (repli).
4. **Réinitialisation** : lien `/auth/reinitialisation/<token>/` → nouveau mot de passe
   (validé par la politique §2).
5. **Filet de sécurité admin** : la réinitialisation manuelle depuis la page **Utilisateurs**
   est **toujours disponible** (bouton &#128273; devant chaque compte). Si un canal email/SMS
   est configuré et livrable, le **nouveau mot de passe est aussi envoyé par email/SMS** à
   l'utilisateur ; sinon tout se fait **en local** (l'administrateur communique le mot de
   passe lui-même).

### Politique de mots de passe (`/auth/securite/mots-de-passe/`)
- **Mode d'attribution** des mots de passe à la création d'un utilisateur :
  - **Aléatoire** (recommandé) : mot de passe généré, communiqué à l'administrateur.
  - **Fixe** : mot de passe par défaut défini dans la configuration.
- **À la création d'un compte** : le mot de passe initial est **toujours affiché** à
  l'administrateur dans la modale « Identifiants du compte » (affichage unique). Si un canal
  email/SMS est configuré et livrable, le mot de passe est **aussi envoyé** directement à
  l'utilisateur par email (et/ou SMS) — l'affichage reste conservé dans les deux cas.
- Réinitialisation de mot de passe d'un utilisateur possible depuis la page **Utilisateurs**.

### Profil utilisateur (`/auth/profil/`)
- Photo, fonction/titre, contact, bureau.
- **Signature électronique** : l'utilisateur peut enregistrer une image de signature, utilisée
  automatiquement sur les PDF (cases de signature pré-remplies).
- Thème préféré (clair/sombre) mémorisé par utilisateur.

---

## 3. Navigation & menu

Le menu latéral (sidebar) est **entièrement piloté par les permissions** : chaque entrée ne
s'affiche que si l'utilisateur (ou son rôle) possède la permission correspondante (`menu_*`).

### Structure du menu

| Section | Entrées |
|---|---|
| **Accueil & Tableau de bord** | Accueil, Tableau de bord |
| **Demandes** | Mes Demandes, Traiter (Guichet), **A Valider** ⚠️ (voir §13) |
| **Mouvements de stock** | Entrées en Stock, Bons de Sortie, Sorties Hors Stock, Retours Services, Livraisons, Réceptions Commandes |
| **Gestion des stocks** | État du Stock, Ajustements Manuels, Campagnes Inventaires, **Inventaire Tournant**, Gestion des Lots, Suivi Péremptions, Historique Mouvements |
| **Achats & catalogue** | Commandes Fourn., Catalogue Articles, Familles d'Articles |
| **Patrimoine & SAV** | Tickets SAV, Espace Tech, Dispatch Pannes, Historique Global, Registre Matériel, Sas Immatriculation, Contrats, Import Excel, Inventaire Parc, Registre Rebuts, Équipements Perdus, Paramètres |
| **Rapports & exports** | Exports CSV / PDF, Stats Demandes, Stats Sondages, Stats Satisfaction |
| **Paramètres** | Administratifs, Logistique, Notifications, Modèles PDF |
| **Sécurité & accès** | Utilisateurs, Rôles & Permissions, Circuits Validation, Journal & Audit |

### Comportement responsive & menu déroulant
- **Sous-menus** : cliquer sur un titre de section déplie/replie le sous-menu.
- Si le sous-menu déployé dépasse la hauteur de l'écran, il est limité à `100vh − 130px` et
  **défile en interne** (`overflow-y: auto`) ; le début du sous-menu reste visible
  (`scrollIntoView`). Plus aucun libellé ne passe hors écran.
- **Mobile (< ~768px)** : la sidebar devient un tiroir (off-canvas) ouvert par le bouton
  hamburger, avec un voile sombre (overlay) cliquable pour fermer.
- **Topbar compacte** : sur très petits écrans, le nom d'utilisateur et le libellé
  « Déconnexion » sont masqués (icônes conservées) et le sélecteur de magasin est compacté
  pour éviter tout débordement horizontal.

### UX grandes listes (beaucoup de données)
- **En-têtes de tableau collants** : sur les listes lourdes (articles, état du stock, entrées,
  sorties, commandes, demandes), le tableau défile dans un conteneur à hauteur bornée
  (`max-height`) avec l'en-tête **sticky** — les colonnes restent lisibles sur des centaines de lignes.
- **Pagination collante** : la barre de pagination reste visible en bas du conteneur de scroll.
- **État de chargement** : pendant une recherche AJAX, un **overlay spinner** (« Chargement… »)
  est affiché par `NxUX.setTableLoading()` (debounce 400 ms conservé) puis masqué à la réponse.
- **Responsive** : en mobile (< 768 px), le conteneur de scroll est désactivé et les tableaux
  basculent en cartes (comportement inchangé).

---

## 4. Accueil & Tableau de bord

### Accueil personnalisé (`/auth/accueil/`)
- Grille des **modules** accessibles selon les permissions de l'utilisateur.
- Chaque tuile ouvre la page correspondante.

### Tableau de bord (`/`)
- **Indicateurs (KPI)** : articles catalogués, entrées / sorties du jour,
  stocks critiques, **valeur totale du stock (CMUP)**, **taux de rotation du
  stock sur 30 jours** (Σ sorties 30 j ÷ Σ stock actuel).
- **Alertes de stock** : 3 onglets (Critique / Alerte / Surstock) avec niveaux visuels.
- **Graphiques** (Chart.js) :
  - Top 5 articles consommés (30 j) et Top 5 services demandeurs (30 j) ;
  - **Flux entrées / sorties sur 14 jours** (courbes) ;
  - **Valeur du stock par famille** (donut) ;
  - **Top 5 entrées** (30 j) ;
  - **Valeur du stock par magasin** (tableau).
- **Rotation du stock par famille (30 j)** : tableau « Taux de rotation »
  (sorties 30 j ÷ stock actuel, trié du plus rapide au plus lent) et tableau
  « Couverture de stock » (jours de stock restants = 30 ÷ taux, trié du plus
  urgent au plus long — rouge < 15 j, orange ≤ 30 j, vert au-delà).
- **Péremptions** : lots périmés (rouge) et lots expirant sous 90 jours (orange).
- **Journal des derniers mouvements** avec pastilles vertes (entrées) / rouges (sorties).
- **Isolation par magasin actif** : si un magasin est sélectionné dans l'en-tête,
  tous les indicateurs et graphiques sont filtrés sur ce magasin ; sinon, toutes
  les données de tous les magasins sont affichées.

---

## 5. Demandes

Le cycle de vie d'une demande de matériel :

```
BROUILLON → EN_ATTENTE_VALIDATION → VALIDÉE → (livraison) → CLÔTURÉE
                │
                └── REFUSÉE / ANNULÉE
```

### Mes Demandes (`/mes-demandes/`)
- Créer une demande (articles + quantités depuis le catalogue).
- Onglets : **Actives** / **Historique** (avec filtres par statut).
- Modifier, annuler une demande en brouillon.
- **Signature de l'accusé de réception** quand la demande a été livrée (avec signature
  électronique si le profil en possède une).

### Traiter (Guichet) (`/gestion-demandes/`)
- Vue du **guichet** : toutes les demandes des services, avec onglets
  (à traiter, attente signature, historique).
- Recherche par numéro, service, statut ; pagination (10/15/50/100 lignes).
- Actions : valider, refuser (avec motif), lancer une **livraison partielle**.
- Badge du nombre de demandes en attente sur la cloche de notifications.

### A Valider (`/valider-demandes/`) — ⚠️ voir §13
- Liste des demandes `EN_ATTENTE_VALIDATION` **du service du validateur**.
- Validation ou refus **en lot** (cases à cocher) ou unitaire, avec commentaire.
- **Ce menu n'apparaît que si le circuit DEMANDE est actif et que l'utilisateur y est
  désigné validateur** (voir §13 pour la règle exacte).

---

## 6. Mouvements de stock

### Entrées en Stock (`/entrees/`)
- Création d'un **bon d'entrée (réception)** : fournisseur, articles, quantités, n° de lot,
  date de péremption, prix unitaire.
- **Scan PDF** : joindre la facture/bon de livraison scanné (remplaçable).
- Aperçu PDF + impression (modale).
- Annulation d'un bon (avec motif, si configuré) → **stock annulé** automatiquement.

### Bons de Sortie (`/sorties/`)
- Création d'un **bon de sortie (distribution)** lié à une demande validée (ou en direct).
- **Traçabilité livraison unifiée** : toute sortie liée à une demande crée automatiquement une
  `LivraisonPartielle` + accusé de réception (même parcours que le guichet « Traiter ») — le
  module **Livraisons** (§6) est donc toujours alimenté, quel que soit le chemin utilisé.
- **Politique FEFO (First-Expired-First-Out)** : pour les articles « gérés en lot », la sortie
  consomme automatiquement les lots **par date de péremption croissante** (le lot qui expire le
  plus tôt est servi en premier), découpée en une ligne/mouvement par lot. Appliqué sur les
  trois chemins de sortie : création directe, validation du circuit SORTIE, et guichet « Traiter ».
- **Blocage des lots périmés** : un lot dont la date de péremption est dépassée ne peut **plus
  être servi** — la sortie est refusée avec un message indiquant les quantités périmées bloquées
  (destruction requise via Suivi Péremptions §7). Les lots sans date de péremption sont
  consommés en dernier.
- Colonnes demandée / servie ; gestion des **livraisons partielles** (reste à livrer).
- **Validation** : selon le circuit SORTIE (§13), le bon passe en attente puis est validé
  par les valideurs désignés ; sans circuit actif, la validation est directe.
- **Sondage de satisfaction** (optionnel, configurable dans le modèle PDF) renseigné à la
  réception par le service demandeur.
- Scan joint, impression PDF, annulation (remise en stock sur le bon lot d'origine).

### Sorties Hors Stock (`/bons/hors-stock/`)
- Sorties **hors catalogue** (fournitures non répertoriées) : désignation libre, service
  bénéficiaire.
- Les signatures suivent la configuration du document (BSHS).

### Retours Services (`/stock/retours-services/`)
- Bon de retour **depuis un service** (matériel non utilisé / excédentaire) : le stock est
  recrédité au magasin.
- Aperçu et impression PDF.

### Livraisons (`/livraisons/`)
- Suivi des **livraisons partielles** issues des demandes validées.
- Accusé de réception signé par le service.

### Réceptions Commandes (`/receptions/`)
- Réceptionner une **commande fournisseur** : saisie des quantités reçues, affectation
  automatique au stock du magasin (mouvement d'entrée).
- Écart entre commandé et reçu géré par le reliquat (voir « Solder » en §8).

---

## 7. Gestion des stocks

### État du Stock (`/etat-stock/`)
- Tableau des **stocks physiques** par magasin actif : quantité, statut d'alerte
  (RUPTURE / CRITIQUE / ALERTE / OK) selon les seuils de l'article.
- Recherche (désignation, référence, famille) et filtre par magasin.
- Export PDF « État du stock » (généré depuis les stocks physiques `StockItem`).

### Ajustements Manuels (`/ajustements/`)
- Ajustement positif ou négatif du stock (avec justification).
- Validation/rejet **selon le circuit AJUSTEMENT** : sans circuit actif, validation directe ;
  sinon réservé aux valideurs désignés.
- Impact immédiat sur le stock et le journal des mouvements.

### Campagnes Inventaires (`/inventaires/`)
- Créer une **campagne d'inventaire** (magasin, articles concernés).
- **Fiche de comptage** (PDF) : saisie du stock réel par article.
- Saisie ligne par ligne (sauvegarde AJAX), clôture de campagne.
- **Résultat d'inventaire** (PDF) : écarts constatés (positifs/négatifs) appliqués au stock.
- Validation selon le circuit INVENTAIRE.

### Inventaire Tournant (`/inventaires/tournants/`)
Rotation du comptage **par famille / par zone** au lieu d'une campagne complète, avec planification :

- **Plan de rotation** : titre, magasin, type de rotation (par famille ou par zone =
  toutes les familles du magasin), fréquence en jours (ex. 90 j), familles cibles.
- **Échéance automatique** : à la création, la prochaine échéance est fixée à aujourd'hui ;
  après chaque génération, elle est repoussée de `fréquence` jours. Un badge rouge
  « Échue » signale les plans dont l'échéance est atteinte.
- **Génération automatique à l'échéance** : les campagnes échues sont générées
  automatiquement à la connexion d'un utilisateur (`_generer_tournants_a_echeance`,
  silencieux et non bloquant) et par la commande
  `python manage.py generer_inventaires_tournants` (avec `--dry-run` pour prévisualiser) —
  à brancher en tâche planifiée (cron / Planificateur Windows) pour une rotation sans
  intervention.
- **Génération d'une campagne ciblée** (`InventaireService.generer_campagne_tournante`) :
  - *Par famille* → seuls les articles des familles cibles sont comptés.
  - *Par zone* → tous les articles du magasin.
  - Les quantités théoriques sont prises du **stock actuel du magasin du plan** (isolation
    magasin : le stock des autres magasins ne compte pas).
  - La campagne créée est de type `PAR_FAMILLE`, liée au magasin du plan, et ouvre
    directement la page de **saisie** (`/inventaires/<id>/saisir/`).
- **Activation / pause** : un plan en pause ne peut pas générer de campagne (refus avec
  message clair) ; un plan sans familles cibles est également refusé.
- Accès : menu **Gestion des stocks → Inventaire Tournant** (permission `menu_inventaires`).
- La page liste est **filtrée par le magasin actif** sélectionné dans l'en-tête.

### Transferts inter-Magasins (`/transferts/`)
- **Déplacement de stock entre deux magasins** (ex. pharmacie centrale → unité de soins)
  sans passer par un fournisseur ni un service.
- Création via modale : magasin **source** (autorisé) → magasin **destination**, lignes
  d'articles + quantités, commentaire.
- **Tracé par deux mouvements liés** (TRANSFERT_SORTIE côté source, TRANSFERT_ENTREE
  côté destination) partageant le même numéro de bon — chaque magasin voit le flux
  dans son historique.
- **FEFO côté source** : les articles gérés en lot partent par péremption la plus
  proche ; les lots **périmés sont bloqués** (destruction requise). Le lot et la date
  de péremption sont **conservés à l'arrivée**, ainsi que la valeur CMUP.
- Impression du bon de transfert (PDF) et **annulation** : le stock revient au magasin
  source (contre-mouvements automatiques).
- Entrée au menu **Mouvements de Stock** (permission `accounts.menu_transferts`).

### Gestion des Lots (`/lots/`) & Suivi Péremptions (`/stock/peremptions/`)
- Lots (n° de lot, dates de péremption) des articles « gérés en lot ».
- Liste des **péremptions proches ou dépassées** (alerte visuelle).
- Onglet **« À expirer »** : liste les lots dont la péremption tombe dans les
  prochains jours, avec **seuil paramétrable (30 / 60 / 90 / 180 j)** — idéal pour
  planifier les destructions préventives ou prioriser une consommation.
  Quantité restante calculée après sorties, jours restants affichés
  (rouge ≤ 15 j, orange ≤ 30 j, jaune sinon).

### Historique Mouvements (`/administration/historique/`)
- Journal complet des mouvements de stock (entrées, sorties, retours, ajustements,
  inventaires) avec recherche, filtres par type et pagination.

---

## 8. Achats & catalogue

### Catalogue Articles (`/articles/`)
- CRUD des articles : référence, désignation, famille, unité de distribution, seuils
  (critique/minimum/maximum), prix de référence, gestion lot/péremption, immobilisable.
- **Recherche live** (fetch AJAX) + filtre par famille + pagination.
- Historique d'un article (mouvements).

### Familles d'Articles (`/familles/`)
- Regroupement des articles (intitulé, code).

### Commandes Fournisseurs (`/commandes/`)
- Créer une **bon de commande** : fournisseur, objet, délai de livraison, lignes
  (réf., description, unité, quantité).
- **Validation** : selon le circuit COMMANDE (§13) — sans circuit actif, la commande est
  directement validée ; sinon réservée aux valideurs désignés.
- **Réceptionner** : saisie des quantités reçues → entrée en stock (voir §6).
- **Solder** : clôturer une commande en reliquat (statut `SOLDE`).
- Impression PDF (modale), suppression.

### Suggestions de Réapprovisionnement (`/commandes/suggestions/`)
- Boucle de réappro **fermée** : la page liste automatiquement les **articles sous seuil
  minimum** dans le magasin actif, avec : stock actuel, seuils (min/critique/max), statut
  d'alerte (CRITIQUE d'abord, puis ratio stock/seuil) et **quantité recommandée**
  (= seuil maximum − stock, sinon double du seuil minimum − stock, minimum 1).
- Valeur estimée par ligne et au total (prix de référence × quantité recommandée).
- Filtres par famille et recherche (désignation, référence).
- **Conversion en un clic** : sélection des suggestions (case tout-cocher, quantités
  modifiables), choix du fournisseur et objet optionnel → **une commande fournisseur par
  famille** est créée avec les lignes (prix unitaire = prix de référence) puis redirection
  vers la liste des commandes pour validation/réception.
- Accès : menu **Achats & Catalogue → Suggestions Réappro** (permission `menu_commandes`).

---

## 9. Patrimoine & SAV

### Registre Matériel (`/patrimoine/`)
- Registre des **immobilisations** : désignation, référence, type d'équipement, localisation,
  valeur, amortissement, statut.
- **Amortissement** : calcul linéaire et dégressif (VNC affichée, réparti sur la durée de vie).
- Fiche détaillée par bien, **modification rapide** (quick-edit AJAX), étiquette **QR code**.
- Recherche, filtres, pagination.

### Sas Immatriculation (`/patrimoine/sas/`)
- Zone d'attente des **biens à immatriculer** (nouveaux achats en attente).
- Validation d'entrée, **éclatement d'un bien composite** en plusieurs sous-biens.
- **Immatriculation directe** (`/patrimoine/sas/direct/`).

### Contrats (`/patrimoine/contrats/`)
- Contrats de maintenance : fournisseur, équipements couverts, dates, montant.
- Détail d'un contrat ; **assigner des équipements** à un contrat.

### Échéancier Maintenance Préventive (`/patrimoine/echeancier-maintenance/`)
- Planifie les **maintenances préventives** par contrat actif : chaque contrat a une
  **fréquence** (en mois, ex. 12 = annuelle, 6 = semestrielle, 3 = trimestrielle).
- La **prochaine échéance** est calculée depuis la dernière intervention préventive
  réalisée (date de fin + fréquence) ; à défaut, depuis la date de début du contrat.
- **KPIs** : contrats actifs, maintenances **en retard**, à prévoir sous 30 jours.
- Les contrats en retard (échéance dépassée sans préventive) sont remontés en tête
  avec le nombre de jours de retard ; chaque ligne indique le prestataire, la dernière
  préventive, les équipements couverts et le coût annuel.

### Interventions / SAV
- **Signaler une panne** sur un bien (`/patrimoine/signaler/<id>/`) → crée un **ticket SAV**.
- **Espace Technicien** (`/patrimoine/mes-interventions/`) : tâches du technicien
  (à faire, en cours, à valider).
- **Dispatch** (`/patrimoine/interventions/dispatch/`) : affecter les pannes aux techniciens.
- **Suivi de ticket** ; validation d'intervention (avec bon de sortie réparation PDF).
- **Portail prestataire** (`/patrimoine/portail/`) : interface dédiée aux prestataires externes.

### Inventaire du parc (`/patrimoine/inventaires/`)
- Campagnes d'inventaire du parc, détail par campagne, fiche de comptage,
  réconciliation et audit scan.

### Import / Export Excel
- **Import** (`/patrimoine/import/`) : import massif d'immobilisations depuis Excel avec
  template par type d'équipement et journal des imports.
- **Export** (`/patrimoine/export/`) : export du registre au format Excel.

### Registre Rebuts & Équipements Perdus
- Biens **mis au rebut** (avec motif) et **perdus** : registres dédiés, sortis du parc actif.

### Paramètres Patrimoine (`/patrimoine/parametres/`)
- Types d'équipements et **schémas de spécifications** (champs propres à chaque type),
  localisations, modèles.

---

## 10. Rapports & exports

- **Exports CSV / PDF** (`/rapports/`) : export des listes (articles, stocks, demandes…).
- **Stats Demandes** (`/stats/demandes/`) : volumes, statuts, délais.
- **Stats Sondages** (`/stats/sondages/`) : taux de satisfaction des bons de sortie.
- **Stats Satisfaction** (`/stats/satisfaction-services/`) : par service demandeur.

---

## 11. Paramètres

### Administratifs (`/parametres/administratifs/`)
- **Identité de l'établissement** : nom, adresse, téléphone, CC N°, email, directions,
  numérotation des bons — alimente le **pied de page officiel** des PDF (ex : « CHU Angré,
  28 BP 1350 ABIDJAN, Tél : …, CC N° : … »).
- La **configuration détaillée des documents PDF** (métadonnées ISO, signatures, colonnes du
  tableau, sondage, pied de page) est regroupée dans la page **Modèles PDF**
  (`/magasin/<id>/modele-pdf/<TYPE>/`) — un lien y est affiché depuis cet accordéon.
- Services, spécialités, fonctions & titres, motifs d'annulation.

### Logistique (`/parametres/logistique/`)
- Paramètres magasins (nom, code), familles, motifs, circuits.

### Notifications (`/parametres/notifications/`)
Configuration **globale** (faite par l'administrateur, mono-tenant) des canaux d'envoi —
**chaque utilisateur reçoit sur les canaux activés**, sans réglage individuel :

| Canal | Réglages | Envoi réel |
|---|---|---|
| **Email** | `activer_email`, hôte SMTP, port, TLS, utilisateur/mot de passe SMTP, email expéditeur | Django `send_mail` (Gmail, Outlook, etc.) |
| **SMS** | `activer_sms`, expéditeur (sender ID), URL d'API + clé (API générique) **ou** Twilio (SID, token, numéro, template) | HTTP POST sur l'API (ex. Twilio) ; **mode test** qui journalise au lieu d'envoyer |

- **Diagnostic de livrabilité** : la page affiche des avertissements si un canal est activé
  mais non livrable (SMTP incomplet, clé API manquante, compte Twilio en mode **trial**).
- **Notifications importantes uniquement par SMS** : les SMS ne partent que pour les
  notifications marquées importantes (`est_importante`) — pas pour chaque événement mineur.
- **Cloche de notifications** (topbar) : dropdown « Aucune nouvelle notification » ou liste
  des dernières, marquage lu, suppression, « Tout marquer lu ».
- **Page Notifications** (`/notifications/`) : liste complète + actions (lues / effacées).

### Modèles PDF (`/magasin/<id>/modele-pdf/<TYPE>/`)
Voir §14 — configuration complète des documents par type.

---

## 12. Sécurité & accès

### Utilisateurs (`/auth/utilisateurs/`)
- Créer/modifier des utilisateurs : identifiant, nom, email, **profil** (fonction, service,
  téléphone), rôle.
- **Vérification en temps réel** de l'unicité de l'identifiant (AJAX).
- **Réinitialiser le mot de passe** (selon la politique §2).
- Chaque utilisateur a un `Profil` créé automatiquement.

### Rôles & Permissions (`/auth/roles/`)
- Les rôles regroupent des **permissions de menu** (`menu_*`).
- La modale de rôle reflète l'architecture du menu sidebar : cocher une entrée donne l'accès
  à la page correspondante.
- Attribution du rôle aux utilisateurs.

### Circuits Validation (`/auth/circuits-validation/`)
- Un circuit par **type de document** : COMMANDE, DEMANDE, ENTREE, SORTIE, AJUSTEMENT, INVENTAIRE.
- Chaque circuit a un **interrupteur Actif/Inactif** et une liste de **valideurs ordonnés**
  (ordre de signature 1, 2, 3…, rôle du signataire).
- Création, modification, suppression d'un circuit.

### Journal & Audit (`/auth/journal-audit/`)
- **Journal d'audit** : actions sensibles tracées (création, modification, suppression,
  validation) avec utilisateur, date et détails.
- **Événements de connexion** : connexions réussies/échouées.

---

## 13. Circuits de validation — règle « A Valider »

### Le principe
Les **validations métier** (demandes, sorties, commandes, ajustements, inventaires) sont
pilotées par les circuits de validation :

- **Circuit inactif** (défaut) → la validation est **directe** (aucune étape d'attente).
- **Circuit actif** → le document passe en statut `EN_ATTENTE_VALIDATION` (ou `ATTENTE`) et
  seuls les **valideurs désignés** du circuit peuvent le valider ou le refuser.

### Règle de visibilité du menu « A Valider »
Le menu **« A Valider »** (section Demandes) n'apparaît **que si toutes les conditions
suivantes sont réunies** :

1. l'utilisateur possède la permission `menu_valider_demandes` **ET**
2. le **circuit DEMANDE existe et est actif** (`est_actif=True`) **ET**
3. l'utilisateur est **désigné validateur** dans ce circuit.

En conséquence :

| Situation | Menu « A Valider » |
|---|---|
| Circuit DEMANDE inactif | ❌ masqué (même pour l'admin) |
| Circuit actif, mais utilisateur non valideur | ❌ masqué |
| Circuit actif + utilisateur valideur du circuit | ✅ visible (avec badge du nombre de demandes en attente) |

La page `/valider-demandes/` applique la **même règle** côté serveur : sans circuit actif ou
sans désignation comme validateur, l'utilisateur est redirigé avec un message d'erreur.
Ce comportement est appliqué par le contexte de menu (`menu_validation_context`) et cohérent
avec la vue `demandes_a_valider`.

> ⚠️ Ce n'est pas parce qu'un utilisateur a la permission `menu_valider_demandes` (ou est
> gestionnaire/superuser) qu'il voit « A Valider » : **seule la désignation dans le circuit
> DEMANDE actif** donne accès.

---

## 14. Configuration des PDF

### Où configurer
- **Modèles PDF** (menu Paramètres) → URL `/magasin/<id>/modele-pdf/<TYPE>/` avec un
  **sélecteur d'onglets** par type : **BS** (Sortie), **BE** (Entrée), **BR** (Retour),
  **BSHS** (Hors stock), **BC** (Commande), **BDM** (Demande).
- **Administratifs → Identité de l'établissement** : identité globale (footer CHU) et
  numérotation. La configuration détaillée des documents (métadonnées, signatures, colonnes,
  sondage) se fait uniquement ici, dans **Modèles PDF** — les anciens onglets « Documents » et
  « Signatures » des administratifs ont été supprimés (regroupement).

### Paramètres par type de document
| Bloc | Éléments configurables |
|---|---|
| **Logo** | Téléversement / suppression (logo du CHU ou du magasin) |
| **Cartouche / en-tête** | République, devise, direction, service, téléphone, CC, IFU, RCCM |
| **Tableau** | Colonnes affichées (N°, Code, Désignation, Unité, Qté, Qté servie, Lot, Péremption, PU, Montant), largeurs |
| **Signatures** | Cases (libellé, rôle, ordre, visibilité) — nombre max selon le type (ex. BC : 2, BS : 6) |
| **Service demandeur** | Encadré, position |
| **Sondage** | Affichage du sondage de satisfaction (BS), trait de séparation |
| **Pied de page** | Texte institutionnel, numéro de page, date de génération, trait de couleur |
| **Métadonnées** | Code document (ex. `ENR-BSM/DAF-001`), dates de création/révision, version, PS2 |
| **Labels & couleur** | Couleur principale, libellés personnalisés |

### Rendu des PDF
- Tous les documents s'ouvrent dans une **modale PDF globale** (iframe) avec boutons
  **Imprimer / Fermer** — une seule implémentation, partagée par toutes les pages
  (`imprimerModal` → `nxOpenPdfModal`).
- **Signatures unifiées** : un partial commun (`_signatures.html`) rend les cases de
  signature de tous les bons (sortie, entrée, retour, commande, hors stock, demande,
  ajustement) à partir de la configuration — avec nom, fonction, date et signature
  électronique si disponible.
- **Pied de page** : composé depuis l'identité CHU (adresse, tél, CC, email, directions,
  postes) avec sauts de ligne corrects et apostrophes non échappées.
- Les PDF générés sont **mis en cache** (fichier attaché au bon) ; le cache est régénéré si
  la configuration change (purge manuelle possible).

### Correspondance avec les exemples officiels (`pdf/`)
| Document | Code ISO attendu |
|---|---|
| Bon de Sortie | `ENR-BSM/DAF-001` |
| Bon de Commande | `ENR-BCM/DAF-002` |
| Bon de Retour | `ENR-BRM/DAF-003` |

---

## 15. Architecture technique & tests

### Stack
- **Backend** : Django (Python) — apps `accounts`, `stock`, `patrimoine`, `core`.
- **Frontend** : templates Django + JS (jQuery, Chart.js, SweetAlert2, Select2,
  daterangepicker), CSS responsive maison.
- **PDF** : WeasyPrint (HTML → PDF).
- **Base de données** : PostgreSQL (seule base supportée — production, staging, dev et tests).

### Modèles clés
- `accounts` : `User` (Django), `Profil`, `MenuAccess` (permissions `menu_*`),
  `ConfigSecurite`, `ConfigDocument`, `Notification`, `JournalAudit`, `AuditConnexion`.
- `stock` : `Magasin`, `Article`, `Famille`, `StockItem` (stock physique), `Mouvement`,
  `BonMouvement`/`LigneBon`, `DemandeMateriel`, `Commande`/`LigneCommande`,
  `CircuitValidation`/`CircuitValidateur`, `Ajustement`, `CampagneInventaire`,
  `PlanInventaireTournant`, `ModeleDocumentMagasin`, `ConfigurationHopital` (core).
- `patrimoine` : `Immobilisation`, `TypeEquipement`, `ContratMaintenance`,
  `TicketSAV`, `Intervention`, `CampagneInventairePatrimoine`.

### Tests
- **Plus de 2100 tests** répartis : `stock` (modèles, services, isolation magasin, sécurité,
  PDF, configuration, recherche sans accents, responsive 375px), `accounts` + `core`
  (politique de mot de passe, login, reset mot de passe email/SMS, notifications, permissions),
  `patrimoine` (amortissement linéaire/dégressif généré en masse, contrats, permissions),
  et l'inventaire tournant (planification, génération par famille/zone, échéances).
- Commandes utiles :
  ```bash
  source venv/Scripts/activate
  DJANGO_SETTINGS_MODULE=config.settings_test python manage.py test          # tout
  DJANGO_SETTINGS_MODULE=config.settings_test python manage.py test stock    # stock
  ```
- **Tests E2E navigateur réel** (`stock/tests/test_e2e_playwright.py`) : 11 parcours
  Playwright + Chromium sur `LiveServerTestCase` (connexion, erreur de login, sélection
  magasin persistante, recherche sans accents, création d'article avec validation,
  pagination, pages stock, cohérence hors-stock/magasin, profil). Prérequis :
  `pip install playwright && playwright install chromium` ; lancement avec
  `DJANGO_ALLOW_ASYNC_UNSAFE=1`. La suite est ignorée proprement si Playwright
  n'est pas installé.
- Scripts d'audit : `scripts/crawl_all_pages.py` (toutes les pages GET, détection 500),
  `scripts/crawl_search_pagination.py` (recherches + paginations).

### Serveur de dev
```bash
source venv/Scripts/activate
python manage.py runserver 127.0.0.1:8765
```
L'application est accessible sur **http://127.0.0.1:8765**.
