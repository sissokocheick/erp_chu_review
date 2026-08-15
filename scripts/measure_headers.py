# -*- coding: utf-8 -*-
"""Mesure la hauteur d'entête (marge haute -> thead) sur la page 1 des 7 bons."""
import os, sys, django
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
django.setup()

from types import SimpleNamespace
from django.test import RequestFactory
from django.contrib.auth.models import AnonymousUser
from stock.models import Magasin
from stock.pdf_utils import get_pdf_config, paginate_lignes, ajouter_hauteurs_lignes, render_pdf_to_bytes
import pymupdf

magasin = Magasin.objects.create(nom="MAGASIN MESURE HDR")
src = SimpleNamespace(nom="MAGASIN CENTRAL")
dst = SimpleNamespace(nom="MAGASIN ANNEXE")
fourn = SimpleNamespace(raison_sociale="FOURNISSEUR TEST", telephone="0102030405")
service = SimpleNamespace(nom="Service Cardiologie", code="SC", poste="POSTE 1")
user = SimpleNamespace(get_full_name=lambda: "Jean KOFFI", username="jkoffi")
cible = SimpleNamespace(nom="MAGASIN CIBLE")

def bon(t, fournisseur=None, mdest=None):
    b = SimpleNamespace(
        numero_bon=f"BS-{t}-001", type_bon=t, date_bon=None,
        fournisseur=fournisseur, reference_externe=None, commentaire="",
        cree_par=user, magasin=src, magasin_destination=mdest,
        demande_origine=None, numero_livraison=None,
        sondage_satisfait=None, sondage_observation="",
    )
    return b

lignes_data = [
    {'idx': i + 1, 'reference': f"R{i:03d}", 'designation': f"Article court {i}",
     'unite': 'U', 'quantite': 5, 'quantite_servie': 5, 'quantite_demandee': 5,
     'quantite_recue': 5, 'reste': None, 'numero_lot': None, 'date_peremption': None}
    for i in range(22)
]

rf = RequestFactory()
request = rf.get('/')
request.user = AnonymousUser()

for code, templ, ctx_extra in [
    ('BS', 'bon_sortie.html', {'bon': bon('SORTIE', fournisseur=fourn), 'service': service,
                               'service_code': 'SC', 'service_poste': 'POSTE 1', 'demande': None,
                               'commande': None, 'sondage_data': None, 'a_lots': False}),
    ('BE', 'bon_entree.html', {'bon': bon('ENTREE', fournisseur=fourn), 'service': None,
                               'service_code': '', 'service_poste': '', 'demande': None,
                               'commande': None, 'sondage_data': None, 'a_lots': False}),
    ('BR', 'bon_retour.html', {'bon': bon('RETOUR_SERVICE', fournisseur=fourn), 'service': service,
                               'service_code': 'SC', 'service_poste': 'POSTE 1', 'demande': None,
                               'commande': None, 'sondage_data': None, 'a_lots': False}),
    ('BT', 'bon_transfert.html', {'bon': bon('TRANSFERT', mdest=dst), 'service': None,
                                  'service_code': '', 'service_poste': '', 'demande': None,
                                  'commande': None, 'sondage_data': None, 'a_lots': False}),
    ('BD', 'bon_demande.html', {'bon': None, 'demande': SimpleNamespace(
        numero_demande='DM-001', date_demande=None, magasin_cible=cible),
        'service': service, 'service_code': 'SC', 'service_poste': 'POSTE 1',
        'commande': None, 'sondage_data': None, 'a_lots': False}),
    ('BC', 'bon_commande.html', {'bon': None, 'commande': SimpleNamespace(numero_commande='CMD-001'),
        'fournisseur': fourn, 'service': None, 'service_code': '', 'service_poste': '',
        'demande': None, 'sondage_data': None, 'a_lots': False}),
    ('BHS', 'bon_hors_stock.html', {'bon': bon('SORTIE_HORS_STOCK'), 'service': service,
        'service_code': 'SC', 'service_poste': 'POSTE 1', 'demande': None,
        'commande': None, 'sondage_data': None, 'a_lots': False}),
]:
    pdf_config, logo_url = get_pdf_config(magasin, code, None)
    pagination = paginate_lignes(lignes_data, pdf_config, lignes_par_page=18)
    pages = [{'lignes': p, 'est_derniere_page': i == len(pagination.pages) - 1}
             for i, p in enumerate(pagination.pages)]
    pages = ajouter_hauteurs_lignes(pages, pdf_config, type_doc={
        'BS': 'SORTIE', 'BE': 'ENTREE', 'BR': 'RETOUR_SERVICE', 'BT': 'TRANSFERT',
        'BD': 'DEMANDE', 'BC': 'COMMANDE', 'BHS': 'SORTIE_HORS_STOCK',
    }[code])
    ctx = {
        'bon': None, 'magasin': magasin, 'lignes_data': lignes_data,
        'lignes_pages': pagination.pages, 'pages': pages,
        'est_multi_page': pagination.est_multi_page,
        'est_reception_partielle': False, 'est_livraison_partielle': False,
        'est_cloture': False, 'numero_livraison': None, 'commande': None,
        'demande': None, 'service': None, 'service_code': '', 'service_poste': '',
        'sondage_data': None, 'pdf_config': pdf_config, 'logo_url': logo_url,
        'signature_cases': [], 'a_lots': False,
        'doc_subtitle': 'DOC SUBTITLE', 'type_bon_label': 'BON DE DEMANDE',
        'fournisseur': fourn,
    }
    ctx.update(ctx_extra)
    try:
        pdf_bytes = render_pdf_to_bytes(request, f'stock/pdf/{templ}', ctx)
    except Exception as e:
        print(f"{templ}: ERREUR {type(e).__name__}: {e}")
        continue
    open(f'.freebuff/tmp/hdr_{code}.pdf', 'wb').write(pdf_bytes)
    doc = pymupdf.open(f'.freebuff/tmp/hdr_{code}.pdf')
    page = doc[0]
    spans = []
    for b in page.get_text('dict')['blocks']:
        for l in b.get('lines', []):
            for s in l['spans']:
                t = s['text'].strip()
                if t:
                    spans.append((round(s['bbox'][1], 1), round(s['bbox'][3], 1), t))
    spans.sort()
    # thead = premier span contenant "ésignation" ou "ésignations"
    thead_y = None
    for y0, y1, t in spans:
        if ('ésignation' in t or 'ésignations' in t or 'DESCRIPTION' in t):
            thead_y = y0
            break
    # dernière ligne de données de la page 1 = dernier span avant le pied de page
    last_data = max(y1 for y0, y1, t in spans if y0 < 800 and 'esign' not in t and 'Réf' not in t and 'Unit' not in t and 'Article court' in t)
    # page 2 : dernière ligne data
    if doc.page_count > 1:
        p2 = doc[1]
        p2data = []
        for b in p2.get_text('dict')['blocks']:
            for l in b.get('lines', []):
                for s in l['spans']:
                    t = s['text'].strip()
                    if 'Article court' in t:
                        p2data.append(round(s['bbox'][3], 1))
        p2_last = max(p2data) if p2data else 0
    else:
        p2_last = 0
    print(f"{templ:22s} thead={round((thead_y - 17) / 2.8346, 1)}mm  p1_derniere={round((last_data - 17) / 2.8346, 1)}mm  p2_derniere={round((p2_last - 17) / 2.8346, 1)}mm  pages={doc.page_count}")
    doc.close()

magasin.delete()
print("OK")
