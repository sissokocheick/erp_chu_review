# -*- coding: utf-8 -*-
from django import template

register = template.Library()

@register.filter
def index(value, arg):
    """Get item from a list by index: {{ mylist|index:0 }}"""
    try:
        return value[int(arg)]
    except (IndexError, TypeError, ValueError):
        return ''
