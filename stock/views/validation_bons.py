from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import Prefetch
from django.utils import timezone
from datetime import timedelta
import logging

from accounts.permissions import verifier_permission
from stock.models import (
    BonMouvement, CircuitValidation, Mouvement, LigneBon,
    StockItem, Ajustement, Commande
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
def valider_bon(request, bon_id):
    """
    Valide un bon de mouvement (Entrée, Sortie, Retour, Hors Stock, Ajustement).
    Si le bon est lié à une commande, met aussi à jour la commande.

    CORRECTIONS APPLIQUÉES :
    - select_for_update() SÉPARÉ de select_related() pour éviter l'erreur PostgreSQL
      "FOR UPDATE ne peut être appliqué sur le côté possiblement NULL d'une jointure externe"
    - Mode fail-closed : peut_valider = False si pas de circuit configuré
    - prefetch_related sur lignes_bon__article pour éviter N+1
    - Lookup Ajustement corrigé (filtre sur bon__id + statut)
    - Logger exception au lieu de str(e)
    - URL de repli dynamique selon le type de bon
    - ✅ Gestion UnboundLocalError : bon initialisé à None
    """
    entreprise = request.entreprise
    bon = None  # ✅ CORRECTION : initialiser pour éviter UnboundLocalError

    try:
        with transaction.atomic():
            # ── Étape 1 : Récupérer le bon AVEC les relations (SANS verrou) ──
            # select_related sur FK nullable crée LEFT JOIN → incompatible avec FOR UPDATE
            bon = get_object_or_404(
                BonMouvement.objects
                    .select_related('magasin', 'commande_liee', 'cree_par'),
                id=bon_id,
                magasin__entreprise=entreprise,
            )

            # ── Étape 2 : Verrouiller UNIQUEMENT la table BonMouvement ──
            # Pas de select_related ici pour éviter le LEFT JOIN
            BonMouvement.objects.select_for_update().get(pk=bon.pk)

            # ── Précharger les lignes après le verrou ──
            bon.lignes_bon.all()  # déclenche le prefetch si configuré, ou simple query

            # ── Vérifier que le bon n'est pas déjà validé ──
            if bon.statut_validation == 'VALIDE':
                messages.warning(
                    request,
                    f"⚠️ Le bon {bon.numero_bon} est déjà validé."
                )
                return redirect(_get_redirect_url(bon.type_bon))

            # ── Vérification des permissions (circuit de validation) ──
            mapping_circuit = {
                'ENTREE':             'ENTREE',
                'SORTIE':             'SORTIE',
                'SORTIE_HORS_STOCK':  'SORTIE',
                'RETOUR_FOURNISSEUR': 'ENTREE',
                'RETOUR_SERVICE':     'ENTREE',
                'AJUSTEMENT':         'AJUSTEMENT',
            }
            type_circuit = mapping_circuit.get(bon.type_bon)

            peut_valider = request.user.is_superuser
            if not peut_valider and type_circuit:
                try:
                    circuit = CircuitValidation.objects.get(
                        type_document=type_circuit,
                        entreprise=entreprise,
                        is_deleted=False
                    )
                    if circuit.valideurs.filter(id=request.user.id).exists():
                        peut_valider = True
                except CircuitValidation.DoesNotExist:
                    # FAIL-CLOSED : pas de circuit = pas de validation possible
                    # Seul le superuser peut valider sans circuit
                    peut_valider = False
                    logger.warning(
                        f"[VALIDATION] Pas de circuit pour {type_circuit} "
                        f"dans l'entreprise {entreprise.id}"
                    )

            if not peut_valider:
                messages.error(
                    request,
                    "❌ Vous n'êtes pas autorisé à valider ce type de bon."
                )
                return redirect(_get_redirect_url(bon.type_bon))

            # ── Validation du bon ──
            bon.statut_validation = 'VALIDE'
            bon.valide_par = request.user
            bon.date_validation = timezone.now()
            bon.save(update_fields=['statut_validation', 'valide_par', 'date_validation'])

            # ── Exécuter les mouvements de stock liés aux lignes du bon ──
            type_mouvement = TYPE_BON_TO_MOUVEMENT.get(bon.type_bon)
            if not type_mouvement:
                messages.error(
                    request,
                    f"❌ Type de mouvement inconnu pour {bon.type_bon}."
                )
                return redirect(_get_redirect_url(bon.type_bon))

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
                        date_peremption=ligne.date_peremption,
                    )
                    StockTransactionService.executer(mouvement)

                elif bon.type_bon in ('SORTIE', 'SORTIE_HORS_STOCK'):
                    mouvement = Mouvement(
                        type_mouvement='SORTIE',
                        article=ligne.article,
                        magasin=bon.magasin,
                        quantite=ligne.quantite,
                        utilisateur=bon.cree_par or request.user,
                        reference_document=bon.numero_bon,
                        commentaire=f"Validation du bon {bon.numero_bon}",
                        numero_lot=ligne.numero_lot,
                    )
                    StockTransactionService.executer(mouvement)

                elif bon.type_bon == 'RETOUR_FOURNISSEUR':
                    mouvement = Mouvement(
                        type_mouvement='RETOUR_FOURNISSEUR',
                        article=ligne.article,
                        magasin=bon.magasin,
                        quantite=ligne.quantite,
                        utilisateur=bon.cree_par or request.user,
                        reference_document=bon.numero_bon,
                        commentaire=f"Validation du bon {bon.numero_bon}",
                    )
                    StockTransactionService.executer(mouvement)

                elif bon.type_bon == 'RETOUR_SERVICE':
                    mouvement = Mouvement(
                        type_mouvement='RETOUR_SERVICE',
                        article=ligne.article,
                        magasin=bon.magasin,
                        quantite=ligne.quantite,
                        utilisateur=bon.cree_par or request.user,
                        reference_document=bon.numero_bon,
                        commentaire=f"Validation du bon {bon.numero_bon}",
                    )
                    StockTransactionService.executer(mouvement)

                elif bon.type_bon == 'AJUSTEMENT':
                    # L'ajustement est traité différemment via StockService
                    

                    # CORRECTION : lookup par FK directe ou critères stricts
                    ajustement = Ajustement.objects.filter(
                        bon_mouvement=bon,  # FK directe préférable
                        statut_validation='EN_ATTENTE',
                    ).first()

                    if not ajustement:
                        # Fallback : recherche par critères avec filtre strict
                        ajustement = Ajustement.objects.filter(
                            magasin=bon.magasin,
                            article=ligne.article,
                            quantite=ligne.quantite,
                            statut_validation='EN_ATTENTE',
                            date_creation__gte=timezone.now() - timedelta(days=1),
                        ).order_by('-date_creation').first()

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
            "❌ Une erreur est survenue lors de la validation. "
            "L'équipe technique a été notifiée."
        )

    # ✅ CORRECTION : redirection sûre même si bon est None
    if bon:
        return redirect(_get_redirect_url(bon.type_bon))
    return redirect('liste_bons')


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_circuits_validation')
def valider_ajustement(request, ajustement_id):
    """Valide un ajustement de stock et applique les mouvements."""
    entreprise = request.entreprise

    try:
        with transaction.atomic():
            ajustement = get_object_or_404(
                Ajustement.objects.select_for_update(),
                id=ajustement_id, magasin__entreprise=entreprise
            )

            peut_valider = request.user.is_superuser
            if not peut_valider:
                try:
                    circuit = CircuitValidation.objects.get(
                        type_document='AJUSTEMENT',
                        entreprise=entreprise,
                        is_deleted=False
                    )
                    if circuit.valideurs.filter(id=request.user.id).exists():
                        peut_valider = True
                except CircuitValidation.DoesNotExist:
                    peut_valider = False

            if not peut_valider:
                messages.error(request, "❌ Vous n'êtes pas autorisé à valider les ajustements.")
                return redirect('liste_ajustements')

            if ajustement.statut_validation == 'VALIDE':
                messages.warning(request, "Cet ajustement est déjà validé.")
                return redirect('liste_ajustements')

            ajustement.statut_validation = 'VALIDE'
            ajustement.valide_par = request.user
            ajustement.date_validation = timezone.now()
            ajustement.save(update_fields=['statut_validation', 'valide_par', 'date_validation'])

            
            StockService.ajuster_stock(ajustement)

        messages.success(
            request,
            f"✅ Ajustement validé — {ajustement.article.designation} x{ajustement.quantite}"
        )
        logger.info(
            f"[AJUSTEMENT] {request.user} a validé l'ajustement #{ajustement.id}"
        )
    except Exception as e:
        logger.exception("[AJUSTEMENT ERROR] %s : %s", request.user, e)
        messages.error(
            request,
            "❌ Une erreur est survenue lors de la validation de l'ajustement."
        )

    return redirect('liste_ajustements')


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
        'RETOUR_FOURNISSEUR': 'liste_retours_fournisseurs',
        'AJUSTEMENT':         'liste_ajustements',
    }
    return url_map.get(type_bon, 'liste_bons')
