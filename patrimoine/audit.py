# -*- coding: utf-8 -*-
"""
Journal d'audit applicatif pour le module Patrimoine.

Centralise l'écriture d'entrées JournalAudit (app accounts) depuis les vues
patrimoine : le « Journal d'audit » (menu Sécurité & Accès → Journal d'audit)
remonte ainsi les créations, modifications, suppressions, validations,
imports et exports du patrimoine, en plus de l'historique fin
(django-simple-history) enregistré par modèle.

L'adresse IP est calculée par accounts.views.get_client_ip (source unique) :
HTTP_X_FORWARDED_FOR n'est utilisé que si USE_X_FORWARDED_FOR est explicitement
activé (reverse proxy), sinon on prend REMOTE_ADDR (l'en-tête est spoofable).
"""
import logging

from accounts.models import JournalAudit
from accounts.views import get_client_ip

logger = logging.getLogger(__name__)


def audit(request, action, type_action='UPDATE', instance=None,
          modele_concerne='', id_objet=None, details=None):
    """Écrit une entrée dans le journal d'audit global (JournalAudit).

    Un échec d'écriture est journalisé dans les logs et n'interrompt pas le
    flux métier. En revanche, une combinaison ambiguë `instance` +
    `modele_concerne`/`id_objet` lève `ValueError` immédiatement : les
    références sont soit dérivées de l'instance, soit fournies explicitement
    pour les mutations sans instance (comme les queryset `.update()`).
    """
    if instance is not None and (modele_concerne or id_objet is not None):
        raise ValueError(
            "audit() : fournir instance ou modele_concerne/id_objet, pas les deux"
        )

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
