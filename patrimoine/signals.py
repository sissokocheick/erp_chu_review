# -*- coding: utf-8 -*-
"""
Signaux Patrimoine.

Quand une LigneBon d'un BonMouvement de type SORTIE / SORTIE_HORS_STOCK est
créée et que l'article est marqué est_immobilisable=True, on crée
automatiquement les Immobilisations en statut EN_ATTENTE (Sas).

Historique : le signal était branché sur post_save de BonMouvement, mais il se
déclenchait AVANT la création des LigneBon -> instance.lignes_bon.all() vide ->
aucune immobilisation n'était jamais créée. Il est maintenant branché sur
post_save de LigneBon (avec garde created=True).
"""

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import transaction
import logging

logger = logging.getLogger(__name__)


@receiver(post_save, sender='stock.LigneBon')
def creer_immobilisations_depuis_bon(sender, instance, created, **kwargs):
    """
    Après la création d'une LigneBon d'un bon de sortie,
    crée une Immobilisation dans le sas pour chaque article immobilisable.
    """
    if not created:
        return

    bon = instance.bon
    if bon.type_bon not in ('SORTIE', 'SORTIE_HORS_STOCK'):
        return
    if bon.est_annule:
        return

    article = instance.article
    if not getattr(article, 'est_immobilisable', False):
        return

    try:
        from .models import Immobilisation, TypeEquipement
        from decimal import Decimal

        # Type d'équipement par défaut (premier type actif)
        type_eq = None
        try:
            type_eq = TypeEquipement.objects.filter(est_actif=True).first()
        except Exception as exc:
            logger.warning(
                "Recherche TypeEquipement impossible pour article %s: %s",
                article.id, exc
            )

        if not type_eq:
            return  # Pas de type configuré -> on ne bloque pas

        prix = getattr(instance, 'prix_unitaire', None) or Decimal('0.00')

        # Créer autant d'immobilisations que la quantité (1 bien = 1 immo)
        quantite = int(getattr(instance, 'quantite', 1) or 1)

        # Garde anti-doublon : si des immos existent déjà pour ce bon + article,
        # ne pas en recréer (protection contre les re-sauvegardes de lignes).
        # La cible est le TOTAL des lignes du bon pour CET article (un bon
        # peut légalement contenir 2 lignes du même article : l'ancien garde
        # comparait la 2e ligne à la quantité de la 1re → sous-création).
        from stock.models import LigneBon
        total_voulu = sum(
            LigneBon.objects.filter(bon=bon, article=article)
            .values_list('quantite', flat=True)
        ) or quantite

        existantes = Immobilisation.objects.filter(
            bon_sortie_origine=bon,
            article_stock=article,
        ).count()
        if existantes >= total_voulu:
            return

        with transaction.atomic():
            for _ in range(total_voulu - existantes):
                Immobilisation.objects.create(
                    type_equipement     = type_eq,
                    article_stock       = article,
                    bon_sortie_origine  = bon,
                    service_affectation = bon.service_demandeur,
                    valeur_acquisition  = prix,
                    prix_depuis_stock   = (prix > 0),
                    fournisseur         = bon.fournisseur,
                    statut              = 'EN_ATTENTE',
                    nom_affichage       = article.designation,
                    cree_par            = bon.cree_par,
                )

    except Exception as e:
        # On log mais on ne plante pas la sauvegarde de la ligne
        logger.exception(
            "Erreur création immobilisation depuis ligne %s (bon %s): %s",
            getattr(instance, 'pk', '?'), getattr(bon, 'pk', '?'), e
        )
