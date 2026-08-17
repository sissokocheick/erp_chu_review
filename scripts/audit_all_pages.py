# -*- coding: utf-8 -*-
"""Audit exhaustif : crawl de toutes les routes applicatives (hors admin/static).

Génère les URLs depuis le resolver Django, remplace les paramètres <int:...>
par des IDs réels de la base quand c'est possible, et vérifie le statut HTTP
de chaque page avec l'utilisateur admin connecté et un magasin actif.
"""
import os, sys, io, re
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import django
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from django.urls import get_resolver
from stock.models import Magasin
from django.apps import apps

c = Client()
admin = User.objects.filter(is_superuser=True).first()
if not admin:
    admin = User.objects.first()
c.force_login(admin)

mag = Magasin.objects.filter(is_deleted=False).first() or Magasin.objects.first()
if mag:
    s = c.session
    s['magasin_actif_id'] = str(mag.id)
    s.save()

# Collecte des premiers IDs de chaque modèle (pour les URLs avec <int:pk>)
id_cache = {}
for model in apps.get_models():
    try:
        obj = model.objects.first()
        if obj:
            id_cache[model._meta.label] = obj.pk
    except Exception:
        pass


def pick_id(param):
    """Tente de trouver un ID plausible pour un paramètre de route."""
    p = param.lower()
    # 1. pattern commun : <int:pk>, <int:id>, <int:article_id>...
    for label, pk in id_cache.items():
        base = label.split('.')[-1].lower()
        if p in (base, base + '_id') or p == 'pk' or p == 'id':
            return pk
    # 2. tentative sur le nom du modèle exact
    for label, pk in id_cache.items():
        base = label.split('.')[-1].lower()
        if p.startswith(base) or base.startswith(p):
            return pk
    # 3. dernier recours : n'importe quel ID existant
    for pk in id_cache.values():
        return pk
    return None


def dump(patterns, prefix=''):
    out = []
    for p in patterns:
        if hasattr(p, 'url_patterns'):
            out += dump(p.url_patterns, prefix + str(p.pattern))
        else:
            full = prefix + str(p.pattern)
            # Nettoie : ^ et $ de début/fin
            full = full.lstrip('^').rstrip('$')
            out.append(full)
    return out


res = get_resolver()
urls = sorted(set(dump(res.url_patterns)))

# Exclut admin / static / media
EXCL = ('admin/', '^media', '^static', 'jsi18n', 'autocomplete')
app_urls = [u for u in urls if not any(u.startswith(x) for x in EXCL)]

results = {'OK': [], 'REDIRECT': [], '404': [], '5xx': [], 'ERROR': [], 'SKIP': []}


def test_url(url, source):
    if url.startswith(('http', '#')):
        return
    try:
        r = c.get(url, follow=False)
        if r.status_code == 200:
            results['OK'].append(url)
        elif r.status_code in (301, 302, 303, 307, 308):
            results['REDIRECT'].append(f"{url} -> {r.get('Location','?')[:80]}")
        elif r.status_code == 404:
            results['404'].append(url)
        else:
            results['5xx'].append(f"{url} [{r.status_code}]")
    except Exception as e:
        results['ERROR'].append(f"{url} : {type(e).__name__}: {str(e)[:120]}")


tested = set()
for u in app_urls:
    # Remplace les paramètres <...> par des valeurs
    m = re.search(r'<.*?>', u)
    if not m:
        if u not in tested:
            test_url('/' + u, u)
            tested.add(u)
        continue
    # URL avec paramètres : tente de les remplacer
    params = re.findall(r'<int:([a-zA-Z_]+)>', u)
    if not params:
        # type de param non-int (slug, path, str...) -> on saute
        results['SKIP'].append(u)
        continue
    filled = u
    ok = True
    for p in params:
        pk = pick_id(p)
        if pk is None:
            ok = False
            break
        filled = filled.replace(f'<int:{p}>', str(pk))
    if not ok:
        results['SKIP'].append(u)
        continue
    url = '/' + filled
    if url in tested:
        continue
    test_url(url, u)
    tested.add(url)

print("=" * 70)
print(f"TOTAL ROUTES APPLICATIVES: {len(app_urls)}  TESTÉES: {len(tested)}")
print(f"OK: {len(results['OK'])}  REDIRECT: {len(results['REDIRECT'])}  "
      f"404: {len(results['404'])}  5xx: {len(results['5xx'])}  "
      f"ERROR: {len(results['ERROR'])}  SKIP(param non-int): {len(results['SKIP'])}")
print("=" * 70)

if results['404']:
    print("\n--- 404 ---")
    for x in results['404']:
        print(" ", x)
if results['5xx']:
    print("\n--- 5xx ---")
    for x in results['5xx']:
        print(" ", x)
if results['ERROR']:
    print("\n--- EXCEPTIONS ---")
    for x in results['ERROR']:
        print(" ", x)
if results['REDIRECT']:
    print("\n--- REDIRECTS (échantillon) ---")
    for x in results['REDIRECT'][:30]:
        print(" ", x)
if results['SKIP']:
    print("\n--- SKIP (paramètres non remplis) ---")
    for x in results['SKIP'][:20]:
        print(" ", x)
