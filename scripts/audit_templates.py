# -*- coding: utf-8 -*-
"""Audit des templates : noms d'URLs {% url %} invalides + assets statiques manquants."""
import os, sys, re, glob, io
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
if hasattr(sys.stdout, 'buffer'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import django
django.setup()
from django.urls import get_resolver, NoReverseMatch
from django.conf import settings
import glob as g

URLLIB = {'stock', 'accounts', 'patrimoine', 'core'}

# Noms d'URLs réels (avec ou sans préfixe d'app) connus du resolver
_KNOWN = None


def _known_names():
    global _KNOWN
    if _KNOWN is None:
        names = set()
        resolver = get_resolver()
        # reverse_dict contient les clés complètes, y compris le préfixe app_name
        for key in resolver.reverse_dict.keys():
            if isinstance(key, str):
                names.add(key)
        # Complète avec les noms nus pour les apps sans app_name
        for pattern in resolver.url_patterns:
            _collect_names(pattern, names)
        _KNOWN = names
    return _KNOWN


def _collect_names(pattern, names):
    if hasattr(pattern, 'url_patterns'):
        for sub in pattern.url_patterns:
            _collect_names(sub, names)
        return
    if pattern.name:
        names.add(pattern.name)


def rev_ok(name):
    # Le reverse_dict du resolver contient les noms "nus" (sans préfixe d'app).
    # Un nom préfixé 'accounts:xxx' est valide si 'xxx' est une clé.
    bare = name.split(':')[-1]
    return bare in _known_names()


def main():
    files = []
    for f in g.glob('**/templates/**/*.html', recursive=True):
        if 'venv' in f or '__pycache__' in f:
            continue
        files.append(f)

    bad_urls = []
    urlnames = set()
    for f in files:
        src = open(f, encoding='utf-8', errors='replace').read()
        for m in re.finditer(r"{%\s*url\s+['\"]([^'\"]+)['\"]", src):
            urlnames.add((m.group(1), f))

    for name, f in sorted(urlnames):
        if not rev_ok(name):
            bad_urls.append((name, f))

    print(f"Templates analysés: {len(files)}")
    print(f"Noms d'URLs {{% url %}}: {len(urlnames)}  INVALIDES: {len(bad_urls)}")
    for name, f in bad_urls:
        print(f"  ✗ {name}  ({f})")

    # 2. Assets statiques référencés mais absents
    print("\n--- ASSETS STATIQUES MANQUANTS ---")
    missing = []
    static_dirs = [str(d) for d in settings.STATICFILES_DIRS]
    for f in files:
        src = open(f, encoding='utf-8', errors='replace').read()
        for m in re.finditer(r"{%\s*static\s+['\"]([^'\"]+)['\"]", src):
            asset = m.group(1)
            found = any(os.path.exists(os.path.join(d, asset.lstrip('/'))) for d in static_dirs)
            if not found:
                missing.append((asset, f))
    seen = set()
    for asset, f in missing:
        if asset not in seen:
            seen.add(asset)
            print(f"  ✗ {asset}  ({f})")
    if not missing:
        print("  Aucun asset manquant ✓")

    # 3. Vérification du rendu : chaque template hérité a bien ses blocs requis ?
    print("\n--- extends/block de base (extrait) ---")
    base_files = [f for f in files if os.path.basename(f) in ('base.html', 'base_ui.html')]
    for bf in base_files:
        src = open(bf, encoding='utf-8', errors='replace').read()
        blocks = re.findall(r"{%\s*block\s+(\w+)", src)
        print(f"  {bf}: blocs={sorted(set(blocks))}")


if __name__ == '__main__':
    main()
