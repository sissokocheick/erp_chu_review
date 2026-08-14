#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Restauration d'une sauvegarde PostgreSQL (.backup créé par backup_db.py).

Usage :
    python scripts/restore_db.py backups/chu_angre_db_20260814120000.backup
    python scripts/restore_db.py <backup> --dry-run     # vérifie l'intégrité, ne restaure pas
    python scripts/restore_db.py <backup> --yes         # confirme sans prompt
    python scripts/restore_db.py <backup> --target-db chu_angre_db

Précautions :
  - DESTRUCTIF : le contenu actuel de la base cible est remplacé
    (--clean --if-exists dans pg_restore). Une confirmation est demandée
    sauf avec --yes.
  - L'intégrité du fichier est vérifiée avant restauration
    (pg_restore --list) — un fichier illisible stoppe le script.
  - Les paramètres de connexion viennent de l'environnement / .env
    (mêmes règles que backup_db.py et config/settings.py).
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

from backup_db import load_env, db_params, find_pg_tool  # noqa: E402


def find_pg_restore():
    return find_pg_tool('pg_restore')


def list_dump(pg_restore, backup_path, params):
    """Vérifie l'intégrité du dump : pg_restore --list doit réussir."""
    env = dict(os.environ)
    if params['password']:
        env['PGPASSWORD'] = params['password']
    cmd = [str(pg_restore), '--list', str(backup_path)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    except OSError as exc:
        return False, f"{pg_restore} : {exc}"
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout).strip()[-800:]
    return True, proc.stdout


def build_restore_cmd(pg_restore, backup_path, params, target_db):
    cmd = [
        str(pg_restore),
        '-h', params['host'], '-p', str(params['port']),
        '-U', params['user'], '-d', target_db,
        '--clean', '--if-exists', '--no-owner', '--verbose',
        str(backup_path),
    ]
    if params['sslmode']:
        cmd += ['--sslmode', params['sslmode']]
    return cmd


def main():
    # Console Windows (cp1252) : force UTF-8 avec remplacement pour ne jamais
    # planter en affichant la sortie de pg_restore (accents, em-dash, …).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

    ap = argparse.ArgumentParser(description="Restauration PostgreSQL")
    ap.add_argument('backup', help="Fichier .backup à restaurer (ex: backups/xxx.backup)")
    ap.add_argument('--target-db', default=None,
                    help="Base cible (défaut : DB_NAME / DATABASE_URL de l'environnement)")
    ap.add_argument('--yes', action='store_true', help="Confirmer sans demande")
    ap.add_argument('--dry-run', action='store_true',
                    help="Vérifie l'intégrité et affiche la commande, sans restaurer")
    args = ap.parse_args()

    load_env()
    params = db_params()
    backup_path = Path(args.backup)
    if not backup_path.is_absolute():
        backup_path = BASE_DIR / backup_path
    if not backup_path.is_file():
        print(f"ERR : fichier de sauvegarde introuvable : {backup_path}", file=sys.stderr)
        return 1

    target_db = args.target_db or params['name']
    if not target_db:
        print("ERR : base cible non définie (--target-db ou DB_NAME/DATABASE_URL)", file=sys.stderr)
        return 1

    candidates = find_pg_restore()
    if not candidates:
        print('ERR : pg_restore introuvable (PATH, PGBIN, dossiers PostgreSQL).',
              file=sys.stderr)
        return 1
    pg_restore = candidates[0]

    # ── 1. Vérification d'intégrité (pg_restore --list) ──
    print(f">> Vérification d'intégrité de {backup_path.name} …")
    ok, output = list_dump(pg_restore, backup_path, params)
    if not ok:
        print(f"ERR : le fichier n'est pas un dump valide.\n{output}", file=sys.stderr)
        return 1
    lines = [l for l in output.splitlines() if l.strip() and not l.startswith(';')]
    print(f"OK  : dump valide — {len(lines)} entrées (tables, index, données…)")
    if args.dry_run:
        print("\n--dry-run : aperçu des entrées (10 max) --")
        for l in lines[:10]:
            print(f"   {l}")
        print("\nCommande qui serait exécutée (sans --dry-run) :")
        print('   ' + ' '.join(build_restore_cmd(pg_restore, backup_path, params, target_db)))
        print("\n(dry-run) rien n'a été modifié.")
        return 0

    # ── 2. Confirmation ──
    print(f"\n⚠️  DESTRUCTIF : le contenu actuel de la base '{target_db}' "
          f"({params['host']}:{params['port']}) sera REMPLACÉ par le dump "
          f"{backup_path.name} ({backup_path.stat().st_size / 1024:.0f} Ko).")
    if not args.yes:
        try:
            answer = input("Continuer ? (taper 'OUI' pour confirmer) : ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nRestauration annulée.")
            return 2
        if answer.upper() != 'OUI':
            print("Restauration annulée.")
            return 2

    # ── 3. Restauration ──
    cmd = build_restore_cmd(pg_restore, backup_path, params, target_db)
    env = dict(os.environ)
    if params['password']:
        env['PGPASSWORD'] = params['password']
    print(f">> Restauration de {backup_path.name} vers '{target_db}' …")
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    except OSError as exc:
        print(f"ERR : {exc}", file=sys.stderr)
        return 1
    if proc.returncode != 0:
        print(f"ERR : restauration échouée (code {proc.returncode}).",
              file=sys.stderr)
        tail = (proc.stderr or proc.stdout).strip()[-1500:]
        print(tail, file=sys.stderr)
        return 1

    print("OK  : restauration terminée.")
    return 0


if __name__ == '__main__':
    sys.exit(main())
