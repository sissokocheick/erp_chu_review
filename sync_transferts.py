import re

content = open('stock/templates/stock/liste_transferts.html', encoding='utf-8').read()
m = re.search(r'<tbody id="tbody-transferts">(.*?)</tbody>', content, re.DOTALL)
if not m:
    m = re.search(r'<tbody>(.*?)</tbody>', content, re.DOTALL)

fallback_html = m.group(1).strip()
# Write to transferts_lignes.html
open('stock/templates/stock/transferts_lignes.html', 'w', encoding='utf-8').write(fallback_html)

# Replace in liste_transferts.html
new_content = content[:m.start(1)] + "\n            {% include 'stock/transferts_lignes.html' %}\n        " + content[m.end(1):]
open('stock/templates/stock/liste_transferts.html', 'w', encoding='utf-8').write(new_content)
