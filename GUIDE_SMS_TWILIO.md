# 📱 Guide : Configurer l'envoi de SMS avec Twilio (compte d'essai gratuit)

Ce guide explique pas-à-pas comment brancher l'application sur **Twilio** pour
recevoir les notifications par SMS. Le compte **trial** de Twilio est **gratuit,
sans carte bancaire** : ~100 SMS offerts pendant 30 jours, envoyés uniquement
vers les numéros que vous avez **vérifiés** (dont votre propre numéro).

> ⏱️ Durée totale : ~15 minutes. Aucune modification de code nécessaire —
> tout se fait dans la console Twilio puis dans la page
> **Paramètres → Notifications** de l'application.

---

## Étape 1 — Créer le compte Twilio

1. Va sur **https://www.twilio.com** → bouton **Sign up** (en haut à droite).
2. Renseigne email + mot de passe, puis valide l'email reçu.
3. À l'étape « *Tell us about yourself* » : choisis un nom de société
   (ex. « CHU — Service Pharmacie »), un pays, et coche « *I'm a developer* ».
4. À l'étape « *Verify your phone number* » : Twilio te demande un numéro à
   vérifier **par code SMS ou appel**. Tu peux utiliser **ton propre numéro
   ivoirien** (celui qui doit recevoir les SMS de test).

   ⚠️ **Format important** : saisis le numéro au format international —
   `+225` **sans le 0 initial** : `+225 07 08 09 10 11` → `+2250708091011`.

5. Choisis la réponse « *Twilio for my own personal project* » → **Finish**.

✅ Compte créé. Tu es dans la **console Twilio** (`console.twilio.com`).

---

## Étape 2 — Vérifier le numéro qui recevra les SMS de test

En mode trial, Twilio **n'envoie que vers les numéros vérifiés** dans ton compte.

1. Dans la console : **Developers → Phone Numbers → Verified Caller IDs**
   (ou cherche « *Verified Caller IDs* »).
2. Clique **+** et ajoute ton numéro de test.
3. Twilio envoie un code par SMS/appel → saisis-le pour valider.

> ⚠️ **Piège découvert en test réel** : en mode trial, Twilio compare le
> numéro **à la lettre près**. L'application envoie `+225` + le numéro local
> **en conservant le 0 initial** : `0173915282` → `+2250173915282`.
> Vérifie donc les numéros **exactement sous cette forme** (avec le 0),
> sinon Twilio refuse l'envoi avec l'erreur `572002`.

> 💡 C'est ce numéro vérifié qui recevra les SMS générés par l'application.
> En production, tu pourras envoyer vers n'importe quel numéro.

---

## Étape 3 — Récupérer le SID et le Token (les clés de l'API)

1. Dans la console, ouvre **Developers → API keys & tokens**.
2. Note deux valeurs :
   - **Account SID** : commence par `AC` (ex. `AC1a2b3c…`).
   - **Auth Token** : long code secret (clique sur l'œil pour l'afficher).
3. ⚠️ **Ne partage jamais l'Auth Token** — c'est la clé qui permet d'envoyer
   des SMS depuis ton compte.

Tu en auras besoin à l'étape 5, combinés dans un seul champ, séparés par
deux-points : `SID:TOKEN`.

---

## Étape 4 — Récupérer un numéro Twilio d'essai (l'expéditeur)

1. Dans la console : **Developers → Phone Numbers → Buy a Number**.
2. En trial, choisis **Get a Trial Number** (gratuit) — tu obtiens un numéro
   américain type `+1 501 712 2661`. **Note-le** : ce sera l'**expéditeur**
   (le numéro « From » visible par le destinataire).

---

## Étape 5 — Remplir la page Paramètres → Notifications de l'application

1. Connecte-toi à l'application (compte administrateur).
2. Menu **PARAMÈTRES → Notifications** (URL : `/parametres/notifications/`).
3. Dans la carte **Canal SMS (API)**, remplis exactement :

| Champ de l'application | Valeur à mettre | Exemple |
|---|---|---|
| ✅ **Activer les notifications par SMS** | Cocher | — |
| **Fournisseur SMS** | `Twilio` | — |
| **Expéditeur (sender ID)** | Ton numéro Twilio d'essai (format `+1…`) | `+15017122661` |
| **URL de l'API SMS** | `https://api.twilio.com/2010-04-01` | — |
| **Clé API / Token** | Ton `Account SID : Auth Token` **séparés par deux-points** | `AC1a2b3c…:abcd1234…` |
| **Modèle Twilio (compte trial)** | Nom d'un **modèle prédéfini** Twilio (liste ci-dessous) — obligatoire en compte trial | `sms_appointment_reminders` |
| **Paramètre du numéro** | `to` (non utilisé par Twilio, laisser tel quel) | `to` |
| **Paramètre du message** | `message` (idem) | `message` |
| **Mode test (journal uniquement)** | **Décocher** pour un vrai envoi | — |

   *(Les champs email de la carte du haut sont indépendants — tu peux les
   laisser tels quels ou les remplir plus tard.)*

4. Clique **💾 Enregistrer la configuration**.

> 🔎 **Astuce avant le premier vrai envoi** : garde **Mode test coché**,
> enregistre, déclenche une notification, puis vérifie dans les logs du serveur
> la ligne `[Notifications][SMS·TEST] À +225…`. Quand tout est bon, **déccoche
> le mode test** et réenregistre : le prochain SMS partira réellement.

---

## Étape 6 — Vérifier que ça marche vraiment

1. Assure-toi que **le destinataire a son téléphone dans son profil** :
   menu **SECURITÉ & ACCÈS → Utilisateurs**, ouvrir l'utilisateur, champ
   **Téléphone** = 10 chiffres ivoiriens (`0708091011`). C'est **ce numéro**
   qui reçoit le SMS (l'application le convertit automatiquement en
   `+225708091011` à l'envoi).
2. Déclenche une notification : par exemple un **stock sous le seuil minimal**
   ou un **bon de sortie créé** pour cet utilisateur.
3. Le SMS arrive sur le téléphone en quelques secondes : `[Alerte Stock] …`.

---

### 📋 Modèles prédéfinis acceptés en compte trial

En trial, le champ **Body** doit être un nom de modèle prédéfini (texte libre →
erreur `572006`). Exemples : `sms_appointment_reminders`,
`sms_verification`, `sms_consultation_reminders`, `sms_billing_notifications`,
`sms_delivery_notifications`, `sms_feedback_requests`, `sms_order_confirmation`,
`sms_payment_confirmations`, `sms_promotional_offers`, `sms_service_notifications`,
`sms_shipping_updates`. Le destinataire reçoit le **texte prédéfini** de Twilio
(et non le texte de la notification). En **compte payant**, laisse le champ vide :
l'app envoie alors le vrai texte de la notification.

## ⚠️ Pièges à éviter

- **Format du numéro de profil** : l'application stocke 10 chiffres ivoiriens
  (`0708091011`) et les convertit **automatiquement** en `+225…` à l'envoi
  (normalisation E.164 intégrée au service SMS). Un numéro déjà international
  (`+225…`) est transmis tel quel.
- **Mode test resté coché** : aucun SMS n'est envoyé, il est juste journalisé.
- **Numéro de destination non vérifié** : en trial, Twilio refuse l'envoi vers
  un numéro non vérifié (erreur `21610`). Vérifie-le à l'étape 2.
- **Clé API mal copiée** : le champ attend **`SID:TOKEN`** (un seul champ,
  deux-points entre les deux) — pas seulement le SID.
- **Compte trial expiré** : le trial dure 30 jours, après quoi il faut recharger
  pour continuer (les SMS réels coûtent ~$0.01–0.03 pièce vers la Côte d'Ivoire).

---

## ❓ Que faire si le SMS ne part pas

| Symptôme | Cause probable | Solution |
|---|---|---|
| Rien dans les logs | Canal SMS désactivé ou mode test coché | Cocher « Activer les SMS », décocher « Mode test » |
| Log : « Pas de téléphone pour … » | L'utilisateur n'a pas de téléphone dans son profil | Renseigner le champ Téléphone (10 chiffres) |
| Log : « Échec envoi SMS » + erreur `21610` | Numéro de destination non vérifié | L'ajouter dans Verified Caller IDs |
| Log : erreur `20003` | Mauvaise clé API | Vérifier `SID:TOKEN` à l'étape 3 |
| Log : erreur `572006` | En trial, le Body doit être un modèle prédéfini | Renseigner le champ « Modèle Twilio (compte trial) » |
| Log : erreur `572002` | Le numéro de destination n'est pas vérifié exactement | Ajouter le numéro au format `+225` + 10 chiffres (avec le 0) dans Verified Caller IDs |
