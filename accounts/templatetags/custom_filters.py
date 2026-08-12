from django import template
from django.utils.safestring import mark_safe

register = template.Library()


@register.filter
def css_string(value):
    """
    Échappe une chaîne pour l'utiliser dans une propriété CSS (ex: content: "...").
    Nécessaire pour les pieds de page PDF : garde les retours \\A (échappement CSS
    valide pour un saut de ligne) et évite que les apostrophes soient transformées
    en entités HTML (&#x27;) par Django.
    """
    if value is None:
        return ""
    s = str(value)
    # Protéger les marqueurs de retour ligne CSS (\\A) avant d'échapper les backslashes
    s = s.replace('\\A', '\x00NL\x00')
    s = s.replace('\\', '\\\\').replace('"', '\\"')
    s = s.replace('\x00NL\x00', '\\A')
    return mark_safe(s)

@register.filter
def get_item(dictionary, key):
    """
    Filtre template pour récupérer une valeur dans un dictionnaire.
    ✅ CORRECTION : retourne None si l'objet n'a pas de méthode .get()
    """
    if dictionary is None:
        return None
    if hasattr(dictionary, 'get') and callable(getattr(dictionary, 'get')):
        return dictionary.get(key)
    return None

@register.filter
def intspace(value):
    """
    Formate un nombre entier avec des espaces comme séparateurs de milliers.
    Ex: 1250000 → "1 250 000"
    """
    if value is None:
        return ""
    try:
        num = int(value)
        return f"{num:,}".replace(",", " ")
    except (ValueError, TypeError):
        return value
