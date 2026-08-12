# -*- coding: utf-8 -*-
"""Teste la recherche et la pagination sur toutes les pages qui en ont."""
import os, sys, io, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import django
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from stock.models import Magasin

c = Client()
c.force_login(User.objects.get(username='admin'))
mag = Magasin.objects.filter(is_deleted=False).first()
s = c.session
s['magasin_actif_id'] = str(mag.id)
s.save()

# (url, params) — chaque entrée teste la page avec ces paramètres
cas = [
    # Recherches
    ('/articles/', {'q': 'para'}),
    ('/articles/', {'q': 'zzzz_inexistant'}),
    ('/articles/', {'q': ''}),
    ('/familles/', {'q': 'med'}),
    ('/entrees/', {'q': 'BE-2026'}),
    ('/entrees/', {'q': 'inexistant'}),
    ('/sorties/', {'q': 'BS'}),
    ('/stock/retours-services/', {'q': 'BR'}),
    ('/commandes/', {'q': 'CMD'}),
    ('/receptions/', {'q': 'CMD'}),
    ('/mes-demandes/', {'q': 'test'}),
    ('/gestion-demandes/', {'q': 'test'}),
    ('/etat-stock/', {'q': 'para'}),
    ('/ajustements/', {'q': 'ajust'}),
    ('/inventaires/', {'q': 'invent'}),
    ('/bons/hors-stock/', {'q': 'HS'}),
    ('/stock/peremptions/', {'q': 'perime'}),
    ('/livraisons/', {'q': 'livr'}),
    ('/parametres/logistique/', {'q': 'pharmacie'}),
    ('/parametres/administratifs/', {'q': 'service'}),
    ('/administration/historique/', {'q': 'BE-2026'}),
    ('/notifications/', {'q': 'notif'}),
    ('/rapports/', {}),
    ('/patrimoine/', {'q': 'test'}),
    ('/patrimoine/sas/', {'q': 'test'}),
    ('/patrimoine/contrats/', {'q': 'maintenance'}),
    ('/patrimoine/interventions/', {'q': 'panne'}),
    ('/auth/utilisateurs/', {'q': 'admin'}),
    ('/auth/roles/', {'q': 'admin'}),
    # Paginations
    ('/articles/', {'page': '1', 'per_page': '15'}),
    ('/articles/', {'page': '2', 'per_page': '15'}),
    ('/entrees/', {'page': '1', 'per_page': '50'}),
    ('/entrees/', {'page': '99'}),
    ('/sorties/', {'page': '1'}),
    ('/etat-stock/', {'page': '1'}),
    ('/administration/historique/', {'page': '1'}),
    ('/patrimoine/', {'page': '1'}),
    ('/patrimoine/', {'page': '999'}),
    ('/auth/utilisateurs/', {'page': '1'}),
    # Date ranges
    ('/entrees/', {'date_range': '01/01/2026 - 31/12/2026'}),
    ('/administration/historique/', {'date_debut': '01/01/2026', 'date_fin': '31/12/2026'}),
    # Tabs/onglets
    ('/stock/peremptions/', {'onglet': 'lots'}),
    ('/stock/peremptions/', {'onglet': 'destruction'}),
    ('/mes-demandes/', {'onglet': 'validees'}),
    ('/gestion-demandes/', {'onglet': 'traitees'}),
    # Stats/rapports (chargement AJAX)
    ('/stats/demandes/', {}),
    ('/stats/sondages/', {}),
    ('/stats/satisfaction-services/', {}),
]

problemes = []
for url, params in cas:
    try:
        r = c.get(url, params, follow=False)
        if r.status_code not in (200, 302):
            problemes.append(f"{url} {params} -> {r.status_code}")
    except Exception as e:
        problemes.append(f"{url} {params} -> EXC {type(e).__name__}: {str(e)[:150]}")
        traceback.print_exc()

print(f"\n=== RECHERCHE/PAGINATION : {len(cas)} cas, {len(problemes)} problèmes ===")
for p in problemes:
    print("  ", p)

# Vérifie que les API de recherche répondent
apis = [
    ('/api/articles/', {'q': 'para'}),
    ('/api/verifier-article/', {'reference': 'PARA500'}),
    ('/notifications/api/', {}),
]
for url, params in apis:
    try:
        r = c.get(url, params)
        if r.status_code != 200:
            problemes.append(f"API {url} {params} -> {r.status_code}")
        else:
            print(f"  API OK {url} {params}")
    except Exception as e:
        problemes.append(f"API {url} -> EXC {type(e).__name__}: {str(e)[:150]}")

print(f"\nTOTAL problèmes: {len(problemes)}")
