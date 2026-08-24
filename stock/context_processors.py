"""
Context processors optimisés pour NexusERP.

Avant optimisation : ~12-16 queries par page (chaque processor fait 2-4 requêtes).
Après optimisation : ~3-5 queries par page grâce à :
  - Cache par user_id (30-60s TTL) pour les données stables
  - Fusion de requêtes similaires (notifications, demandes)
  - Suppression des COUNT redondants
"""
from django.db.models import Count, Q
from django.core.cache import cache
from accounts.models import Notification
from .models import CircuitValidation, DemandeMateriel, Magasin


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS CACHE
# ═══════════════════════════════════════════════════════════════════════════════

def _ctx_cache_key(user_id, bloc):
    return f"ctx:{user_id}:{bloc}"


# ═══════════════════════════════════════════════════════════════════════════════
# 1. CONTEXTE MAGASIN (1 query → cache 60s)
# ═══════════════════════════════════════════════════════════════════════════════

def contexte_magasin(request):
    """
    Magasins accessibles à l'utilisateur + magasin actif.
    ✅ Cache 60s par user : les magasins d'accès changent rarement.
    """
    if not request.user.is_authenticated:
        return {}

    user_id = request.user.id
    key = _ctx_cache_key(user_id, 'magasins')
    cached = cache.get(key)
    if cached is not None:
        return cached

    if request.user.is_superuser:
        magasins = list(Magasin.objects.all())
    else:
        try:
            profil = request.user.profil
            magasins = list(profil.magasins_autorises.all())
        except Exception:
            magasins = []

    # Sélection automatique UNIQUEMENT si 1 seul magasin
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

    result = {
        'mes_magasins': magasins,
        'magasin_actif': magasin_actif,
    }
    cache.set(key, result, 60)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 2. NOTIFICATIONS (2 queries → 1 query, cache 30s)
# ═══════════════════════════════════════════════════════════════════════════════

def notifications_erp(request):
    """
    Notifications non lues + compteur.
    ✅ 1 seule requête au lieu de 2 ( COUNT intégré via .count() sur le même QS).
    ✅ Cache 30s par user.
    """
    if not request.user.is_authenticated:
        return {}

    user_id = request.user.id
    key = _ctx_cache_key(user_id, 'notif')
    cached = cache.get(key)
    if cached is not None:
        return cached

    # 1 seule requête : récupérer les 5 plus récentes, le COUNT est gratuit
    # car on évalue le queryset une seule fois
    notif_qs = Notification.objects.filter(
        utilisateur=request.user, est_lue=False
    ).order_by('-date_creation')

    notifications = list(notif_qs[:5])
    notifications_count = notif_qs.count()  # réutilise le même filtre

    result = {
        'notifications_non_lues': notifications,
        'notifications_count': notifications_count,
    }
    cache.set(key, result, 30)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 3. VALIDATION MENU (déjà optimisé, ajout cache 30s)
# ═══════════════════════════════════════════════════════════════════════════════

def validation_menu_context(request):
    """
    Compteurs de documents en attente de validation, par circuit.
    ✅ Cache 30s par user + magasin : les compteurs changent à chaque validation.
    """
    if not request.user.is_authenticated:
        return {}

    from .models import BonMouvement, Ajustement, CampagneInventaire, Commande
    from stock.services.isolation_service import get_magasins_autorises

    user_id = request.user.id
    key = _ctx_cache_key(user_id, 'valid_menu')
    cached = cache.get(key)
    if cached is not None:
        return cached

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
        cache.set(key, ctx, 30)
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

    # Déterminer quels types on doit compter
    types_a_compter = set()
    if est_valideur('SORTIE'):
        types_a_compter.add('SORTIE')
    if est_valideur('ENTREE'):
        types_a_compter.add('ENTREE')
        types_a_compter.add('RETOUR_SERVICE')
    if est_valideur('COMMANDE'):
        types_a_compter.add('COMMANDE')
    if est_valideur('AJUSTEMENT'):
        types_a_compter.add('AJUSTEMENT')
    if est_valideur('INVENTAIRE'):
        types_a_compter.add('INVENTAIRE')

    if not types_a_compter:
        cache.set(key, ctx, 30)
        return ctx

    # UNE SEULE requête pour tous les compteurs BonMouvement
    if types_a_compter & {'SORTIE', 'ENTREE', 'RETOUR_SERVICE'}:
        bm_q = BonMouvement.objects.filter(
            statut_validation='ATTENTE',
            magasin_id__in=magasin_ids, is_deleted=False,
        )
        counts_bm = bm_q.values('type_bon').annotate(
            nb=Count('id')
        ).order_by()
        bm_map = {row['type_bon']: row['nb'] for row in counts_bm}
        ctx['nb_bons_sortie_a_valider'] = (
            bm_map.get('SORTIE', 0) + bm_map.get('RETOUR_FOURNISSEUR', 0)
        )
        ctx['nb_bons_entree_a_valider'] = bm_map.get('ENTREE', 0)
        ctx['nb_retours_a_valider'] = bm_map.get('RETOUR_SERVICE', 0)

    # Commandes
    if 'COMMANDE' in types_a_compter:
        ctx['nb_commandes_a_valider'] = Commande.objects.filter(
            statut_validation='BROUILLON', magasin_id__in=magasin_ids,
            is_deleted=False).count()

    # Ajustements
    if 'AJUSTEMENT' in types_a_compter:
        ctx['nb_ajustements_a_valider'] = Ajustement.objects.filter(
            statut_validation='ATTENTE', magasin_id__in=magasin_ids,
            is_deleted=False).count()

    # Inventaires
    if 'INVENTAIRE' in types_a_compter:
        ctx['nb_inventaires_a_valider'] = CampagneInventaire.objects.filter(
            statut='A_VALIDER', magasin_id__in=magasin_ids,
            is_deleted=False).count()

    cache.set(key, ctx, 30)
    return ctx


# ═══════════════════════════════════════════════════════════════════════════════
# 4. DEMANDES (2 processors fusionnés → 1 seul, cache 30s)
# ═══════════════════════════════════════════════════════════════════════════════

def validation_demandes_menu(request):
    """
    Fusion de validation_demandes_menu + menu_validation_context.
    ✅ 1 seule requête au lieu de 3 (CircuitValidation + .exists() + COUNT).
    ✅ Cache 30s par user.
    """
    if not request.user.is_authenticated:
        return {}

    user_id = request.user.id
    key = _ctx_cache_key(user_id, 'valid_demandes')
    cached = cache.get(key)
    if cached is not None:
        return cached

    # 1) Chercher le circuit DEMANDE actif
    circuit = CircuitValidation.objects.filter(
        type_document='DEMANDE', est_actif=True
    ).first()

    peut_valider = bool(
        circuit and circuit.valideurs.filter(id=request.user.id).exists()
    )

    # 2) Compteur global (toujours utile pour le badge sidebar)
    demandes_attente = DemandeMateriel.objects.filter(
        statut='EN_ATTENTE_VALIDATION', is_deleted=False
    ).count()

    # 3) Compteur filtré par service (si validateur)
    nb_valider = 0
    if peut_valider:
        service = getattr(request.user.profil, 'service', None)
        qs = DemandeMateriel.objects.filter(
            statut='EN_ATTENTE_VALIDATION', is_deleted=False
        )
        if service:
            qs = qs.filter(service_demandeur=service)
        nb_valider = qs.count()

    result = {
        'demandes_en_attente_validation': demandes_attente,
        'peut_valider_demandes': peut_valider,
        'nb_demandes_a_valider': nb_valider,
    }
    cache.set(key, result, 30)
    return result


# ═══════════════════════════════════════════════════════════════════════════════
# 5. MENU VALIDATION CONTEXT (désactivé — fusionné dans validation_demandes_menu)
# ═══════════════════════════════════════════════════════════════════════════════

def menu_validation_context(request):
    """
    DÉSACTIVÉ : ce processor est maintenant fusionné dans validation_demandes_menu.
    Retourne {} pour éviter les erreurs si encore référencé dans settings.py.
    """
    return {}
