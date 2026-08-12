# -*- coding: utf-8 -*-
# accounts/utils.py
from django.contrib.admin.models import LogEntry, ADDITION, CHANGE, DELETION
from django.contrib.contenttypes.models import ContentType
from django.utils.timezone import now
import logging

logger = logging.getLogger(__name__)


# ==========================================================
# 🔐 VALIDATION MOT DE PASSE CENTRALISÉE (4 contextes)
# ==========================================================
def canaux_notification_actifs():
    """Retourne (email_ok, sms_ok) selon la configuration globale des notifications.

    Un canal n'est considéré actif que s'il est réellement livrable :
    - email : activé + expéditeur renseigné + SMTP complet (hôte, utilisateur, mot de passe).
    - sms   : activé + expéditeur + URL + clé API renseignés.
    """
    try:
        from core.models import ConfigurationNotification
        cfg = ConfigurationNotification.get_instance()
        email_ok = bool(
            cfg.activer_email
            and cfg.email_expediteur
            and cfg.smtp_host
            and cfg.smtp_user
            and cfg.smtp_password
        )
        sms_ok = bool(
            cfg.activer_sms
            and cfg.sms_expediteur
            and cfg.sms_api_url
            and cfg.sms_api_key
        )
        return email_ok, sms_ok
    except Exception:
        logging.getLogger(__name__).exception(
            "[Notifications] Configuration illisible (canaux_notification_actifs)"
        )
        return False, False


def valider_mot_de_passe(password, contexte='default'):
    """
    Valide un mot de passe selon la politique unique NexusERP.

    Règles :
        - Minimum 8 caractères
        - Au moins 1 lettre majuscule
        - Au moins 1 chiffre

    Contextes supportés (même règles pour tous) :
        - 'default'    : Création, réinitialisation admin
        - 'profil'     : Changement depuis le profil
        - 'obligatoire': Changement obligatoire premier login
        - 'admin_reset': Réinitialisation par un admin

    Returns:
        list : Liste des messages d'erreur (vide si valide)
    """
    erreurs = []
    if not password:
        return ["Mot de passe requis"]

    if len(password) < 8:
        erreurs.append("Au moins 8 caractères")
    if not any(c.isupper() for c in password):
        erreurs.append("Une lettre majuscule")
    if not any(c.isdigit() for c in password):
        erreurs.append("Un chiffre")

    return erreurs


def generer_mot_de_passe_aleatoire(longueur=12):
    """
    Génère un mot de passe aléatoire conforme à la politique (8+, maj, chiffre).
    """
    import secrets
    import string

    if longueur < 8:
        longueur = 8

    alphabet = string.ascii_letters + string.digits
    while True:
        chars = [
            secrets.choice(string.ascii_uppercase),
            secrets.choice(string.ascii_lowercase),
            secrets.choice(string.digits),
        ]
        chars += [secrets.choice(alphabet) for _ in range(longueur - 3)]
        # Mélange sécurisé (Fisher-Yates)
        for i in range(len(chars) - 1, 0, -1):
            j = secrets.randbelow(i + 1)
            chars[i], chars[j] = chars[j], chars[i]
        password = ''.join(chars)
        if not valider_mot_de_passe(password):
            return password


# ==========================================================
# 📝 LOG D'AUDIT CORRIGÉ (supporte AnonymousUser)
# ==========================================================
def log_audit(request, message, type_action='OTHER', instance=None, utilisateur=None, details=None):
    """
    Enregistre une action d'audit dans JournalAudit (mono-tenant).
    """
    try:
        from .models import JournalAudit

        user = utilisateur
        if user is None and request and hasattr(request, 'user') and request.user.is_authenticated:
            user = request.user

        adresse_ip = None
        if request and hasattr(request, 'META'):
            x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
            if x_forwarded:
                adresse_ip = x_forwarded.split(',')[0].strip()
            else:
                adresse_ip = request.META.get('REMOTE_ADDR')

        details_final = details or {}
        if instance:
            details_final['modele'] = instance.__class__.__name__
            details_final['pk'] = instance.pk

        JournalAudit.objects.create(
            utilisateur=user,
            action=message[:200],
            type_action=type_action,
            modele_concerne=instance.__class__.__name__ if instance else '',
            id_objet=instance.pk if instance else None,
            details=details_final if details_final else None,
            adresse_ip=adresse_ip,
        )
    except Exception as e:
        logger.error(f"Erreur lors du log d'audit : {e}")


def get_fonction_valideur(user):
    """
    Construit la fonction affichée sous le nom sur le PDF.
    Ex: "Kouassi Jean - Chef de Service Cardiologie"
    """
    if not user:
        return "Non spécifié"
    profil = getattr(user, 'profil', None)
    if not profil:
        return "Non spécifié"

    # Utiliser get_fonction_display() du modèle si disponible
    if hasattr(profil, 'get_fonction_display'):
        fct = profil.get_fonction_display()
        if fct and fct != "Non spécifié":
            return fct

    # Fallback manuel
    if getattr(profil, 'fonction', None):
        return profil.fonction.nom
    fonctions = []
    if getattr(profil, 'est_chef_service', False) and getattr(profil, 'service', None):
        fonctions.append(f"Chef de Service {profil.service.nom}")
    elif getattr(profil, 'service', None):
        fonctions.append(profil.service.nom)
    if getattr(profil, 'specialite', None):
        fonctions.append(profil.specialite.nom)

    result = " / ".join(fonctions)
    return result if result else "Non spécifié"


def get_label_signataire(user, default_label):
    """
    Retourne la fonction personnalisée d'un utilisateur pour les cases signature PDF.
    Si l'utilisateur a une Fonction (FK) dans son profil, on l'utilise.
    Sinon on garde le label par défaut configuré dans l'établissement.

    Usage dans une vue PDF :
        labels = config_hopital.get_labels_signatures()  # 6 labels par défaut
        # Remplacer celui du demandeur par sa vraie fonction
        labels[0] = get_label_signataire(bon.demandeur, labels[0])
    """
    if not user or not hasattr(user, 'profil'):
        return default_label
    profil = user.profil

    # Utiliser get_fonction_display() du modèle pour éviter la duplication
    if hasattr(profil, 'get_fonction_display'):
        fct = profil.get_fonction_display()
        if fct and fct != "Non spécifié":
            return fct

    if profil and getattr(profil, 'fonction', None):
        return profil.fonction.nom

    return default_label


