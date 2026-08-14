# -*- coding: utf-8 -*-
import logging
# stock/services/bon_service.py
from django.db import transaction
from django.core.exceptions import ValidationError, PermissionDenied
from django.utils import timezone
from stock.models import BonMouvement, Mouvement, StockItem, LigneBon, DemandeMateriel
from stock.services.stock_transaction_service import StockTransactionService

logger = logging.getLogger(__name__)


class BonService:
    """Service métier pour la gestion des bons (entrée, sortie, hors stock, retour).

    RÈGLES DE SIGNATURE :
    - Tous les paramètres sont des objets (pas d'ID)
    - `utilisateur` = User instance
    - `magasin` = Magasin instance
    - `lignes` = list[dict] avec article_id, quantite, etc.

    ORDRE DES CASES DE SIGNATURE :
    - Case 1 : Demandeur / Émission
    - Case 2 : Vu pour exécution / Validation
    - Case 3 : Magasinier / Créateur du bon
    - Case 4+ : Responsable, Contrôleur, Réceptionnaire
    """

    @staticmethod
    def _verifier_utilisateur_actif(utilisateur, magasin=None):
        """✅ CORRECTION MONO-TENANT : vérifie que l'utilisateur est actif.
        Le paramètre magasin est conservé pour compatibilité mais ignoré.
        """
        if not utilisateur or not utilisateur.is_active:
            raise PermissionDenied("Utilisateur inactif ou non authentifié.")

    @staticmethod
    def _enregistrer_validation(bon, utilisateur, ordre_case, commentaire=""):
        """Enregistre une signature snapshotée dans ValidationDocument."""
        from accounts.utils import get_fonction_valideur
        from stock.models import ValidationDocument
        profil = getattr(utilisateur, 'profil', None)
        signature_img = None
        if profil and getattr(profil, 'signature', None):
            signature_img = profil.signature

        # ✅ CORRECTION : signature_image dans defaults pour éviter double save
        defaults = {
            'valideur': utilisateur,
            'fonction_snapshot': get_fonction_valideur(utilisateur),
            'commentaire': commentaire,
        }
        if signature_img:
            defaults['signature_image'] = signature_img

        val, created = ValidationDocument.objects.update_or_create(
            bon=bon,
            ordre=ordre_case,
            defaults=defaults
        )
        return val

    @staticmethod
    def _get_articles_en_bulk(article_ids):
        """✅ CORRECTION : Récupère les articles en une seule requête pour éviter N+1.
        Utilise _base_manager pour contourner tout filtre implicite.
        Convertit les IDs en int car in_bulk() retourne des clés int."""
        from stock.models import Article
        ids_int = [int(aid) for aid in article_ids if aid is not None]
        return Article._base_manager.filter(id__in=ids_int).in_bulk()

    # ═══════════════════════════════════════════════════════════════════════
    # BON D'ENTRÉE
    # ═══════════════════════════════════════════════════════════════════════
    @classmethod
    @transaction.atomic
    def creer_bon_entree(cls, lignes, utilisateur, magasin,
                         commentaire="", reference_document=None,
                         fournisseur=None, reference_externe=None):
        """Crée un bon d'entrée avec mouvements de stock.

        Args:
            lignes: list[dict] — [{'article_id': int, 'quantite': int, 
                                    'prix_unitaire': Decimal|None,
                                    'numero_lot': str|None, 'date_peremption': str|None}]
            utilisateur: User instance
            magasin: Magasin instance
            commentaire: str
            reference_document: str|None
            fournisseur: Fournisseur instance|None
            reference_externe: str|None
        """
        # ✅ CORRECTION MONO-TENANT : vérification utilisateur
        cls._verifier_utilisateur_actif(utilisateur, magasin)

        # ✅ CORRECTION SANITAIRE : bloquer les lots déjà périmés à l'entrée,
        # AVANT toute écriture (défense en profondeur : la vue contrôle déjà,
        # le service est le point de vérité utilisé par les tests).
        article_ids = sorted([l.get('article_id') for l in lignes if l.get('article_id')])
        articles_map = cls._get_articles_en_bulk(article_ids)
        for ligne in lignes:
            erreur = cls._verifier_peremption(
                articles_map.get(int(ligne['article_id'])) if ligne.get('article_id') else None,
                ligne.get('date_peremption'),
            )
            if erreur:
                raise ValidationError(erreur)

        bon_kwargs = {
            'type_bon': 'ENTREE',
            'magasin': magasin,
            'cree_par': utilisateur,
            'commentaire': commentaire,
            'statut_validation': 'VALIDE',
        }
        if reference_externe:
            bon_kwargs['reference_externe'] = reference_externe
        if reference_document:
            bon_kwargs['reference_document'] = reference_document
        if fournisseur:
            bon_kwargs['fournisseur'] = fournisseur

        bon = BonMouvement.objects.create(**bon_kwargs)

        # ✅ CORRECTION : verrouiller tous les StockItem concernés AVANT la boucle pour éviter deadlocks
        # Tri par article_id garantit un ordre de verrouillage cohérent entre threads
        # On verrouille par (article_id, batch_number) pour couvrir TOUS les cas (avec et sans lot)
        from stock.models import StockItem
        from django.db.models import Q

        # Regrouper les lignes par (article_id, batch_number) pour verrouiller correctement
        lignes_par_batch = {}
        for l in lignes:
            aid = l.get('article_id')
            batch = l.get('numero_lot') or None
            if aid:
                lignes_par_batch.setdefault((aid, batch), []).append(l)

        for (article_id, batch) in sorted(lignes_par_batch.keys()):
            filtre = {'article_id': article_id, 'magasin': magasin}
            if batch:
                filtre['batch_number'] = batch
            else:
                filtre['batch_number__isnull'] = True
            StockItem.objects.select_for_update().filter(**filtre).first()

        for ligne_data in lignes:
            article_id = ligne_data.get('article_id')
            quantite = ligne_data.get('quantite')
            prix_unitaire = ligne_data.get('prix_unitaire')
            numero_lot = ligne_data.get('numero_lot')
            date_peremption = ligne_data.get('date_peremption')

            # ✅ CORRECTION : lever ValidationError au lieu de silencier
            if not article_id:
                raise ValidationError("Ligne sans article_id.")
            if not quantite or quantite <= 0:
                raise ValidationError(f"Quantité invalide pour article_id={article_id} : {quantite}")

            article = articles_map.get(int(article_id))
            if not article:
                raise ValidationError(f"Article ID {article_id} introuvable.")

            ligne_kwargs = {
                'bon': bon,
                'article': article,
                'quantite': quantite,
            }
            if prix_unitaire is not None:
                ligne_kwargs['prix_unitaire'] = prix_unitaire
            if numero_lot:
                ligne_kwargs['numero_lot'] = numero_lot
            if date_peremption:
                ligne_kwargs['date_peremption'] = date_peremption

            LigneBon.objects.create(**ligne_kwargs)

            mouvement = Mouvement(
                type_mouvement='ENTREE',
                article=article,
                magasin=magasin,
                quantite=quantite,
                prix_unitaire=prix_unitaire,
                utilisateur=utilisateur,
                reference_document=bon.numero_bon,
                numero_lot=numero_lot,
                date_peremption=date_peremption,
            )
            StockTransactionService.executer(mouvement)

        # ── Snapshot : créateur = magasinier (case 3) ──
        cls._enregistrer_validation(bon, utilisateur, ordre_case=3, commentaire="Création bon d'entrée")

        return bon

    @staticmethod
    def _verifier_peremption(article, date_peremption):
        """Retourne un message d'erreur si la date de péremption est déjà passée.

        Règle sanitaire : un produit périmé ne peut pas entrer en stock.
        - ``date_peremption`` accepte str ('YYYY-MM-DD' ou 'DD/MM/YYYY') ou date.
        - Retourne None si la date est absente, illisible ou future/aujourd'hui.
        """
        if not date_peremption:
            return None
        from datetime import date as date_cls

        peremp = date_peremption
        if isinstance(peremp, str):
            peremp = peremp.strip()
            parsed = None
            for fmt in ('%Y-%m-%d', '%d/%m/%Y'):
                try:
                    parsed = timezone.datetime.strptime(peremp, fmt).date()
                    break
                except ValueError:
                    continue
            if parsed is None:
                return None  # format inconnu : la validation du modèle s'en charge
            peremp = parsed

        if peremp < date_cls.today():
            designation = getattr(article, 'designation', '') or 'cet article'
            return (
                f"⛔ Réception refusée : le lot de '{designation}' est déjà périmé "
                f"(péremption {peremp:%d/%m/%Y}). Un produit périmé ne peut pas "
                f"entrer en stock."
            )
        return None

    # ═══════════════════════════════════════════════════════════════════════
    # BON DE SORTIE
    # ═══════════════════════════════════════════════════════════════════════
    @classmethod
    @transaction.atomic
    def creer_bon_sortie(cls, lignes, utilisateur, magasin,
                         circuit_validation=None, commentaire="",
                         reference_document=None, demande=None,
                         service_demandeur=None, reference_externe=None):
        """Crée un bon de sortie.

        Args:
            lignes: list[dict] — [{'article_id': int, 'quantite': int}]
            utilisateur: User instance
            magasin: Magasin instance
            circuit_validation: CircuitValidation instance|None
            commentaire: str
            reference_document: str|None
            demande: DemandeMateriel instance|None
            service_demandeur: Service instance|None
            reference_externe: str|None
        """
        # ✅ CORRECTION MONO-TENANT : vérification utilisateur
        cls._verifier_utilisateur_actif(utilisateur, magasin)

        statut = 'ATTENTE' if circuit_validation and circuit_validation.est_actif else 'VALIDE'

        # ✅ CORRECTION : charger articles_map UNE SEULE FOIS (factorisé avant le if)
        from stock.models import Article
        article_ids = [l.get('article_id') for l in lignes if l.get('article_id')]
        articles_map = Article.objects.filter(id__in=article_ids).in_bulk()

        # ✅ CORRECTION : vérifier le stock AVANT de créer le bon (mode VALIDE) avec verrou pessimiste
        if statut == 'VALIDE':
            # Verrouiller tous les StockItem concernés
            stock_items = {}
            for ligne_data in lignes:
                article_id = ligne_data.get('article_id')
                quantite = ligne_data.get('quantite')
                if not article_id or not quantite or quantite <= 0:
                    continue
                article = articles_map.get(int(article_id))
                if not article:
                    continue
                # ✅ FEFO : pour les articles gérés en lot, la disponibilité
                # s'apprécie par lots (hors lots périmés, qui sont bloqués).
                if article.requiert_lot_peremption:
                    StockTransactionService.resoudre_lots_fefo(
                        article, magasin, quantite)
                    continue
                stock_item = StockItem.objects.select_for_update().filter(
                    article=article, magasin=magasin
                ).first()
                qte_dispo = stock_item.quantite_physique if stock_item else 0
                if qte_dispo < quantite:
                    raise ValidationError(
                        f"Stock insuffisant pour {article.designation} : "
                        f"{qte_dispo} disponible(s), {quantite} demandé(s).",
                        code='stock_insuffisant'
                    )
                stock_items[article_id] = stock_item

        # ✅ CORRECTION : cohérence service_demandeur vs demande
        if demande and demande.service_demandeur:
            if service_demandeur and service_demandeur != demande.service_demandeur:
                logger.warning(
                    f"Incohérence service_demandeur : fourni={service_demandeur}, "
                    f"demande={demande.service_demandeur}. Utilisation de la demande."
                )
            service_demandeur = demande.service_demandeur

        bon_kwargs = {
            'type_bon': 'SORTIE',
            'magasin': magasin,
            'cree_par': utilisateur,
            'commentaire': commentaire,
            'statut_validation': statut,
        }
        if reference_externe:
            bon_kwargs['reference_externe'] = reference_externe
        if reference_document:
            bon_kwargs['reference_document'] = reference_document
        if service_demandeur:
            bon_kwargs['service_demandeur'] = service_demandeur

        bon = BonMouvement.objects.create(**bon_kwargs)

        if demande:
            from stock.models import DemandeMateriel
            if isinstance(demande, DemandeMateriel):
                demande.bon_sortie_lie = bon
                demande.save(update_fields=['bon_sortie_lie'])

        # Si pas de circuit, exécuter immédiatement
        if statut == 'VALIDE':
            for ligne_data in lignes:
                article_id = ligne_data.get('article_id')
                quantite = ligne_data.get('quantite')

                if not article_id or not quantite or quantite <= 0:
                    continue

                article = articles_map.get(int(article_id))
                if not article:
                    continue

                # ✅ FEFO : découpage de la sortie par lot (péremption la plus
                # proche d'abord, lots périmés bloqués). Une ligne par lot
                # pour une traçabilité complète sur le bon.
                consommations = StockTransactionService.resoudre_lots_fefo(
                    article, magasin, quantite)
                if consommations:
                    for conso in consommations:
                        LigneBon.objects.create(
                            bon=bon, article=article,
                            quantite=conso['quantite'],
                            numero_lot=conso['numero_lot'],
                            date_peremption=conso['date_peremption'],
                        )
                        mouvement = Mouvement(
                            type_mouvement='SORTIE',
                            article=article,
                            magasin=magasin,
                            quantite=conso['quantite'],
                            utilisateur=utilisateur,
                            reference_document=bon.numero_bon,
                            numero_lot=conso['numero_lot'],
                            date_peremption=conso['date_peremption'],
                        )
                        StockTransactionService.executer(mouvement)
                    continue

                LigneBon.objects.create(
                    bon=bon, article=article, quantite=quantite
                )

                mouvement = Mouvement(
                    type_mouvement='SORTIE',
                    article=article,
                    magasin=magasin,
                    quantite=quantite,
                    utilisateur=utilisateur,
                    reference_document=bon.numero_bon,
                )
                StockTransactionService.executer(mouvement)
        else:
            # En attente : créer les lignes sans mouvement
            for ligne_data in lignes:
                article_id = ligne_data.get('article_id')
                quantite = ligne_data.get('quantite')
                if not article_id or not quantite or quantite <= 0:
                    continue
                article = articles_map.get(int(article_id))
                if not article:
                    continue
                LigneBon.objects.create(
                    bon=bon, article=article, quantite=quantite
                )

        # ── Traçabilité livraison : si le bon est lié à une demande interne,
        #    on alimente le module Livraisons (LivraisonPartielle + lignes +
        #    accusé de réception) pour que les deux parcours — guichet
        #    « Traiter » (LivraisonService.traiter_demande) et création directe
        #    d'une sortie liée à une demande — restent cohérents.
        if demande and demande.pk:
            from django.db.models import Sum
            from stock.models import (
                LivraisonPartielle, LivraisonLigne, AccuseReception, LigneDemande,
            )

            livraison = LivraisonPartielle.objects.create(
                demande=demande,
                livre_par=utilisateur,
                bon_sortie=bon,
                quantite_livree=0,
            )

            lignes_demande = {
                ld.article_id: ld
                for ld in LigneDemande.objects.filter(demande=demande)
            }

            total_livre = 0
            est_partielle = False
            for ligne_data in lignes:
                article_id = ligne_data.get('article_id')
                quantite = ligne_data.get('quantite')
                if not article_id or not quantite or quantite <= 0:
                    continue
                article = articles_map.get(int(article_id))
                if not article:
                    continue
                ld = lignes_demande.get(int(article_id))
                qte_demandee = ld.quantite_demandee if ld else quantite
                deja_livre = LivraisonLigne.objects.filter(
                    livraison__demande=demande, article=article
                ).exclude(livraison=livraison).aggregate(
                    total=Sum('quantite_livree')
                )['total'] or 0
                reste_avant = max(0, qte_demandee - deja_livre)
                reste_apres = max(0, reste_avant - quantite)
                if reste_apres > 0:
                    est_partielle = True
                LivraisonLigne.objects.create(
                    livraison=livraison,
                    article=article,
                    quantite_demandee=qte_demandee,
                    reste_avant_livraison=reste_avant,
                    quantite_livree=quantite,
                    reste=reste_apres,
                )
                total_livre += quantite

            livraison.quantite_livree = total_livre
            livraison.est_partielle = est_partielle
            livraison.save(update_fields=['quantite_livree', 'est_partielle'])

            AccuseReception.objects.create(livraison=livraison, est_signe=False)

        # ── Snapshot : créateur = magasinier (case 3) ──
        cls._enregistrer_validation(bon, utilisateur, ordre_case=3, commentaire="Création bon de sortie")

        # ── Snapshot : demandeur = case 1 (si demande liée) ──
        if demande and hasattr(demande, 'demandeur') and demande.demandeur:
            cls._enregistrer_validation(bon, demande.demandeur, ordre_case=1, commentaire="Demandeur")
        elif service_demandeur:
            # Chercher le chef de service
            from django.contrib.auth.models import User
            # ✅ CORRECTION : order_by pour déterminisme
            chef = User.objects.filter(
                profil__service=service_demandeur,
                profil__est_chef_service=True,
                is_active=True
            ).order_by('id').first()
            if chef:
                cls._enregistrer_validation(bon, chef, ordre_case=1, commentaire="Chef de service demandeur")

        return bon

    # ═══════════════════════════════════════════════════════════════════════
    # BON HORS STOCK
    # ═══════════════════════════════════════════════════════════════════════
    @classmethod
    @transaction.atomic
    def creer_bon_hors_stock(cls, lignes, utilisateur, magasin,
                             commentaire="", reference_document=None,
                             service_demandeur=None, reference_externe=None,
                             destinataire=None, fournisseur=None):
        """Crée un bon hors stock (pas d'impact sur stock physique).

        Args:
            lignes: list[dict] — [{'article_id': int, 'quantite': int}]
            utilisateur: User instance
            magasin: Magasin instance
            commentaire: str
            reference_document: str|None
            service_demandeur: Service instance|None
            reference_externe: str|None
            destinataire: Beneficiaire instance|None
            fournisseur: Fournisseur instance|None
        """
        # ✅ CORRECTION MONO-TENANT : vérification utilisateur
        cls._verifier_utilisateur_actif(utilisateur, magasin)

        bon_kwargs = {
            'type_bon': 'SORTIE_HORS_STOCK',
            'magasin': magasin,
            'cree_par': utilisateur,
            'commentaire': commentaire,
            'statut_validation': 'VALIDE',
        }
        if reference_externe:
            bon_kwargs['reference_externe'] = reference_externe
        if reference_document:
            bon_kwargs['reference_document'] = reference_document
        if service_demandeur:
            bon_kwargs['service_demandeur'] = service_demandeur
        if destinataire:
            bon_kwargs['destinataire'] = destinataire
        if fournisseur:
            bon_kwargs['fournisseur'] = fournisseur

        bon = BonMouvement.objects.create(**bon_kwargs)

        # ✅ CORRECTION : articles en bulk
        article_ids = [l.get('article_id') for l in lignes if l.get('article_id')]
        from stock.models import Article
        articles_map = Article.objects.filter(id__in=article_ids).in_bulk()

        for ligne_data in lignes:
            article_id = ligne_data.get('article_id')
            quantite = ligne_data.get('quantite')

            if not article_id or not quantite or quantite <= 0:
                continue

            article = articles_map.get(int(article_id))
            if not article:
                continue

            LigneBon.objects.create(
                bon=bon, article=article, quantite=quantite
            )

            mouvement = Mouvement(
                type_mouvement='SORTIE_HORS_STOCK',
                article=article,
                magasin=magasin,
                quantite=quantite,
                utilisateur=utilisateur,
                reference_document=bon.numero_bon,
            )
            # Pas d'impact stock — update_stock=False doit être géré par Mouvement.save()
            mouvement.save(update_stock=False)

        # ── Snapshot : créateur = magasinier (case 3) ──
        cls._enregistrer_validation(bon, utilisateur, ordre_case=3, commentaire="Création bon hors stock")

        return bon

    # ═══════════════════════════════════════════════════════════════════════
    # BON DE RETOUR SERVICE
    # ═══════════════════════════════════════════════════════════════════════
    @classmethod
    @transaction.atomic
    def creer_bon_retour(cls, lignes, utilisateur, magasin,
                         commentaire="", reference_document=None,
                         service=None, reference_externe=None):
        """Crée un bon de retour service (entrée de stock).

        Args:
            lignes: list[dict] — [{'article_id': int, 'quantite': int,
                                    'numero_lot': str|None, 'date_peremption': str|None}]
            utilisateur: User instance
            magasin: Magasin instance
            commentaire: str
            reference_document: str|None
            service: Service instance|None
            reference_externe: str|None
        """
        # ✅ CORRECTION MONO-TENANT : vérification utilisateur
        cls._verifier_utilisateur_actif(utilisateur, magasin)

        bon_kwargs = {
            'type_bon': 'RETOUR_SERVICE',
            'magasin': magasin,
            'cree_par': utilisateur,
            'commentaire': commentaire,
            'statut_validation': 'VALIDE',
        }
        if service:
            bon_kwargs['service_demandeur'] = service
        if reference_externe:
            bon_kwargs['reference_externe'] = reference_externe
        if reference_document:
            bon_kwargs['reference_document'] = reference_document

        bon = BonMouvement.objects.create(**bon_kwargs)

        # ✅ CORRECTION : articles en bulk
        article_ids = [l.get('article_id') for l in lignes if l.get('article_id')]
        from stock.models import Article
        articles_map = Article.objects.filter(id__in=article_ids).in_bulk()

        for ligne_data in lignes:
            article_id = ligne_data.get('article_id')
            quantite = ligne_data.get('quantite')
            numero_lot = ligne_data.get('numero_lot')
            date_peremption = ligne_data.get('date_peremption')

            if not article_id or not quantite or quantite <= 0:
                continue

            article = articles_map.get(int(article_id))
            if not article:
                continue

            ligne_kwargs = {
                'bon': bon,
                'article': article,
                'quantite': quantite,
            }
            if numero_lot:
                ligne_kwargs['numero_lot'] = numero_lot
            if date_peremption:
                ligne_kwargs['date_peremption'] = date_peremption

            LigneBon.objects.create(**ligne_kwargs)

            mouvement = Mouvement(
                type_mouvement='RETOUR_SERVICE',
                article=article,
                magasin=magasin,
                quantite=quantite,
                utilisateur=utilisateur,
                reference_document=bon.numero_bon,
                numero_lot=numero_lot,
                date_peremption=date_peremption,
            )
            StockTransactionService.executer(mouvement)

        # ── Snapshot : créateur = magasinier (case 3) ──
        cls._enregistrer_validation(bon, utilisateur, ordre_case=3, commentaire="Création bon de retour")

        return bon

    # ═══════════════════════════════════════════════════════════════════════
    # VALIDATION D'UN BON DE SORTIE
    # ═══════════════════════════════════════════════════════════════════════
    @classmethod
    @transaction.atomic
    def valider_bon_sortie(cls, bon, utilisateur):
        """Passe un bon ATTENTE en VALIDE et crée les mouvements de sortie."""
        if bon.statut_validation == 'VALIDE':
            raise ValueError("Bon déjà validé.")
        if bon.statut_validation == 'REJETE':
            raise ValueError("Bon rejeté, impossible de valider.")

        # ✅ CORRECTION : vérifier utilisateur/magasin
        cls._verifier_utilisateur_actif(utilisateur, bon.magasin)

        # ✅ CORRECTION : revérifier le stock AVANT validation (le stock a pu changer)
        from stock.models import StockItem
        for ligne in bon.lignes_bon.select_related('article').all():
            # ✅ FEFO : la disponibilité des articles gérés en lot s'apprécie
            # par lots (hors lots périmés, qui sont bloqués).
            if ligne.article.requiert_lot_peremption:
                StockTransactionService.resoudre_lots_fefo(
                    ligne.article, bon.magasin, ligne.quantite)
                continue
            stock_item = StockItem.objects.select_for_update().filter(
                article=ligne.article, magasin=bon.magasin
            ).first()
            qte_dispo = stock_item.quantite_physique if stock_item else 0
            if qte_dispo < ligne.quantite:
                raise ValidationError(
                    f"Stock insuffisant pour {ligne.article.designation} : "
                    f"{qte_dispo} disponible(s), {ligne.quantite} demandé(s). "
                    f"Le stock a changé depuis la création du bon.",
                    code='stock_insuffisant'
                )

        bon.statut_validation = 'VALIDE'
        bon.date_validation = timezone.now()
        bon.valide_par = utilisateur
        bon.save(update_fields=['statut_validation', 'date_validation', 'valide_par'])

        # ── Snapshot de la validation (case 2 : Vu pour exécution) ──
        cls._enregistrer_validation(bon, utilisateur, ordre_case=2, commentaire="Validation circuit de validation")

        # Créer les mouvements de sortie
        for ligne in bon.lignes_bon.all():
            # ✅ FEFO : découpage par lot au moment de la validation pour
            # consommer le stock réel au plus proche de la péremption.
            consommations = StockTransactionService.resoudre_lots_fefo(
                ligne.article, bon.magasin, ligne.quantite)
            if consommations:
                for conso in consommations:
                    mouvement = Mouvement(
                        type_mouvement='SORTIE',
                        article=ligne.article,
                        magasin=bon.magasin,
                        quantite=conso['quantite'],
                        utilisateur=utilisateur,
                        reference_document=bon.numero_bon,
                        numero_lot=conso['numero_lot'],
                        date_peremption=conso['date_peremption'],
                    )
                    StockTransactionService.executer(mouvement)
                continue

            mouvement = Mouvement(
                type_mouvement='SORTIE',
                article=ligne.article,
                magasin=bon.magasin,
                quantite=ligne.quantite,
                utilisateur=utilisateur,
                reference_document=bon.numero_bon,
            )
            StockTransactionService.executer(mouvement)

        return bon

    # ═══════════════════════════════════════════════════════════════════════
    # ANNULATIONS
    # ═══════════════════════════════════════════════════════════════════════
    @classmethod
    @transaction.atomic
    def annuler_bon_entree(cls, bon, motif, utilisateur):
        """Annule un bon d'entrée et remet le stock via contre-mouvements."""
        if bon.est_annule:
            raise ValueError("Bon déjà annulé.")

        # ✅ CORRECTION : vérifier utilisateur/magasin
        cls._verifier_utilisateur_actif(utilisateur, bon.magasin)

        # ✅ CORRECTION : gérer motif comme string ou objet
        motif_libelle = getattr(motif, 'libelle', str(motif)) if motif else "Non spécifié"

        mouvements = Mouvement.objects.filter(
            reference_document__startswith=bon.numero_bon,
            type_mouvement='ENTREE'
        )

        for mouvement_original in mouvements:
            try:
                StockTransactionService.annuler_par_contre_mouvement(
                    mouvement_original=mouvement_original,
                    utilisateur=utilisateur,
                    commentaire=f"Annulation du bon {bon.numero_bon}. Motif : {motif_libelle}"
                )
            except ValidationError as e:
                # ✅ CORRECTION : test sur le code d'erreur + fallback message
                code_erreur = getattr(e, 'code', None)
                message_erreur = str(e)
                if code_erreur == 'stock_insuffisant' or "Stock insuffisant" in message_erreur:
                    # Forcer un ajustement négatif
                    prix_unitaire = mouvement_original.prix_unitaire
                    mouvement = Mouvement(
                        type_mouvement='AJUSTEMENT_NEG_FORCE',
                        article=mouvement_original.article,
                        magasin=mouvement_original.magasin,
                        quantite=mouvement_original.quantite,
                        prix_unitaire=prix_unitaire,
                        utilisateur=utilisateur,
                        reference_document=f"ANNUL-FORCE-{bon.numero_bon}",
                        commentaire=f"Annulation forcée bon {bon.numero_bon} (stock déjà consommé). Motif : {motif_libelle}",
                    )
                    # ✅ CORRECTION : utiliser AJUSTEMENT_NEG_FORCE pour contourner la vérif stock
                    StockTransactionService.executer(mouvement)
                    logger.warning(
                        f"AJUSTEMENT FORCÉ négatif : bon={bon.numero_bon}, "
                        f"article={mouvement_original.article}, qte={mouvement_original.quantite}, "
                        f"user={utilisateur}, motif={motif_libelle}"
                    )
                    # ✅ CORRECTION : notification explicite aux responsables
                    try:
                        from accounts.models import Notification
                        from django.contrib.auth.models import User
                        responsables = User.objects.filter(
                            profil__est_chef_service=True,
                            is_active=True
                        )
                        for resp in responsables:
                            Notification.objects.create(
                                utilisateur=resp,
                                titre="⚠️ Ajustement forcé lors d'annulation",
                                message=(
                                    f"Un ajustement négatif a été forcé lors de l'annulation "
                                    f"du bon {bon.numero_bon}. Stock déjà consommé. "
                                    f"Motif : {motif_libelle}"
                                ),
                                url=f"/stock/bons/{bon.id}/",
                                type_notif="ALERTE_STOCK",
                                est_importante=True
                            )
                    except Exception:
                        logger.exception("Échec notification ajustement forcé")
                else:
                    raise

        bon.est_annule = True
        # ✅ CORRECTION : gérer motif comme objet ou string
        if hasattr(motif, 'pk'):
            bon.motif_annulation = motif
        bon.annule_par = utilisateur
        bon.date_annulation = timezone.now()
        bon.save(update_fields=['est_annule', 'motif_annulation', 'annule_par', 'date_annulation'])

        return bon

    @classmethod
    @transaction.atomic
    def annuler_bon_sortie(cls, bon, motif, utilisateur):
        """Annule un bon de sortie et remet le stock via contre-mouvements."""
        if bon.est_annule:
            raise ValueError("Bon déjà annulé.")

        # ✅ CORRECTION : vérifier utilisateur/magasin
        cls._verifier_utilisateur_actif(utilisateur, bon.magasin)

        # ✅ CORRECTION : vérifier si une demande est liée et mettre à jour son statut
        motif_libelle = getattr(motif, 'libelle', str(motif)) if motif else "Non spécifié"

        demande_liee = DemandeMateriel.objects.filter(bon_sortie_lie=bon).first() if hasattr(bon, 'pk') else None
        if demande_liee:
            if demande_liee.statut not in ('ANNULEE', 'CLOTUREE'):
                demande_liee.statut = 'EN_ATTENTE'
                demande_liee.bon_sortie_lie = None
                demande_liee.save(update_fields=['statut', 'bon_sortie_lie'])

        mouvements = Mouvement.objects.filter(
            reference_document__startswith=bon.numero_bon,
            type_mouvement='SORTIE'
        )

        for mouvement_original in mouvements:
            StockTransactionService.annuler_par_contre_mouvement(
                mouvement_original=mouvement_original,
                utilisateur=utilisateur,
                commentaire=f"Annulation du bon {bon.numero_bon}. Motif : {motif_libelle}"
            )

        bon.est_annule = True
        if hasattr(motif, 'pk'):
            bon.motif_annulation = motif
        bon.annule_par = utilisateur
        bon.date_annulation = timezone.now()
        bon.save(update_fields=['est_annule', 'motif_annulation', 'annule_par', 'date_annulation'])

        return bon

    @classmethod
    @transaction.atomic
    def annuler_bon_hors_stock(cls, bon, motif, utilisateur):
        """Annule un bon hors stock (pas de contre-mouvement stock)."""
        if bon.est_annule:
            raise ValueError("Bon déjà annulé.")

        # ✅ CORRECTION : vérifier utilisateur/magasin
        cls._verifier_utilisateur_actif(utilisateur, bon.magasin)

        # ✅ CORRECTION : soft delete des mouvements hors stock (pas de hard delete)
        mouvements_hs = Mouvement.objects.filter(
            reference_document=bon.numero_bon,
            type_mouvement='SORTIE_HORS_STOCK'
        )
        for mvt in mouvements_hs:
            mvt.est_annule = True
            mvt.save(update_fields=['est_annule'], update_stock=False)

        bon.est_annule = True
        if hasattr(motif, 'pk'):
            bon.motif_annulation = motif
        bon.annule_par = utilisateur
        bon.date_annulation = timezone.now()
        bon.save(update_fields=['est_annule', 'motif_annulation', 'annule_par', 'date_annulation'])

        return bon

    @classmethod
    @transaction.atomic
    def calculer_numero_livraison(cls, commande):
        """Calcule le prochain numéro de livraison pour une commande."""
        # ✅ CORRECTION : transaction atomique + select_for_update
        from stock.models import BonMouvement
        dernier = BonMouvement.objects.select_for_update().filter(
            commande_liee=commande,
            is_deleted=False
        ).order_by('-numero_livraison').first()

        if not dernier or dernier.numero_livraison is None:
            return 1
        return dernier.numero_livraison + 1
