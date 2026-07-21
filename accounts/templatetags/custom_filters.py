# accounts/templatetags/custom_filters.py
from django import template

register = template.Library()

@register.filter
def get_item(dictionary, key):
    """Récupère une valeur dans un dictionnaire par sa clé."""
    if dictionary is None:
        return None
    return dictionary.get(key)


@register.filter
def intspace(value):
    """
    Formate un nombre entier avec un espace comme séparateur de milliers (format français).
    Exemple : 10000 -> "10 000"
    """
    try:
        return f"{int(value):,}".replace(',', ' ')
    except (ValueError, TypeError):
        return value