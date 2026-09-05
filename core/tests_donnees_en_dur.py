# -*- coding: utf-8 -*-
"""
Filet anti données métier codées en dur (vues + templates).

Principe : les données d'exploitation (familles d'articles, articles,
magasins, services, fournisseurs, bénéficiaires...) vivent dans la base
de données. Le code applicatif (vues) et les templates ne doivent que les
manipuler — jamais les créer avec des valeurs littérales en dur, ni les
lister en dur dans le HTML.

Deux garde-fous :

1. VUES : aucun appel `ModeleReference.objects.create/get_or_create/...`
   ne doit passer un libellé/code littéral (nom, code, intitulé...) — les
   valeurs doivent venir de la saisie (request.POST, form.cleaned_data,
   variables) ou de la base.

2. TEMPLATES : aucun <option> statique avec une valeur métier non vide —
   seules autorisées : les valeurs des choix de modèles (statuts, types),
   les valeurs numériques (pagination, seuils) et les libellés
   d'interface (value vide, « Tous/Toutes », ...).

Ce test est volontairement conservateur : toute nouvelle donnée métier
codée en dur fera échouer la CI avec un message indiquant le fichier et
la ligne.
"""

import importlib
import re
from pathlib import Path

from django.test import SimpleTestCase

RACINE = Path(__file__).resolve().parent.parent

# Modèles de référence : données métier persistantes qui doivent être
# créées uniquement par saisie utilisateur / import — jamais codées en dur.
MODELES_REFERENCE = (
    "FamilleArticle", "Article", "Magasin", "Service", "Fournisseur",
    "Beneficiaire", "TypeArticle", "UniteMesure", "ModeleDocumentMagasin",
)

# Champs porteurs de libellés/codes métier : interdits en littéral dans
# une création de modèle de référence.
CHAMPS_LITTERAUX = (
    "nom", "nom_complet", "raison_sociale", "intitule", "designation",
    "reference", "code", "telephone", "poste", "specialite",
)

# Valeurs d'interface tolérées dans les <option> (pas des données métier).
# - pagination : all
# - tri de listes : date_desc, date_asc, alpha
# - filtres livraison : signe, attente
# - mise en page PDF : left/center/right, solid/dashed/dotted/none, fine/normal/strong,
#   ligne_pleine/ligne_pointillee/encadre/sans_trait, toujours/si_valide/si_rejete
# - motifs "autre" : __AUTRE__, __OTHER__
# - granularité de stats : jour, semaine, mois, annee
# - filtres comptes : actif, inactif, tous ; filtres intervention : ALL
# - types de champs de formulaire dynamique : text, number, date, select
# - mode de division SAS : manuel
VALEURS_INTERFACE = {
    "all", "__AUTRE__", "__OTHER__",
    "date_desc", "date_asc", "alpha",
    "signe", "attente",
    "left", "center", "right",
    "solid", "dashed", "dotted", "none",
    "fine", "normal", "strong",
    "ligne_pleine", "ligne_pointillee", "encadre", "sans_trait",
    "toujours", "si_valide", "si_rejete",
    "jour", "semaine", "mois", "annee",
    "actif", "inactif", "tous", "ALL",
    "text", "number", "date", "select",
    "manuel",
    # Paramètres › Sauvegardes : type de destination et planification
    # (core/backups.py). Ces valeurs décrivent le schéma de configuration,
    # elles ne représentent pas des données d'exploitation.
    "ssh", "smb", "aucun", "daily", "interval", "weekly", "desactive",
    # Choix déclarés par les modèles Patrimoine.
    "HEBDOMADAIRE", "BIMENSUEL", "MENSUEL",
    "videoconf", "ecran", "wifi", "clim",
    "ESSENCE", "DIESEL", "HYBRIDE",
}

RE_CREATION = re.compile(
    r"\b(" + "|".join(MODELES_REFERENCE) + r")\.objects\.("
    r"create|get_or_create|update_or_create|bulk_create)\("
)
RE_LITTERAL = re.compile(
    r"\b(" + "|".join(CHAMPS_LITTERAUX) + r")\s*=\s*"
    r'(?:"[^"]+"|\'[^\']+\')'
)
RE_OPTION = re.compile(
    r"<option[^>]*\bvalue\s*=\s*[\"']([^\"']*)[\"'][^>]*>\s*"
    r"([^<{]*?)\s*</option>"
)


def _fichiers_vues():
    """Tous les fichiers de vues de l'application (hors tests)."""
    fichiers = list((RACINE / "stock" / "views").rglob("*.py"))
    for rel in (
        "accounts/views.py", "accounts/views_fonctions.py",
        "accounts/views_reset.py", "core/views.py", "patrimoine/views.py",
    ):
        p = RACINE / rel
        if p.exists():
            fichiers.append(p)
    return fichiers


def _fichiers_templates():
    """Tous les templates HTML de l'application."""
    fichiers = []
    for dossier in (
        "stock/templates", "templates", "accounts/templates",
        "core/templates", "patrimoine/templates",
    ):
        base = RACINE / dossier
        if base.exists():
            fichiers.extend(base.rglob("*.html"))
    return fichiers


def _extraire_appel(texte, pos):
    """Extrait le bloc d'un appel à partir de sa parenthèse ouvrante."""
    profondeur = 0
    i = pos
    while i < len(texte):
        if texte[i] == "(":
            profondeur += 1
        elif texte[i] == ")":
            profondeur -= 1
            if profondeur == 0:
                return texte[pos:i + 1]
        i += 1
    return texte[pos:]


def _collecter_choix(valeurs, valeur):
    """Ajoute les valeurs d'une constante *CHOICES dans l'ensemble donné."""
    if isinstance(valeur, type):  # TextChoices / IntegerChoices
        try:
            choix = valeur.choices
        except Exception:
            return
        if isinstance(choix, (list, tuple)):
            for v, _ in choix:
                valeurs.add(str(v))
        return
    if isinstance(valeur, dict):
        valeurs.update(str(k) for k in valeur)
        return
    if isinstance(valeur, (list, tuple)):
        for item in valeur:
            if isinstance(item, (list, tuple)) and item:
                valeurs.add(str(item[0]))
            elif isinstance(item, str):
                valeurs.add(item)


def _choix_modeles():
    """Toutes les valeurs des constantes *CHOICES des modèles de l'app.

    Couvre les constantes au niveau du module ET les attributs de classe
    des modèles (ex. `Demande.STATUT_CHOICES`). Ces valeurs (statuts,
    types...) sont des choix de schéma — autorisées dans les <option>
    statiques des templates.
    """
    valeurs = set()
    for app in ("stock", "core", "accounts", "patrimoine"):
        try:
            mod = importlib.import_module(f"{app}.models")
        except Exception:
            continue
        for nom, valeur in vars(mod).items():
            if nom.endswith("CHOICES"):
                _collecter_choix(valeurs, valeur)
        for nom, classe in vars(mod).items():
            if isinstance(classe, type) and hasattr(classe, "_meta"):
                for attr, valeur in vars(classe).items():
                    if attr.endswith("CHOICES"):
                        _collecter_choix(valeurs, valeur)
    return valeurs


class AucuneDonneeMetierEnDurTest(SimpleTestCase):
    """Garde-fou : aucune donnée métier codée en dur dans les vues/templates."""

    def test_aucune_creation_metier_litterale_dans_les_vues(self):
        """Aucune création d'un modèle de référence avec un libellé en dur."""
        echecs = []
        for f in _fichiers_vues():
            texte = f.read_text(encoding="utf-8")
            for m in RE_CREATION.finditer(texte):
                bloc = _extraire_appel(texte, m.end() - 1)
                for lit in RE_LITTERAL.finditer(bloc):
                    echecs.append(
                        f"{f.relative_to(RACINE)}:{texte[:m.start()].count(chr(10)) + 1} — "
                        f"{m.group(1)}.{m.group(2)}() champ "
                        f"« {lit.group(1)} » codé en dur : {lit.group(2)}"
                    )
        self.assertEqual(
            echecs, [],
            "Données métier codées en dur dans les vues (elles doivent "
            "venir de la base ou de la saisie) :\n" + "\n".join(echecs[:15]),
        )

    def test_aucune_option_metier_en_dur_dans_les_templates(self):
        """Aucun <option> statique avec une valeur métier non autorisée."""
        choix = _choix_modeles()
        echecs = []
        for f in _fichiers_templates():
            texte = f.read_text(encoding="utf-8")
            for m in RE_OPTION.finditer(texte):
                valeur = m.group(1).strip()
                libelle = m.group(2).strip()
                if not valeur or not libelle:
                    continue  # placeholder / option dynamique
                if "{" in valeur or "%" in valeur:
                    continue  # valeur injectée par le template
                if valeur in choix or valeur in VALEURS_INTERFACE:
                    continue  # choix de modèle / interface
                if valeur.isdigit():
                    continue  # pagination / seuils numériques
                echecs.append(
                    f"{f.relative_to(RACINE)} — "
                    f"<option value=\"{valeur}\">{libelle}</option>"
                )
        self.assertEqual(
            echecs, [],
            "Options métier codées en dur dans les templates (les données "
            "doivent venir de la base via {% for %}):\n"
            + "\n".join(echecs[:15]),
        )
