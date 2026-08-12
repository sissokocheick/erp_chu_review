from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Q
from django.apps import apps
from django.contrib import messages
from django.utils.http import url_has_allowed_host_and_scheme
from django.conf import settings

from ..services import NotificationService
from ..decorators import catch_errors
from .catalogue import paginer
from accounts.permissions import verifier_permission
from accounts.models import Notification
import logging

from ..models import BonMouvement
from ..models import Article

logger = logging.getLogger(__name__)

# Constante : taille maximale de fichier upload (1 Mo)
MAX_FILE_SIZE = 1024 * 1024  # 1 Mo en octets


def _safe_referer_redirect(request):
    """Redirige vers le referer si sûr, sinon vers '/'."""
    referer = request.META.get('HTTP_REFERER', '/')
    if referer and url_has_allowed_host_and_scheme(
        referer,
        allowed_hosts={request.get_host()},
        require_https=(not settings.DEBUG and request.is_secure())
    ):
        return redirect(referer)
    return redirect('/')

@login_required(login_url='/auth/login/')
def api_notifications(request):
    notifs = Notification.objects.filter(
        utilisateur=request.user, est_lue=False
    ).order_by('-date_creation')[:10]

    TYPE_STYLES = {
        'SUCCESS': ('fa-check-circle', '#28a745'),
        'ERROR':   ('fa-times-circle', '#dc3545'),
        'WARNING': ('fa-exclamation-triangle', '#ffc107'),
        'INFO':    ('fa-info-circle', '#0d6efd'),
    }

    data = []
    for n in notifs:
        icon_default, color_default = TYPE_STYLES.get(n.type_notif, ('fa-bell', '#6c757d'))
        data.append({
            'id': n.id,
            'titre': n.titre,
            'message': n.message[:80] + '…' if len(n.message) > 80 else n.message,
            'url': n.url or '#',
            'type': n.type_notif,
            'icon': getattr(n, 'icon', None) or icon_default,
            'color': getattr(n, 'color', None) or color_default,
            'date': n.date_creation.strftime('%d/%m %H:%M'),
            'est_lue': n.est_lue,
        })

    total_non_lues = Notification.objects.filter(
        utilisateur=request.user, est_lue=False
    ).count()
    return JsonResponse({'count': len(notifs), 'total_non_lues': total_non_lues, 'notifications': data})

@login_required(login_url='/auth/login/')
def liste_notifications(request):
    notifs = Notification.objects.filter(utilisateur=request.user)

    # ── Filtres ──
    categorie = request.GET.get('categorie', '').strip()
    type_notif = request.GET.get('type', '').strip()
    q = request.GET.get('q', '').strip()
    if categorie in dict(Notification.CATEGORIE_CHOICES):
        notifs = notifs.filter(categorie=categorie)
    if type_notif in dict(Notification.TYPE_CHOICES):
        notifs = notifs.filter(type_notif=type_notif)
    if q:
        notifs = notifs.filter(
            Q(titre__icontains=q) | Q(message__icontains=q)
        )

    # ── Action : marquer TOUTES les non-lues comme lues (pas seulement la page) ──
    if request.GET.get('marquer_lues') == '1':
        nb = Notification.marquer_toutes_lues(request.user)
        messages.success(request, f"✅ {nb} notification(s) marquée(s) comme lue(s).")
        return redirect(request.path + _filtres_qs(request))

    nb_non_lues = Notification.objects.filter(
        utilisateur=request.user, est_lue=False
    ).count()
    notifs = notifs.order_by('-date_creation')
    page_obj, per_page = paginer(notifs, request, per_page_key='per_page', default=25)

    return render(request, 'stock/notifications.html', {
        'notifications': page_obj,
        'per_page': per_page,
        'nb_non_lues': nb_non_lues,
        'filtre_categorie': categorie,
        'filtre_type': type_notif,
        'filtre_q': q,
        'categories': Notification.CATEGORIE_CHOICES,
        'types_notif': Notification.TYPE_CHOICES,
    })


def _filtres_qs(request):
    """Reconstruit la querystring des filtres pour préserver le filtre après action."""
    parts = []
    for key in ('categorie', 'type', 'q', 'page'):
        val = request.GET.get(key, '').strip()
        if val:
            parts.append(f"{key}={val}")
    return ('?' + '&'.join(parts)) if parts else ''


@login_required(login_url='/auth/login/')
@require_POST
def marquer_notification_lue(request, notif_id):
    notif = get_object_or_404(
        Notification, id=notif_id, utilisateur=request.user
    )
    notif.est_lue = True
    notif.date_lecture = timezone.now()
    notif.save(update_fields=['est_lue', 'date_lecture'])
    return JsonResponse({'success': True})


@login_required(login_url='/auth/login/')
@require_POST
def supprimer_notification(request, notif_id):
    """Supprime une notification (POST)."""
    notif = get_object_or_404(
        Notification, id=notif_id, utilisateur=request.user
    )
    notif.delete()
    return JsonResponse({'success': True})


@login_required(login_url='/auth/login/')
@require_POST
def tout_effacer_notifications(request):
    """Supprime toutes les notifications de l'utilisateur (POST)."""
    Notification.tout_effacer(request.user)
    messages.success(request, "🗑️ Toutes vos notifications ont été supprimées.")
    return JsonResponse({'success': True, 'redirect': '/notifications/'})

@login_required(login_url='/auth/login/')
@catch_errors(redirect_url='/')
def upload_fichier_generique(request, app_label, model_name, obj_id, field_name):
    """
    Upload générique d'un fichier sur n'importe quel modèle.

    CORRECTIONS APPLIQUÉES :
    - La logique BonMouvement n'est plus écrasée par perm_map.get()
    - Le check 'not in perm_map' inclut désormais 'bonmouvement'
    - Import messages factorisé (1 seul import en haut du fichier)
    """
    model_name_lower = model_name.lower()

    perm_map = {
        'commande':     'accounts.menu_commandes',
        'ajustement':   'accounts.menu_ajustements',
    }

    # ── Calcul de la permission requise ──
    if model_name_lower == 'bonmouvement':
        try:
            bon = BonMouvement.objects.get(id=obj_id)
            type_bon = getattr(bon, 'type_bon', '')
            perm_by_type = {
                'ENTREE':             'accounts.menu_entrees',
                'SORTIE':             'accounts.menu_sorties',
                'RETOUR_SERVICE':     'accounts.menu_retours_services',
                'SORTIE_HORS_STOCK':  'accounts.menu_sorties_hors_stock',
                'RETOUR_FOURNISSEUR': 'accounts.menu_retours_fournisseurs',
                'AJUSTEMENT':         'accounts.menu_ajustements',
            }
            required_perm = perm_by_type.get(type_bon)
        except BonMouvement.DoesNotExist:
            required_perm = None
    else:
        required_perm = perm_map.get(model_name_lower)

    # ── Vérification de la permission ──
    if model_name_lower == 'bonmouvement':
        # Pour BonMouvement, required_perm peut être None si type inconnu
        if required_perm:
            if not (request.user.is_superuser or request.user.has_perm(required_perm)):
                messages.error(
                    request,
                    f"⛔ Vous n'avez pas le droit de joindre un document à ce {model_name_lower}."
                )
                return _safe_referer_redirect(request)
    else:
        # Pour les autres modèles
        if model_name_lower not in perm_map:
            messages.error(request, "⛔ Upload non autorisé sur ce type de document.")
            return _safe_referer_redirect(request)

        if required_perm and not (
            request.user.is_superuser or request.user.has_perm(required_perm)
        ):
            messages.error(
                request,
                f"⛔ Vous n'avez pas le droit de joindre un document à ce {model_name_lower}."
            )
            return _safe_referer_redirect(request)

    if request.method == 'POST' and request.FILES.get('document'):
        fichier = request.FILES['document']
        if not fichier.name.lower().endswith(('.jpg', '.jpeg', '.png', '.pdf')):
            messages.error(
                request,
                "Format invalide ! Seuls JPG, PNG et PDF sont autorisés."
            )
            return _safe_referer_redirect(request)
        if fichier.size > MAX_FILE_SIZE:
            messages.error(
                request,
                "Fichier trop lourd ! Maximum 1 Mo."
            )
            return _safe_referer_redirect(request)

        # ═══════════════════════════════════════════════════════════════════
        # ✅ CORRECTION : Whitelist des champs autorisés pour setattr
        # Empêche la modification de n'importe quel champ (ex: is_deleted, is_superuser)
        # ═══════════════════════════════════════════════════════════════════
        ALLOWED_FIELDS = {
            'document_scan', 'fichier_pdf', 'document_livraison',
            'fichier', 'scan', 'justificatif', 'piece_jointe',
        }
        if field_name not in ALLOWED_FIELDS:
            logger.warning(
                f"[UPLOAD SECURITY] Tentative d'upload sur champ non autorisé : "
                f"{field_name} par {request.user} sur {model_name}#{obj_id}"
            )
            messages.error(request, "⛔ Champ non autorisé pour l'upload.")
            return _safe_referer_redirect(request)

        try:
            Model = apps.get_model(app_label, model_name)
            obj = get_object_or_404(Model, id=obj_id)
                # Mono-tenant : vérification supprimée
            setattr(obj, field_name, fichier)
            obj.save()
            messages.success(request, "Le document a été joint avec succès !")
        except Exception as e:
            logger.exception("[UPLOAD ERROR] %s", e)

            messages.error(
                request,
                "Une erreur est survenue lors de l'upload. "
                "Veuillez réessayer ou contacter l'administrateur."
            )
    return _safe_referer_redirect(request)

# ═══════════════════════════════════════════════════════════════════════
# API LISTE ARTICLES (pour inventaire personnalisé)
# ═══════════════════════════════════════════════════════════════════════
@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_articles')
def api_articles_json(request):
    """Retourne la liste des articles en JSON (pour sélection inventaire personnalisé)."""
    articles = Article.objects.filter(
        is_deleted=False
    ).values('id', 'reference', 'designation').order_by('designation')
    return JsonResponse({'articles': list(articles)})
