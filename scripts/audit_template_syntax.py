# -*- coding: utf-8 -*-
"""Compile tous les templates pour attraper les erreurs de syntaxe Django."""
import os, sys, glob, io
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import django
django.setup()
from django.template.loader import get_template
from django.template import TemplateSyntaxError

errors = []
count = 0
for f in glob.glob('**/templates/**/*.html', recursive=True):
    if 'venv' in f or '__pycache__' in f:
        continue
    rel = f.split('templates' + os.sep, 1)[-1].replace(os.sep, '/')
    try:
        get_template(rel)
        count += 1
    except TemplateSyntaxError as e:
        errors.append(f'{rel}: {e}')
    except Exception as e:
        errors.append(f'{rel}: {type(e).__name__}: {e}')

print(f'Templates compilés sans erreur: {count}')
print(f'Erreurs: {len(errors)}')
for e in errors[:20]:
    print('  !', e)
