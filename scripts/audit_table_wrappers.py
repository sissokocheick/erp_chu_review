# -*- coding: utf-8 -*-
"""Analyse : pour chaque URL, trouve les tables >= 5 colonnes et vérifie si
leur conteneur scroll en interne (inline ou via classe CSS avec overflow-x)."""
import re
import sys
from html.parser import HTMLParser

import django

sys.path.insert(0, '.')
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

django.setup()

from django.test import Client
from django.contrib.auth.models import User
from stock.models import Magasin

u = User.objects.get(username='admin')
c = Client()
c.force_login(u)
m = Magasin.objects.filter(nom='PHARMACIE CENTRALE').first() or Magasin.objects.first()
s = c.session
s['magasin_actif_id'] = str(m.id)
s.save()

# (url, nb colonnes attendu) — pages signalées par le test
URLS = [
    '/', '/articles/', '/entrees/', '/sorties/', '/bons/hors-stock/',
    '/livraisons/', '/receptions/', '/commandes/', '/mes-demandes/',
    '/gestion-demandes/', '/parametres/administratifs/', '/stats/sondages/',
    '/auth/roles/', '/auth/journal-audit/', '/patrimoine/parametres/',
    '/patrimoine/mes-tickets/', '/articles/1/historique/',
]

# 1) Règles CSS des blocs <style> : classe -> a-t-elle overflow-x ?
CSS_OVERFLOW = set()
CSS_RULES = []


def extract_css(html):
    for m in re.finditer(r'<style[^>]*>(.*?)</style>', html, re.S | re.I):
        block = m.group(1)
        for rule in re.finditer(r'([^{}]+)\{([^{}]*)\}', block):
            sel, decl = rule.group(1), rule.group(2)
            if 'overflow' in decl and 'auto' in decl:
                for cls in re.findall(r'\.([\w-]+)', sel):
                    CSS_OVERFLOW.add(cls)
            CSS_RULES.append((sel.strip(), decl.strip()))


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []  # (tag, class, style)
        self.tables = []
        self.cur = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.stack.append((tag, attrs.get('class', ''), attrs.get('style', '')))
        if tag == 'table':
            self.cur = {'ths': 0, 'chain': []}
            self.tables.append(self.cur)

    def handle_startendtag(self, tag, attrs):
        pass

    def handle_endtag(self, tag):
        if self.stack:
            self.stack.pop()

    def handle_data(self, data):
        pass

    def handle_comment(self, data):
        pass


def chain_overflow(html, start):
    """Remonte les ancêtres d'une table à partir de la position `start` du <table>."""
    # On re-parse simplement avec une pile complète
    parser = TableParser()
    parser.feed(html)
    return parser


for url in URLS:
    r = c.get(url)
    if r.status_code != 200:
        print(f"{url} -> HTTP {r.status_code}")
        continue
    html = r.content.decode('utf-8', errors='replace')
    CSS_OVERFLOW.clear()
    CSS_RULES.clear()
    extract_css(html)
    parser = TableParser()
    parser.feed(html)
    # Re-feed avec tracking de position pour associer ancêtres
    # (approche simple : re-parcours et on regarde la pile à chaque <table>)
    stack = []
    tables = []

    class P2(HTMLParser):
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            info = {'tag': tag, 'class': attrs.get('class', ''), 'style': attrs.get('style', '')}
            stack.append(info)
            if tag == 'table':
                tables.append(list(stack))

        def handle_endtag(self, tag):
            for i in range(len(stack) - 1, -1, -1):
                if stack[i]['tag'] == tag:
                    del stack[i:]
                    break

    p = P2()
    p.feed(html)

    prob = []
    # positions de début de chaque <table> pour compter les <th> dans son contenu
    table_starts = []
    for m in re.finditer(r'<table[^>]*>', html):
        table_starts.append(m.start())
    starts = table_starts + [len(html)]

    for idx, chain in enumerate(tables):
        start, end = starts[idx], starts[idx + 1]
        ths = len(re.findall(r'<th[ >]', html[start:end], re.I))
        if ths < 5:
            continue
        scrolls = False
        reasons = []
        for info in chain:
            style = info['style']
            if re.search(r'overflow-x\s*:\s*(auto|scroll)', style, re.I):
                scrolls = True
                reasons.append(f"inline:{info['tag']}.{info['class']}")
            if info['class']:
                for cls in info['class'].split():
                    if cls in CSS_OVERFLOW:
                        scrolls = True
                        reasons.append(f"css:{info['tag']}.{cls}")
        if not scrolls:
            wrappers = ' > '.join(
                f"{i['tag']}.{i['class'].split()[0] if i['class'] else ''}" for i in chain[-4:]
            )
            prob.append(f"  table {ths}col: ancêtres={wrappers}")

    print(f"== {url}")
    if prob:
        print("\n".join(prob))
    else:
        print("  OK (scroll interne présent)")
