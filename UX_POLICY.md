# NexusERP — Politique d’expérience utilisateur (UX)

> Référence unique à respecter sur **toute** l’application.  
> Dernière mise à jour : 2026-07-25

---

## 1. Design system global — NxUX

Chargé dans `base_ui.html`, disponible sur toutes les pages qui l’étendent.

| API | Usage |
|-----|--------|
| `NxUX.toast(type, message)` | Feedback non bloquant (`success` / `error` / `warning` / `info`) |
| `NxUX.confirm({ title, text, onConfirm })` | Confirmation avant action |
| `NxUX.confirmDelete(message, onConfirm)` | Confirmation suppression (bouton rouge) |
| `NxUX.loading(btn)` / `NxUX.stopLoading(btn)` | Spinner sur bouton pendant le traitement |
| `NxUX.submitWithConfirm(form, options)` | Confirm + loading + submit en une fois |

**Compatibilité :** les anciennes fonctions `confirmerSuppression` / `confirmerAction` appellent NxUX en interne.

**Pages déjà migrées :** Rôles, Utilisateurs, Profil, Réinitialisation MDP.

---

## 2. Formulaires & erreurs

| Règle | Détail |
|-------|--------|
| Pas de redirect sur erreur de validation | Utiliser `render()` avec le contexte |
| Données conservées | Dictionnaire `form_data` aligné sur les noms de champs du template |
| Message d’erreur dans la modale | Clé `form_error` + bloc `.modal-error-box` |
| Modale reste ouverte | `show_modal=True` dans le contexte |
| Doublons bloqués | Login, email, téléphone → message clair côté serveur |
| Clés form_data = noms HTML | Ex. `groupe`, `service`, `fonction` (pas `groupe_id`) |

### Pattern Python recommandé

```python
form_data = {
    'username': username,
    'first_name': first_name,
    'last_name': last_name,
    'email': email,
    'contact': contact_display,
    'groupe': groupe_id or '',
    'service': service_id or '',
    'fonction': fonction_id or '',
    # …
}
if erreur:
    return render(request, '…', {
        **contexte,
        'form_data': form_data,
        'show_modal': True,
        'form_error': "⛔ Message clair.",
    })
```

---

## 3. Formatage des champs (global)

Attribut HTML `data-nx-format` — appliqué automatiquement au `input` et au `blur`.

| Valeur | Effet | Exemple |
|--------|-------|---------|
| `upper` / `nom` | MAJUSCULES | `DUPONT` |
| `prenom` | Première lettre de chaque mot | `Jean Pierre` |
| `login` | Minuscules, sans espaces | `j.dupont` |
| `email` | Minuscules + trim | `jean@hopital.ci` |
| `phone` | 10 chiffres → groupes de 2 | `01 02 03 04 05` |

```html
<input name="last_name" data-nx-format="upper">
<input name="first_name" data-nx-format="prenom">
<input name="username"  data-nx-format="login">
<input name="email"     data-nx-format="email">
<input name="contact"   data-nx-format="phone" maxlength="14">
```

**Côté serveur (obligatoire) :** normaliser aussi dans la vue (`.upper()`, `.title()`, `.lower()`, chiffres seuls pour le téléphone).

**Login :** minimum **3** caractères, minuscules, sans espaces.

**Email :** si renseigné, doit contenir `@`.  
**Téléphone :** si renseigné, exactement **10 chiffres**.

API JS manuelle : `NxUX.formatPhone(el)`, `NxUX.formatUpper(el)`, `NxUX.formatLogin(el)`, etc.

---

## 4. Mots de passe — politique unique

| Règle | Valeur |
|-------|--------|
| Longueur minimum **login** | **3** caractères |
| Longueur minimum **mot de passe** | **8** caractères |
| Majuscule | Obligatoire |
| Chiffre | Obligatoire |
| Génération automatique | **12** caractères conformes |
| Fonction de validation | `valider_mot_de_passe(password)` → `list` d’erreurs |
| Fonction de génération | `generer_mot_de_passe_aleatoire(12)` |
| Configuration | Modèle `ConfigSecurite` (singleton) : mode `ALEATOIRE` ou `FIXE` |
| Premier login | `profil.doit_changer_mdp = True` → écran obligatoire |

**À utiliser partout :** création user, réinit admin, profil, changement obligatoire.  
Ne plus coder de `len(password) < 8` isolé.

---

## 5. Création d’utilisateur

1. Confirmation NxUX avant enregistrement  
2. Spinner sur le bouton (`NxUX.loading`)  
3. Mot de passe selon `ConfigSecurite` (aléatoire 12 car. ou fixe validé)  
4. Session `new_user_credentials` → modale login + MDP + bouton copier (**une seule fois**)  
5. En cas d’erreur : modale ouverte, champs remplis, `form_error` affiché  

---

## 6. Confirmations & actions sensibles

| Action | Comportement |
|--------|--------------|
| Suppression (rôle, etc.) | `NxUX.confirmDelete` |
| Activation / désactivation | `NxUX.confirm` (couleur selon action) |
| Changement photo / MDP profil | `NxUX.confirm` |
| Réinit MDP admin | `NxUX.confirm` + loading |
| Création / modification rôle | `NxUX.confirm` + loading |

Toute action **irréversible** ou **sensible** passe par une confirmation.

---

## 7. Validation en temps réel (AJAX)

Sur les champs à unicité (login, email, téléphone) :

| Règle | Détail |
|-------|--------|
| Debounce | **400 ms** après la dernière frappe |
| Feedback | Bordure verte/rouge + hint sous le champ |
| Spinner | Pendant l’appel API |
| Édition | Passer `exclude_id` pour ne pas se bloquer soi-même |
| Login min | **3** caractères (constante `MIN_USERNAME_LENGTH`) |

Endpoint : `GET /auth/api/utilisateurs/verifier/?type=username|email|contact&value=…&exclude_id=…`

---

## 8. Permissions UX

| Situation | Comportement UI |
|-----------|-----------------|
| Pas le droit d’agir | **Masquer** le bouton / lien (pas de bouton grisé sans explication) |
| Droit lecture seule | Champs `readonly` / `disabled` + bouton Enregistrer masqué |
| Tentative d’accès direct (URL) | Message : *« Vous n’avez pas l’autorisation pour cette action. »* + redirect sûr |
| Superuser | Accès total, sauf actions auto-destructrices (ex. se désactiver soi-même) |

Ne jamais laisser un bouton visible qui mène à une erreur 403 silencieuse.

---

## 9. États vides, chargement, erreur

Chaque liste / tableau doit gérer **3 états** :

| État | Affichage |
|------|-----------|
| **Chargement** | Spinner centré ou skeleton (pas de tableau vide trompeur) |
| **Vide** | Icône + message clair + **CTA** (*« Créer le premier… »*) si l’utilisateur a le droit |
| **Erreur** | Message + bouton *Réessayer* |

Exemple :

```html
{% empty %}
<tr>
  <td colspan="N" style="text-align:center;padding:50px;color:var(--text-light);">
    <i class="fas fa-users" style="font-size:40px;opacity:.4;display:block;margin-bottom:15px;"></i>
    Aucun utilisateur trouvé.<br>
    <button type="button" class="btn-primary" onclick="ouvrirModal()" style="margin-top:15px;">
      <i class="fas fa-plus"></i> Créer le premier utilisateur
    </button>
  </td>
</tr>
{% endempty %}
```

---

## 10. Accessibilité (minimum obligatoire)

| Règle | Application |
|-------|-------------|
| Bouton icône seule | `title` **et** `aria-label` avec le même libellé |
| Focus visible | Ne jamais supprimer l’outline sans alternative claire |
| Modale | Focus dans la modale à l’ouverture ; Escape la ferme |
| Toasts | `role="status"` / `aria-live="polite"` (déjà dans NxUX si applicable) |
| Champs obligatoires | `required` + astérisque visible dans le label |
| Contraste | Texte d’erreur/succès lisible en light **et** dark mode |

---

## 11. Mobile / tablette

| Règle | Valeur |
|-------|--------|
| Bouton d’action principale | Hauteur min **44 px** |
| Modale formulaire | Quasi plein écran sous **768 px** |
| Tables larges | Scroll horizontal **ou** bascule en cartes |
| Touch | Pas de hover-only pour les actions critiques |

---

## 12. Micro-copy (messages)

| Type | Style | Exemple |
|------|--------|---------|
| Succès | Court, positif | *« Utilisateur créé »* |
| Erreur | Actionnable | *« Ce login existe déjà — choisissez-en un autre »* |
| Warning | Conséquence claire | *« Le compte sera désactivé immédiatement »* |
| Info | Neutre | *« Le mot de passe temporaire s’affiche une seule fois »* |

**Interdit côté UI :** messages techniques (`IntegrityError`, traceback, codes HTTP bruts).

---

## 13. Principes transverses

1. **Feedback immédiat** — toast ou message in-modal, jamais de silence  
2. **Pas de perte de saisie** — erreur = page / modale conservée avec les données  
3. **Actions destructives confirmées** — toujours une étape de validation  
4. **Loading visible** — bouton désactivé + spinner pendant le traitement  
5. **Messages clairs** — français, avec icône, sans jargon technique  
6. **Cohérence visuelle** — classes `nx-*`, dark mode, mêmes patterns de modales  
7. **Focus utile** — premier champ en erreur, Escape ferme les modales  
8. **Validation anticipée** — AJAX avant submit dès que possible  
9. **Permissions honnêtes** — masquer ce qui est interdit  

---

## 14. Checklist nouvelle page / nouveau formulaire

```
☐ Boutons d’action critique → NxUX.confirm ou confirmDelete
☐ Submit long → NxUX.loading(btn) avant envoi
☐ Erreur validation → render + form_data + form_error (pas redirect)
☐ Champs texte concernés → data-nx-format="…"
☐ Champs unicité → validation AJAX (debounce 400 ms)
☐ Login → min 3 caractères
☐ Succès rapide / AJAX → NxUX.toast('success', '…')
☐ Mot de passe → valider_mot_de_passe() / generer_mot_de_passe_aleatoire()
☐ Boutons icône → title + aria-label
☐ État vide → icône + texte + CTA
☐ Pas le droit → bouton masqué
☐ Dark mode → tester alertes et toasts
☐ Mobile → modale lisible, boutons ≥ 44 px
```

---

## 15. Fichiers de référence

| Fichier | Rôle |
|---------|------|
| `templates/base_ui.html` | NxUX + tokens CSS + formatage + confirmations |
| `accounts/utils.py` | `valider_mot_de_passe`, `generer_mot_de_passe_aleatoire` |
| `accounts/models.py` | `ConfigSecurite` (singleton politique MDP) |
| `accounts/views.py` | `form_data` / `form_error` / credentials / API verifier |
| Templates accounts | Exemples d’intégration (utilisateurs, roles, profil, réinit) |
| `docs/UX_POLICY.md` | Ce document |

---

*Toute dérogation à cette politique doit être justifiée et documentée.*
