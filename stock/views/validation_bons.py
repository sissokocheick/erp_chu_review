from django.shortcuts import redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.utils import timezone
import logging

from accounts.permissions import verifier_permission
from stock.models import (
    BonMouvement, CircuitValidation, Mouvement,
    Ajustement,
)
from stock.services.stock_transaction_service import StockTransactionService

logger = logging.getLogger(__name__)

from stock.services.stock_service import StockService

# ──────────────────────────────────────────────────────────────
# MAPPING TYPE_BON → TYPE_MOUVEMENT
# ──────────────────────────────────────────────────────────────

TYPE_BON_TO_MOUVEMENT = {
    'ENTREE':             'ENTREE',
    'SORTIE':             'SORTIE',
    'SORTIE_HORS_STOCK':  'SORTIE',
    'RETOUR_FOURNISSEUR': 'RETOUR_FOURNISSEUR',
    'RETOUR_SERVICE':     'RETOUR_SERVICE',
    'AJUSTEMENT':         'AJUSTEMENT',
}

# ──────────────────────────────────────────────────────────────
# VALIDER UN BON DE MOUVEMENT
# ──────────────────────────────────────────────────────────────

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_circuits_validation')
@transaction.atomic
def valider_bon(request, bon_id):
    """
    Valide un bon de mouvement (Entrée, Sortie, Retour, Hors Stock, Ajustement).
    Si le bon est lié à une commande, met aussi à jour la commande.
    """
    bon = None

    if request.method != 'POST':
        messages.error(request, "❌ Cette action doit être effectuée en POST.")
        return redirect('liste_sorties')

    try:
        # Étape 1 : verrouiller la ligne du bon et TRAVAILLER sur l'instance
        # verrouillée (sinon le statut lu est antérieur au verrou → double
        # validation possible entre deux requêtes concurrentes).
        bon = get_object_or_404(
            BonMouvement.objects
                .select_related('magasin', 'commande_liee', 'cree_par')
                # PostgreSQL refuse FOR UPDATE sur les tables côté nullable
                # d'un OUTER JOIN (commande_liee/cree_par). On verrouille
                # explicitement uniquement la ligne du bon ; les relations
                # restent chargées pour éviter les accès supplémentaires.
                .select_for_update(of=('self',)),
            id=bon_id)

        # Vérifier que le bon n'est pas déjà validé
        if bon.statut_validation == 'VALIDE':
            messages.warning(
                request,
                f"⚠️ Le bon {bon.numero_bon} est déjà validé."
            )
            return redirect(_get_redirect_url(bon.type_bon))

        # Un bon annulé ou rejeté ne peut pas être validé
        if bon.est_annule:
            messages.error(
                request,
                f"❌ Le bon {bon.numero_bon} est annulé et ne peut pas être validé."
            )
            return redirect(_get_redirect_url(bon.type_bon))

        if bon.statut_validation == 'REJETE':
            messages.error(
                request,
                f"❌ Le bon {bon.numero_bon} a été rejeté et ne peut pas être validé."
            )
            return redirect(_get_redirect_url(bon.type_bon))

        # Les transferts suivent leur propre circuit : la sortie est déjà
        # exécutée à la création, l'entrée doit passer par la réception
        # (TransfertService.receptionner_transfert).
        if bon.type_bon == 'TRANSFERT':
            messages.error(
                request,
                f"❌ Le transfert {bon.numero_bon} se réceptionne depuis la "
                f"liste des transferts (bouton « Réceptionner »)."
            )
            return redirect('liste_transferts')

        # Vérification des permissions (circuit de validation)
        # NOTE : un retour fournisseur RETIRE du stock (mouvement décrémentant,
        # comme une sortie) → il est gouverné par le circuit SORTIE, pas ENTREE.
        # Seul le retour service (réintégration) relève du circuit ENTREE.
        mapping_circuit = {
            'ENTREE':             'ENTREE',
            'SORTIE':             'SORTIE',
            'SORTIE_HORS_STOCK':  'SORTIE',
            'RETOUR_FOURNISSEUR': 'SORTIE',
            'RETOUR_SERVICE':     'ENTREE',
            'AJUSTEMENT':         'AJUSTEMENT',
        }
        type_circuit = mapping_circuit.get(bon.type_bon)

        peut_valider = request.user.is_superuser
        if not peut_valider and type_circuit:
            try:
                circuit = CircuitValidation.objects.get(
                    type_document=type_circuit,
                    is_deleted=False
                )
                if circuit.valideurs.filter(id=request.user.id).exists():
                    peut_valider = True
            except CircuitValidation.DoesNotExist:
                peut_valider = False
                logger.warning(
                    f"[VALIDATION] Pas de circuit pour {type_circuit}"
                )

        if not peut_valider:
            messages.error(
                request,
                "❌ Vous n'êtes pas autorisé à valider ce type de bon."
            )
            return redirect(_get_redirect_url(bon.type_bon))

        # Le type de mouvement doit être connu AVANT toute écriture : sinon le
        # bon serait marqué VALIDE sans qu'aucun mouvement de stock ne soit
        # exécuté (l'erreur doit faire remonter la transaction, pas un simple
        # redirect qui commiterait le statut déjà sauvegardé).
        type_mouvement = TYPE_BON_TO_MOUVEMENT.get(bon.type_bon)
        if not type_mouvement:
            logger.error(
                "[VALIDATION] Type de mouvement inconnu pour %s (bon %s)",
                bon.type_bon, bon.numero_bon)
            raise ValueError(
                f"Type de mouvement inconnu pour {bon.type_bon}.")

        # ── Toutes les vérifications sont passées : à partir d'ici les
        #    écritures démarrent. Toute erreur doit lever (rollback). ──

        bon.statut_validation = 'VALIDE'
        bon.valide_par = request.user
        bon.date_validation = timezone.now()
        bon.save(update_fields=['statut_validation', 'valide_par', 'date_validation'])

        # Exécuter les mouvements de stock liés aux lignes du bon
        for ligne in bon.lignes_bon.all():
            if bon.type_bon == 'ENTREE':
                mouvement = Mouvement(
                    type_mouvement='ENTREE',
                    article=ligne.article,
                    magasin=bon.magasin,
                    quantite=ligne.quantite,
                    prix_unitaire=ligne.prix_unitaire,
                    utilisateur=bon.cree_par or request.user,
                    reference_document=bon.numero_bon,
                    commentaire=f"Validation du bon {bon.numero_bon}",
                    numero_lot=ligne.numero_lot,
                    date_peremption=ligne.date_peremption)
                StockTransactionService.executer(mouvement)

            elif bon.type_bon == 'SORTIE':
                mouvement = Mouvement(
                    type_mouvement='SORTIE',
                    article=ligne.article,
                    magasin=bon.magasin,
                    quantite=ligne.quantite,
                    utilisateur=bon.cree_par or request.user,
                    reference_document=bon.numero_bon,
                    commentaire=f"Validation du bon {bon.numero_bon}",
                    numero_lot=ligne.numero_lot)
                StockTransactionService.executer(mouvement)

            elif bon.type_bon == 'SORTIE_HORS_STOCK':
                # Bon hors stock : aucun impact sur le stock physique.
                # Les mouvements HS (update_stock=False) sont créés à la
                # création du bon ; la validation ne fait que l'approuver.
                pass

            elif bon.type_bon == 'RETOUR_FOURNISSEUR':
                mouvement = Mouvement(
                    type_mouvement='RETOUR_FOURNISSEUR',
                    article=ligne.article,
                    magasin=bon.magasin,
                    quantite=ligne.quantite,
                    utilisateur=bon.cree_par or request.user,
                    reference_document=bon.numero_bon,
                    commentaire=f"Validation du bon {bon.numero_bon}")
                StockTransactionService.executer(mouvement)

            elif bon.type_bon == 'RETOUR_SERVICE':
                mouvement = Mouvement(
                    type_mouvement='RETOUR_SERVICE',
                    article=ligne.article,
                    magasin=bon.magasin,
                    quantite=ligne.quantite,
                    utilisateur=bon.cree_par or request.user,
                    reference_document=bon.numero_bon,
                    commentaire=f"Validation du bon {bon.numero_bon}")
                StockTransactionService.executer(mouvement)

            elif bon.type_bon == 'AJUSTEMENT':
                # L'ajustement est traité différemment via StockService.
                # Seul l'ajustement EXPLICITEMENT lié au bon est validé :
                # jamais un ajustement correspondant « par hasard »
                # (magasin/article/quantité d'un autre utilisateur).
                ajustement = Ajustement.objects.select_for_update().filter(
                    bon_mouvement=bon,
                    statut_validation='ATTENTE').first()

                if ajustement:
                    ajustement.statut_validation = 'VALIDE'
                    ajustement.valide_par = request.user
                    ajustement.date_validation = timezone.now()
                    ajustement.save(update_fields=['statut_validation', 'valide_par', 'date_validation'])
                    StockService.ajuster_stock(ajustement)

        messages.success(
            request,
            f"✅ Bon {bon.numero_bon} validé et mouvements de stock appliqués."
        )
        logger.info(
            f"[VALIDATION] {request.user} a validé le bon {bon.numero_bon}"
        )

    except Exception as e:
        logger.exception("[VALIDATION ERROR] %s : %s", request.user, e)
        messages.error(
            request,
            "❌ Une erreur est survenue lors de la validation."
        )

    if bon:
        return redirect(_get_redirect_url(bon.type_bon))
    return redirect('liste_sorties')


# ──────────────────────────────────────────────────────────────
# HELPERS
# ──────────────────────────────────────────────────────────────

def _get_redirect_url(type_bon):
    """Retourne l'URL de redirection appropriée selon le type de bon."""
    url_map = {
        'ENTREE':             'liste_entrees',
        'SORTIE':             'liste_sorties',
        'SORTIE_HORS_STOCK':  'liste_bons_hors_stock',
        'RETOUR_SERVICE':     'liste_retours_services',
        # Un retour fournisseur est un document de sortie de stock : la page
        # des retours ne liste que les RETOUR_SERVICE, on redirige donc vers
        # les sorties (où le mouvement de sortie apparaît dans l'historique).
        'RETOUR_FOURNISSEUR': 'liste_sorties',
        'AJUSTEMENT':         'liste_ajustements',
        'TRANSFERT':          'liste_transferts',
    }
    return url_map.get(type_bon, 'liste_sorties')
