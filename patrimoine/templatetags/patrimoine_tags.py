from django import template

register = template.Library()

@register.simple_tag(takes_context=True)
def url_replace(context, **kwargs):
    """Remplace/ajoute des paramètres GET dans l'URL courante."""
    request = context.get('request')
    if not request:
        return ''
    params = request.GET.copy()
    for k, v in kwargs.items():
        params[k] = v
    return params.urlencode()