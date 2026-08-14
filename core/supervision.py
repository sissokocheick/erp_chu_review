# -*- coding: utf-8 -*-
"""
Aides pour le tableau de bord de supervision (core/views.supervision) :
état des sauvegardes PostgreSQL et erreurs récentes dans les logs.

Le endpoint /health/ (core/health.py) couvre la disponibilité temps réel ;
ce module ajoute la visibilité *historique* : sauvegardes et erreurs.
"""
import re
from datetime import datetime
from pathlib import Path

from django.conf import settings

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
    """Formate une taille en octets (Ko/Mo)."""
    if octets < 1024:
        return f"{octets} o"
    if octets < 1024 * 1024:
        return f"{octets / 1024:.0f} Ko"
    return f"{octets / (1024 * 1024):.1f} Mo"
