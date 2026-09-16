import os
import glob
import re

def fix_hardcoded_data():
    html_files = glob.glob('**/templates/**/*.html', recursive=True)
    count_fcfa = 0
    count_chu = 0
    
    for filepath in html_files:
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Replace FCFA
            new_content = re.sub(r'\bFCFA\b(?!\s*,)', '{{ devise_monetaire }}', content)
            
            # Handle CHU ANGRE, CHU d'Angré, etc
            new_content = re.sub(r'CHU ANGR[EÉ]', '{{ etablissement_nom|upper }}', new_content, flags=re.IGNORECASE)
            new_content = re.sub(r'CHU d[\'’]Angr[eé]', '{{ etablissement_nom }}', new_content, flags=re.IGNORECASE)
            new_content = re.sub(r'CHU Angr[eé]', '{{ etablissement_nom }}', new_content, flags=re.IGNORECASE)
            new_content = re.sub(r'Universitaire d[\'’]Angr[eé]', 'Universitaire', new_content, flags=re.IGNORECASE)
            new_content = re.sub(r'ANGRE BESSIKOI Adresse : 28 BP 135', '{{ config_hopital.adresse|default:"" }}', new_content, flags=re.IGNORECASE)
            
            # Handle JS template literal context where we put {{ devise_monetaire }} inside backticks or JS strings
            # Note: Django template engine resolves {{ devise_monetaire }} before sending to client,
            # so `... ${value} {{ devise_monetaire }}` will be correctly rendered by Django to `... 123 FCFA`
            
            if new_content != content:
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(new_content)
                print(f"Updated {filepath}")
                count_fcfa += content.count('FCFA')
                count_chu += len(re.findall(r'Angr', content, flags=re.IGNORECASE))
        except Exception as e:
            print(f"Error processing {filepath}: {e}")
            
    print(f"Fixed {count_fcfa} FCFA occurrences and {count_chu} CHU occurrences.")

if __name__ == '__main__':
    fix_hardcoded_data()
