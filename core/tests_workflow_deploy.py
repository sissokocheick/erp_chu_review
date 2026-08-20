# -*- coding: utf-8 -*-
"""
Tests du workflow GitHub Actions `.github/workflows/deploy.yml`.

Vérifie le comportement « ignorer proprement le déploiement quand les
secrets staging sont absents » (correction du bug où l'étape « Déployer »
s'exécutait quand même et échouait en 14 s) :

1. structure : l'étape de préparation publie `configured` et les étapes
   de déploiement sont conditionnées sur `configured == 'true'` ;
2. comportement réel : exécution du script `run:` de l'étape de
   préparation dans un environnement simulé (GITHUB_OUTPUT temporaire) —
   sans STAGING_HOST → `configured=false` et aucun inventaire créé ;
   avec STAGING_HOST → `configured=true` et inventaire généré.

Ces tests n'ont pas besoin de la base de données (SimpleTestCase) ni
d'Ansible : seul bash est requis (Git Bash sous Windows, bash sur CI).
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml
from django.test import SimpleTestCase

RACINE = Path(__file__).resolve().parent.parent
DEPLOY_YML = RACINE / ".github" / "workflows" / "deploy.yml"
CI_YML = RACINE / ".github" / "workflows" / "ci.yml"
REQUIREMENTS = RACINE / "requirements.txt"

BASHE = shutil.which("bash")


def _requirements_contient(nom_dependance):
    """True si la dépendance (ex: 'pyyaml') est déclarée dans requirements.txt.
    Insensible à la casse ; ignore les commentaires et les lignes vides."""
    nom_dependance = nom_dependance.strip().lower()
    try:
        texte = REQUIREMENTS.read_text(encoding="utf-8")
    except FileNotFoundError:
        return False
    for ligne in texte.splitlines():
        ligne = ligne.split("#", 1)[0].strip()
        if not ligne:
            continue
        nom = ligne.split("==", 1)[0].split(">=", 1)[0].split("<=", 1)[0].split("[", 1)[0].strip().lower()
        if nom == nom_dependance:
            return True
    return False


def _lire_workflow():
    """Charge deploy.yml en contournant le booléen YAML 1.1 pour la clé `on`."""
    with open(DEPLOY_YML, encoding="utf-8") as f:
        texte = f.read()
    # PyYAML (YAML 1.1) interprète `on:` comme un booléen True — on renomme
    # la clé en `triggers:` avant le chargement pour l'inspecter.
    texte = texte.replace("\non:\n", "\ntriggers:\n")
    return yaml.safe_load(texte)


def _lire_ci():
    """Charge ci.yml de la même façon (clé `on` renommée en `triggers`)."""
    with open(CI_YML, encoding="utf-8") as f:
        texte = f.read()
    texte = texte.replace("\non:\n", "\ntriggers:\n")
    return yaml.safe_load(texte)


def _step_par_nom(workflow, nom):
    for step in workflow["jobs"]["deploy-staging"]["steps"]:
        if step.get("name") == nom:
            return step
    raise AssertionError(f"Étape introuvable dans deploy.yml : {nom!r}")


@unittest.skipUnless(BASHE, "bash requis pour tester le workflow (Git Bash sous Windows)")
class DeployWorkflowIgnoreSansSecretsTest(SimpleTestCase):
    """Exécute réellement le script de préparation dans les 2 cas."""

    maxDiff = None

    def _executer_preparation(self, env_extra):
        """Lance le `run:` de l'étape « Préparer » avec un GITHUB_OUTPUT temp."""
        workflow = _lire_workflow()
        step = _step_par_nom(workflow, "Préparer inventaire + variables d'hôte")
        self.assertEqual(step.get("id"), "prepare",
                         "L'étape de préparation doit avoir id=prepare pour que "
                         "les conditions `steps.prepare.outputs.*` fonctionnent.")

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            # Le script écrit deploy/ansible/inventory et host_vars/staging.yml
            (tmp_path / "deploy" / "ansible" / "host_vars").mkdir(parents=True)

            script = tmp_path / "preparer.sh"
            script.write_text(step["run"], encoding="utf-8")

            output_file = tmp_path / "GITHUB_OUTPUT"
            env = {
                "PATH": os.environ.get("PATH", ""),
                "HOME": str(tmp_path),          # ~/.ssh dans le temp
                "GITHUB_OUTPUT": str(output_file),
                # Tous les secrets vides par défaut
                "STAGING_HOST": "",
                "STAGING_SSH_USER": "",
                "STAGING_SSH_KEY": "",
                "STAGING_SERVER_NAME": "",
                "STAGING_SECRET_KEY": "",
                "STAGING_DB_PASSWORD": "",
                "STAGING_DB_USER": "",
                "STAGING_DB_NAME": "",
            }
            env.update(env_extra)

            result = subprocess.run(
                [BASHE, str(script)],
                cwd=str(tmp_path),
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )
            outputs = {}
            if output_file.exists():
                for line in output_file.read_text(encoding="utf-8").splitlines():
                    if "=" in line:
                        k, _, v = line.partition("=")
                        outputs[k.strip()] = v.strip()
            # NB : on lit les fichiers DANS le `with` — le TemporaryDirectory
            # est supprimé à la sortie du bloc.
            inventaire = tmp_path / "deploy" / "ansible" / "inventory"
            host_vars = tmp_path / "deploy" / "ansible" / "host_vars" / "staging.yml"
            return result, outputs, {
                "inventaire_existe": inventaire.exists(),
                "inventaire_contenu": inventaire.read_text(encoding="utf-8") if inventaire.exists() else None,
                "host_vars_existe": host_vars.exists(),
                "host_vars_contenu": host_vars.read_text(encoding="utf-8") if host_vars.exists() else None,
            }

    def test_sans_secret_configured_false_et_aucun_inventaire(self):
        """STAGING_HOST vide → configured=false, exit 0, pas d'inventaire."""
        result, outputs, fichiers = self._executer_preparation({})
        self.assertEqual(result.returncode, 0,
                         f"Le script doit sortir en 0 (ignore proprement) :\n"
                         f"stdout={result.stdout}\nstderr={result.stderr}")
        self.assertEqual(outputs.get("configured"), "false",
                         "Sans STAGING_HOST, l'output doit être configured=false")
        self.assertFalse(fichiers["inventaire_existe"],
                         "Sans secrets, aucun inventaire Ansible ne doit être créé")

    def test_avec_secret_configured_true_et_inventaire_genere(self):
        """STAGING_HOST défini → configured=true, exit 0, inventaire créé."""
        result, outputs, fichiers = self._executer_preparation({
            "STAGING_HOST": "192.0.2.10",
            "STAGING_SSH_USER": "ubuntu",
            "STAGING_SSH_KEY": "clé-de-test\nligne2",
            "STAGING_SERVER_NAME": "erp-staging.chu.example",
            "STAGING_SECRET_KEY": "secret-de-test",
            "STAGING_DB_PASSWORD": "mdp-de-test",
        })
        self.assertEqual(result.returncode, 0,
                         f"stdout={result.stdout!r} stderr={result.stderr!r}")
        self.assertEqual(outputs.get("configured"), "true")
        self.assertTrue(fichiers["inventaire_existe"],
                        f"L'inventaire doit être généré. outputs={outputs}")
        self.assertIn("192.0.2.10", fichiers["inventaire_contenu"])
        self.assertTrue(fichiers["host_vars_existe"])
        self.assertIn("secret-de-test", fichiers["host_vars_contenu"])

    def test_etapes_deploiement_conditionnees(self):
        """Déployer et Succès ne tournent que si configured == 'true'."""
        workflow = _lire_workflow()
        deploy = _step_par_nom(workflow, "Déployer via Ansible (clone git du commit exact)")
        succes = _step_par_nom(workflow, "Succès")
        self.assertEqual(deploy.get("if"),
                         "steps.prepare.outputs.configured == 'true'",
                         "L'étape Déployer doit être conditionnée sur configured == 'true'")
        self.assertEqual(succes.get("if"),
                         "steps.prepare.outputs.configured == 'true'",
                         "L'étape Succès doit être conditionnée sur configured == 'true'")

    def test_condition_job_apres_ci(self):
        """Le job ne se déclenche qu'après une CI réussie (ou manuellement)."""
        workflow = _lire_workflow()
        job = workflow["jobs"]["deploy-staging"]
        self.assertIn("workflow_run", workflow.get("triggers", {}))
        self.assertEqual(
            job.get("if"),
            "github.event_name == 'workflow_dispatch' || github.event.workflow_run.conclusion == 'success'",
        )


class CjAlerteEchecCiTest(SimpleTestCase):
    """Le workflow CI notifie un webhook (Slack) quand un job échoue."""

    def setUp(self):
        self.ci = _lire_ci()
        self.alert = self.ci["jobs"]["alert"]

    def test_job_alerte_present(self):
        self.assertEqual(self.alert["name"], "Alerte échec CI (Slack/webhook)")

    def test_se_declenche_uniquement_sur_echec(self):
        self.assertEqual(self.alert.get("if"), "failure()",
                         "L'alerte ne doit partir que si un job a échoué")
        self.assertEqual(self.alert["needs"], ["tests", "security"],
                         "L'alerte dépend des jobs tests et security")

    def test_ignore_proprement_sans_secret(self):
        """Sans CI_ALERT_WEBHOOK, l'alerte est ignorée (pas d'échec du job)."""
        run = self.alert["steps"][0]["run"]
        self.assertIn("CI_ALERT_WEBHOOK non configuré", run)
        self.assertIn("exit 0", run)

    def test_message_contient_les_infos_utiles(self):
        step = self.alert["steps"][0]
        self.assertEqual(step["env"]["WEBHOOK_URL"], "${{ secrets.CI_ALERT_WEBHOOK }}")
        self.assertEqual(step["env"]["RUN_URL"],
                         "${{ github.server_url }}/${{ github.repository }}/actions/runs/${{ github.run_id }}")
        self.assertIn("curl", step["run"])


class DependancesTestsFiletTest(SimpleTestCase):
    """Filet de sécurité sur les dépendances de test.

    Chaque dépendance utilisée par les tests doit être À LA FOIS déclarée dans
    requirements.txt ET importable dans l'environnement. Retirer une ligne de
    requirements (ou le paquet) fait échouer la CI proprement au lieu de la
    laisser passer en local puis planter sur un runner vierge.

    - PyYAML  : core/tests_workflow_deploy.py importe `yaml` (avait été oublié
      dans requirements → collecte des tests cassée en CI).
    - playwright : tests E2E (skip si absent, mais doit rester déclaré pour que
      la CI installe le paquet + chromium).
    - pymupdf : assertions de contenu des PDF multi-pages (nombre de pages,
      numérotation) — sans lui ces assertions sont silencieusement sautées.
    """

    DEPENDANCES = [
        # (nom dans requirements, nom du module, attribut attendu, raison)
        ("pyyaml", "yaml", "safe_load",
         "core/tests_workflow_deploy.py l'importe (yaml)"),
        ("playwright", "playwright.sync_api", "sync_playwright",
         "tests E2E Playwright (LiveServerTestCase)"),
        ("pymupdf", "pymupdf", "open",
         "assertions de contenu des PDF multi-pages (pages, numérotation)"),
    ]

    def test_dependances_declarees_dans_requirements(self):
        for nom_req, module, attr, raison in self.DEPENDANCES:
            with self.subTest(dependance=nom_req):
                self.assertTrue(
                    _requirements_contient(nom_req),
                    f"{nom_req!r} doit être déclaré dans requirements.txt — "
                    f"utilisé par {raison}. Sans lui, la collecte des tests "
                    "échoue (ou des assertions sont sautées) sur un runner CI.",
                )

    def test_dependances_importables(self):
        import importlib
        for nom_req, module, attr, raison in self.DEPENDANCES:
            with self.subTest(dependance=module):
                mod = importlib.import_module(module)
                self.assertTrue(
                    hasattr(mod, attr),
                    f"{module!r} doit exposer {attr!r} (utilisé par {raison})",
                )
