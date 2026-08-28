# -*- coding: utf-8 -*-
"""
Gestion des sauvegardes PostgreSQL pilotée depuis l'interface (page Paramètres).

Ce module est la couche service derrière core.views.parametres_sauvegardes :
  - lire_config / ecrire_config : configuration persistée dans backups/config.json
    (pas de migration DB nécessaire — fonctionne même si la base est HS).
  - lancer_sauvegarde : exécute scripts/backup_db.py en sous-processus
    (pg_dump) avec les options de la configuration.
  - lister_backups : liste détaillée des fichiers .backup locaux.
  - supprimer_backup / chemin_backup : manipulation sûre d'un fichier
    (nom validé par regex, jamais de traversée de dossier).

La copie vers un serveur distant (SSH/SCP, partage SMB Windows ou NAS QNAP)
est déléguée à scripts/backup_db.py --remote-host … qui gère déjà SCP puis
le fallback UNC.
"""
import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from django.conf import settings

BASE_DIR = Path(settings.BASE_DIR)

# Fichier de config (créé au premier enregistrement depuis l'interface).
CONFIG_PATH = BASE_DIR / 'backups' / 'config.json'

# Nom de fichier de backup accepté (produit par scripts/backup_db.py).
_NOM_BACKUP_RE = re.compile(r'^[A-Za-z0-9_]+_\d{14}\.backup$')

# Délai maximal d'une sauvegarde lancée depuis le navigateur (10 min).
TIMEOUT_SAUVEGARDE = 600

# Au-delà de ce délai sans backup local, l'état passe en « alerte »
# (bandeau sur la page Sauvegardes + notification sur le dashboard).
SEUIL_ALERTE_HEURES = 24

CONFIG_DEFAUT = {
    'type_distant': 'smb',        # ssh | smb | aucun
    'host': '',
    'user': 'backup',
    'password': '',               # mot de passe du compte distant (SMB/SSH)
    'remote_dir': '/backups',
    'keep_days': 7,
    'keep_weeks': 8,
    'keep_months': 12,
    # Planification
    'cron_mode': 'desactive',     # daily | interval | weekly | desactive
    'cron_hour': '02',            # heure (00-23) — daily & weekly
    'cron_minute': '00',          # minute (00-59)
    'cron_interval': '60',        # minutes entre chaque exécution — interval
    'cron_days': '',              # jours (lu,ma,me,je,ve,sa,di) — weekly
}

JOURS_SEMAINE = [
    ('lu', 'Lundi'), ('ma', 'Mardi'), ('me', 'Mercredi'),
    ('je', 'Jeudi'), ('ve', 'Vendredi'), ('sa', 'Samedi'), ('di', 'Dimanche'),
]

MOIS_ANNEE = [
    (1, 'Janvier'), (2, 'Février'), (3, 'Mars'), (4, 'Avril'),
    (5, 'Mai'), (6, 'Juin'), (7, 'Juillet'), (8, 'Août'),
    (9, 'Septembre'), (10, 'Octobre'), (11, 'Novembre'), (12, 'Décembre'),
]


def _dossier_backups():
    return BASE_DIR / 'backups'


def lire_config():
    """Retourne la configuration fusionnée avec les valeurs par défaut."""
    config = dict(CONFIG_DEFAUT)
    if CONFIG_PATH.is_file():
        try:
            donnees = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
            if isinstance(donnees, dict):
                config.update({k: v for k, v in donnees.items() if k in CONFIG_DEFAUT})
        except (OSError, ValueError):
            pass
    # Hériter du .env si rien n'est encore configuré via l'interface
    if not config.get('host'):
        import os
        config['host'] = os.environ.get('BACKUP_REMOTE_HOST', '') or ''
        config['user'] = os.environ.get('BACKUP_REMOTE_USER', '') or config['user']
        config['remote_dir'] = os.environ.get('BACKUP_REMOTE_DIR', '') or config['remote_dir']
    return config


def ecrire_config(donnees):
    """Valide et écrit la configuration dans backups/config.json.

    Retourne (ok, message).
    """
    config = dict(CONFIG_DEFAUT)
    config['type_distant'] = str(donnees.get('type_distant', 'smb')).strip()
    if config['type_distant'] not in ('ssh', 'smb', 'aucun'):
        return False, "Type de destination invalide (ssh, smb ou aucun)."

    host = str(donnees.get('host', '')).strip()
    if config['type_distant'] != 'aucun':
        if not re.match(r'^[A-Za-z0-9._-]+$', host):
            return False, "Hôte invalide (IP ou nom de machine attendu)."
        if not host:
            return False, "L'hôte est obligatoire quand une destination distante est choisie."
    config['host'] = host

    user = str(donnees.get('user', 'backup')).strip() or 'backup'
    if not re.match(r'^[A-Za-z0-9._-]+$', user):
        return False, "Utilisateur distant invalide."
    config['user'] = user

    # Mot de passe distant (champ vide = conserver l'ancien)
    password = donnees.get('password', '')
    if password:
        config['password'] = str(password)
    elif 'password' in donnees:
        # Champ soumis vide → on conserve l'ancien mot de passe
        config['password'] = config.get('password', '')
    else:
        config['password'] = donnees.get('password', '')

    remote_dir = str(donnees.get('remote_dir', '/backups')).strip() or '/backups'
    if '\\' in remote_dir or '..' in remote_dir:
        return False, "Dossier distant invalide."
    config['remote_dir'] = remote_dir

    for champ in ('keep_days', 'keep_weeks', 'keep_months'):
        try:
            valeur = int(donnees.get(champ, CONFIG_DEFAUT[champ]))
            if valeur < 0:
                raise ValueError
        except (TypeError, ValueError):
            return False, f"Valeur de rétention invalide pour {champ}."
        config[champ] = valeur

    # ── Planification ──
    cron_mode = str(donnees.get('cron_mode', 'desactive')).strip()
    if cron_mode not in ('daily', 'interval', 'weekly', 'desactive'):
        return False, "Mode de planification invalide."
    config['cron_mode'] = cron_mode
    config['cron_hour'] = str(donnees.get('cron_hour', '02')).strip() or '02'
    config['cron_minute'] = str(donnees.get('cron_minute', '00')).strip() or '00'
    config['cron_interval'] = str(donnees.get('cron_interval', '60')).strip() or '60'
    config['cron_days'] = str(donnees.get('cron_days', '')).strip()

    try:
        _dossier_backups().mkdir(parents=True, exist_ok=True)
        CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False),
                               encoding='utf-8')
    except OSError as exc:
        return False, f"Impossible d'écrire la configuration : {exc}"
    return True, "✅ Configuration des sauvegardes enregistrée."


def lancer_sauvegarde():
    """Lance scripts/backup_db.py (pg_dump + rétention + copie distante).

    Retourne (ok, sortie_texte).
    """
    config = lire_config()
    script = BASE_DIR / 'scripts' / 'backup_db.py'
    if not script.is_file():
        return False, f"Script introuvable : {script}"

    cmd = [
        sys.executable, str(script),
        '--dir', str(_dossier_backups()),
        '--keep-days', str(config['keep_days']),
        '--keep-weeks', str(config['keep_weeks']),
        '--keep-months', str(config['keep_months']),
    ]
    if config['type_distant'] != 'aucun' and config['host']:
        cmd += ['--remote-host', config['host'],
                '--remote-user', config['user'],
                '--remote-dir', config['remote_dir']]
        if config.get('password'):
            cmd += ['--remote-password', config['password']]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=TIMEOUT_SAUVEGARDE, cwd=str(BASE_DIR))
    except subprocess.TimeoutExpired:
        return False, f"⏱ Sauvegarde interrompue : durée max ({TIMEOUT_SAUVEGARDE}s) dépassée."
    except OSError as exc:
        return False, f"Impossible de lancer la sauvegarde : {exc}"

    sortie = ((proc.stdout or '') + '\n' + (proc.stderr or '')).strip()
    ok = proc.returncode == 0

    # Rafraîchir le cache distant après une copie réussie
    if ok and config['type_distant'] != 'aucun' and config['host']:
        if 'copie' in sortie.lower() or 'remote' in sortie.lower() or 'scp' in sortie.lower():
            _ecrire_cache_distant('ok', '', None, None)

    return ok, (sortie or ('Sauvegarde terminée.' if ok else 'Échec (code %d).' % proc.returncode))[-4000:]


def lister_backups(limit=50):
    """Liste détaillée des sauvegardes locales (la plus récente d'abord)."""
    from datetime import datetime
    from core.supervision import _taille_lisible

    dossier = _dossier_backups()
    resultats = []
    if not dossier.is_dir():
        return resultats
    try:
        fichiers = sorted(dossier.glob('*.backup'),
                          key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return resultats
    for f in fichiers[:limit]:
        try:
            st = f.stat()
        except OSError:
            continue
        mtime = datetime.fromtimestamp(st.st_mtime)
        resultats.append({
            'nom': f.name,
            'taille': st.st_size,
            'taille_lisible': _taille_lisible(st.st_size),
            'date': mtime.strftime('%d/%m/%Y %H:%M'),
        })
    return resultats


def chemin_backup(nom):
    """Chemin absolu d'un backup si le nom est valide, sinon None."""
    nom = (nom or '').strip()
    if not _NOM_BACKUP_RE.match(nom):
        return None
    chemin = (_dossier_backups() / nom).resolve()
    try:
        chemin.relative_to(_dossier_backups().resolve())
    except ValueError:
        return None
    return chemin if chemin.is_file() else None


def supprimer_backup(nom):
    """Supprime un fichier de backup (nom validé). Retourne (ok, message)."""
    chemin = chemin_backup(nom)
    if not chemin:
        return False, "❌ Sauvegarde introuvable ou nom invalide."
    try:
        chemin.unlink()
    except OSError as exc:
        return False, f"❌ Suppression impossible : {exc}"
    return True, f"🗑️ Sauvegarde « {nom} » supprimée."


# ═════════════════════════════════════════════════════════════════════════════
# FRAÎCHEUR DES SAUVEGARDES (alerte > 24h)
# ═════════════════════════════════════════════════════════════════════════════

def dernier_backup():
    """Retourne (chemin, datetime) du backup local le plus récent, sinon None."""
    dossier = _dossier_backups()
    if not dossier.is_dir():
        return None
    try:
        fichiers = sorted(dossier.glob('*.backup'),
                          key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return None
    for f in fichiers:
        try:
            return f, datetime.fromtimestamp(f.stat().st_mtime)
        except OSError:
            continue
    return None


def _duree_lisible(heures):
    """Formate une durée en heures (« 31 h », « 2 j 5 h »)."""
    heures = int(round(heures))
    if heures < 48:
        return f"{heures} h"
    jours = heures // 24
    return f"{jours} j {heures % 24} h"


def _chemin_distant():
    """Chemin UNC du dossier distant (//host/partage) selon la config, ou None
    si aucune destination distante n'est configurée."""
    config = lire_config()
    if config['type_distant'] == 'aucun' or not config['host']:
        return None
    base = (config['remote_dir'] or '').replace('\\', '/').strip('/')
    if not base:
        return None
    return Path(f"//{config['host']}/{base}")


def _lire_cache_distant():
    """Lit le cache du statut distant depuis config.json."""
    config = lire_config()
    return config.get('_distant_cache', None)


def _ecrire_cache_distant(statut, age_libelle='', dernier_nom=None, dernier_date=None):
    """Écrit le cache du statut distant dans config.json."""
    config = lire_config()
    config['_distant_cache'] = {
        'statut': statut,
        'age_libelle': age_libelle,
        'dernier_nom': dernier_nom,
        'dernier_date': dernier_date,
        'timestamp': datetime.now().isoformat(),
    }
    try:
        CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding='utf-8')
    except OSError:
        pass


def etat_distant():
    """État de fraîcheur de la COPIE DISTANTE (partage SMB / serveur SSH).

    Utilise un cache (config.json) pour éviter de tester la connectivité
    à chaque chargement de page (ce qui est lent et sujet aux timeouts).
    Le cache est rafraîchi quand :
      - l'utilisateur clique « Tester la connexion distante »
      - une copie distante est effectuée (backup_db.py)
      - le cache a plus d'1 heure → fait un check live
    """
    dossier = _chemin_distant()
    if not dossier:
        return {'statut': 'non_configure', 'age_libelle': '',
                'dernier_nom': None, 'dernier_date': None}

    # ── Vérifier le cache (valide 1 heure) ──
    cache = _lire_cache_distant()
    if cache and cache.get('timestamp'):
        try:
            ts = datetime.fromisoformat(cache['timestamp'])
            age_cache = (datetime.now() - ts).total_seconds() / 3600
            if age_cache < 1:
                # Cache récent : l'utiliser tel quel
                return {
                    'statut': cache.get('statut', 'indisponible'),
                    'age_libelle': cache.get('age_libelle', ''),
                    'dernier_nom': cache.get('dernier_nom'),
                    'dernier_date': cache.get('dernier_date'),
                }
        except (ValueError, TypeError):
            pass

    # ── Cache absent ou expiré : faire un check live ──
    # ⚠️ Timeout court (3s) pour ne pas bloquer le chargement de la page.
    import socket, threading
    result = {'statut': 'indisponible', 'age_libelle': '',
              'dernier_nom': None, 'dernier_date': None}

    def _check():
        nonlocal result
        try:
            if not dossier.is_dir():
                return
            fichiers = sorted(dossier.glob('*.backup'),
                              key=lambda p: p.stat().st_mtime, reverse=True)
            dernier = None
            for f in fichiers:
                try:
                    dernier = (f, datetime.fromtimestamp(f.stat().st_mtime))
                    break
                except OSError:
                    continue
            if not dernier:
                result = {'statut': 'critique', 'age_libelle': '',
                          'dernier_nom': None, 'dernier_date': None}
                return
            chemin, mtime = dernier
            heures = (datetime.now() - mtime).total_seconds() / 3600
            result = {
                'statut': 'alerte' if heures > SEUIL_ALERTE_HEURES else 'ok',
                'age_libelle': _duree_lisible(heures),
                'dernier_nom': chemin.name,
                'dernier_date': mtime.strftime('%d/%m/%Y %H:%M'),
            }
        except OSError:
            pass

    t = threading.Thread(target=_check, daemon=True)
    t.start()
    t.join(timeout=3)  # Max 3 secondes pour ne pas bloquer

    # Mettre à jour le cache
    _ecrire_cache_distant(
        result['statut'],
        result.get('age_libelle', ''),
        result.get('dernier_nom'),
        result.get('dernier_date'),
    )

    return result


def actualiser_etat_distant():
    """Force le rafraîchissement du cache distant (appelé après test AJAX)."""
    # Supprimer le cache pour forcer un check live
    config = lire_config()
    config.pop('_distant_cache', None)
    try:
        CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding='utf-8')
    except OSError:
        pass
    return etat_distant()


def etat_sauvegardes():
    """État de fraîcheur des sauvegardes LOCALES + DISTANTES.

    Retourne un dict :
      - statut : 'ok' (dernier backup local ≤ SEUIL_ALERTE_HEURES),
                 'alerte' (plus vieux que le seuil),
                 'critique' (aucun backup du tout)
      - heures : âge du dernier backup en heures (float), sinon None
      - age_libelle : « 5 h », « 2 j 3 h »…
      - dernier_nom / dernier_date : infos du dernier fichier
      - distant : dict etat_distant() (fraîcheur de la copie sur le partage)
    """
    dernier = dernier_backup()
    if not dernier:
        local = {
            'statut': 'critique',
            'heures': None,
            'age_libelle': '',
            'dernier_nom': None,
            'dernier_date': None,
            'seuil_heures': SEUIL_ALERTE_HEURES,
        }
    else:
        chemin, mtime = dernier
        heures = (datetime.now() - mtime).total_seconds() / 3600
        local = {
            'statut': 'alerte' if heures > SEUIL_ALERTE_HEURES else 'ok',
            'heures': round(heures, 1),
            'age_libelle': _duree_lisible(heures),
            'dernier_nom': chemin.name,
            'dernier_date': mtime.strftime('%d/%m/%Y %H:%M'),
            'seuil_heures': SEUIL_ALERTE_HEURES,
        }
    local['distant'] = etat_distant()
    return local


def notifier_retard_backup(utilisateur=None):
    """Notifie les administrateurs quand aucun backup récent n'existe.

    Crée une Notification (catégorie SYSTÈME) pour les superutilisateurs —
    ou juste pour `utilisateur` s'il est fourni — visible dans la cloche du
    dashboard avec un lien vers la page Sauvegardes.

    Anti-spam : au maximum une notification par jour et par utilisateur
    (lue ou non). Appelé depuis le dashboard des superusers.
    """
    etat = etat_sauvegardes()

    # ── Construire la liste des problèmes (local + distant) ──
    problemes = []  # [(titre, message, couleur)]
    if etat['statut'] == 'critique':
        problemes.append((
            "Aucune sauvegarde de la base de données",
            "⚠️ Aucun fichier de sauvegarde n'existe dans le dossier backups/. "
            "La base de données n'est protégée par aucune copie de secours.",
            '#e74c3c'))
    elif etat['statut'] == 'alerte':
        problemes.append((
            "Sauvegarde de la base trop ancienne",
            f"⚠️ La dernière sauvegarde locale date de {etat['age_libelle']} "
            f"({etat['dernier_date']}) — seuil d'alerte : {SEUIL_ALERTE_HEURES} h.",
            '#fd7e14'))

    distant = etat.get('distant') or {}
    dst_statut = distant.get('statut')
    if dst_statut == 'critique':
        problemes.append((
            "Aucune copie de sauvegarde distante",
            "⚠️ Aucun fichier .backup n'existe sur le partage de backup distant. "
            "La copie hors site n'est pas assurée.",
            '#e74c3c'))
    elif dst_statut == 'alerte':
        problemes.append((
            "Copie de sauvegarde distante trop ancienne",
            f"⚠️ La dernière copie sur le serveur de backup distant date de "
            f"{distant.get('age_libelle', '?')} ({distant.get('dernier_date', '?')}) "
            f"— seuil d'alerte : {SEUIL_ALERTE_HEURES} h.",
            '#fd7e14'))
    elif dst_statut == 'indisponible':
        problemes.append((
            "Serveur de backup distant inaccessible",
            "⚠️ Le partage de backup distant est injoignable (réseau, machine "
            "éteinte ou identifiants expirés) — la copie hors site échoue.",
            '#e74c3c'))

    if not problemes:
        return []

    from django.contrib.auth import get_user_model
    from accounts.models import Notification
    from django.utils import timezone

    User = get_user_model()
    if utilisateur is not None:
        cibles = [utilisateur]
    else:
        cibles = list(User.objects.filter(is_superuser=True, is_active=True))

    aujourd_hui = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    creees = []
    for u in cibles:
        for titre, message, couleur in problemes:
            # Déjà notifié aujourd'hui pour CE problème ? (lu ou non) → non recréé
            deja = Notification.objects.filter(
                utilisateur=u, titre=titre, date_creation__gte=aujourd_hui,
            ).exists()
            if deja:
                continue
            creees.append(Notification.objects.create(
                utilisateur=u,
                titre=titre,
                message=message,
                type_notif='DANGER',
                categorie='SYSTEME',
                url='/parametres/sauvegardes/',
                icon='fa-database',
                color=couleur,
            ))
    return creees


# ═════════════════════════════════════════════════════════════════════════════
# PLANNING DE SAUVEGARDE AUTOMATIQUE (Task Scheduler Windows / crontab Linux)
# ═════════════════════════════════════════════════════════════════════════════

def _description_planning(config):
    """Retourne une description lisible du planning configuré."""
    mode = config.get('cron_mode', 'desactive')
    h = config.get('cron_hour', '02').zfill(2)
    m = config.get('cron_minute', '00').zfill(2)
    if mode == 'daily':
        return f'Tous les jours à {h}:{m}'
    if mode == 'interval':
        minutes = int(config.get('cron_interval', '60'))
        if minutes < 60:
            return f'Toutes les {minutes} minutes'
        heures = minutes // 60
        reste = minutes % 60
        if reste == 0:
            return f'Toutes les {heures} heures'
        return f'Toutes les {heures}h{reste:02d}'
    if mode == 'weekly':
        jours_raw = config.get('cron_days', '')
        if not jours_raw:
            return 'Hebdomadaire (aucun jour choisi)'
        jours_liste = [label for code, label in JOURS_SEMAINE if code in jours_raw]
        if not jours_liste:
            return 'Hebdomadaire (jours invalides)'
        return f'Les {', '.join(jours_liste)} à {h}:{m}'
    return 'Désactivé'


def appliquer_planning(donnees=None):
    """Crée / met à jour la tâche planifiée selon la config.

    Modes supportés :
      - daily   : tous les jours à HH:MM
      - interval: toutes les X minutes (5-1440)
      - weekly  : jours de la semaine à HH:MM
      - desactive: supprime la tâche

    Si `donnees` est fourni (POST dict), les valeurs sont sauvegardées
    dans config.json AVANT de créer la tâche.
    """
    config = lire_config()

    # Fusionner les données du formulaire si fournies
    if donnees:
        config['cron_mode'] = str(donnees.get('cron_mode', config.get('cron_mode', 'desactive'))).strip()
        config['cron_hour'] = str(donnees.get('cron_hour', config.get('cron_hour', '02'))).strip() or '02'
        config['cron_minute'] = str(donnees.get('cron_minute', config.get('cron_minute', '00'))).strip() or '00'
        config['cron_interval'] = str(donnees.get('cron_interval', config.get('cron_interval', '60'))).strip() or '60'
        # cron_days peut être une liste (checkboxes) ou une chaîne
        days_raw = donnees.get('cron_days', config.get('cron_days', ''))
        if isinstance(days_raw, list):
            config['cron_days'] = ','.join(days_raw)
        else:
            config['cron_days'] = str(days_raw).strip()
        # Sauvegarder immédiatement
        try:
            _dossier_backups().mkdir(parents=True, exist_ok=True)
            CONFIG_PATH.write_text(json.dumps(config, indent=2, ensure_ascii=False), encoding='utf-8')
        except OSError:
            pass

    mode = config.get('cron_mode', 'desactive')
    if mode == 'desactive':
        return _desactiver_planning()

    heure = config.get('cron_hour', '02').zfill(2)
    minute = config.get('cron_minute', '00').zfill(2)
    interval = config.get('cron_interval', '60')
    jours = config.get('cron_days', '')

    # Commande backup_db.py
    python = str(BASE_DIR / 'venv' / 'Scripts' / 'python.exe')
    if not Path(python).is_file():
        python = str(BASE_DIR / 'venv' / 'bin' / 'python')
    script = str(BASE_DIR / 'scripts' / 'backup_db.py')
    log = str(BASE_DIR / 'logs' / 'backup.log')

    if sys.platform.startswith('win'):
        return _schtasks_create(mode, heure, minute, interval, jours, python, script, log)
    else:
        return _crontab_create(mode, heure, minute, interval, jours, python, script, log)


def _desactiver_planning():
    """Supprime la tâche planifiée. Retourne (ok, message)."""
    if sys.platform.startswith('win'):
        import subprocess as sp
        r = sp.run(['schtasks', '/Delete', '/TN', 'NexusERP_Backup', '/F'],
                   capture_output=True, text=True, timeout=30)
        if r.returncode == 0 or 'introuvable' in (r.stderr or '').lower():
            return True, "🗑️ Tâche planifiée NexusERP_Backup supprimée."
        return False, f"❌ Erreur : {r.stderr.strip()[:200]}"
    # Linux : supprimer l'entrée crontab
    try:
        import subprocess as sp
        r = sp.run('crontab -l 2>/dev/null | grep -v NexusERP_Backup | crontab -',
                   shell=True, capture_output=True, text=True, timeout=30)
        return True, "🗑️ Entrée NexusERP_Backup supprimée du crontab."
    except Exception as exc:
        return False, f"❌ {exc}"


def _schtasks_create(mode, heure, minute, interval, jours, python, script, log):
    """Crée la tâche NexusERP_Backup via schtasks (Windows).

    schtasks /TR a une limite de 261 car. : on écrit un .bat dans backups/
    qui contient la vraie commande, et on appelle ce .bat.
    """
    import subprocess as sp
    import os as _os

    # Lire la config pour injecter les paramètres distants dans le .bat
    config = lire_config()
    remote_args = ''
    if config.get('type_distant') != 'aucun' and config.get('host'):
        remote_args = (
            f' --remote-host "{config["host"]}"'
            f' --remote-user "{config["user"]}"'
            f' --remote-dir "{config["remote_dir"]}"'
        )
        if config.get('password'):
            remote_args += f' --remote-password "{config["password"]}"'

    bat_path = _dossier_backups() / 'run_backup.bat'
    bat_lines = ['@echo off']
    bat_lines.append(f'cd /d "{BASE_DIR}"')
    # Établir la connexion SMB si distant configuré
    if remote_args:
        smb_host = config['host']
        smb_user = config['user']
        smb_pass = config.get('password', '')
        remote_dir = config['remote_dir'].replace('\\', '/').strip('/')
        share_name = remote_dir.split('/')[0]
        unc = f'\\\\{smb_host}\\{share_name}'
        # 1. Tenter la connexion SANS mot de passe (partage ouvert / accès réseau)
        bat_lines.append('net use "' + unc + '" >nul 2>&1')
        # 2. Si ça échoue ET qu'un mot de passe est configuré, utiliser cmdkey
        if smb_pass:
            bat_lines.append('if errorlevel 1 (')
            bat_lines.append('    cmdkey /generic:"' + smb_host + '" /user:"' + smb_user + '" /pass:"' + smb_pass + '" >nul 2>&1')
            bat_lines.append('    net use "' + unc + '" >nul 2>&1')
            bat_lines.append(')')
    bat_lines.append(f'"{python}" "{script}" --quiet{remote_args} >> "{log}" 2>&1')
    if remote_args:
        bat_lines.append(f'net use "{unc}" /delete >nul 2>&1')
    bat_content = '\r\n'.join(bat_lines) + '\r\n'
    try:
        bat_path.write_text(bat_content, encoding='utf-8')
    except OSError as exc:
        return False, f"❌ Impossible de créer run_backup.bat : {exc}"

    action = f'cmd.exe /c "{bat_path}"'
    tn = 'NexusERP_Backup'

    sp.run(['schtasks', '/Delete', '/TN', tn, '/F'],
           capture_output=True, timeout=30)

    # Construire les arguments schtasks selon le mode
    if mode == 'daily':
        cmd = ['schtasks', '/Create', '/TN', tn, '/SC', 'daily',
               '/ST', f'{heure}:{minute}', '/F', '/TR', action]
    elif mode == 'interval':
        minutes = max(5, min(1440, int(interval or '60')))
        if minutes < 60:
            cmd = ['schtasks', '/Create', '/TN', tn,
                   '/SC', 'minute', '/MO', str(minutes),
                   '/F', '/TR', action]
        else:
            heures = minutes // 60
            cmd = ['schtasks', '/Create', '/TN', tn,
                   '/SC', 'daily', '/ST', f'{heure}:{minute}',
                   '/RI', str(heures * 60), '/DU', '24:00',
                   '/F', '/TR', action]
    elif mode == 'weekly':
        if not jours:
            return False, "❌ Aucun jour sélectionné."
        day_map = {'lu': 'MON', 'ma': 'TUE', 'me': 'WED', 'je': 'THU',
                   've': 'FRI', 'sa': 'SAT', 'di': 'SUN'}
        schtasks_days = [day_map[j.strip()] for j in jours.split(',')
                         if j.strip() in day_map]
        if not schtasks_days:
            return False, "❌ Jours invalides."
        cmd = ['schtasks', '/Create', '/TN', tn,
               '/SC', 'weekly', '/D', ','.join(schtasks_days),
               '/ST', f'{heure}:{minute}', '/F', '/TR', action]
    else:
        return False, f"❌ Mode inconnu : {mode}"

    # Essayer SYSTEM d'abord, fallback sur l'utilisateur courant
    for ru in ('SYSTEM', _os.environ.get('USERNAME', 'SYSTEM')):
        cmd_try = cmd.copy()
        idx = cmd_try.index('/F')
        cmd_try.insert(idx, '/RU')
        cmd_try.insert(idx + 1, ru)
        r = sp.run(cmd_try, capture_output=True, text=True, timeout=30)
        if r.returncode == 0:
            break
    if r.returncode != 0:
        return False, f"❌ schtasks : {r.stderr.strip()[:200]}"

    desc = _description_planning(lire_config())
    return True, f"✅ Tâche « {tn} » créée — {desc}."


def _crontab_create(mode, heure, minute, interval, jours, python, script, log):
    """Ajoute / met à jour l'entrée crontab NexusERP_Backup (Linux)."""
    import subprocess as sp

    if mode == 'daily':
        cron_expr = f'{minute} {heure} * * *'
    elif mode == 'interval':
        minutes = max(5, min(1440, int(interval or '60')))
        cron_expr = f'*/{minutes} * * * *'
    elif mode == 'weekly':
        day_map = {'lu': '1', 'ma': '2', 'me': '3', 'je': '4',
                   've': '5', 'sa': '6', 'di': '0'}
        nums = [day_map[j.strip()] for j in jours.split(',')
                if j.strip() in day_map]
        if not nums:
            return False, "❌ Jours invalides."
        cron_expr = f'{minute} {heure} * * {','.join(nums)}'
    else:
        return False, f"❌ Mode inconnu : {mode}"

    entry = (f'{cron_expr} cd {BASE_DIR} && venv/bin/python '
             f'scripts/backup_db.py --quiet >> logs/backup.log 2>&1')

    try:
        r = sp.run('crontab -l 2>/dev/null', shell=True, capture_output=True, text=True)
        lignes = [l for l in r.stdout.splitlines()
                  if 'NexusERP_Backup' not in l and 'backup_db.py' not in l]
        lignes.append(entry)
        sp.run('crontab -', input='\n'.join(lignes) + '\n',
               shell=True, capture_output=True, timeout=30)
        return True, f"✅ crontab mis à jour — {_description_planning(lire_config())}"
    except Exception as exc:
        return False, f"❌ {exc}"


def etat_planning():
    """Retourne l'état de la tâche planifiée."""
    config = lire_config()
    mode = config.get('cron_mode', 'desactive')
    desc = _description_planning(config)
    if mode == 'desactive':
        return {'actif': False, 'label': desc, 'prochaine': ''}
    try:
        if sys.platform.startswith('win'):
            import subprocess as sp
            r = sp.run(['schtasks', '/Query', '/TN', 'NexusERP_Backup', '/FO', 'LIST'],
                       capture_output=True, text=True, timeout=15)
            if r.returncode != 0:
                return {'actif': False, 'label': desc,
                        'prochaine': 'Tâche introuvable — clique « Appliquer »'}
            return {'actif': True, 'label': desc, 'prochaine': ''}
        return {'actif': True, 'label': desc, 'prochaine': 'Crontab Linux'}
    except Exception:
        return {'actif': False, 'label': desc, 'prochaine': ''}


# ═════════════════════════════════════════════════════════════════════════════
# UPLOAD DE FICHIER .backup DEPUIS SUPPORT EXTERNE
# ═════════════════════════════════════════════════════════════════════════════

# Taille max upload (500 Mo)
UPLOAD_MAX_SIZE = 500 * 1024 * 1024

def uploadeer_backup(fichier_django):
    """Reçoit un fichier UploadFile Django, le valide et le sauvegarde
    dans backups/ avec un nom horodaté.

    Retourne (ok, message, nom_fichier).
    """
    if not fichier_django or not fichier_django.name:
        return False, "❌ Aucun fichier sélectionné.", ''

    nom_original = fichier_django.name
    if not nom_original.endswith('.backup'):
        return False, "❌ Le fichier doit avoir l'extension .backup (pg_dump).", ''

    if fichier_django.size > UPLOAD_MAX_SIZE:
        taille_mo = fichier_django.size / (1024 * 1024)
        return False, f"❌ Fichier trop volumineux ({taille_mo:.0f} Mo). Taille max : 500 Mo.", ''

    # Nom horodaté : backup_upload_YYYYMMDDHHMMSS.backup
    ts = datetime.now().strftime('%Y%m%d%H%M%S')
    nom_secure = f'backup_upload_{ts}.backup'
    dest = _dossier_backups() / nom_secure

    try:
        _dossier_backups().mkdir(parents=True, exist_ok=True)
        with open(dest, 'wb') as f:
            for chunk in fichier_django.chunks():
                f.write(chunk)
    except OSError as exc:
        return False, f"❌ Erreur d'écriture : {exc}", ''

    taille_mo = dest.stat().st_size / (1024 * 1024)
    return True, f"✅ Fichier « {nom_original} » uploadé ({taille_mo:.1f} Mo) → {nom_secure}.", nom_secure


def valider_backup_fichier(chemin):
    """Vérifie qu'un fichier .backup est un dump pg_restore valide.
    Retourne (ok, message, nb_entrees).
    """
    if not chemin.is_file():
        return False, "Fichier introuvable.", 0

    sys.path.insert(0, str(BASE_DIR / 'scripts'))
    try:
        from backup_db import db_params, find_pg_tool, load_env
        load_env()
    except Exception:
        return False, "Erreur d'import du module backup.", 0

    params = db_params()
    candidates = find_pg_tool('pg_restore')
    if not candidates:
        return False, "pg_restore introuvable.", 0

    env = dict(__import__('os').environ)
    if params.get('password'):
        env['PGPASSWORD'] = params['password']
    r = subprocess.run([str(candidates[0]), '--list', str(chemin)],
                       capture_output=True, text=True, env=env, timeout=60)
    if r.returncode != 0:
        return False, f"Fichier invalide : {r.stderr.strip()[:200]}", 0

    nb = len([l for l in r.stdout.splitlines() if l.strip() and not l.startswith(';')])
    return True, f"Dump valide — {nb} entrées.", nb


# ═════════════════════════════════════════════════════════════════════════════
# ANALYSE DE SAUVEGARDE (PREVIEW AVANT RESTAURATION)
# ═════════════════════════════════════════════════════════════════════════════

def analyser_backup(nom):
    """Analyse un fichier .backup et retourne un preview détaillé.

    Retourne un dict avec :
    - taille_fichier: taille en octets
    - nb_tables: nombre de tables dans le dump
    - tables: liste de dicts {nom, nb_entrees, type}
    - stats_actuelles: dict {table: nb_lignes} de la base actuelle
    - resume: texte résumé
    """
    chemin = chemin_backup(nom)
    if not chemin or not chemin.is_file():
        return None, "Fichier introuvable."

    # Taille du fichier
    taille_octets = chemin.stat().st_size
    taille_mo = taille_octets / (1024 * 1024)

    sys.path.insert(0, str(BASE_DIR / 'scripts'))
    try:
        from backup_db import db_params, find_pg_tool, load_env
        load_env()
    except Exception:
        return None, "Erreur de configuration de la base."

    params = db_params()
    pg_restore_candidates = find_pg_tool('pg_restore')
    if not pg_restore_candidates:
        return None, "pg_restore introuvable."

    env = dict(__import__('os').environ)
    if params.get('password'):
        env['PGPASSWORD'] = params['password']

    # pg_restore --list pour analyser le contenu du dump
    r = subprocess.run(
        [str(pg_restore_candidates[0]), '--list', str(chemin)],
        capture_output=True, text=True, env=env, timeout=120)
    if r.returncode not in (0, 1):  # 1 = warnings mineurs
        return None, f"Fichier dump invalide : {r.stderr.strip()[:300]}"

    # Parser la sortie pg_restore --list
    # Format : "OID; DUMP_ID DB_ID TYPE SCHEMA NAME [OWNER]"
    # Ex : "374; 1259 18555 TABLE public accounts_auditconnexion nexuserp_db"
    # Types connus : TABLE, SEQUENCE, INDEX, FUNCTION, TRIGGER, etc.
    _TYPES_TABLE = {'TABLE'}
    _TYPES_INDEX = {'INDEX'}
    _TYPES_IGNORE = {'SEQUENCE', 'SEQUENCE SET', 'ACL', 'COMMENT',
                     'FUNCTION', 'TRIGGER', 'CONSTRAINT', 'RULE',
                     'TYPE', 'DOMAIN', 'AGGREGATE', 'OPERATOR',
                     'CAST', 'EXTENSION', 'COLLATION', 'STATISTICS'}
    tables_dump = []
    nb_total_entrees = 0
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith(';'):
            continue
        if ';' not in line:
            continue
        try:
            # Séparer avant et après le premier ';' (OID; reste)
            _, rest = line.split(';', 1)
            rest = rest.strip()
            parts = rest.split()
            if len(parts) < 5:
                nb_total_entrees += 1
                continue
            # DUMP_ID DB_ID TYPE ...
            obj_type = parts[2]
            # Gérer les types multi-mots (ex: "SEQUENCE SET")
            if obj_type == 'SEQUENCE' and len(parts) > 3 and parts[3] == 'SET':
                obj_type = 'SEQUENCE SET'
                schema_idx = 4
            else:
                schema_idx = 3
            if schema_idx >= len(parts):
                nb_total_entrees += 1
                continue
            schema = parts[schema_idx]
            # Le nom est le dernier élément significatif (avant OWNER éventuel)
            # Pour TABLE : "TABLE public nom_table owner" -> nom = parts[-2] ou parts[-1]
            # On prend le premier après le schéma qui n'est pas un mot-clé connu
            obj_name = None
            for i in range(schema_idx + 1, len(parts)):
                candidate = parts[i]
                # Ignorer les noms qui sont clairement des schémas ou des mots-clés
                if candidate in ('public', '-', 'pg_database'):
                    continue
                obj_name = candidate
                break
            if obj_name and obj_type in _TYPES_TABLE:
                tables_dump.append({'nom': obj_name, 'type': 'TABLE'})
            elif obj_name and obj_type in _TYPES_INDEX:
                tables_dump.append({'nom': obj_name, 'type': 'INDEX'})
            nb_total_entrees += 1
        except (ValueError, IndexError):
            nb_total_entrees += 1

    # Stats de la base actuelle
    stats_actuelles = {}
    try:
        import psycopg2
        conn = psycopg2.connect(
            dbname=params['name'], user=params['user'],
            password=params.get('password', ''),
            host=params['host'], port=params['port'])
        cur = conn.cursor()
        # Tables dans la base actuelle
        cur.execute("""
            SELECT tablename FROM pg_tables
            WHERE schemaname = 'public'
            ORDER BY tablename
        """)
        tables_actuelles = {row[0]: 0 for row in cur.fetchall()}
        # Compter les lignes de chaque table
        for tbl in tables_actuelles:
            try:
                cur.execute(f'SELECT COUNT(*) FROM "{tbl}"')
                tables_actuelles[tbl] = cur.fetchone()[0]
            except Exception:
                pass
        stats_actuelles = tables_actuelles
        cur.close()
        conn.close()
    except Exception:
        pass  # Si pas possible, on continue sans stats

    # Identifier les tables affectées
    tables_affectees = []
    tables_nouvelles = []
    tables_perdues = []

    noms_dump = {t['nom'] for t in tables_dump if t['type'] == 'TABLE'}
    noms_actuels = set(stats_actuelles.keys())

    for t in tables_dump:
        if t['type'] != 'TABLE':
            continue
        nom_t = t['nom']
        if nom_t in noms_actuels:
            tables_affectees.append({
                'nom': nom_t,
                'lignes_actuelles': stats_actuelles.get(nom_t, 0),
            })
        else:
            tables_nouvelles.append(nom_t)

    tables_perdues = list(noms_actuels - noms_dump)

    resume = (
        f"Taille : {taille_mo:.1f} Mo — "
        f"{len(tables_affectees)} tables seront remplacées, "
        f"{len(tables_nouvelles)} nouvelles tables seront créées, "
        f"{len(tables_perdues)} tables existantes seront supprimées."
    )

    return {
        'taille_fichier': taille_octets,
        'taille_lisible': f"{taille_mo:.1f} Mo",
        'nb_tables': len(tables_affectees) + len(tables_nouvelles),
        'nb_entrees_dump': nb_total_entrees,
        'tables_affectees': tables_affectees,
        'tables_nouvelles': tables_nouvelles,
        'tables_perdues': tables_perdues,
        'stats_actuelles': stats_actuelles,
        'resume': resume,
    }, None


# ═════════════════════════════════════════════════════════════════════════════
# RESTAURATION DEPUIS L'INTERFACE
# ═════════════════════════════════════════════════════════════════════════════

def restaurer_backup(nom, confirmation):
    """Restaure un fichier .backup dans la base actuelle.

    ⚠️ DÉSTRUCTIF : le contenu actuel de la base est remplacé.
    `confirmation` doit être 'RESTAURER' pour autoriser l'opération.

    Retourne (ok, message).
    """
    if confirmation != 'RESTAURER':
        return False, "❌ Confirmation incorrecte — tapez RESTAURER pour confirmer."

    chemin = chemin_backup(nom)
    if not chemin:
        return False, "❌ Sauvegarde introuvable ou nom invalide."

    sys.path.insert(0, str(BASE_DIR / 'scripts'))
    from backup_db import db_params, find_pg_tool, load_env
    load_env()
    params = db_params()

    pg_restore_candidates = find_pg_tool('pg_restore')
    if not pg_restore_candidates:
        return False, "❌ pg_restore introuvable (PATH, PGBIN)."
    pg_restore = pg_restore_candidates[0]

    # Vérifier l'intégrité du dump
    env = dict(__import__('os').environ)
    if params['password']:
        env['PGPASSWORD'] = params['password']
    r = subprocess.run([str(pg_restore), '--list', str(chemin)],
                       capture_output=True, text=True, env=env)
    if r.returncode != 0:
        return False, f"❌ Fichier dump invalide : {r.stderr.strip()[:300]}"
    nb_entrees = len([l for l in r.stdout.splitlines() if l.strip() and not l.startswith(';')])

    # Fermer les connexions Django à la base cible
    from django.db import connection
    connection.close()

    # Restaurer
    cmd = [
        str(pg_restore),
        '-h', params['host'], '-p', str(params['port']),
        '-U', params['user'], '-d', params['name'],
        '--clean', '--if-exists', '--no-owner', '--verbose',
        str(chemin),
    ]
    if params.get('sslmode'):
        cmd += ['--sslmode', params['sslmode']]

    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              timeout=TIMEOUT_SAUVEGARDE, env=env)
    except subprocess.TimeoutExpired:
        return False, "⏱ Restauration interrompue (timeout)."
    except OSError as exc:
        return False, f"❌ {exc}"

    # pg_restore retourne 1 même pour des warnings mineurs — on considère
    # que c'est un succès si le fichier était valide (déjà vérifié).
    sortie = (proc.stderr or proc.stdout or '')[-2000:]
    if proc.returncode == 0:
        return True, (
            f"✅ Restauration terminée — {nb_entrees} entrées restaurées "
            f"depuis {nom}. La base a été remplacée."
        )
    elif proc.returncode == 1:
        # Vérifier si des tables ont été restaurées (warnings = OK)
        if any(m in sortie.lower() for m in ['pg_restore: done', 'warning']):
            return True, (
                f"⚠️ Restauration terminée avec warnings — {nb_entrees} entrées. "
                f"La base a été restaurée (vérifier les logs pour les détails)."
            )
        return False, f"❌ Restauration échouée (code 1) :\n{sortie[-800:]}"
    else:
        return False, f"❌ Restauration échouée (code {proc.returncode}) :\n{sortie[-800:]}"
