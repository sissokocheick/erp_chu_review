"""
Signal : quand un BonMouvement de type SORTIE est sauvegardé
et que l'article est marqué est_immobilisable=True,
on crée automatiquement une Immobilisation en statut EN_ATTENTE (Sas).
"""

from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender='stock.BonMouvement')
def creer_immobilisations_depuis_bon(sender, instance, created, **kwargs):
    """
    Après la sauvegarde d'un BonMouvement, parcourt les lignes
    et crée une Immobilisation dans le sas pour chaque article immobilisable.
    """
    if not created:
        return
    if instance.type_bon not in ('SORTIE', 'SORTIE_HORS_STOCK'):
        return

    try:
        from .models import Immobilisation, TypeEquipement
        from decimal import Decimal

        for ligne in instance.lignes_bon.select_related('article__famille').all():
            article = ligne.article
            if not getattr(article, 'est_immobilisable', False):
                continue

            # Chercher le TypeEquipement par défaut pour cet article
            # (correspondance par famille si possible, sinon premier type dispo)
            type_eq = None
            try:
                type_eq = TypeEquipement.objects.filter(est_actif=True).first()
            except Exception:
                pass

            if not type_eq:
                continue  # Pas de type configuré — on ne bloque pas

            # Valeur depuis la ligne du bon (prix_unitaire)
            prix = getattr(ligne, 'prix_unitaire', None) or Decimal('0.00')

            # Créer autant d'immobilisations que la quantité (1 bien = 1 immo)
            quantite = int(getattr(ligne, 'quantite', 1) or 1)
            for _ in range(quantite):
                Immobilisation.objects.create(
                    type_equipement     = type_eq,
                    article_stock       = article,
                    bon_sortie_origine  = instance,
                    service_affectation = instance.service_demandeur,
                    valeur_acquisition  = prix,
                    prix_depuis_stock   = (prix > 0),
                    fournisseur         = instance.fournisseur,
                    statut              = 'EN_ATTENTE',
                    nom_affichage       = article.designation,
                    cree_par            = instance.cree_par,
                )

    except Exception as e:
        # On log mais on ne plante pas la sauvegarde du bon
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Erreur création immobilisation depuis bon {instance.pk}: {e}")