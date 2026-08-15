# -*- coding: utf-8 -*-
"""Mesure la répartition verticale du contenu sur un PDF multi-pages (bon de sortie).

Usage : DJANGO_DEBUG=True DJANGO_SETTINGS_MODULE=config.settings venv/Scripts/python.exe scripts/measure_pdf_pages.py
"""
import os
import sys
import django

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from django.test import RequestFactory
from stock.models import Magasin, Service
from stock.pdf_utils import get_pdf_config, paginate_lignes, ajouter_hauteurs_lignes, render_pdf_to_bytes

import pymupdf

NB = 22  # > 18 => 2 pages

magasin = Magasin.objects.create(nom="MAGASIN MESURE TEMP")
service = Service.objects.create(nom="Service Cardiologie", code="SC", poste="POSTE 1")

pdf_config, logo_url = get_pdf_config(magasin, 'BS', None)

lignes_data = []
for i in range(NB):
    lignes_data.append({
        'idx': i + 1,
        'reference': f"REF-{i:03d}",
        'designation': f"Serum physiologique 0.9% 500ml perfusion - lot {i}",
        'unite': 'U',
        'quantite': 10 + i,
        'quantite_servie': 10 + i,
        'quantite_demandee': 10 + i,
        'quantite_recue': 10 + i,
        'reste': None,
        'numero_lot': f"LOT-{i:04d}",
        'date_peremption': None,
    })

class BonFake:
    numero_bon = "BS-MESURE-001"
    type_bon = "SORTIE"
    date_bon = None
    demande_origine = None
    reference_externe = None
    numero_livraison = None
    sondage_satisfait = None
    sondage_observation = ""

bon = BonFake()

pagination = paginate_lignes(lignes_data, pdf_config, lignes_par_page=18)
pages = [
    {'lignes': page, 'est_derniere_page': i == len(pagination.pages) - 1}
    for i, page in enumerate(pagination.pages)
]
pages = ajouter_hauteurs_lignes(pages, pdf_config, type_doc=bon.type_bon)

context = {
    'bon': bon,
    'magasin': magasin,
    'lignes_data': lignes_data,
    'lignes_pages': pagination.pages,
    'pages': pages,
    'est_multi_page': pagination.est_multi_page,
    'est_reception_partielle': False,
    'est_livraison_partielle': False,
    'est_cloture': False,
    'numero_livraison': None,
    'commande': None,
    'demande': None,
    'service': service,
    'service_code': getattr(service, 'code', ''),
    'service_poste': getattr(service, 'poste', ''),
    'sondage_data': None,
    'pdf_config': pdf_config,
    'logo_url': logo_url,
    'signature_cases': [],
    'a_lots': True,
}

rf = RequestFactory()
request = rf.get('/')
from django.contrib.auth.models import AnonymousUser
request.user = AnonymousUser()
pdf_bytes = render_pdf_to_bytes(request, 'stock/pdf/bon_sortie.html', context)

with open('.freebuff/tmp/mesure_sortie.pdf', 'wb') as f:
    f.write(pdf_bytes)

doc = pymupdf.open('.freebuff/tmp/mesure_sortie.pdf')
print(f"PAGES: {doc.page_count}")
for pi in range(doc.page_count):
    page = doc[pi]
    words = page.get_text('dict')
    ys = []
    for b in words['blocks']:
        for l in b.get('lines', []):
            for s in l['spans']:
                if s['text'].strip():
                    ys.append((round(s['bbox'][1], 1), round(s['bbox'][3], 1), s['text'][:40]))
    ys.sort()
    print(f"--- PAGE {pi+1}: {len(ys)} spans ---")
    if ys:
        print(f"  premier y0={ys[0][0]}  dernier y1={ys[-1][1]}  hauteur page={page.rect.height}")
        for y in ys:
            print(f"  {y[0]:>7} -> {y[1]:>7}  {y[2]}")
doc.close()

magasin.delete()
service.delete()
print("OK")
