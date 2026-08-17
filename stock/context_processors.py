from django.db.models import Count, Q
from accounts.models import Notification
from .models import CircuitValidation, DemandeMateriel, Magasin


def contexte_magasin(request):
    """
    Context processor : magasins accessibles à l'utilisateur.
    ✅ CORRECTION : le superuser accède à TOUS les magasins (règle identique
       à stock.services.isolation_service.get_magasins_autorises).
    ✅ Retourne mes_magasins et magasin_actif pour le template base_ui.html.
    """
    if not request.user.is_authenticated:
        return {}

    if request.user.is_superuser:
        magasins = list(Magasin.objects.all())
    else:
        try:
            profil = request.user.profil
            magasins = list(profil.magasins_autorises.all())
        except Exception:
            magasins = []

    # Sélection automatique UNIQUEMENT si l'utilisateur n'a qu'un seul magasin.
    # Avec plusieurs magasins, on ne choisit JAMAIS à sa place : l'en-tête reste
    # sans sélection et le décorateur @magasin_requis affiche l'écran de choix.
    # (Cohérent partout : la sélection en session magasin_actif_id s'applique
    # à toutes les pages — aucune clé périmée ne doit être écrite.)
    magasin_actif = None
    if len(magasins) == 1:
        magasin_actif = magasins[0]
        request.session['magasin_actif_id'] = str(magasin_actif.id)
    elif len(magasins) > 1:
        magasin_id = request.session.get('magasin_actif_id')
        if magasin_id:
            for m in magasins:
                if str(m.id) == str(magasin_id):
                    magasin_actif = m
                    break

    return {
        'mes_magasins': magasins,
        'magasin_actif': magasin_actif,
    }


def notifications_erp(request):
    """
    Notifications non lues pour l'utilisateur connecté.
    """
    if not request.user.is_authenticated:
        return {}

    notifications = Notification.objects.filter(
        utilisateur=request.user,
        est_lue=False
    ).order_by('-date_creation')[:5]

    return {
        'notifications_non_lues': notifications,
        'notifications_count': Notification.objects.filter(
            utilisateur=request.user, est_lue=False
        ).count(),
    }


def validation_menu_context(request):
    """
    Compteurs de documents en attente de validation, par circuit, pour le menu.

    Chaque compteur n'est calculé que si l'utilisateur est désigné validateur
    du circuit correspondant (ou superuser) : les badges d'attente n'apparaissent
    donc que chez les validateurs, jamais pour un simple magasinier. Les comptes
    sont limités aux magasins auxquels l'utilisateur a accès.
    """
    if not request.user.is_authenticated:
        return {}

    from .models import BonMouvement, Ajustement, CampagneInventaire, Commande
    from stock.services.isolation_service import get_magasins_autorises

    ctx = {
        'nb_bons_sortie_a_valider': 0,
        'nb_bons_entree_a_valider': 0,
        'nb_retours_a_valider': 0,
        'nb_commandes_a_valider': 0,
        'nb_ajustements_a_valider': 0,
        'nb_inventaires_a_valider': 0,
    }

    magasins = get_magasins_autorises(request)
    magasin_ids = list(magasins.values_list('id', flat=True))
    if not magasin_ids:
        return ctx

    user = request.user
    circuits = {
        c.type_document: c for c in CircuitValidation.objects.filter(
            est_actif=True, is_deleted=False
        ).prefetch_related('valideurs')
    }

    def est_valideur(type_document):
        circuit = circuits.get(type_document)
        return bool(
            user.is_superuser
            or (circuit and circuit.valideurs.filter(id=user.id).exists())
        )

    if est_valideur('SORTIE'):
        # Un retour fournisseur RETIRE du stock (mouvement décrémentant) : il
        # est gouverné par le circuit SORTIE et compte donc dans ce badge.
        ctx['nb_bons_sortie_a_valider'] = BonMouvement.objects.filter(
            type_bon__in=['SORTIE', 'RETOUR_FOURNISSEUR'],
            statut_validation='ATTENTE',
            magasin_id__in=magasin_ids, is_deleted=False).count()

    if est_valideur('ENTREE'):
        ctx['nb_bons_entree_a_valider'] = BonMouvement.objects.filter(
            type_bon='ENTREE', statut_validation='ATTENTE',
            magasin_id__in=magasin_ids, is_deleted=False).count()
        ctx['nb_retours_a_valider'] = BonMouvement.objects.filter(
            type_bon='RETOUR_SERVICE', statut_validation='ATTENTE',
            magasin_id__in=magasin_ids, is_deleted=False).count()

    if est_valideur('COMMANDE'):
        ctx['nb_commandes_a_valider'] = Commande.objects.filter(
            statut_validation='BROUILLON', magasin_id__in=magasin_ids,
            is_deleted=False).count()

    if est_valideur('AJUSTEMENT'):
        ctx['nb_ajustements_a_valider'] = Ajustement.objects.filter(
            statut_validation='ATTENTE', magasin_id__in=magasin_ids,
            is_deleted=False).count()

    if est_valideur('INVENTAIRE'):
        ctx['nb_inventaires_a_valider'] = CampagneInventaire.objects.filter(
            statut='A_VALIDER', magasin_id__in=magasin_ids,
            is_deleted=False).count()

    return ctx


def validation_demandes_menu(request):
    """
    Contexte pour le menu de validation des demandes.
    """
    if not request.user.is_authenticated:
        return {}

    demandes_attente = DemandeMateriel.objects.filter(
        statut='EN_ATTENTE_VALIDATION',
        is_deleted=False
    ).count()

    return {
        'demandes_en_attente_validation': demandes_attente,
    }


def menu_validation_context(request):
    """
    Contexte pour le badge "A Valider" (validations de demandes) dans le menu sidebar.

    Le menu "A Valider" n'apparaît que si :
      1. le circuit de validation DEMANDE est actif, ET
      2. l'utilisateur est désigné comme validateur dans ce circuit.
    (Cohérent avec la vue demandes_a_valider qui refuse tout autre cas.)
    """
    if not request.user.is_authenticated:
        return {}

    from .models import CircuitValidation
    circuit = CircuitValidation.objects.filter(
        type_document='DEMANDE', est_actif=True
    ).first()

    peut_valider = bool(
        circuit and circuit.valideurs.filter(id=request.user.id).exists()
    )

    # Le validateur ne voit que les demandes de SON service (cohérent avec
    # la vue demandes_a_valider) : le compteur est filtré de la même façon.
    nb = 0
    if peut_valider:
        service = getattr(request.user.profil, 'service', None)
        qs = DemandeMateriel.objects.filter(
            statut='EN_ATTENTE_VALIDATION',
            is_deleted=False
        )
        if service:
            qs = qs.filter(service_demandeur=service)
        nb = qs.count()

    return {
        'peut_valider_demandes': peut_valider,
        'nb_demandes_a_valider': nb,
    }
