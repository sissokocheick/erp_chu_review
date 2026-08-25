# -*- coding: utf-8 -*-
"""Chiffrement des secrets stockés en base (mots de passe SMTP, clés API SMS).

Les valeurs sont chiffrées avec Fernet (AES-128-CBC + HMAC-SHA256) via une
clé dérivée de DJANGO_SECRET_KEY. Format en base : « enc1:<token Fernet> ».

Compatibilité : toute valeur qui ne commence pas par le préfixe est renvoyée
telle quelle (données legacy en clair) ; elle sera chiffrée à la prochaine
sauvegarde. Si DJANGO_SECRET_KEY change, les secrets deviennent illisibles →
les ressaisir dans Paramètres ▸ Notifications.
"""
import base64
import hashlib
import logging

from django.conf import settings

logger = logging.getLogger(__name__)

PREFIXE = "enc1:"

try:
    from cryptography.fernet import Fernet, InvalidToken
    _CRYPTO_DISPONIBLE = True
except Exception:  # pragma: no cover — dépendance absente (ne doit pas arriver)
    _CRYPTO_DISPONIBLE = False


def _fernet():
    """Fernet construit depuis SECRET_KEY (dérivation SHA-256, stable)."""
    cle = hashlib.sha256(
        (str(settings.SECRET_KEY) + ":nexuserp-secrets").encode("utf-8")
    ).digest()
    return Fernet(base64.urlsafe_b64encode(cle))


def chiffrer(valeur):
    """Chiffre une valeur secrète. Retourne '' si vide ; idempotent."""
    if not valeur:
        return ""
    texte = str(valeur)
    if not _CRYPTO_DISPONIBLE or texte.startswith(PREFIXE):
        return texte
    try:
        return PREFIXE + _fernet().encrypt(texte.encode("utf-8")).decode("ascii")
    except Exception:
        logger.exception("[crypto] Chiffrement impossible — valeur conservée en clair")
        return texte


def dechiffrer(valeur):
    """Déchiffre une valeur secrète. Valeur non préfixée = legacy en clair.
    Retourne '' si la clé a changé (secret indéchiffrable)."""
    if not valeur:
        return ""
    texte = str(valeur)
    if not texte.startswith(PREFIXE):
        return texte  # legacy en clair (ou chiffrement indisponible à l'écriture)
    if not _CRYPTO_DISPONIBLE:
        logger.error("[crypto] Module cryptography absent — secret illisible")
        return ""
    try:
        return _fernet().decrypt(texte[len(PREFIXE):].encode("ascii")).decode("utf-8")
    except InvalidToken:
        logger.error(
            "[crypto] Secret indéchiffrable (DJANGO_SECRET_KEY a changé ?) — "
            "ressaisir la valeur dans Paramètres ▸ Notifications"
        )
        return ""


class SecretCharFieldMixin:
    """Mixin CharField : chiffre à l'écriture en base, déchiffre à la lecture.

    ⚠️ Les filtres .filter(champ='x') comparent au format chiffré : ne pas
    filtrer sur un champ secret (aucun cas dans l'application).
    """

    def get_prep_value(self, value):
        return chiffrer(super().get_prep_value(value))

    def from_db_value(self, value, expression, connection):
        return dechiffrer(value)
