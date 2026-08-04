import logging
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

logger = logging.getLogger(__name__)


class InventaireService:
    """Orchestration des campagnes d'inventaire."""

    @staticmethod
    @transaction.atomic
    def creer_campagne(titre, magasin, user, entreprise=None):
        """
        Crée une campagne d'inventaire avec une ligne par article.

        ✅ CORRECTION MONO-TENANT : paramètre entreprise ignoré (compatibilité).
        """
        from ..models import CampagneInventaire, LigneInventaire, Article, StockItem

        campagne = CampagneInventaire.objects.create(
            titre=titre.upper(),
            magasin=magasin,
            cree_par=user,
        )

        articles = Article.objects.all()
        # ✅ CORRECTION : une seule requête pour éviter N+1
        stock_map = dict(StockItem.objects.filter(
            article__in=articles, magasin=magasin
        ).values_list('article_id', 'quantite_physique'))

        lignes_a_creer = []
        for article in articles:
            qte_theo = stock_map.get(article.id, 0)
            lignes_a_creer.append(
                LigneInventaire(
                    campagne=campagne,
                    article=article,
                    quantite_theorique=qte_theo
                )
            )

        LigneInventaire.objects.bulk_create(lignes_a_creer)
        return campagne

    @staticmethod
    @transaction.atomic
    def sauvegarder_saisie(campagne, quantites_dict, user):
        """
        Sauvegarde les quantités physiques saisies (brouillon).

        Args:
            quantites_dict: {ligne_id: quantite_physique|None}
                - int  → écrire la valeur (y compris 0)
                - None → effacer la saisie (mettre NULL)
        """
        from ..models import LigneInventaire

        # ✅ CORRECTION : vérifier le statut de la campagne
        if campagne.statut not in ('EN_COURS', 'A_VALIDER'):
            raise ValidationError(
                f"Impossible de modifier une campagne au statut '{campagne.statut}'."
            )

        # ✅ CORRECTION : utiliser in_bulk au lieu de N requêtes .get()
        ligne_ids = [int(k) for k in quantites_dict.keys() if str(k).isdigit()]
        lignes = LigneInventaire.objects.in_bulk(ligne_ids)

        lignes_a_mettre_a_jour = []
        for ligne_id, val in quantites_dict.items():
            ligne = lignes.get(int(ligne_id) if str(ligne_id).isdigit() else None)
            if not ligne or ligne.campagne_id != campagne.id:
                continue

            if val is None or val == '':
                ligne.quantite_physique = None
            else:
                try:
                    ligne.quantite_physique = int(val)
                except (ValueError, TypeError):
                    continue
            lignes_a_mettre_a_jour.append(ligne)

        if lignes_a_mettre_a_jour:
            LigneInventaire.objects.bulk_update(
                lignes_a_mettre_a_jour, ['quantite_physique']
            )

        return campagne

    @staticmethod
    @transaction.atomic
    def valider_campagne(campagne, user):
        """
        Valide une campagne et ajuste le stock réel directement.
        Contourne Mouvement.clean() qui bloque sur stock insuffisant.

        Returns:
            int: nombre d'ajustements créés.
        """
        from django.core.exceptions import PermissionDenied

        # ✅ CORRECTION : empêcher la double validation
        if campagne.statut == 'VALIDE':
            raise ValidationError("Cette campagne d'inventaire a déjà été validée.")

        # ✅ CORRECTION MONO-TENANT : vérifier que l'utilisateur est actif
        if not user or not user.is_active:
            raise PermissionDenied("Utilisateur inactif.")

        from ..models import Mouvement, StockItem

        # ✅ CORRECTION : précharger config et responsables HORS de la boucle
        from core.models import ConfigurationHopital
        from django.contrib.auth.models import User
        from accounts.models import Notification

        config = ConfigurationHopital.get_instance()
        seuil_alert = config.seuil_ecart_inventaire if (config and hasattr(config, 'seuil_ecart_inventaire')) else 10

        responsables = list(User.objects.filter(
            profil__est_chef_service=True,
            is_active=True
        ))

        notifications_a_creer = []
        ajustements_crees = 0

        for ligne in campagne.lignes_inventaire.select_related('article').all():
            if ligne.quantite_physique is not None:
                ecart = ligne.quantite_physique - ligne.quantite_theorique
                if ecart != 0:
                    # ═══════════════════════════════════════════════════════
                    # 1. MISE À JOUR DIRECTE DU STOCK (sans vérification)
                    # ═══════════════════════════════════════════════════════
                    # ✅ CORRECTION : select_for_update() pour verrouiller le stock
                    stock_item, _ = StockItem.objects.select_for_update().get_or_create(
                        article=ligne.article,
                        magasin=campagne.magasin,
                        defaults={'quantite_physique': 0, 'valeur_cmup': 0}
                    )
                    # Forcer le stock réel à la quantité physique constatée
                    stock_item.quantite_physique = ligne.quantite_physique

                    # ✅ CORRECTION : ne PAS reset le CMUP à 0
                    # On conserve le CMUP existant pour l'historique de valorisation
                    # Si le stock passe à 0, le CMUP reste inchangé

                    # ✅ CORRECTION : ne PAS inclure valeur_cmup dans update_fields (non modifié)
                    stock_item.save(update_fields=['quantite_physique'])

                    # ═══════════════════════════════════════════════════════
                    # 2. MOUVEMENT D'HISTORIQUE (sans déclencher clean/sortie)
                    #    update_stock=False → contourne le contrôleur de stock
                    #    ⚠️ Nécessite que Mouvement.save() gère update_stock
                    # ═══════════════════════════════════════════════════════
                    type_mvt = 'AJUSTEMENT_POS' if ecart > 0 else 'AJUSTEMENT_NEG'
                    mouvement = Mouvement(
                        type_mouvement=type_mvt,
                        article=ligne.article,
                        magasin=campagne.magasin,
                        quantite=abs(ecart),
                        utilisateur=user,
                        reference_document=f"Inventaire #{campagne.id}",
                        commentaire=f"Validation Inventaire #{campagne.id}. Écart corrigé : {ecart} (théorique={ligne.quantite_theorique}, physique={ligne.quantite_physique})",
                    )
                    # Sauvegarde brute : pas de clean(), pas de retrait stock
                    mouvement.save(update_stock=False)
                    ajustements_crees += 1

                    # ✅ CORRECTION : audit trail explicite + notification si écart anormal
                    # Seuil récupéré depuis ConfigurationHopital, fallback à 10
                    if abs(ecart) > seuil_alert:
                        logger.warning(
                            f"ÉCART ANORMAL détecté lors de l'inventaire : "
                            f"article={ligne.article.designation}, écart={ecart}, "
                            f"campagne={campagne.titre}, validateur={user}"
                        )
                        for resp in responsables:
                            notifications_a_creer.append(Notification(
                                utilisateur=resp,
                                titre="⚠️ Écart anormal lors d'inventaire",
                                message=(
                                    f"Un écart de {abs(ecart)} unités a été détecté "
                                    f"pour l'article {ligne.article.designation} "
                                    f"lors de l'inventaire {campagne.titre}."
                                ),
                                url=f"/stock/inventaires/{campagne.id}/",
                                type_notif="ALERTE_INVENTAIRE"
                            ))

        # ✅ CORRECTION : bulk_create pour les notifications
        if notifications_a_creer:
            Notification.objects.bulk_create(notifications_a_creer)

        campagne.statut = 'VALIDE'
        campagne.valide_par = user
        campagne.date_validation = timezone.now()
        campagne.save()

        return ajustements_crees

    @staticmethod
    @transaction.atomic
    def annuler_campagne(campagne, user=None):
        """Annule une campagne d'inventaire avec garde-fous."""
        from ..models import Mouvement

        # ✅ CORRECTION : vérifier que la campagne n'est pas déjà validée
        if campagne.statut == 'VALIDE':
            # Vérifier si des ajustements ont déjà été appliqués
            # ✅ CORRECTION : utiliser exact match au lieu de icontains
            ajustements_existants = Mouvement.objects.filter(
                reference_document=f"Inventaire #{campagne.id}",
                type_mouvement__in=['AJUSTEMENT_POS', 'AJUSTEMENT_NEG']
            ).exists()
            if ajustements_existants:
                raise ValidationError(
                    "Impossible d'annuler une campagne validée avec des ajustements appliqués. "
                    "Vous devez d'abord annuler les mouvements d'ajustement."
                )

        campagne.statut = 'ANNULE'
        if user:
            campagne.annule_par = user
            campagne.date_annulation = timezone.now()
            campagne.save(update_fields=['statut', 'annule_par', 'date_annulation'])
        else:
            campagne.save(update_fields=['statut'])
        return campagne

    @staticmethod
    def soumettre_validation(campagne):
        campagne.statut = 'A_VALIDER'
        campagne.save(update_fields=['statut'])
        return campagne

    @staticmethod
    def rejeter_campagne(campagne):
        campagne.statut = 'EN_COURS'
        campagne.save(update_fields=['statut'])
        return campagne
