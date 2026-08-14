# -*- coding: utf-8 -*-
# stock/services/transfert_service.py
"""Service de transfert inter-magasins.

Un transfert déplace du stock d'un magasin source vers un magasin
destination sans passer par un fournisseur ni un service. Il est tracé
par deux mouvements liés (TRANSFERT_SORTIE dans le magasin source,
TRANSFERT_ENTREE dans le magasin destination) partageant le même
reference_document (numéro du bon de transfert).

Les articles gérés en lot/péremption sont consommés en FEFO côté source
(lots périmés bloqués) et le lot + la date de péremption sont conservés
à l'arrivée dans le magasin destination.
"""
from django.core.exceptions import ValidationError
from django.db import transaction

from stock.models import BonMouvement, LigneBon, Mouvement
from stock.services.compteur_service import CompteurDocumentService
from stock.services.stock_transaction_service import StockTransactionService


class TransfertService:
    """Gère les transferts de stock entre magasins."""

    @staticmethod
    def _verifier_utilisateur(utilisateur):
        if not utilisateur or not utilisateur.is_active:
            raise ValidationError("Utilisateur inactif ou non authentifié.")

    @classmethod
    @transaction.atomic
    def creer_transfert(cls, utilisateur, magasin_source, magasin_destination,
                        lignes, commentaire=""):
        """
        Crée un bon de transfert et exécute les mouvements de stock.

        Args:
            utilisateur: utilisateur connecté (créateur du transfert).
            magasin_source: Magasin d'où sort le stock.
            magasin_destination: Magasin où entre le stock (≠ source).
            lignes: liste de dicts {'article': Article, 'quantite': int,
                    'numero_lot': str|None, 'date_peremption': date|None}.
            commentaire: texte libre.

        Returns:
            BonMouvement créé (type_bon='TRANSFERT').

        Raises:
            ValidationError si magasins invalides, aucune ligne, stock
            insuffisant côté source ou lot périmé.
        """
        cls._verifier_utilisateur(utilisateur)
        if not magasin_source or not magasin_destination:
            raise ValidationError(
                "Les magasins source et destination sont obligatoires.")
        if magasin_source.id == magasin_destination.id:
            raise ValidationError(
                "Le magasin de destination doit être différent du magasin source.")
        if not lignes:
            raise ValidationError("Aucune ligne de transfert fournie.")

        bon = BonMouvement(
            type_bon='TRANSFERT',
            numero_bon=CompteurDocumentService.generer_numero_bon('TRANSFERT'),
            magasin=magasin_source,
            magasin_destination=magasin_destination,
            commentaire=commentaire or None,
            cree_par=utilisateur,
        )
        bon.save()

        for ligne_data in lignes:
            article = ligne_data.get('article')
            quantite = ligne_data.get('quantite')
            if not article or not quantite or quantite <= 0:
                continue

            # FEFO pour les articles gérés en lot : découpe la sortie par lot
            # (péremption la plus proche d'abord, lots périmés bloqués).
            consommations = StockTransactionService.resoudre_lots_fefo(
                article, magasin_source, quantite)
            if consommations:
                for conso in consommations:
                    cls._transferer_ligne(
                        bon, utilisateur, article, magasin_source,
                        magasin_destination, conso['quantite'],
                        conso['numero_lot'], conso['date_peremption'])
            else:
                cls._transferer_ligne(
                    bon, utilisateur, article, magasin_source,
                    magasin_destination, quantite,
                    ligne_data.get('numero_lot'),
                    ligne_data.get('date_peremption'))

        return bon

    @staticmethod
    def _transferer_ligne(bon, utilisateur, article, magasin_source,
                          magasin_destination, quantite, numero_lot,
                          date_peremption):
        """Exécute la sortie (source) puis l'entrée (destination) d'une ligne."""
        ref = bon.numero_bon

        # ── Sortie du magasin source (vérifie le stock, décrémente) ──
        mvt_sortie = Mouvement(
            type_mouvement='TRANSFERT_SORTIE',
            article=article,
            magasin=magasin_source,
            quantite=quantite,
            utilisateur=utilisateur,
            reference_document=ref,
            numero_lot=numero_lot,
            date_peremption=date_peremption,
            commentaire=f"Transfert vers {magasin_destination.nom}",
        )
        StockTransactionService.executer(mvt_sortie)

        # Prix transféré = CMUP du stock source (pour valoriser l'entrée).
        stock_source = getattr(mvt_sortie, '_stock_item', None)
        prix = stock_source.valeur_cmup if stock_source else None

        # ── Entrée dans le magasin destination (incrémente, conserve lot) ──
        mvt_entree = Mouvement(
            type_mouvement='TRANSFERT_ENTREE',
            article=article,
            magasin=magasin_destination,
            quantite=quantite,
            utilisateur=utilisateur,
            reference_document=ref,
            numero_lot=numero_lot,
            date_peremption=date_peremption,
            prix_unitaire=prix,
            commentaire=f"Transfert depuis {magasin_source.nom}",
        )
        StockTransactionService.executer(mvt_entree)

        LigneBon.objects.create(
            bon=bon,
            article=article,
            quantite=quantite,
            numero_lot=numero_lot,
            date_peremption=date_peremption,
            prix_unitaire=prix,
        )

    @classmethod
    @transaction.atomic
    def annuler_transfert(cls, bon, utilisateur, motif=""):
        """
        Annule un bon de transfert : contre-mouvements sur les deux magasins.

        Le stock revient dans le magasin source (l'entrée en destination est
        retirée, la sortie source est réintégrée) via contre-mouvements, et
        le bon est marqué annulé.
        """
        cls._verifier_utilisateur(utilisateur)
        if bon.type_bon != 'TRANSFERT':
            raise ValidationError("Ce document n'est pas un transfert.")
        if bon.est_annule:
            raise ValidationError("Ce transfert est déjà annulé.")

        mouvements = Mouvement.objects.filter(
            reference_document=bon.numero_bon,
            type_mouvement__in=['TRANSFERT_SORTIE', 'TRANSFERT_ENTREE'],
            est_annule=False,
        )

        for mvt in mouvements:
            # Le service annule le mouvement ET sauvegarde le contre-mouvement.
            StockTransactionService.annuler_par_contre_mouvement(
                mvt, utilisateur,
                commentaire=f"Annulation transfert {bon.numero_bon} — {motif}".strip())

        bon.est_annule = True
        bon.motif_annulation = None
        bon.annule_par = utilisateur
        from django.utils import timezone
        bon.date_annulation = timezone.now()
        bon.commentaire = (bon.commentaire or "") + f" [ANNULÉ] {motif}".strip()
        bon.save(update_fields=[
            'est_annule', 'annule_par', 'date_annulation', 'commentaire',
        ])
        return bon
