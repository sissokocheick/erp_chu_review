# -*- coding: utf-8 -*-
import logging
from decimal import Decimal

from django.db import transaction
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.utils import timezone

from ..services.stock_transaction_service import StockTransactionService

logger = logging.getLogger(__name__)


class LivraisonService:
    """Traitement des demandes, livraisons partielles et destructions."""

    @staticmethod
    def _verifier_utilisateur(utilisateur, demande=None):
        """✅ CORRECTION MONO-TENANT : vérifie que l'utilisateur est actif.
        Le paramètre demande est conservé pour compatibilité mais ignoré.
        """
        from django.core.exceptions import PermissionDenied
        if not utilisateur or not utilisateur.is_active:
            raise PermissionDenied("Utilisateur inactif ou non authentifié.")

    @staticmethod
    @transaction.atomic
    def traiter_demande(demande, magasin_id, lignes_qte_map, user,
                        cloturer=False, motif_cloture=''):
        """
        Traite une demande matériel : crée le bon de sortie, la livraison partielle,
        les lignes et les mouvements de stock (si pas de circuit de validation).
        """
        from ..models import (
            BonMouvement, LigneBon, LivraisonPartielle, LivraisonLigne,
            Mouvement, StockItem, AccuseReception, CircuitValidation,
            LigneDemande
        )

        # ✅ CORRECTION MONO-TENANT : vérification utilisateur
        LivraisonService._verifier_utilisateur(user, demande)

        circuit_sortie = CircuitValidation.objects.filter(
            type_document='SORTIE',
            est_actif=True
        ).first()

        from ..services.compteur_service import CompteurDocumentService

        # ── Génération du numéro de bon ──
        numero_bon = CompteurDocumentService.generer_numero_bon('SORTIE')

        bon = BonMouvement.objects.create(
            type_bon='SORTIE',
            numero_bon=numero_bon,
            magasin_id=magasin_id,
            service_demandeur=demande.service_demandeur,
            cree_par=user,
            commentaire=f"Livraison — demande {demande.numero_demande}",
            statut_validation='ATTENTE' if circuit_sortie else 'VALIDE',
        )

        livraison = LivraisonPartielle.objects.create(
            demande=demande,
            livre_par=user,
            bon_sortie=bon,
            quantite_livree=0
        )

        total_livre = 0
        au_moins_un = False
        est_livraison_partielle = False

        # ✅ CORRECTION : précalculer les quantités déjà livrées pour éviter N+1
        livraisons_par_article = dict(
            LivraisonLigne.objects.filter(livraison__demande=demande)
            .values('article_id')
            .annotate(total=Sum('quantite_livree'))
            .values_list('article_id', 'total')
        )

        for ligne in demande.lignes_demande.select_related('article').all():
            qte = lignes_qte_map.get(ligne.id, 0)
            if qte <= 0:
                continue

            # ✅ CORRECTION : verrouiller la ligne de demande en concurrence
            ligne_verrouillee = LigneDemande.objects.select_for_update().get(id=ligne.id)

            # ── Calculer le reste AVANT cette livraison (précalculé) ──
            qte_livree_precedente = livraisons_par_article.get(ligne.article_id, 0)
            reste_avant = ligne_verrouillee.quantite_demandee - qte_livree_precedente

            if qte > reste_avant:
                raise ValidationError(
                    f"Quantité invalide pour {ligne.article.designation} : "
                    f"reste {reste_avant} à livrer."
                )

            # ✅ CORRECTION : éviter race condition get_or_create avec select_for_update
            # ✅ FEFO : pour les articles gérés en lot, la disponibilité
            # s'apprécie par lots (hors lots périmés, qui sont bloqués).
            consos_fefo = []
            prix_unitaire_ligne = Decimal('0')
            if ligne.article.requiert_lot_peremption:
                consos_fefo = StockTransactionService.resoudre_lots_fefo(
                    ligne.article, bon.magasin, qte)
                premier_lot = consos_fefo[0] if consos_fefo else None
                stock_item = StockItem.objects.select_for_update().filter(
                    article=ligne.article, magasin_id=magasin_id,
                    batch_number=premier_lot['numero_lot'] if premier_lot else None,
                ).first()
            else:
                try:
                    stock_item = StockItem.objects.select_for_update().get(
                        article=ligne.article, magasin_id=magasin_id
                    )
                except StockItem.DoesNotExist:
                    stock_item = StockItem.objects.create(
                        article=ligne.article, magasin_id=magasin_id,
                        quantite_physique=0, valeur_cmup=0
                    )

                if qte > stock_item.quantite_physique:
                    raise ValidationError(
                        f"Stock insuffisant pour {ligne.article.designation} : "
                        f"{stock_item.quantite_physique} disponible(s)."
                    )

            if stock_item:
                prix_unitaire_ligne = stock_item.valeur_cmup

            au_moins_un = True
            total_livre += qte

            # ── Calculer le reste APRÈS cette livraison ──
            reste_apres = reste_avant - qte
            if reste_apres > 0:
                est_livraison_partielle = True

            LigneBon.objects.create(
                bon=bon,
                article=ligne.article,
                quantite=qte
            )
            # ✅ CORRECTION : sémantique correcte — reste_avant_livraison au lieu de quantite_demandee
            LivraisonLigne.objects.create(
                livraison=livraison,
                article=ligne.article,
                quantite_demandee=ligne_verrouillee.quantite_demandee,  # ✅ VRAIE quantité demandée
                reste_avant_livraison=reste_avant,  # ✅ NOUVEAU CHAMP : reste avant cette livraison
                quantite_livree=qte,
                reste=reste_apres,
                prix_unitaire=prix_unitaire_ligne,
            )

            if not circuit_sortie:
                # ✅ FEFO : un mouvement par lot consommé (traçabilité complète)
                if consos_fefo:
                    for conso in consos_fefo:
                        mouvement = Mouvement(
                            type_mouvement='SORTIE',
                            article=ligne.article,
                            magasin_id=magasin_id,
                            service_demandeur=demande.service_demandeur,
                            quantite=conso['quantite'],
                            prix_unitaire=prix_unitaire_ligne,
                            reference_document=bon.numero_bon,
                            utilisateur=user,
                            commentaire=f"Sortie via Bon {bon.numero_bon}",
                            numero_lot=conso['numero_lot'],
                            date_peremption=conso['date_peremption'],
                        )
                        StockTransactionService.executer(mouvement)
                else:
                    mouvement = Mouvement(
                        type_mouvement='SORTIE',
                        article=ligne.article,
                        magasin_id=magasin_id,
                        service_demandeur=demande.service_demandeur,
                        quantite=qte,
                        prix_unitaire=prix_unitaire_ligne,
                        reference_document=bon.numero_bon,
                        utilisateur=user,
                        commentaire=f"Sortie via Bon {bon.numero_bon}",
                    )
                    StockTransactionService.executer(mouvement)

        if not au_moins_un:
            # ✅ CORRECTION : pas de delete() manuel — @transaction.atomic fera le rollback
            raise ValidationError("Aucune quantité saisie. Livraison annulée.")

        livraison.quantite_livree = total_livre
        livraison.est_partielle = est_livraison_partielle
        livraison.save(update_fields=['quantite_livree', 'est_partielle'])

        AccuseReception.objects.create(
            livraison=livraison,
            est_signe=False
        )

        if not demande.bon_sortie_lie:
            demande.bon_sortie_lie = bon
            demande.valide_par = user
            demande.date_validation = timezone.now()
            demande.save(update_fields=['bon_sortie_lie', 'valide_par', 'date_validation'])

        if cloturer and demande.reste > 0:
            demande.statut = 'CLOTUREE'
            demande.motif_cloture = motif_cloture or "Clôturé manuellement dès le traitement initial."
            demande.cloture_par = user
            demande.date_cloture = timezone.now()
            demande.save(update_fields=['statut', 'motif_cloture', 'cloture_par', 'date_cloture'])

        return livraison, bon, total_livre

    @staticmethod
    @transaction.atomic
    def annuler_bons_en_attente(demande, user):
        """
        Annule les bons de sortie en attente liés à une demande.
        """
        from ..models import LivraisonPartielle, MotifAnnulation, Mouvement, AccuseReception

        # ✅ CORRECTION MONO-TENANT : vérification utilisateur
        LivraisonService._verifier_utilisateur(user, demande)

        livraisons_en_attente = demande.livraisons.filter(
            bon_sortie__statut_validation='ATTENTE'
        ).select_related('bon_sortie')

        if not livraisons_en_attente.exists():
            return None, "Aucun bon en attente à annuler."

        # ✅ CORRECTION : utiliser un code interne unique pour éviter collision
        from ..models import MotifAnnulation
        motif_defaut, _ = MotifAnnulation.objects.get_or_create(
            libelle="ANNULATION AUTOMATIQUE",
            defaults={'actif': True, 'cree_par': user, 'modifie_par': user}
        )

        for liv in livraisons_en_attente:
            bon = liv.bon_sortie
            if bon and not bon.est_annule:
                # ✅ CORRECTION : soft delete des objets liés au lieu de hard delete
                try:
                    accuse = AccuseReception.objects.get(livraison=liv)
                    accuse.est_signe = False
                    accuse.save(update_fields=['est_signe'])
                except AccuseReception.DoesNotExist:
                    pass

                # Les bons en attente n'ont pas de mouvements de stock à annuler
                # (les mouvements ne sont créés qu'après validation)

                bon.est_annule = True
                bon.motif_annulation = motif_defaut
                bon.date_annulation = timezone.now()
                bon.annule_par = user
                bon.save()
                # ✅ CORRECTION : soft delete de la livraison au lieu de hard delete
                liv.est_annule = True
                liv.save(update_fields=['est_annule'])

        if demande.livraisons.filter(est_annule=False).exists():
            demande.statut = 'CLOTUREE'
            demande.motif_cloture = (
                "Clôturée — reliquat abandonné après annulation de bon(s) "
                "en attente de validation."
            )
            msg = f"Demande {demande.numero_demande} clôturée. Les bons en attente ont été annulés."
        else:
            demande.statut = 'ANNULEE'
            demande.motif_cloture = "Annulée — bon(s) en attente de validation annulé(s)."
            msg = f"Demande {demande.numero_demande} annulée."

        demande.cloture_par = user
        demande.date_cloture = timezone.now()
        demande.save()

        return demande.statut, msg

    @staticmethod
    @transaction.atomic
    def destruction_lot_perime(entree, quantite, user):
        """
        Crée un bon de destruction pour un lot périmé.
        """
        from ..models import BonMouvement, LigneBon, Mouvement, Service, StockItem

        # ✅ CORRECTION : vérifier que la quantité ne dépasse pas le stock disponible
        stock_item = StockItem.objects.filter(
            article=entree.article,
            magasin=entree.magasin,
            batch_number=entree.numero_lot or None
        ).first()

        if not stock_item:
            raise ValidationError(
                f"Stock inexistant pour {entree.article.designation} "
                f"(lot {entree.numero_lot or 'N/A'})."
            )

        if quantite > stock_item.quantite_physique:
            raise ValidationError(
                f"Quantité de destruction ({quantite}) supérieure au stock disponible "
                f"({stock_item.quantite_physique}) pour le lot {entree.numero_lot or 'N/A'}."
            )

        # Service système REBUTS — seedé en base par la data migration
        # core.0004_seed_service_rebuts (donnée de référence, pas de création
        # à la volée dans le code). Garde de secours si la migration n'a pas
        # encore été appliquée sur un environnement existant.
        service_destruction = Service.objects.filter(code='REBUTS').first()
        if service_destruction is None:
            from django.db.utils import IntegrityError
            try:
                service_destruction, _ = Service.objects.get_or_create(
                    code='REBUTS',
                    defaults={'nom': 'DESTRUCTION / PÉREMPTIONS'},
                )
            except IntegrityError:
                service_destruction = Service.objects.filter(code='REBUTS').first()
            if service_destruction is None:
                raise ValidationError(
                    "Service système REBUTS introuvable — exécutez les migrations "
                    "(python manage.py migrate)."
                )

        # ✅ CORRECTION : utiliser type_bon='DESTRUCTION' si le modèle le supporte, sinon SORTIE
        # Note : si le modèle n'a pas DESTRUCTION dans les choices, utiliser SORTIE avec flag
        type_bon = 'DESTRUCTION' if 'DESTRUCTION' in dict(BonMouvement.TYPE_BON_CHOICES or []) else 'SORTIE'

        bon = BonMouvement.objects.create(
            type_bon=type_bon,
            magasin=entree.magasin,
            service_demandeur=service_destruction,
            cree_par=user,
            # Le mouvement SORTIE est exécuté immédiatement ci-dessous :
            # le bon doit être VALIDE (pas de double exécution à la validation)
            statut_validation='VALIDE',
            commentaire=f"Destruction automatique du lot {entree.numero_lot or 'N/A'}"
        )

        LigneBon.objects.create(
            bon=bon,
            article=entree.article,
            quantite=quantite,
            numero_lot=entree.numero_lot,
            date_peremption=entree.date_peremption
        )

        # ✅ CORRECTION : utiliser type_mouvement='DESTRUCTION' si disponible
        type_mvt = 'DESTRUCTION' if 'DESTRUCTION' in dict(Mouvement.TYPE_MOUVEMENT_CHOICES or []) else 'SORTIE'

        mouvement = Mouvement(
            type_mouvement=type_mvt,
            article=entree.article,
            magasin=entree.magasin,
            quantite=quantite,
            numero_lot=entree.numero_lot,
            date_peremption=entree.date_peremption,
            reference_document=bon.numero_bon,
            utilisateur=user,
            service_demandeur=service_destruction,
            commentaire=f"Destruction automatique du lot {entree.numero_lot or 'N/A'}"
        )
        StockTransactionService.executer(mouvement)

        return bon
