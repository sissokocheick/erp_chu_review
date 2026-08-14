# -*- coding: utf-8 -*-
"""
Aides pour le tableau de bord de supervision (core/views.supervision) :
état des sauvegardes PostgreSQL et erreurs récentes dans les logs.

Le endpoint /health/ (core/health.py) couvre la disponibilité temps réel ;
ce module ajoute la visibilité *historique* : sauvegardes et erreurs.
"""
import re
import shutil
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.db import connection

# Lignes de log considérées comme des erreurs (niveaux + exceptions).
# ⚠️ Pas de \b final : il échoue après ')' ou ':' (caractères non-mots) —
# on s'appuie sur le \b initial + le mot complet.
_PATTERN_ERREUR = re.compile(
    r'\b(ERROR|CRITICAL|FATAL|Traceback|IntegrityError|OperationalError|'
    r'ProgrammingError|SynchronousOnlyOperation)\b',
    re.IGNORECASE,
)
# Extension des sauvegardes produites par scripts/backup_db.py
_EXT_BACKUP = '.backup'


def lister_sauvegardes(limit=10):
    """Retourne les N sauvegardes les plus récentes (nom, taille, date, âge)."""
    dossier = Path(settings.BASE_DIR) / 'backups'
    resultats = []
    if dossier.is_dir():
        try:
            fichiers = sorted(dossier.glob(f'*{_EXT_BACKUP}'), key=lambda p: p.stat().st_mtime, reverse=True)
        except OSError:
            fichiers = []
        for f in fichiers[:limit]:
            try:
                st = f.stat()
                taille = st.st_size
                mtime = datetime.fromtimestamp(st.st_mtime)
            except OSError:
                continue
            age = (datetime.now() - mtime)
            jours = age.days
            heures = int(age.seconds // 3600)
            minutes = int((age.seconds % 3600) // 60)
            if jours > 0:
                libelle_age = f"{jours} j {heures} h"
            elif heures > 0:
                libelle_age = f"{heures} h {minutes} min"
            else:
                libelle_age = f"{minutes} min"
            resultats.append({
                'nom': f.name,
                'taille': taille,
                'taille_lisible': _taille_lisible(taille),
                'date': mtime.strftime('%d/%m/%Y %H:%M'),
                'age': libelle_age,
            })
    return resultats


def lister_erreurs_logs(limit=50, max_lignes_par_fichier=3000):
    """Dernières lignes d'erreur des fichiers logs/*.log (ordre chronologique global).

    Lit au plus `max_lignes_par_fichier` lignes de la fin de chaque fichier
    (les logs sont append-only : les erreurs récentes sont en bas).
    """
    dossier = Path(settings.BASE_DIR) / 'logs'
    erreurs = []
    if not dossier.is_dir():
        return erreurs
    try:
        fichiers = sorted(dossier.glob('*.log'))
    except OSError:
        return erreurs

    for f in fichiers:
        try:
            lignes = f.read_text(encoding='utf-8', errors='replace').splitlines()[-max_lignes_par_fichier:]
        except OSError:
            continue
        for ligne in lignes:
            if _PATTERN_ERREUR.search(ligne):
                erreurs.append({
                    'fichier': f.name,
                    'texte': ligne.strip()[:400],
                })
    # Les erreurs les plus récentes en premier : on trie par ordre inverse
    # d'apparition dans la concaténation (fichiers triés, lignes en ordre).
    erreurs.reverse()
    return erreurs[:limit]


def _taille_lisible(octets):
    """Formate une taille en octets (Ko/Mo/Go)."""
    if octets < 1024:
        return f"{octets} o"
    if octets < 1024 * 1024:
        return f"{octets / 1024:.0f} Ko"
    if octets < 1024 * 1024 * 1024:
        return f"{octets / (1024 * 1024):.1f} Mo"
    return f"{octets / (1024 * 1024 * 1024):.1f} Go"


def taille_base():
    """Taille de la base de données (octets), indépendante du moteur.

    PostgreSQL : pg_database_size(current_database()).
    SQLite : fichier sur disque, sinon page_count * page_size (base en mémoire).
    """
    moteur = connection.vendor
    try:
        if moteur == 'postgresql':
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_database_size(current_database())')
                octets = cursor.fetchone()[0]
        elif moteur == 'sqlite':
            with connection.cursor() as cursor:
                cursor.execute('PRAGMA page_count')
                pages = cursor.fetchone()[0]
                cursor.execute('PRAGMA page_size')
                taille_page = cursor.fetchone()[0]
            octets = pages * taille_page
        else:
            return None
    except Exception:  # noqa: BLE001 — une métrique ne doit jamais casser la page
        return None
    return octets


def usage_disque():
    """Usage disque du système de fichiers + tailles des dossiers clés."""
    try:
        total, utilise, libre = shutil.disk_usage(str(settings.BASE_DIR))
    except OSError:
        return None
    dossiers = {}
    for nom in ('media', 'logs', 'backups', 'staticfiles'):
        p = Path(settings.BASE_DIR) / nom
        if p.is_dir():
            try:
                dossiers[nom] = sum(
                    f.stat().st_size for f in p.rglob('*') if f.is_file()
                )
            except OSError:
                dossiers[nom] = None
        else:
            dossiers[nom] = None
    pourcentage = round(utilise / total * 100, 1) if total else 0
    return {
        'total': total,
        'total_lisible': _taille_lisible(total),
        'libre': libre,
        'libre_lisible': _taille_lisible(libre),
        'utilise': utilise,
        'utilise_lisible': _taille_lisible(utilise),
        'pourcentage': pourcentage,
        'dossiers': dossiers,
    }


_PATTERN_REQUETE_LENTE = re.compile(r'\((\d+\.\d+)\)\s+(.*)$')


def lister_requetes_lentes(limit=20, fichier=None):
    """Dernières requêtes lentes du fichier logs/slow-queries.log.

    Chaque ligne (logger django.db.backends) a la forme
    "[date] DEBUG (0.512) SELECT …; args=…; alias=default". On extrait la
    durée en ms et le SQL (les args sont retirées : elles peuvent contenir
    des données). La plus récente en premier.
    """
    fichier = fichier or (Path(settings.BASE_DIR) / 'logs' / 'slow-queries.log')
    resultats = []
    if not fichier.is_file():
        return resultats
    try:
        lignes = fichier.read_text(encoding='utf-8', errors='replace').splitlines()
    except OSError:
        return resultats
    for ligne in lignes:
        m = _PATTERN_REQUETE_LENTE.search(ligne)
        if not m:
            continue
        secondes = float(m.group(1))
        sql = m.group(2)
        # Retire "; args=…" (données potentiellement sensibles) et tronque
        if '; args=' in sql:
            sql = sql.split('; args=', 1)[0]
        resultats.append({
            'ms': int(round(secondes * 1000)),
            'sql': sql.strip()[:400],
        })
    resultats.reverse()  # la plus récente en premier
    return resultats[:limit]
