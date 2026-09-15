from decimal import Decimal
from django import template

register = template.Library()

@register.filter(name='format_milliers')
def format_milliers(valeur, devise=None):
    """
    Formate un montant ou nombre avec des espaces comme séparateurs de milliers :
    Ex: 15000000 -> "15 000 000"
    Ex: 15000000|format_milliers:"FCFA" -> "15 000 000 FCFA"
    Ex: None -> "—" (si devise) ou ""
    """
    if valeur is None or valeur == '' or valeur == '—':
        return '—' if devise else ''
    
    try:
        if isinstance(valeur, str):
            valeur = valeur.strip().replace(' ', '').replace(',', '.')
            if not valeur:
                return '—' if devise else ''
        
        val_float = float(valeur)
        val_int = round(val_float)
        
        # Si la valeur a des centimes réels (ex: devis au centime)
        if abs(val_float - val_int) > 0.001:
            formatted = f"{val_float:,.2f}".replace(",", " ").replace(".", ",")
        else:
            formatted = f"{val_int:,}".replace(",", " ")
        
        if devise:
            return f"{formatted} {devise}"
        return formatted
    except (ValueError, TypeError):
        return str(valeur)

@register.filter(name='separateur_milliers')
def separateur_milliers(valeur, devise=None):
    """Alias pour format_milliers."""
    return format_milliers(valeur, devise)

@register.filter(name='intspace')
def intspace(valeur, devise=None):
    """Alias pour format_milliers."""
    return format_milliers(valeur, devise)

