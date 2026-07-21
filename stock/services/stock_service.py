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
    """Service métier pour les opérations de stock."""

    @staticmethod
    def _get_stock_item_sans_lot(article, magasin):
        """✅ CORRECTION : Helper pour éviter duplication du filtre batch_number."""
        return StockItem.objects.filter(
            (Q(batch_number__isnull=True) | Q(batch_number="")),
            article=article, magasin=magasin
        ).first()

    @staticmethod
    @transaction.atomic  # ✅ CORRECTION : ajout transaction atomique
    def ajuster_stock(ajustement, utilisateur=None):
        """
        Applique un ajustement de stock (ajout ou retrait).
        """
        if not utilisateur:
            utilisateur = getattr(ajustement, 'cree_par', None)

        if not utilisateur:
            raise ValueError("Un utilisateur est requis pour créer un mouvement d'ajustement.")

        # Vérification défensive : l'ajustement doit être sauvegardé en base
        if not ajustement.id:
            raise ValueError(
                "L'ajustement doit être sauvegardé en base (ajustement.save()) "
                "avant d'appeler ajuster_stock()."
            )

        # ✅ CORRECTION : vérification des permissions (entreprise/magasin)
        # Si l'utilisateur n'a pas de profil → REFUS (pas de bypass)
        try:
            profil = utilisateur.profil
            entreprise_user = profil.entreprise
            magasin_user = getattr(profil, 'magasin', None)
        except AttributeError:
            # ✅ CORRECTION : capturer uniquement AttributeError, pas Exception
            logger.warning(
                f"Tentative d'ajustement par un utilisateur sans profil : {utilisateur}"
            )
            raise ValidationError(
                "Vous devez avoir un profil utilisateur pour effectuer un ajustement de stock."
            )

        article = ajustement.article
        magasin = ajustement.magasin

        # ✅ CORRECTION : refuser si l'utilisateur n'a pas d'entreprise rattachée
        if not entreprise_user:
            raise ValidationError(
                "Vous devez avoir un profil entreprise pour effectuer un ajustement de stock."
            )
        # Vérifier que l'utilisateur appartient à la même entreprise
        if article.entreprise != entreprise_user:
            raise ValidationError(
                "Vous n'avez pas le droit d'ajuster le stock d'un article d'une autre entreprise."
            )
        if magasin_user and magasin != magasin_user:
            raise ValidationError(
                "Vous n'avez pas le droit d'ajuster le stock d'un autre magasin."
            )

        quantite = ajustement.quantite
        motif = ajustement.motif  # 'CASSE', 'PERTE', 'ERREUR', 'AJOUT'

        # Déterminer le type de mouvement
        if motif == 'AJOUT':
            type_mouvement = 'AJUSTEMENT_POS'
        elif motif in ('CASSE', 'PERTE', 'ERREUR'):
            type_mouvement = 'AJUSTEMENT_NEG'
        else:
            raise ValueError(f"Motif d'ajustement inconnu : {motif}")

        # Vérifier le stock disponible UNIQUEMENT pour un retrait
        if type_mouvement == 'AJUSTEMENT_NEG':
            # ✅ CORRECTION : utiliser le helper factorisé
            stock_item = StockService._get_stock_item_sans_lot(article, magasin)
            if not stock_item:
                # ✅ CORRECTION : ne PAS créer un stock_item inutilement
                # Si pas de stock, on ne peut pas retirer
                raise ValidationError(
                    f"Stock inexistant pour {article.designation}. Impossible d'appliquer un ajustement négatif."
                )
            if stock_item.quantite_physique < quantite:
                raise ValidationError(
                    f"Quantité supérieure au stock actuel ({stock_item.quantite_physique} disponible(s))"
                )

        # Créer et exécuter le mouvement
        mouvement = Mouvement(
            type_mouvement=type_mouvement,
            article=article,
            magasin=magasin,
            quantite=quantite,
            utilisateur=utilisateur,
            reference_document=f"AJUST-{ajustement.id}",
            commentaire=ajustement.commentaire or f"Ajustement stock : {motif}",
        )

        mouvement = StockTransactionService.executer(mouvement)

        # ✅ CORRECTION : utiliser le StockItem attaché au mouvement pour éviter re-requête
        stock_item = getattr(mouvement, '_stock_item', None)
        if not stock_item:
            stock_item = StockService._get_stock_item_sans_lot(article, magasin)

        return ajustement, stock_item

    @staticmethod
    def _verifier_entreprise_helper(utilisateur, article, magasin):
        """Vérifie l'isolation entreprise pour les helpers de mouvement."""
        from django.core.exceptions import PermissionDenied
        try:
            entreprise_user = utilisateur.profil.entreprise
        except AttributeError:
            raise PermissionDenied("Utilisateur sans profil entreprise.")
        if article.entreprise != entreprise_user:
            raise PermissionDenied("Article d'une autre entreprise.")
        if magasin.entreprise != entreprise_user:
            raise PermissionDenied("Magasin d'une autre entreprise.")

    @staticmethod
    def appliquer_mouvement_entree(article, magasin, quantite, utilisateur, 
                                   prix_unitaire=None, reference_document='', 
                                   commentaire='', numero_lot=None, date_peremption=None):
        """Helper pour créer une entrée de stock."""
        # ✅ CORRECTION : vérifier l'isolation entreprise
        StockService._verifier_entreprise_helper(utilisateur, article, magasin)
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
        """Helper pour créer une sortie de stock."""
        # ✅ CORRECTION : vérifier l'isolation entreprise
        StockService._verifier_entreprise_helper(utilisateur, article, magasin)
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
        """
        ✅ CORRECTION : Calcule la quantité théorique à une date donnée.

        Args:
            numero_lot: str|None — si fourni, calcule uniquement pour ce lot
        """
        from django.db.models import Sum, Q

        # Construire le filtre de base
        filtre_entrees = {
            'article': article,
            'magasin': magasin,
            'type_mouvement__in': ['ENTREE', 'AJUSTEMENT_POS', 'RETOUR_SERVICE'],
            'date_mouvement__lte': date_reference,
        }
        filtre_sorties = {
            'article': article,
            'magasin': magasin,
            'type_mouvement__in': ['SORTIE', 'AJUSTEMENT_NEG', 'RETOUR_FOURNISSEUR'],
            'date_mouvement__lte': date_reference,
        }

        # ✅ CORRECTION : filtrer correctement par lot
        if numero_lot is None:
            # Si numero_lot=None, on veut UNIQUEMENT les mouvements SANS lot
            filtre_entrees['numero_lot__isnull'] = True
            filtre_sorties['numero_lot__isnull'] = True
        else:
            # Si numero_lot est fourni, filtrer par ce lot spécifique
            filtre_entrees['numero_lot'] = numero_lot
            filtre_sorties['numero_lot'] = numero_lot

        # Exclure les mouvements annulés/supprimés
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
