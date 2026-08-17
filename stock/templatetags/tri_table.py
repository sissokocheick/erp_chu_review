# -*- coding: utf-8 -*-
"""
Tag de template pour les en-têtes de colonnes triables.

Usage dans un template (après `{% load tri_table %}`) :

    {% th_tri 'designation' 'Désignation' tri ordre %}
    {% th_tri 'date_bon' 'Date' tri ordre %}

Génère un <th> cliquable qui relance la page avec tri=<cle>&ordre=asc|desc,
en préservant tous les autres paramètres GET (recherche, filtres,
pagination). Une flèche ▲/▼ indique la colonne et le sens actifs.
"""

from django import template
from django.utils.html import format_html

register = template.Library()


@register.simple_tag(takes_context=True)
def th_tri(context, cle, libelle, tri='', ordre='asc', prefix=''):
    """En-tête cliquable triant la colonne `cle`.

    tri/ordre : valeurs courantes du contexte (vides si aucun tri).
    prefix : préfixe optionnel des paramètres GET (ex. 'd' → dtri/dordre)
    pour gérer plusieurs tableaux triables sur la même page.
    """
    request = context.get('request')
    if request is not None:
        params = request.GET.copy()
    else:
        from django.http import QueryDict
        params = QueryDict('')

    param_tri = (prefix + 'tri') if prefix else 'tri'
    param_ordre = (prefix + 'ordre') if prefix else 'ordre'
    nouveau_ordre = 'desc' if (tri == cle and ordre == 'asc') else 'asc'
    params[param_tri] = cle
    params[param_ordre] = nouveau_ordre
    params.pop('page', None)  # un tri relance à la page 1
    url = '?' + params.urlencode()

    actif = tri == cle
    if actif:
        icone = format_html(
            '<i class="fas fa-sort-{}" aria-hidden="true"></i>',
            'up' if ordre == 'asc' else 'down',
        )
    else:
        icone = ''
    classe = 'th-tri active' if actif else 'th-tri'

    return format_html(
        '<th class="{}"><a href="{}" title="Trier par {}">{}{}</a></th>',
        classe, url, libelle, libelle, icone,
    )
