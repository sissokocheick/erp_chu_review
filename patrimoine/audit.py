# -*- coding: utf-8 -*-
"""
Journal d'audit applicatif pour le module Patrimoine.

Centralise l'écriture d'entrées JournalAudit (app accounts) depuis les vues
patrimoine : le « Journal d'audit » (menu Sécurité & Accès → Journal d'audit)
remonte ainsi les créations, modifications, suppressions, validations,
imports et exports du patrimoine, en plus de l'historique fin
(django-simple-history) enregistré par modèle.

L'adresse IP respecte la même règle que accounts.views.get_client_ip :
HTTP_X_FORWARDED_FOR n'est utilisé que si USE_X_FORWARDED_FOR est explicitement
activé (reverse proxy), sinon on prend REMOTE_ADDR (l'en-tête est spoofable).
"""
import logging

from django.conf import settings

from accounts.models import JournalAudit

logger = logging.getLogger(__name__)


def get_client_ip(request):
    """IP réelle du client (mêmes règles que accounts.views.get_client_ip)."""
    if getattr(settings, 'USE_X_FORWARDED_FOR', False):
        x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded:
            ips = [ip.strip() for ip in x_forwarded.split(',') if ip.strip()]
            if ips:
                return ips[-1]
    return request.META.get('REMOTE_ADDR', '')


def audit(request, action, type_action='UPDATE', instance=None,
          modele_concerne='', id_objet=None, details=None):
    """Écrit une entrée dans le journal d'audit global (JournalAudit).

    Ne lève jamais : un échec d'écriture est journalisé dans les logs et
    n'interrompt pas le flux métier.
    """
    try:
        utilisateur = None
        if request is not None and getattr(request, 'user', None) is not None \
                and request.user.is_authenticated:
            utilisateur = request.user

        if instance is not None:
            modele_concerne = instance.__class__.__name__
            id_objet = getattr(instance, 'pk', None)

        JournalAudit.objects.create(
            utilisateur=utilisateur,
            action=action[:200],
            type_action=type_action,
            modele_concerne=modele_concerne or '',
            id_objet=id_objet,
            details=details,
            adresse_ip=get_client_ip(request) if request is not None else None,
        )
    except Exception:
        logger.exception("Impossible d'écrire l'entrée d'audit patrimoine : %s", action)
