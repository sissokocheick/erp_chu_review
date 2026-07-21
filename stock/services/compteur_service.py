# stock/services/compteur_service.py
"""Service de génération des numéros de documents uniques.

Wrapper autour de CompteurDocument.generer_numero() avec les formats
métier prédéfinis (bons, commandes, demandes).

La vérification d'unicité du numéro généré est ACTIVE ici via les
paramètres model_class et field_name passés à CompteurDocument.generer_numero().
Cette vérification complète les contraintes UNIQUE sur les modèles cibles
(BonMouvement.numero_bon, Commande.numero_commande, etc.).
"""

from stock.models import CompteurDocument


class CompteurDocumentService:
    """Génère des numéros de documents uniques via le compteur global."""

    # ✅ CORRECTION : mapping externalisé en constante de classe
    TYPE_BON_MAPPING = {
        'ENTREE':             ('BON_ENTREE', 'BE'),
        'SORTIE':             ('BON_SORTIE', 'BS'),
        'RETOUR_SERVICE':     ('BON_RETOUR', 'BR'),
        'SORTIE_HORS_STOCK':  ('BON_HS', 'BSHS'),
    }

    @classmethod
    def generer_numero_bon(cls, type_bon, entreprise):
        """
        Génère un numéro de bon au format PREFIXE-ANNEE-SEQUENCE.
        La séquence est CONTINUE (pas de réinitialisation par année).
        """
        type_doc, prefix = cls.TYPE_BON_MAPPING.get(type_bon, ('BON_ENTREE', 'BE'))

        # ✅ CORRECTION : suppression du paramètre mort `eid`
        def format_num(compteur, annee, eid):
            # eid est fourni par CompteurDocument.generer_numero mais non utilisé ici
            return f"{prefix}-{annee}-{compteur:04d}"

        # Vérification d'unicité active via model_class et field_name
        from stock.models import BonMouvement
        return CompteurDocument.generer_numero(
            entreprise.id, type_doc, format_num,
            model_class=BonMouvement,
            field_name='numero_bon',
            max_retries=10
        )

    @classmethod
    def generer_numero_commande(cls, entreprise):
        """Génère un numéro de commande au format BC-ANNEE-SEQUENCE."""
        def format_num(compteur, annee, eid):
            return f"BC-{annee}-{compteur:04d}"

        # Vérification d'unicité active via model_class et field_name
        from stock.models import Commande
        return CompteurDocument.generer_numero(
            entreprise.id, 'COMMANDE', format_num,
            model_class=Commande,
            field_name='numero_commande',
            max_retries=10
        )

    @classmethod
    def generer_numero_demande(cls, entreprise):
        """Génère un numéro de demande au format BDM-ANNEE-SEQUENCE."""
        def format_num(compteur, annee, eid):
            return f"BDM-{annee}-{compteur:04d}"

        # Vérification d'unicité active via model_class et field_name
        from stock.models import DemandeMateriel
        return CompteurDocument.generer_numero(
            entreprise.id, 'DEMANDE_MATERIEL', format_num,
            model_class=DemandeMateriel,
            field_name='numero_demande',
            max_retries=10
        )
