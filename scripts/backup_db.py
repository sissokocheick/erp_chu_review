#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Sauvegarde PostgreSQL (pg_dump) avec rétention graduée.

Usage :
    python scripts/backup_db.py                          # sauvegarde + rétention
    python scripts/backup_db.py --dir /mnt/backups       # dossier cible
    python scripts/backup_db.py --keep-days 7 --keep-weeks 8 --keep-months 12
    python scripts/backup_db.py --dry-run                # simule sans rien créer/supprimer
    python scripts/backup_db.py --quiet                  # sortie minimale (cron)

Les paramètres de connexion viennent de l'environnement (ou d'un .env à la
racine) : DATABASE_URL, sinon DB_NAME/DB_USER/DB_PASSWORD/DB_HOST/DB_PORT
(mêmes défauts que config/settings.py). pg_dump est cherché automatiquement
(PATH, PGBIN, dossiers d'installation PostgreSQL Windows/Linux/macOS) en
préférant la version la plus récente.

Rétention graduée :
  - backups des N derniers jours : conservés (défaut 7)
  - au-delà : le PLUS ANCIEN backup de chaque semaine ISO des N dernières
    semaines (défaut 8)
  - encore au-delà : le plus ancien backup de chaque mois des N derniers mois
    (défaut 12)
  - le reste est supprimé (jamais avant une sauvegarde réussie).
"""
import argparse
import datetime as dt
import glob
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


# ── Chargement du .env (sans écraser l'environnement) ──────────────────────
def load_env():
    env_file = BASE_DIR / '.env'
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding='utf-8').splitlines():
        line = raw.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        line = re.sub(r'^export\s+', '', line)
        key, _, value = line.partition('=')
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value


# ── Résolution des paramètres de connexion ─────────────────────────────────
def db_params():
    url = os.environ.get('DATABASE_URL')
    if url:
        try:
            import dj_database_url
            cfg = dj_database_url.parse(url)
        except Exception:
            cfg = {}
        return {
            'name': cfg.get('NAME', 'postgres'),
            'user': cfg.get('USER', 'postgres'),
            'password': cfg.get('PASSWORD', ''),
            'host': cfg.get('HOST', 'localhost'),
            'port': cfg.get('PORT', '5432'),
            'sslmode': (cfg.get('OPTIONS') or {}).get('sslmode'),
        }
    return {
        'name': os.environ.get('DB_NAME', 'chu_angre_db'),
        'user': os.environ.get('DB_USER', 'postgres'),
        'password': os.environ.get('DB_PASSWORD', ''),
        'host': os.environ.get('DB_HOST', 'localhost'),
        'port': os.environ.get('DB_PORT', '5432'),
        'sslmode': None,
    }


# ── Découverte des outils PostgreSQL (pg_dump / pg_restore) ────────────────
def find_pg_tool(tool):
    """Retourne la liste des chemins candidats pour `tool` (pg_dump, pg_restore…),
    la version la plus récente d'abord (gère les installations multiples)."""
    candidates = []
    pgb = os.environ.get('PGBIN')
    if pgb:
        candidates.append(Path(pgb) / tool)
    found = shutil.which(tool)
    if found:
        candidates.append(Path(found))

    patterns = []
    if sys.platform.startswith('win'):
        patterns = [rf'C:\Program Files\PostgreSQL\*\bin\{tool}.exe']
    elif sys.platform.startswith('darwin'):
        patterns = [rf'/opt/homebrew/opt/postgresql*/bin/{tool}',
                    rf'/usr/local/opt/postgresql*/bin/{tool}']
    else:
        patterns = [rf'/usr/lib/postgresql/*/bin/{tool}',
                    rf'/usr/pgsql-*/bin/{tool}']
    for pattern in patterns:
        try:
            for p in glob.glob(pattern):
                candidates.append(Path(p))
        except Exception:
            pass

    # Déduplique et trie : version la plus récente d'abord
    seen, unique = set(), []
    for p in candidates:
        key = str(p).lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(p)

    def version_key(p):
        m = re.search(r'(\d+)', str(p).replace('\\', '/').split('bin/')[0])
        return int(m.group(1)) if m else 0
    unique.sort(key=version_key, reverse=True)
    return unique


def find_pg_dump():
    """Chemins candidats pour pg_dump (version la plus récente d'abord)."""
    return find_pg_tool('pg_dump')


# ── Rétention graduée ──────────────────────────────────────────────────────
NAME_RE = re.compile(r'^(?P<prefix>.+?)_(?P<ts>\d{14})\.backup$')


def list_backups(directory):
    """Retourne [(chemin, datetime)] pour les backups au format attendu."""
    result = []
    for path in directory.iterdir():
        if not path.is_file():
            continue
        m = NAME_RE.match(path.name)
        if not m:
            continue
        try:
            ts = dt.datetime.strptime(m.group('ts'), '%Y%m%d%H%M%S')
        except ValueError:
            continue
        result.append((path, ts))
    return result


def retention_keep(files, keep_days, keep_weeks, keep_months, now):
    """Ensemble des chemins à conserver selon la politique graduée."""
    keep = set()
    today = now.date()

    # 1) Backup récents
    for path, ts in files:
        if (today - ts.date()).days <= keep_days:
            keep.add(path)

    # 2) Le plus ancien de chaque semaine ISO (dernières keep_weeks semaines)
    for w in range(keep_weeks + 1):
        week_start = today - dt.timedelta(days=today.weekday(), weeks=w)
        target = week_start.isocalendar()[:2]
        oldest = None
        for path, ts in files:
            if ts.date().isocalendar()[:2] == target and (today - ts.date()).days > keep_days:
                if oldest is None or ts < oldest[1]:
                    oldest = (path, ts)
        if oldest:
            keep.add(oldest[0])

    # 3) Le plus ancien de chaque mois (derniers keep_months mois)
    year, month = today.year, today.month
    for m in range(keep_months + 1):
        yy, mm = year, month - m
        while mm <= 0:
            yy -= 1
            mm += 12
        oldest = None
        for path, ts in files:
            if (ts.year, ts.month) == (yy, mm) and (today - ts.date()).days > keep_days:
                if oldest is None or ts < oldest[1]:
                    oldest = (path, ts)
        if oldest:
            keep.add(oldest[0])

    return keep


# ── Sauvegarde ─────────────────────────────────────────────────────────────
def run_backup(pg_dump, params, dest, quiet, dry_run):
    env = dict(os.environ)
    if params['password']:
        env['PGPASSWORD'] = params['password']
    cmd = [
        str(pg_dump), '-h', params['host'], '-p', str(params['port']),
        '-U', params['user'], '-d', params['name'], '-Fc', '-f', str(dest),
    ]
    if params['sslmode']:
        cmd += ['--sslmode', params['sslmode']]
    if dry_run:
        return True, ' '.join(cmd)
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, env=env)
    except OSError as exc:
        return False, f"{pg_dump} : {exc}"
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout).strip()[-800:]
    return True, ''


def copy_to_remote(local_path, host, user, remote_dir, quiet, dry_run, password=''):
    """Copie le backup local vers un serveur distant via SSH/SCP ou SMB."""
    # 1. Essayer SCP d'abord (Linux)
    remote_path = f'{user}@{host}:{remote_dir}/'
    cmd = ['scp', '-o', 'StrictHostKeyChecking=no', '-o', 'ConnectTimeout=5',
            str(local_path), remote_path]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if proc.returncode == 0:
            if not quiet:
                print(f"OK  : copie SCP vers {remote_path}{local_path.name}")
            return True
    except (OSError, subprocess.TimeoutExpired):
        pass

    # 2. Fallback : copie locale via montage SMB/UNC (Windows ou Linux)
    # Stocker les identifiants via cmdkey si mot de passe fourni (Windows)
    if password and sys.platform.startswith('win'):
        try:
            subprocess.run(['cmdkey', f'/generic:{host}', f'/user:{user}', f'/pass:{password}'],
                           capture_output=True, timeout=10)
        except Exception:
            pass
    # Construire le chemin UNC pour Windows : //HOST/SHARE/path
    unc_base = remote_dir.replace('\\', '/')
    if unc_base.startswith('/'):
        unc_base = unc_base[1:]
    unc_path = Path(f'//{host}/{unc_base}')
    try:
        unc_path.mkdir(parents=True, exist_ok=True)
        dest_unc = unc_path / local_path.name
        import shutil as _shutil
        _shutil.copy2(str(local_path), str(dest_unc))
        if not quiet:
            print(f"OK  : copie vers {dest_unc}")
        return True
    except Exception as exc:
        print(f"ERR : copie distante echouee (SCP et SMB) : {exc}", file=sys.stderr)
        return False


def main():
    # Console Windows (cp1252) : force UTF-8 avec remplacement pour ne jamais
    # planter à l'affichage (accents, em-dash, …).
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

    ap = argparse.ArgumentParser(description="Sauvegarde PostgreSQL + rétention")
    ap.add_argument('--dir', default=os.environ.get('BACKUP_DIR', 'backups'))
    ap.add_argument('--keep-days', type=int, default=7)
    ap.add_argument('--keep-weeks', type=int, default=8)
    ap.add_argument('--keep-months', type=int, default=12)
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    # Options de copie distante
    ap.add_argument('--remote-host', default=os.environ.get('BACKUP_REMOTE_HOST'),
                     help='IP ou hostname du serveur distant (ou BACKUP_REMOTE_HOST)')
    ap.add_argument('--remote-user', default=os.environ.get('BACKUP_REMOTE_USER', 'backup'),
                     help='User SSH du serveur distant (defaut: backup)')
    ap.add_argument('--remote-dir', default=os.environ.get('BACKUP_REMOTE_DIR', '/home/backup/backups'),
                     help='Dossier distant pour les backups')
    ap.add_argument('--remote-password', default=os.environ.get('BACKUP_REMOTE_PASSWORD', ''),
                     help='Mot de passe du compte distant (pour cmdkey/SMB)')
    args = ap.parse_args()

    load_env()
    params = db_params()
    if not params['name'] or not params['user']:
        print('ERR : DB_NAME/DB_USER non définis (voir .env.example)', file=sys.stderr)
        return 1

    backup_dir = Path(args.dir)
    if not backup_dir.is_absolute():
        backup_dir = BASE_DIR / backup_dir
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        print(f'ERR : impossible de créer {backup_dir} : {exc}', file=sys.stderr)
        return 1

    now = dt.datetime.now()
    dest = backup_dir / f"{re.sub(r'[^A-Za-z0-9_]', '_', params['name'])}_{now:%Y%m%d%H%M%S}.backup"

    if not args.quiet:
        print(f">> Base : {params['name']}@{params['host']}:{params['port']}")
        print(f">> Dossier : {backup_dir}")

    candidates = find_pg_dump()
    if not candidates:
        print('ERR : pg_dump introuvable (PATH, PGBIN, dossiers PostgreSQL) — '
              'installer les outils client PostgreSQL.', file=sys.stderr)
        return 1

    # On tente chaque pg_dump (le plus récent d'abord) — gère les écarts de version
    last_err = ''
    success = False
    for pg_dump in candidates:
        ok, err = run_backup(pg_dump, params, dest, args.quiet, args.dry_run)
        if ok:
            success = True
            if not args.quiet:
                print(f">> pg_dump : {pg_dump.name}")
            break
        last_err = err

    if not success:
        print('ERR : sauvegarde échouée.\n' + (last_err or 'détail inconnu'), file=sys.stderr)
        return 1

    if args.dry_run:
        print(f"(dry-run) commande : {last_err}" if last_err else "(dry-run) pg_dump ok")
        return 0

    size = dest.stat().st_size
    if not args.quiet:
        print(f"OK  : {dest.name} ({size / 1024:.0f} Ko)")

    # ── Copie vers serveur distant (si configuré) ──
    if args.remote_host:
        copy_to_remote(dest, args.remote_host, args.remote_user, args.remote_dir,
                       args.quiet, args.dry_run, password=args.remote_password)

    # ── Rétention (uniquement après une sauvegarde réussie) ──
    files = list_backups(backup_dir)
    keep = retention_keep(files, args.keep_days, args.keep_weeks, args.keep_months, now)
    to_delete = [p for p, _ in files if p not in keep]
    for path in to_delete:
        if args.dry_run:
            print(f"(dry-run) supprimerait : {path.name}")
        else:
            path.unlink(missing_ok=True)
    if not args.quiet:
        print(f"OK  : rétention — {len(files)} backup(s), {len(to_delete)} supprimé(s), "
              f"{len(files) - len(to_delete)} conservé(s)")
    return 0


if __name__ == '__main__':
    sys.exit(main())
