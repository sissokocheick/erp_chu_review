import logging
# stock/context_processors.py
from django.db.models import Q

logger = logging.getLogger(__name__)
from stock.models import DemandeMateriel, BonMouvement, CircuitValidation

def notifications_erp(request):
    """Context processor global pour les notifications ERP."""
    if not request.user.is_authenticated:
        return {}

    user = request.user
    entreprise = getattr(request, 'entreprise', None)

    if not entreprise:
        return {'notifications_count': 0, 'notifications_list': []}

    # Notifications non lues (modèle Notification supprimé → compteur à 0)
    notifications_count = 0
    notifications_qs = []

    # Demandes en attente (si l'utilisateur est validateur)
    demandes_attente = 0
    try:
        circuit = CircuitValidation.objects.filter(
            entreprise=entreprise,
            type_document='SORTIE',
            est_actif=True
        ).first()
        # CORRECTION : .filter().exists() au lieu de "in .all()"
        if circuit and circuit.valideurs.filter(id=user.id).exists():
            demandes_attente = DemandeMateriel.objects.filter(
                magasin_cible__entreprise=entreprise,
                statut='EN_COURS',
                is_deleted=False
            ).count()
    except Exception as e:
        logger.warning("[notifications_erp] Erreur demandes en attente: %s", e)

    # Bons en attente de validation
    bons_attente = 0
    try:
        bons_attente = BonMouvement.objects.filter(
            magasin__entreprise=entreprise,
            statut_validation='ATTENTE',
            is_deleted=False
        ).count()
    except Exception as e:
        logger.warning("[notifications_erp] Erreur bons en attente: %s", e)

    return {
        'notifications_count': notifications_count,
        'notifications_list': notifications_qs,
        'demandes_attente_count': demandes_attente,
        'bons_attente_count': bons_attente,
    }


def contexte_magasin(request):
    """Injecte le magasin actif de l'utilisateur dans le contexte."""
    if not request.user.is_authenticated:
        return {}

    entreprise = getattr(request, 'entreprise', None)
    magasin_actif = None
    mes_magasins = []

    if entreprise:
        from stock.models import Magasin
        from accounts.models import Profil

        # ── 1. Récupérer tous les magasins autorisés ──
        try:
            profil = request.user.profil
            if profil.magasins_autorises.exists():
                mes_magasins = list(profil.magasins_autorises.filter(
                    entreprise=entreprise,
                    is_deleted=False
                ))
            else:
                # Fallback : tous les magasins de l'entreprise
                mes_magasins = list(Magasin.objects.filter(
                    entreprise=entreprise,
                    is_deleted=False
                ))
        except Exception as e:
            logger.warning("[contexte_magasin] Erreur récupération magasins profil: %s", e)
            mes_magasins = list(Magasin.objects.filter(
                entreprise=entreprise,
                is_deleted=False
            ))

        # ── 2. Déterminer le magasin actif ──
        # Priorité 1 : magasin stocké en session (via le sélecteur en haut de page)
        magasin_session_id = request.session.get('magasin_actif_id')
        if magasin_session_id:
            try:
                magasin_session = Magasin.objects.get(
                    id=magasin_session_id,
                    entreprise=entreprise,
                    is_deleted=False
                )
                if magasin_session in mes_magasins or request.user.is_superuser:
                    magasin_actif = magasin_session
            except Magasin.DoesNotExist:
                logger.debug("[contexte_magasin] Magasin session %s introuvable", magasin_session_id)

        # Priorité 2 : premier magasin autorisé
        if not magasin_actif and mes_magasins:
            magasin_actif = mes_magasins[0]

        # Priorité 3 : magasin lié au profil (legacy)
        if not magasin_actif:
            try:
                if hasattr(request.user, 'profil') and request.user.profil.magasins_autorises.exists():
                    magasin_actif = request.user.profil.magasins_autorises.filter(
                        entreprise=entreprise,
                        is_deleted=False
                    ).first()
            except Exception:
                pass

    return {
        'magasin_actif': magasin_actif,
        'mes_magasins': mes_magasins,
        'entreprise_active': entreprise,
    }


def validation_menu_context(request):
    """Injecte les infos de validation pour l'affichage des badges/menu."""
    if not request.user.is_authenticated:
        return {}

    entreprise = getattr(request, 'entreprise', None)
    if not entreprise:
        return {'validation_count': 0}

    validation_count = 0
    try:
        # Bons en attente
        validation_count += BonMouvement.objects.filter(
            magasin__entreprise=entreprise,
            statut_validation='ATTENTE',
            is_deleted=False
        ).count()
        # Demandes en attente
        validation_count += DemandeMateriel.objects.filter(
            magasin_cible__entreprise=entreprise,
            statut='EN_COURS',
            is_deleted=False
        ).count()
    except Exception as e:
        logger.warning("[validation_menu_context] Erreur: %s", e)

    return {'validation_count': validation_count}


def entreprises_nav(request):
    """Injecte la liste des entreprises pour le switcher de navigation."""
    if not request.user.is_authenticated:
        return {'entreprises_nav': []}

    try:
        from accounts.models import Entreprise
        if request.user.is_superuser:
            entreprises = list(Entreprise.objects.filter(est_active=True))
        else:
            entreprises = list(request.user.entreprises.filter(est_active=True))
    except Exception as e:
        logger.warning("[entreprises_nav] Erreur: %s", e)
        entreprises = []

    return {
        'entreprises_nav': entreprises,
        'entreprise_active': getattr(request, 'entreprise', None),
    }


# ═══════════════════════════════════════════════════════════════════════════════
# NOUVEAU : Menu "Valider Demandes" pour le circuit DEMANDE
# ═══════════════════════════════════════════════════════════════════════════════

def validation_demandes_menu(request):
    """
    Détermine si l'utilisateur connecté doit voir le menu
    "Valider Demandes" et combien de demandes sont en attente.
    S'appuie sur CircuitValidation (type_document='DEMANDE').
    """
    result = {
        'peut_valider_demandes': False,
        'nb_demandes_a_valider': 0,
    }

    if not hasattr(request, 'user') or not request.user.is_authenticated:
        return result

    entreprise = getattr(request, 'entreprise', None)
    if not entreprise:
        return result

    # Vérifier si le circuit DEMANDE est actif
    circuit = CircuitValidation.objects.filter(
        type_document='DEMANDE',
        est_actif=True,
        entreprise=entreprise
    ).first()

    if not circuit:
        return result

    # L'utilisateur est-il valideur du circuit ?
    if not circuit.valideurs.filter(id=request.user.id).exists():
        return result

    # Récupérer le service de l'utilisateur (helper robuste)
    service_user = None
    profil = getattr(request.user, 'profil', None)
    if profil:
        service_user = getattr(profil, 'service', None) or getattr(
            profil, 'service_demandeur', None
        )
        if not service_user and hasattr(profil, 'services'):
            service_user = profil.services.first()

    if not service_user:
        return result

    # Compter les demandes EN_ATTENTE_VALIDATION du service
    nb = DemandeMateriel.objects.filter(
        service_demandeur=service_user,
        statut='EN_ATTENTE_VALIDATION',
        service_demandeur__entreprise=entreprise
    ).count()

    result['peut_valider_demandes'] = True
    result['nb_demandes_a_valider'] = nb

    return result
