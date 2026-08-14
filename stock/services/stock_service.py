# stock/services/stock_service.py
import logging
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.db import transaction
from stock.models import Mouvement, StockItem, Ajustement
from stock.services.stock_transaction_service import StockTransactionService
from decimal import Decimal

logger = logging.getLogger(__name__)


class StockService:
    """Service metier pour les operations de stock."""

    @staticmethod
    def _get_stock_item_sans_lot(article, magasin):
        """Helper pour eviter duplication du filtre batch_number."""
        return StockItem.objects.filter(
            (Q(batch_number__isnull=True) | Q(batch_number="")),
            article=article, magasin=magasin
        ).first()

    @staticmethod
    @transaction.atomic
    def ajuster_stock(ajustement, utilisateur=None):
        """
        Applique un ajustement de stock (ajout ou retrait).

        ✅ CORRECTIONS :
        - Idempotent : verifie si un mouvement existe deja avant d'en creer un
        - Thread-safe : select_for_update() sur l'ajustement pour bloquer les requetes paralleles
        - Anti-race-condition : le mouvement est cree en memoire puis execute() le sauvegarde
        - Verifie que l'ajustement est au statut VALIDE avant d'agir
        """
        if not utilisateur:
            utilisateur = getattr(ajustement, 'cree_par', None)

        if not utilisateur:
            raise ValueError("Un utilisateur est requis pour creer un mouvement d'ajustement.")

        if not ajustement.id:
            raise ValueError(
                "L'ajustement doit etre sauvegarde en base (ajustement.save()) "
                "avant d'appeler ajuster_stock()."
            )

        if not utilisateur or not utilisateur.is_active:
            raise ValidationError(
                "Vous devez etre connecte pour effectuer un ajustement de stock."
            )

        # 🔒 Verrouiller l'ajustement pour bloquer les requetes paralleles
        ajustement = Ajustement.objects.select_for_update().get(pk=ajustement.id)

        # ✅ Verifier que l'ajustement est bien au statut VALIDE
        if ajustement.statut_validation != 'VALIDE':
            raise ValidationError(
                "L'ajustement doit etre au statut VALIDE avant d'ajuster le stock."
            )

        article = ajustement.article
        magasin = ajustement.magasin
        quantite = ajustement.quantite
        motif = ajustement.motif

        if motif == 'AJOUT':
            type_mouvement = 'AJUSTEMENT_POS'
        elif motif in ('CASSE', 'PERTE', 'ERREUR'):
            type_mouvement = 'AJUSTEMENT_NEG'
        else:
            raise ValueError(f"Motif d'ajustement inconnu : {motif}")

        ref_doc = f"ADJ-{ajustement.id}"

        # 🔍 PROTECTION ANTI-DOUBLON : verifier si le mouvement existe deja
        if Mouvement.objects.filter(
            reference_document=ref_doc,
            type_mouvement=type_mouvement
        ).exists():
            logger.warning(
                f"[AJUSTER_STOCK] Mouvement deja existant pour ajustement {ajustement.id}. "
                f"Doublon ignore."
            )
            stock_item = StockService._get_stock_item_sans_lot(article, magasin)
            return ajustement, stock_item

        if type_mouvement == 'AJUSTEMENT_NEG':
            stock_item = StockService._get_stock_item_sans_lot(article, magasin)
            if not stock_item:
                raise ValidationError(
                    f"Stock inexistant pour {article.designation}. Impossible d'appliquer un ajustement negatif."
                )
            if stock_item.quantite_physique < quantite:
                raise ValidationError(
                    f"Quantite superieure au stock actuel ({stock_item.quantite_physique} disponible(s))"
                )

        # Creer le mouvement EN MEMOIRE (pas sauvegarde — executer() s'en charge)
        mouvement = Mouvement(
            type_mouvement=type_mouvement,
            article=article,
            magasin=magasin,
            quantite=quantite,
            utilisateur=utilisateur,
            reference_document=ref_doc,
            commentaire=ajustement.commentaire or f"Ajustement stock : {motif}",
        )

        # Executer le mouvement (sauvegarde + mise a jour du stock)
        mouvement = StockTransactionService.executer(mouvement)

        stock_item = getattr(mouvement, '_stock_item', None)
        if not stock_item:
            stock_item = StockService._get_stock_item_sans_lot(article, magasin)

        return ajustement, stock_item

    @staticmethod
    def _verifier_utilisateur_actif_helper(utilisateur, article=None, magasin=None):
        from django.core.exceptions import PermissionDenied
        if not utilisateur or not utilisateur.is_active:
            raise PermissionDenied("Utilisateur inactif ou non authentifie.")

    @staticmethod
    def appliquer_mouvement_entree(article, magasin, quantite, utilisateur, 
                                   prix_unitaire=None, reference_document='', 
                                   commentaire='', numero_lot=None, date_peremption=None):
        StockService._verifier_utilisateur_actif_helper(utilisateur, article, magasin)
        mouvement = Mouvement(
            type_mouvement='ENTREE',
            article=article,
            magasin=magasin,
            quantite=quantite,
            prix_unitaire=prix_unitaire,
            utilisateur=utilisateur,
            reference_document=reference_document,
            commentaire=commentaire,
            numero_lot=numero_lot,
            date_peremption=date_peremption,
        )
        return StockTransactionService.executer(mouvement)

    @staticmethod
    def appliquer_mouvement_sortie(article, magasin, quantite, utilisateur,
                                    reference_document='', commentaire='', 
                                    numero_lot=None):
        StockService._verifier_utilisateur_actif_helper(utilisateur, article, magasin)
        mouvement = Mouvement(
            type_mouvement='SORTIE',
            article=article,
            magasin=magasin,
            quantite=quantite,
            utilisateur=utilisateur,
            reference_document=reference_document,
            commentaire=commentaire,
            numero_lot=numero_lot,
        )
        return StockTransactionService.executer(mouvement)

    @staticmethod
    def get_quantite_a_date(article, magasin, date_reference, numero_lot=None):
        from django.db.models import Sum, Q

        filtre_entrees = {
            'article': article,
            'magasin': magasin,
            'type_mouvement__in': ['ENTREE', 'AJUSTEMENT_POS', 'RETOUR_SERVICE', 'TRANSFERT_ENTREE'],
            'date_mouvement__lte': date_reference,
        }
        filtre_sorties = {
            'article': article,
            'magasin': magasin,
            'type_mouvement__in': ['SORTIE', 'AJUSTEMENT_NEG', 'RETOUR_FOURNISSEUR', 'TRANSFERT_SORTIE'],
            'date_mouvement__lte': date_reference,
        }

        if numero_lot is None:
            filtre_entrees['numero_lot__isnull'] = True
            filtre_sorties['numero_lot__isnull'] = True
        else:
            filtre_entrees['numero_lot'] = numero_lot
            filtre_sorties['numero_lot'] = numero_lot

        entrees = Mouvement.objects.filter(
            **filtre_entrees
        ).exclude(
            Q(est_annule=True) | Q(is_deleted=True)
        ).aggregate(total=Sum('quantite'))['total'] or 0

        sorties = Mouvement.objects.filter(
            **filtre_sorties
        ).exclude(
            Q(est_annule=True) | Q(is_deleted=True)
        ).aggregate(total=Sum('quantite'))['total'] or 0

        return entrees - sorties
