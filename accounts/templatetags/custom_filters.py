from django import template

register = template.Library()

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
