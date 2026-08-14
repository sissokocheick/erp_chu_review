# -*- coding: utf-8 -*-
# stock/services/stock_transaction_service.py
from django.db import transaction
from django.db.models import Case, Value, When
from django.core.exceptions import ValidationError
from django.utils import timezone
from stock.models import Mouvement, StockItem
from decimal import Decimal

class StockTransactionService:
    """Service pour l'exécution des mouvements de stock."""

    TYPE_CONTRE_MOUVEMENT = {
        'ENTREE': 'RETOUR_FOURNISSEUR',
        'SORTIE': 'ENTREE',
        'AJUSTEMENT_POS': 'AJUSTEMENT_NEG',
        'AJUSTEMENT_NEG': 'AJUSTEMENT_POS',
        'AJUSTEMENT_NEG_FORCE': 'AJUSTEMENT_POS',
        'RETOUR_SERVICE': 'SORTIE',
        'RETOUR_FOURNISSEUR': 'ENTREE',
    }

    @staticmethod
    def resoudre_lots_fefo(article, magasin, quantite):
        """Résout une sortie d'article géré en lot en consommations FEFO.

        - Consomme d'abord les lots dont la péremption est la plus proche
          (First-Expired-First-Out).
        - Bloque la sortie des lots déjà périmés (destruction requise).
        - Retourne [] si l'article ne gère pas les lots (comportement hérité,
          consommation sur le stock générique sans lot).
        - Lève ValidationError si le stock disponible non périmé est
          insuffisant, en précisant les quantités périmées bloquées.

        Returns:
            list[dict] — [{'numero_lot', 'date_peremption', 'quantite'}]
        """
        if not article.requiert_lot_peremption:
            return []

        aujourdhui = timezone.now().date()

        # Lots avec stock positif, les plus proches de péremption d'abord
        # (les lots sans date de péremption passent en dernier).
        lots = list(
            StockItem.objects.filter(
                article=article,
                magasin=magasin,
                batch_number__isnull=False,
                quantite_physique__gt=0,
            ).order_by(
                Case(When(expiry_date__isnull=True, then=Value(1)), default=Value(0)),
                'expiry_date',
                'id',
            )
        )

        lots_valides = [
            l for l in lots
            if l.expiry_date is None or l.expiry_date >= aujourdhui
        ]
        lots_perimes = [
            l for l in lots
            if l.expiry_date is not None and l.expiry_date < aujourdhui
        ]

        total_dispo = sum(l.quantite_physique for l in lots_valides)
        if total_dispo < quantite:
            total_perime = sum(l.quantite_physique for l in lots_perimes)
            msg = (
                f"Stock insuffisant pour {article.designation} : {total_dispo} "
                f"disponible(s) hors lots périmés, {quantite} demandé(s)."
            )
            if total_perime:
                msg += (
                    f" {total_perime} unité(s) bloquée(s) : lot(s) périmé(s) "
                    f"— destruction requise avant toute sortie."
                )
            raise ValidationError(msg, code='stock_insuffisant')

        restant = quantite
        consommations = []
        for lot in lots_valides:
            if restant <= 0:
                break
            pris = min(lot.quantite_physique, restant)
            consommations.append({
                'numero_lot': lot.batch_number,
                'date_peremption': lot.expiry_date,
                'quantite': pris,
            })
            restant -= pris
        return consommations

    @classmethod
    @transaction.atomic
    def executer(cls, mouvement):
        """
        Exécute un mouvement de stock : sauvegarde et met à jour le stock.
        Retourne le mouvement sauvegardé.

        ⚠️ Nécessite que Mouvement.save() gère le paramètre update_stock=False
        pour éviter la double mise à jour du stock.
        """
        if mouvement.pk:
            raise ValidationError("Impossible d'exécuter un mouvement déjà sauvegardé.")

        # Sauvegarder le mouvement (update_stock=False pour contrôler nous-mêmes)
        mouvement.save(update_stock=False)

        # Mettre à jour le stock
        stock_item = cls._maj_stock(mouvement)

        # ✅ CORRECTION : attacher le StockItem au mouvement pour éviter re-requête
        mouvement._stock_item = stock_item
        return mouvement

    @classmethod
    def executer_batch(cls, mouvements):
        """
        ✅ CORRECTION : Exécute plusieurs mouvements de manière atomique.
        Utilise une seule transaction atomique englobante.
        """
        resultats = []
        with transaction.atomic():
            for mouvement in mouvements:
                resultats.append(cls.executer(mouvement))
        return resultats

    @classmethod
    def _maj_stock(cls, mouvement):
        """Met à jour le StockItem après un mouvement."""
        if mouvement.type_mouvement == 'SORTIE_HORS_STOCK':
            return None

        if not mouvement.magasin:
            raise ValidationError("Un magasin est requis pour ce type de mouvement.")

        batch = mouvement.numero_lot if mouvement.numero_lot else None

        # ✅ CORRECTION : éviter la race condition get_or_create avec select_for_update
        try:
            stock_item = StockItem.objects.select_for_update().get(
                article=mouvement.article,
                magasin=mouvement.magasin,
                batch_number=batch,
            )
        except StockItem.DoesNotExist:
            stock_item = StockItem.objects.create(
                article=mouvement.article,
                magasin=mouvement.magasin,
                batch_number=batch,
                quantite_physique=0,
                valeur_cmup=mouvement.prix_unitaire or 0,
            )

        # Propager la date de péremption si présente
        if mouvement.date_peremption:
            stock_item.expiry_date = mouvement.date_peremption

        if mouvement.type_mouvement == 'ENTREE':
            ancienne_qte = stock_item.quantite_physique
            ancienne_val = stock_item.valeur_cmup or Decimal('0')
            nouvelle_qte = ancienne_qte + mouvement.quantite

            # ✅ CORRECTION : recalculer CMUP UNIQUEMENT pour ENTREE (pas AJUSTEMENT_POS)
            if mouvement.prix_unitaire and nouvelle_qte > 0:
                try:
                    pu = Decimal(str(mouvement.prix_unitaire))
                except (ValueError, TypeError, decimal.InvalidOperation):
                    raise ValidationError(f"Prix unitaire invalide : {mouvement.prix_unitaire}")
                nouveau_cmup = ((ancienne_val * ancienne_qte) + (pu * mouvement.quantite)) / nouvelle_qte
                stock_item.valeur_cmup = nouveau_cmup.quantize(Decimal('0.01'))

            stock_item.quantite_physique = nouvelle_qte

        elif mouvement.type_mouvement in ('AJUSTEMENT_POS', 'RETOUR_SERVICE'):
            ancienne_qte = stock_item.quantite_physique
            nouvelle_qte = ancienne_qte + mouvement.quantite

            # ✅ CORRECTION : AJUSTEMENT_POS et RETOUR_SERVICE ne recalculent PAS le CMUP
            # Ils conservent le CMUP existant. Seul cas où on met à jour : stock était à 0
            if ancienne_qte == 0 and mouvement.prix_unitaire:
                stock_item.valeur_cmup = Decimal(str(mouvement.prix_unitaire)).quantize(Decimal('0.01'))
            # Sinon, le CMUP reste inchangé

            stock_item.quantite_physique = nouvelle_qte

        elif mouvement.type_mouvement == 'AJUSTEMENT_NEG_FORCE':
            # ✅ CORRECTION : ajustement négatif forcé — bloquer à 0, pas négatif
            ancienne_qte = stock_item.quantite_physique
            nouvelle_qte = max(0, ancienne_qte - mouvement.quantite)
            stock_item.quantite_physique = nouvelle_qte
            # Logger le forçage si quantité différente
            if nouvelle_qte != (ancienne_qte - mouvement.quantite):
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(
                    f"AJUSTEMENT_NEG_FORCE bloqué à 0 : stock={ancienne_qte}, "
                    f"demandé={mouvement.quantite}, appliqué={ancienne_qte - nouvelle_qte}"
                )

        elif mouvement.type_mouvement in ('SORTIE', 'AJUSTEMENT_NEG', 'RETOUR_FOURNISSEUR'):
            if stock_item.quantite_physique < mouvement.quantite:
                raise ValidationError(
                    f"Stock insuffisant dans {mouvement.magasin}: {stock_item.quantite_physique} disponible(s)",
                    code='stock_insuffisant'
                )

            ancienne_qte = stock_item.quantite_physique
            nouvelle_qte = ancienne_qte - mouvement.quantite

            # ✅ CORRECTION : ne PAS reset le CMUP à 0 quand stock = 0
            # On conserve le dernier CMUP connu pour l'historique de valorisation
            stock_item.quantite_physique = nouvelle_qte

        # Sauvegarder aussi expiry_date si modifiée
        update_fields = ['quantite_physique', 'valeur_cmup']
        if mouvement.date_peremption:
            update_fields.append('expiry_date')
        stock_item.save(update_fields=update_fields)
        return stock_item

    @classmethod
    @transaction.atomic
    def annuler_par_contre_mouvement(cls, mouvement_original, utilisateur, commentaire=""):
        """
        Crée un contre-mouvement pour annuler un mouvement original.
        """
        if not mouvement_original.pk:
            raise ValidationError("Le mouvement original doit être sauvegardé.")

        type_contre = cls.TYPE_CONTRE_MOUVEMENT.get(mouvement_original.type_mouvement)
        if not type_contre:
            raise ValidationError(f"Type de mouvement non mappé pour annulation : {mouvement_original.type_mouvement}")

        # Déterminer le prix unitaire du contre-mouvement
        prix_unitaire = mouvement_original.prix_unitaire

        # ✅ CORRECTION : récupérer le CMUP actuel pour TOUS les types (pas seulement ENTREE)
        filtre = {
            'article': mouvement_original.article,
            'magasin': mouvement_original.magasin,
        }
        if mouvement_original.numero_lot:
            filtre['batch_number'] = mouvement_original.numero_lot
        else:
            filtre['batch_number__isnull'] = True

        stock_item = StockItem.objects.filter(**filtre).first()
        if stock_item and stock_item.valeur_cmup:
            prix_unitaire = stock_item.valeur_cmup

        contre_mouvement = Mouvement(
            type_mouvement=type_contre,
            article=mouvement_original.article,
            magasin=mouvement_original.magasin,
            quantite=mouvement_original.quantite,
            prix_unitaire=prix_unitaire,
            utilisateur=utilisateur,
            reference_document=f"ANNULATION-{mouvement_original.reference_document}",
            commentaire=commentaire,
            numero_lot=mouvement_original.numero_lot,
            service_demandeur=mouvement_original.service_demandeur,
            fournisseur=mouvement_original.fournisseur,
        )

        contre_mouvement.save(update_stock=False)
        cls._maj_stock(contre_mouvement)

        # ✅ CORRECTION : marquer le mouvement original comme annulé
        mouvement_original.est_annule = True
        mouvement_original.save(update_fields=['est_annule'], update_stock=False)

        return contre_mouvement
