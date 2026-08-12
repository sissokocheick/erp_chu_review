"""
Stubs legacy pour stock/_services.py

Ce fichier est un fallback minimal si stock/_services.py n'existe pas.
Remplacez-le par votre vrai fichier legacy si vous l'avez.
"""
import logging
from django.utils import timezone

logger = logging.getLogger(__name__)


# ══════════════════════════════════════════════════════════════════════════════
# IMPORTS DES VRAIS SERVICES (mono-tenant)
# ══════════════════════════════════════════════════════════════════════════════
try:
    from .stock_service import StockService
except ImportError:
    StockService = None  # fallback si le module n'existe pas encore



class NumeroGenerator:
    """Génère un numéro de demande unique via le compteur global."""

    @staticmethod
    def generer_numero_demande(service):
        """Génère un numéro de demande via le compteur global."""
        from ..services.compteur_service import CompteurDocumentService
        return CompteurDocumentService.generer_numero_demande()


class PDFService:
    """Stub — ne génère pas de PDF (évite le crash)."""

    @staticmethod
    def generer_et_sauvegarder_pdf(bon, request, force=False):
        """
        Stub PDF — retourne None au lieu de lever une exception pour ne pas
        casser les flux qui appellent ce service sans try/except.
        Le warning dans les logs alerte l'administrateur.
        """
        msg = (
            f"[PDFService stub] PDF non généré pour {getattr(bon, 'numero_bon', bon)} — "
            f"le service PDF legacy n'est pas disponible. "
            f"Vérifiez que stock/_services.py existe et contient PDFService."
        )
        logger.warning(msg)
        return None  # ✅ CORRECTION : retourne None au lieu de RuntimeError


def _normaliser_telephone(tel):
    """Normalise un numéro local ivoirien en format international pour les API SMS.

    L'app stocke les téléphones en chiffres locaux (10 chiffres, ex. 0708091011).
    Le préfixe international +225 est ajouté, en CONSERVANT le 0 initial :
    0708091011 → +2250708091011. C'est le format sous lequel les numéros sont
    vérifiés chez Twilio (Verified Caller IDs) — en compte trial, Twilio
    compare le numéro à la lettre près (erreur 572002 sinon). Ce format est
    accepté et livré par Twilio.
    """
    tel = str(tel or '').strip()
    if not tel:
        return ''
    if tel.startswith('+'):
        return tel  # déjà international
    digits = ''.join(c for c in tel if c.isdigit())
    if len(digits) == 10 and digits.startswith('0'):
        return '+225' + digits  # numéro ivoirien local → +225 + 10 chiffres
    if digits:
        return '+' + digits  # autre numéro sans indicatif : best effort
    return tel


class NotificationService:
    """Crée une notification en base et la diffuse sur les canaux configurés.

    Canaux (si activés globalement par l'administrateur dans
    Paramètres → Notifications) :
    - Email : SMTP configuré dans Paramètres → Notifications.
    - SMS   : API HTTP générique / Twilio, ou mode test (journal).
    """

    @staticmethod
    def creer(utilisateur, titre, message, url=None, type_notif='INFO',
              categorie='SYSTEME', est_importante=False):
        """Crée la notification en base puis tente la diffusion email/SMS.

        - Email : toujours diffusé (si le canal est activé).
        - SMS   : UNIQUEMENT si ``est_importante=True`` — les SMS coûtent de
          l'argent, ils sont réservés aux notifications importantes
          (alertes, ajustements forcés…), pas aux simples informations.

        Ne lève JAMAIS d'exception : un échec d'envoi ne doit pas casser
        le flux métier qui a déclenché la notification.
        """
        try:
            from accounts.models import Notification
            notif = Notification.objects.create(
                utilisateur=utilisateur,
                titre=titre,
                message=message,
                url=url or '',
                type_notif=type_notif,
                categorie=categorie,
                est_importante=est_importante,
            )
            NotificationService._diffuser(utilisateur, notif)
            return notif
        except Exception:
            logger.exception(
                f"[NotificationService] Échec création notification "
                f"pour utilisateur {getattr(utilisateur, 'id', '?')}"
            )
            return None

    @staticmethod
    def _diffuser(utilisateur, notif):
        """Diffuse la notification selon la configuration globale (décision admin).

        - Email : si le canal email est activé → email à l'utilisateur (s'il a une adresse).
        - SMS   : si le canal SMS est activé ET que la notification est importante
          (``notif.est_importante``) → SMS à l'utilisateur (s'il a un téléphone).

        Il n'y a pas de préférence individuelle : la config globale s'applique
        à tous les utilisateurs.
        """
        try:
            from core.models import ConfigurationNotification
            config = ConfigurationNotification.get_instance()
        except Exception:
            logger.exception(
                "[NotificationService] Configuration de notification illisible"
            )
            return
        if config.activer_email:
            NotificationService.envoyer_email(utilisateur, notif)
        if config.activer_sms and notif.est_importante:
            NotificationService.envoyer_sms(utilisateur, notif)

    @staticmethod
    def _envoyer_email_vers(adresse, sujet, html, txt):
        """Envoi SMTP réel en réutilisant la config globale (hôte, port, TLS, identifiants).

        Si aucun hôte SMTP n'est configuré, on passe par le backend par défaut
        (locmem dans les tests, EMAIL_BACKEND en production).
        """
        from django.conf import settings as dj_settings
        from django.core.mail import EmailMultiAlternatives
        from django.core.mail import get_connection
        from core.models import ConfigurationNotification

        config = ConfigurationNotification.get_instance()
        conn = None
        if config.smtp_host and 'smtp' in dj_settings.EMAIL_BACKEND.lower():
            conn = get_connection(
                backend='django.core.mail.backends.smtp.EmailBackend',
                host=config.smtp_host,
                port=config.smtp_port,
                username=config.smtp_user or None,
                password=config.smtp_password or None,
                use_tls=config.smtp_use_tls,
                fail_silently=False,
            )

        email = EmailMultiAlternatives(
            subject=sujet, body=txt,
            from_email=config.email_expediteur or dj_settings.DEFAULT_FROM_EMAIL,
            to=[adresse],
            connection=conn,
        )
        email.attach_alternative(html, 'text/html')
        email.send(fail_silently=False)
        return True

    @staticmethod
    def envoyer_email(utilisateur, notif):
        """Envoie la notification par email (SMTP configuré)."""
        try:
            from django.template.loader import render_to_string
            from core.models import ConfigurationNotification

            config = ConfigurationNotification.get_instance()
            if not config.activer_email or not config.email_expediteur:
                logger.info(
                    f"[Notifications] Email désactivé — {notif.titre} "
                    f"pour {utilisateur.username}"
                )
                return False
            if not utilisateur.email:
                logger.info(
                    f"[Notifications] Pas d'adresse email pour "
                    f"{utilisateur.username} — email ignoré."
                )
                return False

            sujet = f"{notif.titre} — NexusERP"
            html = render_to_string('emails/notification_email.html', {
                'notif': notif,
                'utilisateur': utilisateur,
            })
            txt = f"{notif.titre}\n\n{notif.message}\n\n— NexusERP"

            NotificationService._envoyer_email_vers(utilisateur.email, sujet, html, txt)
            logger.info(
                f"[Notifications] Email envoyé à {utilisateur.email} : {notif.titre}"
            )
            return True
        except Exception:
            logger.exception(
                f"[Notifications] Échec envoi email pour {notif.titre}"
            )
            return False

    @staticmethod
    def envoyer_email_direct(adresse, sujet, html, txt):
        """Envoie un email hors notification (ex: lien de réinitialisation du mot de passe)."""
        try:
            from core.models import ConfigurationNotification
            config = ConfigurationNotification.get_instance()
            if not adresse or not config.email_expediteur:
                logger.info(
                    "[Notifications] Pas d'expéditeur configuré — email direct ignoré."
                )
                return False
            NotificationService._envoyer_email_vers(adresse, sujet, html, txt)
            logger.info(f"[Notifications] Email direct envoyé à {adresse} : {sujet}")
            return True
        except Exception:
            logger.exception(f"[Notifications] Échec envoi email direct à {adresse}")
            return False

    @staticmethod
    def _envoyer_sms_vers(telephone, texte, utiliser_modele_twilio=True):
        """Envoi SMS réel en réutilisant la config globale.

        Supporte :
        - Mode test (journal) : sms_mode_test=True → rien n'est réellement envoyé.
        - API HTTP générique : POST JSON {'<sms_param_numero>': tel,
          '<sms_param_message>': texte} avec en-tête Authorization: Bearer <clé>.
        - Twilio : utilise l'API Messages de Twilio si configurée.

        ``utiliser_modele_twilio`` : en compte trial Twilio, le Body doit être un
        modèle prédéfini (texte libre refusé). Pour les codes de réinitialisation
        on passe False : on envoie TOUJOURS le vrai texte (le code doit arriver).
        """
        import requests
        from core.models import ConfigurationNotification

        config = ConfigurationNotification.get_instance()
        telephone = _normaliser_telephone(telephone)

        if config.sms_mode_test or config.sms_provider == 'TEST':
            logger.info(
                f"[Notifications][SMS·TEST] À {telephone} — {texte}"
            )
            return True

        if config.sms_provider == 'TWILIO':
            # Twilio : POST .../Accounts/{SID}/Messages.json (Basic Auth SID:Token)
            base = config.sms_api_url or 'https://api.twilio.com/2010-04-01'
            account_sid, _, auth_token = config.sms_api_key.partition(':')
            url = (
                f"{base.rstrip('/')}/Accounts/{account_sid}/Messages.json"
                if account_sid
                else config.sms_api_url
            )
            auth = (account_sid, auth_token) if account_sid else None
            # Compte trial : Twilio exige un nom de modèle prédéfini comme
            # Body (erreur 572006 sinon). En compte payant, on envoie le
            # vrai texte de la notification.
            body = (config.sms_twilio_template or texte) if utiliser_modele_twilio else texte
            resp = requests.post(
                url, auth=auth, timeout=15,
                data={'From': config.sms_expediteur or '', 'To': telephone, 'Body': body},
            )
            if resp.status_code >= 400:
                # Log détaillé : les comptes trial Twilio refusent le texte libre
                # (erreur 572006) et n'acceptent que les modèles prédéfinis.
                detail = resp.text[:300]
                logger.error(
                    f"[Notifications] SMS Twilio REFUSÉ ({resp.status_code}) "
                    f"pour {telephone} : {detail}"
                )
                if config.sms_twilio_template and not utiliser_modele_twilio:
                    logger.error(
                        "[Notifications] Le compte Twilio semble en mode essai "
                        "(modèle prédéfini configuré) : le texte libre est refusé. "
                        "Le code de réinitialisation ne peut pas être envoyé par SMS "
                        "dans ce cas — repli sur l'email automatique."
                    )
                resp.raise_for_status()
            logger.info(f"[Notifications] SMS Twilio envoyé à {telephone}")
            return True

        # API HTTP générique (JSON)
        payload = {
            (config.sms_param_numero or 'to'): telephone,
            (config.sms_param_message or 'message'): texte,
        }
        if config.sms_expediteur:
            payload.setdefault('from', config.sms_expediteur)
        headers = {'Content-Type': 'application/json'}
        if config.sms_api_key:
            headers['Authorization'] = f"Bearer {config.sms_api_key}"
        resp = requests.post(
            config.sms_api_url, json=payload, headers=headers, timeout=15
        )
        resp.raise_for_status()
        logger.info(f"[Notifications] SMS envoyé à {telephone} via API générique")
        return True

    @staticmethod
    def envoyer_sms(utilisateur, notif):
        """Envoie la notification par SMS via l'API configurée."""
        try:
            from core.models import ConfigurationNotification

            config = ConfigurationNotification.get_instance()
            if not config.activer_sms:
                logger.info(f"[Notifications] SMS désactivé — {notif.titre}")
                return False

            profil = getattr(utilisateur, 'profil', None)
            telephone = getattr(profil, 'contact', None) if profil else None
            if not telephone:
                logger.info(
                    f"[Notifications] Pas de téléphone pour "
                    f"{utilisateur.username} — SMS ignoré."
                )
                return False

            texte = (
                f"[{notif.get_type_notif_display()}] {notif.titre}\n"
                f"{notif.message[:150]}"
            )
            return NotificationService._envoyer_sms_vers(telephone, texte)
        except Exception:
            logger.exception(f"[Notifications] Échec envoi SMS pour {notif.titre}")
            return False

    @staticmethod
    def envoyer_sms_direct(telephone, texte):
        """Envoie un SMS hors notification (ex: code de réinitialisation du mot de passe).

        Le texte réel est TOUJOURS envoyé (jamais remplacé par un modèle Twilio) :
        un code de réinitialisation doit obligatoirement arriver.
        """
        try:
            from core.models import ConfigurationNotification
            config = ConfigurationNotification.get_instance()
            if not config.activer_sms:
                logger.info("[Notifications] SMS désactivé — SMS direct ignoré.")
                return False
            if not telephone:
                logger.info("[Notifications] Pas de téléphone — SMS direct ignoré.")
                return False
            return NotificationService._envoyer_sms_vers(
                telephone, texte, utiliser_modele_twilio=False
            )
        except Exception:
            logger.exception(f"[Notifications] Échec envoi SMS direct à {telephone}")
            return False


class DemandeService:
    """Stub — logique métier minimale des demandes."""

    @staticmethod
    def recalculer_statut_apres_signature(demande):
        if hasattr(demande, 'actualiser_statut'):
            demande.actualiser_statut()

    @staticmethod
    def annuler(demande, user):
        """
        Annule une demande de matériel.

        Returns:
            tuple: (statut: str, message: str)
                - statut : 'ANNULEE', 'ANNULEE_DEJA', ou 'IMPOSSIBLE'
                - message : description de l'action
        """
        # ✅ CORRECTION : vérification du statut avant annulation
        statut_actuel = getattr(demande, 'statut', None)
        if statut_actuel in ('ANNULEE', 'CLOTUREE'):
            logger.warning(
                f"Tentative d'annulation d'une demande déjà {statut_actuel} "
                f"(ID: {demande.id})"
            )
            return 'ANNULEE_DEJA', f"Demande déjà {statut_actuel}."

        # Vérifier si des bons validés sont liés
        if hasattr(demande, 'livraisons'):
            bons_valides = demande.livraisons.filter(
                bon_sortie__statut_validation='VALIDE',
                bon_sortie__est_annule=False
            ).exists()
            if bons_valides:
                logger.warning(
                    f"Tentative d'annulation d'une demande avec bons validés "
                    f"(ID: {demande.id})"
                )
                return 'IMPOSSIBLE', "Impossible d'annuler : des bons validés sont liés."

            # ✅ CORRECTION : annuler les bons en ATTENTE liés pour éviter les orphelins
            # Utiliser bulk_update au lieu de N requêtes save()
            bons_attente = list(demande.livraisons.filter(
                bon_sortie__statut_validation='ATTENTE',
                bon_sortie__est_annule=False
            ).select_related('bon_sortie'))

            bons_a_annuler = []
            for liv in bons_attente:
                bon = liv.bon_sortie
                if bon:
                    bon.est_annule = True
                    bons_a_annuler.append(bon)

            if bons_a_annuler:
                from stock.models import BonMouvement, LivraisonPartielle
                BonMouvement.objects.bulk_update(bons_a_annuler, ['est_annule'])
                # Annuler aussi les livraisons liées pour ne pas fausser
                # quantite_servie_totale / reste de la demande
                LivraisonPartielle.objects.filter(
                    demande=demande, bon_sortie__in=bons_a_annuler
                ).update(est_annule=True)

        demande.statut = 'ANNULEE'
        # ✅ CORRECTION : utiliser update_fields pour éviter écrasement concurrent
        demande.save(update_fields=['statut'])
        return 'ANNULEE', f"Demande {getattr(demande, 'numero_demande', demande.id)} annulée."
