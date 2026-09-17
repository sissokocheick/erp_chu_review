import re

content = open('patrimoine/templates/patrimoine/parametres.html', encoding='utf-8').read()
panels = re.findall(r'<div class="pm-panel.*?id="(tab-[a-z]+)">', content)

for panel in panels:
    start_idx = content.find(f'<div class="pm-panel" id="{panel}"')
    if start_idx == -1:
        start_idx = content.find(f'<div class="pm-panel active" id="{panel}"')
    
    if panels.index(panel) < len(panels) - 1:
        next_panel = panels[panels.index(panel) + 1]
        end_idx = content.find(f'<div class="pm-panel" id="{next_panel}"')
        if end_idx == -1:
            end_idx = content.find(f'<div class="pm-panel active" id="{next_panel}"')
    else:
        # For the last one, find the end of block contenu
        end_idx = content.find('{% endblock %}', start_idx)
    
    chunk = content[start_idx:end_idx]
    open_divs = chunk.count('<div')
    close_divs = chunk.count('</div')
    print(f'{panel}: open={open_divs}, close={close_divs}, diff={open_divs - close_divs}')
