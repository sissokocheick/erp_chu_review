# Données d'import Sage 100 (data_sage/)

Ce dossier contient les **données de référence** chargées par la commande
`import_sage_data` (extrait des PDFs Sage 100 Gestion Commerciale du CHU
d'Angré, effectué lors de la migration initiale).

**Principe** : les données vivent dans ces fichiers — le code Python ne fait
que les lire et les importer. Pour ajouter, modifier ou retirer une donnée
(famille, fournisseur, service, article), on modifie le CSV correspondant,
**jamais le code**.

## Les 4 fichiers

| Fichier | Contenu | Nombre de lignes de données |
|---|---|---|
| `familles.csv` | 15 familles d'articles | 15 |
| `fournisseurs.csv` | 25 fournisseurs | 25 |
| `services.csv` | 18 services (clients) | 18 |
| `articles.csv` | 664 articles | 664 |

> ⚠️ Ces comptages sont **verrouillés par un test de non-régression**
> (`stock/tests/test_import_sage_data.py`, test `test_comptages_stables`).
> Si tu ajoutes ou retires une ligne, la CI échouera tant que le test n'est
> pas mis à jour. C'est voulu : ça empêche une suppression accidentelle.

## Format des CSV

- **Séparateur** : `;` (point-virgule)
- **Encodage** : UTF-8 (avec ou sans BOM — le chargeur gère les deux)
- **1ʳᵉ ligne** = en-têtes (les noms de colonnes sont importants : renommer
  une colonne casse l'import)
- **Fin de ligne** : indifférente (LF ou CRLF)

### Colonnes attendues

| Fichier | Colonnes |
|---|---|
| `familles.csv` | `code;intitule;type;methode;categorie` |
| `fournisseurs.csv` | `code;raison_sociale;telephone` |
| `services.csv` | `code;nom;poste_telephone` |
| `articles.csv` | `reference;famille_code;designation;unite;seuil_min;seuil_critique` |

Exemple de ligne (`familles.csv`) :

```
code;intitule;type;methode;categorie
AFE;AUTRES FOURNITURES D'EXPLOITATION;D;CMUP;Exploitation
```

### Règles à respecter

1. **Codes uniques** : pas de doublon de `code` (familles, fournisseurs,
   services) ni de `reference` (articles) — vérifié par le test
   `test_codes_uniques`.
2. **`famille_code` d'un article** doit exister dans `familles.csv`, sinon
   l'article est ignoré avec un avertissement (et compté en erreur).
3. **`seuil_min` / `seuil_critique`** : entiers ≥ 0 (les virgules ou texte
   cassent l'import).
4. **`type`** (famille) : `D` (Divers/consommable) ou `T` (Technique/
   durable) — les valeurs acceptées par `TYPE_FAMILLE_CHOICES`.
5. **`methode`** : `CMUP` (méthode de valorisation, ex. CMUP).

## Comment modifier puis relancer l'import

### 1. Modifier le CSV

Exemple — ajouter un fournisseur dans `fournisseurs.csv` :

```
code;raison_sociale;telephone
401BUR;BUROMAT;0759861067
401XYZ;NOUVEAU FOURNISSEUR;0700000000
```

### 2. Tester en dry-run (recommandé)

La commande ne modifie rien en base avec `--dry-run` :

```bash
python manage.py import_sage_data --dry-run
```

Elle affiche le nombre d'éléments prêts et les éventuelles erreurs
(famille manquante, ligne mal formée…) sans rien écrire.

### 3. Lancer l'import réel

```bash
python manage.py import_sage_data
```

Options disponibles :

| Option | Effet |
|---|---|
| `--dry-run` | Simule l'import sans écrire en base |
| `--skip-articles` | Ignore les articles (si déjà importés) |
| `--skip-services` | Ignore les services |

### 4. Comportement (idempotent)

L'import utilise `get_or_create` sur les codes : un code déjà présent en
base est **laissé tel quel** (il n'est pas écrasé par le CSV), seuls les
nouveaux codes sont créés. Relancer la commande ne crée donc pas de doublons.

> Pour mettre à jour un libellé existant (ex. renommer un service), il faut
> le modifier en base (via l'interface) — l'import ne réécrit que les
> nouvelles entrées. (Le CSV reste la référence pour les installations
> neuves.)

### 5. Vérifier le test de stabilité

Après tout changement de comptage :

```bash
python manage.py test stock.tests.test_import_sage_data
```

et mettre à jour les valeurs dans `test_import_sage_data.py` si le nombre
de lignes change **volontairement**.

## Notes

- **Mode mono-tenant** : l'import est global — le paramètre historique
  `--entreprise-id` est ignoré (conservé pour compatibilité).
- **Windows** : la commande configure la console en UTF-8 automatiquement
  (pas d'erreur d'encodage sur les accents des désignations).
- Ce dossier est **commité** : les modifications de données font partie du
  code (auditables dans l'historique Git).
