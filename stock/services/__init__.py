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
    def generer_numero_demande(service, entreprise=None):
        """
        ✅ CORRECTION MONO-TENANT : paramètre `entreprise` ignoré.
        Gardé pour compatibilité avec les appelants existants.
        """
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


class NotificationService:
    """Stub — crée une notification en base si le modèle existe."""

    @staticmethod
    def creer(utilisateur, titre, message, url, type_notif):
        try:
            from accounts.models import Notification
            return Notification.objects.create(
                utilisateur=utilisateur,
                titre=titre,
                message=message,
                url=url,
                type_notif=type_notif,
            )
        except (ImportError, RuntimeError, Exception):
            # ✅ CORRECTION : capturer Exception plus spécifiques
            # ImportError : modèle non trouvé
            # RuntimeError : problème d'import circulaire
            # Exception : fallback général (DB down, etc.)
            logger.exception(
                f"[NotificationService stub] Échec création notification "
                f"pour utilisateur {getattr(utilisateur, 'id', '?')}"
            )
            return None


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
                from stock.models import BonMouvement
                BonMouvement.objects.bulk_update(bons_a_annuler, ['est_annule'])

        demande.statut = 'ANNULEE'
        # ✅ CORRECTION : utiliser update_fields pour éviter écrasement concurrent
        demande.save(update_fields=['statut'])
        return 'ANNULEE', f"Demande {getattr(demande, 'numero_demande', demande.id)} annulée."
