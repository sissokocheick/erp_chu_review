# -*- coding: utf-8 -*-
"""Réinitialisation du mot de passe par l'utilisateur lui-même (« Mot de passe oublié »).

Disponible uniquement si au moins un canal de notification (email ou SMS) est
configuré. Dans ce cas, la réinitialisation manuelle par l'administrateur est
désactivée : l'utilisateur reçoit un lien (email) et/ou un code (SMS) et choisit
lui-même son nouveau mot de passe depuis la page de connexion.
"""
import logging
import secrets
import time
from datetime import timedelta

from django.contrib import messages
from django.contrib.auth.models import User
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone

from stock.services import NotificationService

from .models import AuditConnexion, MotDePasseResetToken, Profil
from .utils import canaux_notification_actifs, valider_mot_de_passe
from .views import get_client_ip, log_audit

logger = logging.getLogger(__name__)

DUREE_VALIDITE_MINUTES = MotDePasseResetToken.DUREE_VALIDITE_MINUTES

# ── Protection anti-force-brute / anti-bombing ──
MAX_TENTATIVES_CODE = 5          # échecs de code avant blocage
DUREE_BLOCAGE_MINUTES = 15       # durée du blocage après échecs
MIN_DELAI_DEMANDE_SECONDES = 60  # délai minimal entre deux demandes d'envoi
MAX_DEMANDES_PAR_HEURE = 5       # nb max de demandes d'envoi par heure

# ✅ CORRECTION anti brute-force : garde serveur (indépendante des cookies)
# sur les échecs de code par IP — une session peut être contournée en
# supprimant les cookies, pas le journal en base.
MAX_ECHECS_CODE_PAR_IP = 10      # échecs de code / 15 min / IP avant blocage


def _bloquage_ip_actif(request):
    """True si cette IP a trop d'échecs de code récents (garde en base)."""
    return AuditConnexion.objects.filter(
        type_action='ECHEC',
        description="[ResetMDP] Code invalide",
        adresse_ip=get_client_ip(request),
        date_creation__gte=timezone.now() - timedelta(minutes=DUREE_BLOCAGE_MINUTES),
    ).count() >= MAX_ECHECS_CODE_PAR_IP


def _enregistrer_echec_code_ip(request):
    """Journalise un échec de code côté serveur (throttle par IP)."""
    try:
        AuditConnexion.objects.create(
            type_action='ECHEC',
            description="[ResetMDP] Code invalide",
            adresse_ip=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:500],
        )
    except Exception:
        logger.exception("[ResetMDP] Journalisation échec code impossible")


def _bloquage_actif(request):
    """True si la session est bloquée suite à trop d'échecs de code."""
    jusqu_a = request.session.get('reset_blocage_jusqua', 0)
    return time.time() < jusqu_a


def _enregistrer_echec_code(request):
    """Compte un échec de saisie de code ; bloque la session au-delà du seuil."""
    nb = request.session.get('reset_echecs_code', 0) + 1
    if nb >= MAX_TENTATIVES_CODE:
        request.session['reset_blocage_jusqua'] = (
            time.time() + DUREE_BLOCAGE_MINUTES * 60)
        request.session['reset_echecs_code'] = 0
    else:
        request.session['reset_echecs_code'] = nb


def _reinitialiser_echecs(request):
    request.session.pop('reset_echecs_code', None)
    request.session.pop('reset_blocage_jusqua', None)


def _verifier_cadence_demande(request):
    """Anti-bombing SMS/email : 1 demande/minute et max 5/heure par session.

    Retourne True si la demande est autorisée (et enregistre la cadence).
    """
    maintenant = time.time()
    derniere = request.session.get('reset_derniere_demande', 0)
    if maintenant - derniere < MIN_DELAI_DEMANDE_SECONDES:
        return False
    historique = [
        t for t in request.session.get('reset_historique_demandes', [])
        if maintenant - t < 3600
    ]
    if len(historique) >= MAX_DEMANDES_PAR_HEURE:
        return False
    historique.append(maintenant)
    request.session['reset_derniere_demande'] = maintenant
    request.session['reset_historique_demandes'] = historique
    return True


def _chiffres(texte):
    """Extrait uniquement les chiffres d'une chaîne (pour comparer les téléphones)."""
    return ''.join(c for c in (texte or '') if c.isdigit())


def _normaliser_telephone_saisi(tel):
    """Normalise un téléphone saisi par l'utilisateur en 10 chiffres locaux.

    Accepte 0708091011, 07 08 09 10 11, +2250708091011, +225 07 08 09 10 11…
    Retourne une chaîne de chiffres (10 chiffres si numéro ivoirien).
    """
    digits = _chiffres(tel)
    if len(digits) == 13 and digits.startswith('225'):
        digits = digits[3:]  # +2250708091011 → 0708091011
    return digits


def _trouver_par_telephone(tel_saisi):
    """Cherche un utilisateur actif dont le téléphone correspond.

    Normalise le numéro saisi ET le contact stocké : un contact enregistré
    avec +225 (13 chiffres, ex. 2250708091011) doit matcher une saisie locale
    (0708091011) comme une saisie internationale (+225 07 08 09 10 11).
    """
    digits = _normaliser_telephone_saisi(tel_saisi)
    if len(digits) != 10:
        return None
    for p in Profil.objects.select_related('user').filter(user__is_active=True):
        if not p.contact:
            continue
        contact_normalise = _normaliser_telephone_saisi(p.contact)
        if contact_normalise and contact_normalise == digits:
            return p.user
    return None


def mot_de_passe_oublie(request):
    """Étape 1 : l'utilisateur choisit son canal (email ou SMS), saisit son
    email ou son numéro de téléphone → envoi du lien (email) ou du code (SMS)."""
    if request.user.is_authenticated:
        return redirect('accounts:accueil_personnalise')

    email_ok, sms_ok = canaux_notification_actifs()
    if not (email_ok or sms_ok):
        messages.info(
            request,
            "La réinitialisation du mot de passe n'est pas disponible. "
            "Contactez l'administrateur.",
        )
        return redirect('accounts:custom_login')

    if request.method == 'POST':
        if _bloquage_actif(request):
            messages.error(
                request,
                "Trop de tentatives. Réessayez dans 2 minutes.",
            )
            return redirect('accounts:mot_de_passe_oublie')
        if not _verifier_cadence_demande(request):
            messages.error(
                request,
                "Veuillez patienter avant de refaire une demande "
                "(limite anti-abus).",
            )
            return redirect('accounts:mot_de_passe_oublie')

        canal = request.POST.get('canal', 'email').strip().lower()
        identifiant = request.POST.get('identifiant', '').strip()
        user = None
        if identifiant:
            if canal == 'sms':
                user = _trouver_par_telephone(identifiant)
            else:
                user = (
                    User.objects.filter(username__iexact=identifiant, is_active=True).first()
                    or User.objects.filter(email__iexact=identifiant, is_active=True).first()
                )
        if user is not None:
            # ✅ CORRECTION : mémoriser le compte demandé en session pour que
            # le code SMS ne puisse valider QUE ce compte à l'étape 2 (sinon
            # un code deviné pouvait matcher le jeton de n'importe quel
            # utilisateur ayant un jeton actif).
            request.session['reset_user_id'] = user.id
            try:
                # Ménage : purge des jetons expirés de plus d'un jour
                MotDePasseResetToken.objects.filter(
                    expire_le__lt=timezone.now() - timedelta(days=1)
                ).delete()
                # Un seul jeton actif par utilisateur : on invalide les précédents
                MotDePasseResetToken.objects.filter(
                    user=user, utilise=False
                ).update(utilise=True)

                jeton = MotDePasseResetToken.objects.create(
                    user=user,
                    token=secrets.token_urlsafe(32),
                    code=f"{secrets.randbelow(1_000_000):06d}",
                    expire_le=timezone.now() + timedelta(minutes=DUREE_VALIDITE_MINUTES),
                )
                lien = request.build_absolute_uri(
                    reverse('accounts:reinitialiser_mot_de_passe_lien', args=[jeton.token])
                )
                lien_code = request.build_absolute_uri(
                    reverse('accounts:reinitialiser_mot_de_passe')
                )
                telephone = getattr(getattr(user, 'profil', None), 'contact', None)

                envoye_email = False
                envoye_sms = False

                # Envoi sur le canal choisi par l'utilisateur
                if canal == 'sms':
                    if sms_ok and telephone:
                        texte = (
                            f"NexusERP : votre code de réinitialisation est {jeton.code}. "
                            f"Saisissez-le sur {lien_code} "
                            f"(valable {DUREE_VALIDITE_MINUTES} minutes)."
                        )
                        envoye_sms = NotificationService.envoyer_sms_direct(telephone, texte)
                    # Repli : si le SMS n'a pas pu partir (ex. compte Twilio trial),
                    # on tente l'email quand le compte en a un.
                    if not envoye_sms and email_ok and user.email:
                        envoye_email = _envoyer_lien_reset(request, user, jeton, lien, DUREE_VALIDITE_MINUTES)
                else:
                    if email_ok and user.email:
                        envoye_email = _envoyer_lien_reset(request, user, jeton, lien, DUREE_VALIDITE_MINUTES)
                    # Repli : si l'email n'a pas pu partir, on tente le SMS.
                    if not envoye_email and sms_ok and telephone:
                        texte = (
                            f"NexusERP : votre code de réinitialisation est {jeton.code}. "
                            f"Saisissez-le sur {lien_code} "
                            f"(valable {DUREE_VALIDITE_MINUTES} minutes)."
                        )
                        envoye_sms = NotificationService.envoyer_sms_direct(telephone, texte)

                log_audit(
                    request,
                    f"Demande de réinitialisation du mot de passe pour {user.username}",
                    type_action='UPDATE', modele_concerne='User', id_objet=user.id,
                )
                try:
                    AuditConnexion.objects.create(
                        utilisateur=user,
                        type_action='ADMIN',
                        description="Demande de réinitialisation du mot de passe (mot de passe oublié)",
                        adresse_ip=get_client_ip(request),
                    )
                except Exception:
                    logger.exception("[ResetMDP] AuditConnexion impossible")
            except Exception:
                logger.exception("[ResetMDP] Échec création du jeton de réinitialisation")
        # Message neutre : ne révèle jamais l'existence d'un compte
        messages.success(
            request,
            "Si un compte correspond à cet identifiant, un lien (email) ou "
            "un code (SMS) vous a été envoyé.",
        )
        return redirect('accounts:mot_de_passe_oublie')

    return render(request, 'accounts/mot_de_passe_oublie.html', {
        'email_ok': email_ok,
        'sms_ok': sms_ok,
        'duree': DUREE_VALIDITE_MINUTES,
    })


def _envoyer_lien_reset(request, user, jeton, lien, duree):
    """Envoie l'email contenant le lien de réinitialisation (et le code en rappel)."""
    sujet = "Réinitialisation de votre mot de passe — NexusERP"
    html = render_to_string('emails/reset_mdp_email.html', {
        'utilisateur': user,
        'lien': lien,
        'code': jeton.code,
        'duree': duree,
    })
    txt = (
        f"Bonjour {user.get_full_name() or user.username},\n\n"
        f"Vous avez demandé la réinitialisation de votre mot de passe.\n"
        f"Cliquez sur ce lien (valable {duree} minutes) :\n"
        f"{lien}\n\n"
        f"Code de vérification SMS : {jeton.code}\n\n"
        f"Si vous n'êtes pas à l'origine de cette demande, ignorez cet email.\n\n"
        f"— NexusERP"
    )
    return NotificationService.envoyer_email_direct(user.email, sujet, html, txt)


def reinitialiser_mot_de_passe(request, token=None):
    """Étape 2 : nouveau mot de passe après validation du lien (token) ou du code SMS."""
    if request.user.is_authenticated:
        return redirect('accounts:accueil_personnalise')

    erreur = None
    if request.method == 'POST':
        if _bloquage_actif(request) or _bloquage_ip_actif(request):
            erreur = ("Trop de tentatives. Réessayez dans 2 minutes.")
            return render(request, 'accounts/reinitialiser_mot_de_passe.html',
                          {'erreur': erreur, 'token': token, 'duree': DUREE_VALIDITE_MINUTES})

        token_saisi = (request.POST.get('token') or token or '').strip()
        code_saisi = request.POST.get('code', '').strip()
        nouveau = request.POST.get('nouveau_mdp', '')
        confirmer = request.POST.get('confirmer_mdp', '')

        valides = MotDePasseResetToken.objects.filter(
            utilise=False, expire_le__gte=timezone.now()
        )
        jeton = None
        if token_saisi:
            jeton = valides.filter(token=token_saisi).first()
        if jeton is None and code_saisi:
            jetons_code = valides.filter(code=code_saisi)
            # ✅ CORRECTION : si le compte demandé est connu en session
            # (parcours standard), le code ne peut valider QUE ce compte.
            reset_user_id = request.session.get('reset_user_id')
            jeton = (
                jetons_code.filter(user_id=reset_user_id).first()
                if reset_user_id else jetons_code.first()  # parcours multi-appareils
            )

        if jeton is None:
            _enregistrer_echec_code(request)
            _enregistrer_echec_code_ip(request)
            erreur = "Ce lien ou code est invalide ou a expiré. Veuillez refaire une demande."
        elif nouveau != confirmer:
            erreur = "Les mots de passe ne correspondent pas."
        else:
            erreurs = valider_mot_de_passe(nouveau, contexte='reset')
            if erreurs:
                erreur = "Mot de passe invalide : " + ", ".join(erreurs) + "."
            else:
                user = jeton.user
                user.set_password(nouveau)
                user.save()
                jeton.invalider()
                # ✅ CORRECTION : invalider TOUS les jetons restants du compte
                # (un lien email encore actif ne doit pas survivre au reset).
                MotDePasseResetToken.objects.filter(
                    user=user, utilise=False
                ).update(utilise=True)
                _reinitialiser_echecs(request)
                request.session.pop('reset_user_id', None)
                try:
                    profil = user.profil
                    profil.doit_changer_mdp = False
                    profil.save(update_fields=['doit_changer_mdp'])
                except Exception:
                    pass
                log_audit(
                    request,
                    f"Réinitialisation du mot de passe de {user.username} (mot de passe oublié)",
                    type_action='UPDATE', modele_concerne='User', id_objet=user.id,
                )
                try:
                    AuditConnexion.objects.create(
                        utilisateur=user,
                        type_action='PASSWORD_CHANGE',
                        description="Réinitialisation du mot de passe (mot de passe oublié)",
                        adresse_ip=get_client_ip(request),
                    )
                except Exception:
                    logger.exception("[ResetMDP] AuditConnexion PASSWORD_CHANGE impossible")
                messages.success(
                    request,
                    "✅ Mot de passe réinitialisé. Connectez-vous avec votre nouveau mot de passe.",
                )
                return redirect('accounts:custom_login')

    return render(request, 'accounts/reinitialiser_mot_de_passe.html', {
        'token': token,
        'erreur': erreur,
        'duree': DUREE_VALIDITE_MINUTES,
    })
