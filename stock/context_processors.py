from django.db.models import Count, Q
from accounts.models import Notification
from .models import CircuitValidation, DemandeMateriel


def contexte_magasin(request):
    """
    Context processor : magasins accessibles à l'utilisateur.
    ✅ CORRECTION : suppression de toute référence à entreprise/tenant.
    ✅ Retourne mes_magasins et magasin_actif pour le template base_ui.html.
    """
    if not request.user.is_authenticated:
        return {}

    try:
        profil = request.user.profil
        magasins = list(profil.magasins_autorises.all())
    except Exception:
        magasins = []

    # Sélection automatique si un seul magasin
    magasin_actif = None
    if len(magasins) == 1:
        magasin_actif = magasins[0]
    elif len(magasins) > 1:
        # Vérifier si un magasin est stocké en session
        magasin_id = request.session.get('magasin_id')
        if magasin_id:
            for m in magasins:
                if str(m.id) == str(magasin_id):
                    magasin_actif = m
                    break
        # Sinon, prendre le premier
        if not magasin_actif:
            magasin_actif = magasins[0]
            request.session['magasin_id'] = magasin_actif.id

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
    Contexte pour le menu de validation (bons en attente).
    """
    if not request.user.is_authenticated:
        return {}

    from .models import BonMouvement
    bons_attente = BonMouvement.objects.filter(
        statut_validation='ATTENTE',
        is_deleted=False
    ).count()

    return {
        'bons_en_attente': bons_attente,
    }


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
    Contexte pour le badge "Valider Demandes" dans le menu sidebar.
    """
    if not request.user.is_authenticated:
        return {}

    from accounts.models import Profil
    try:
        profil = request.user.profil
        peut_valider = profil.est_valideur or profil.est_gestionnaire or request.user.is_superuser
    except Exception:
        peut_valider = request.user.is_superuser

    nb = DemandeMateriel.objects.filter(
        statut='EN_ATTENTE_VALIDATION',
        is_deleted=False
    ).count()

    return {
        'peut_valider_demandes': peut_valider,
        'nb_demandes_a_valider': nb,
    }
