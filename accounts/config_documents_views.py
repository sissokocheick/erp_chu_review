# accounts/config_documents_views.py
"""
Configuration globale des documents PDF (mono-tenant).
Utilise core.ConfigurationHopital + accounts.ConfigDocument.
"""

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction

from .permissions import verifier_permission
from .models import ConfigDocument
from core.models import ConfigurationHopital


TYPE_DOCS = [
    ('BS', 'Bon de Sortie'),
    ('BE', "Bon d'Entrée"),
    ('BDM', 'Bon de Demande de Matériel'),
    ('BSHS', 'Bon Hors Stock'),
    ('BC', 'Bon de Commande'),
    ('BDM', 'Bon de Demande'),
]


def _get_config_hopital():
    """Retourne (ou crée) la configuration hôpital singleton."""
    # CORRECTION : utiliser get_or_create pour éviter les doublons
    obj = ConfigurationHopital.objects.order_by('id').first()
    if not obj:
        obj = ConfigurationHopital.objects.create()
    return obj


def _ensure_config_documents():
    """Crée les ConfigDocument manquants pour chaque type."""
    for code, _ in TYPE_DOCS:
        ConfigDocument.objects.get_or_create(type_doc=code)


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_param_admin', 'accounts.menu_parametres')
def config_documents_globaux(request):
    """Page de configuration globale des documents PDF."""
    hopital = _get_config_hopital()
    _ensure_config_documents()
    configs = {c.type_doc: c for c in ConfigDocument.objects.all()}

    if request.method == 'POST':
        return _handle_post(request, hopital, configs)

    return _handle_get(request, hopital, configs)


def _handle_get(request, hopital, configs):
    configs_list = []
    for code, label in TYPE_DOCS:
        c = configs.get(code)
        configs_list.append({
            'code': code,
            'label': label,
            'config': c,
            'code_document': getattr(c, 'code_document', '') if c else '',
            'date_creation_doc': getattr(c, 'date_creation_doc', '') if c else '',
            'date_revision_doc': getattr(c, 'date_revision_doc', '') if c else '',
            'version_doc': getattr(c, 'version_doc', '') if c else '',
            'ps2_label': getattr(c, 'ps2_label', '') if c else '',
            'afficher_logo': getattr(c, 'afficher_logo', True) if c else True,
            'afficher_cc': getattr(c, 'afficher_cc', True) if c else True,
            'afficher_ifu': getattr(c, 'afficher_ifu', True) if c else True,
            'afficher_rccm': getattr(c, 'afficher_rccm', True) if c else True,
            'afficher_telephone': getattr(c, 'afficher_telephone', True) if c else True,
            'afficher_signatures': getattr(c, 'afficher_signatures', True) if c else True,
        })

    context = {
        'hopital': hopital,
        'configs_list': configs_list,
        # Labels signataires (si présents sur ConfigurationHopital)
        'label_signataire_1': getattr(hopital, 'label_signataire_1', 'Le Demandeur'),
        'label_signataire_2': getattr(hopital, 'label_signataire_2', 'Le Magasinier'),
        'label_signataire_3': getattr(hopital, 'label_signataire_3', 'Le Responsable Service'),
        'label_signataire_4': getattr(hopital, 'label_signataire_4', 'Le Directeur'),
        'label_signataire_5': getattr(hopital, 'label_signataire_5', 'Le Contrôleur'),
        'label_signataire_6': getattr(hopital, 'label_signataire_6', 'Le Réceptionnaire'),
        # Hiérarchie
        'direction_label': getattr(hopital, 'direction_label', ''),
        'sous_direction_label': getattr(hopital, 'sous_direction_label', ''),
        'service_label': getattr(hopital, 'service_label', ''),
        'republique_label': "RÉPUBLIQUE DE CÔTE D'IVOIRE",
        'devise_label': "Union - Discipline - Travail",
        # Pied de page
        'pied_page_pdf': getattr(hopital, 'pied_page_pdf', ''),
        'couleur_principale': getattr(hopital, 'couleur_principale', '#1c5b96'),
        # Préfixes
        'prefixe_bon_sortie': getattr(hopital, 'prefixe_bon_sortie', 'BS'),
        'prefixe_bon_entree': getattr(hopital, 'prefixe_bon_entree', 'BE'),
        'prefixe_bon_retour': getattr(hopital, 'prefixe_bon_retour', 'BR'),
        'prefixe_bon_hors_stock': getattr(hopital, 'prefixe_bon_hors_stock', 'BSHS'),
        'prefixe_commande': getattr(hopital, 'prefixe_commande', 'BC'),
    }
    return render(request, 'accounts/config_documents.html', context)


def _handle_post(request, hopital, configs):
    user = request.user
    if not user.is_superuser and not (
        user.has_perm('accounts.menu_parametres') or
        user.has_perm('accounts.menu_param_admin')
    ):
        messages.error(request, "⛔ Vous n'avez pas la permission de modifier cette configuration.")
        return redirect('accounts:config_documents_globaux')

    try:
        with transaction.atomic():
            # ── 1. Infos hôpital (si les champs existent) ──
            # CORRECTION : whitelist des champs autorisés pour éviter setattr arbitraire
            ALLOWED_FIELDS = {
                'direction_label': 200, 'sous_direction_label': 200, 'service_label': 200,
                'pied_page_pdf': 500,
                'label_signataire_1': 100, 'label_signataire_2': 100, 'label_signataire_3': 100,
                'label_signataire_4': 100, 'label_signataire_5': 100, 'label_signataire_6': 100,
                'prefixe_bon_sortie': 50, 'prefixe_bon_entree': 50, 'prefixe_bon_retour': 50,
                'prefixe_bon_hors_stock': 50, 'prefixe_commande': 50,
            }
            for field, max_len in ALLOWED_FIELDS.items():
                if hasattr(hopital, field):
                    val = request.POST.get(field, '').strip()
                    if val or field.startswith('label_') or field.startswith('prefixe_'):
                        setattr(hopital, field, val[:max_len])

            couleur = request.POST.get('couleur_principale', '#1c5b96').strip()
            if hasattr(hopital, 'couleur_principale') and _validate_hex_color(couleur):
                hopital.couleur_principale = couleur

            hopital.save()

            # ── 2. Configs par type de document ──
            for code, _ in TYPE_DOCS:
                config = configs.get(code)
                if not config:
                    continue

                prefix = f'config_{code}_'
                config.code_document = _truncate(request.POST.get(f'{prefix}code_document', '').strip(), 50)
                config.date_creation_doc = _truncate(request.POST.get(f'{prefix}date_creation_doc', '').strip(), 20)
                config.date_revision_doc = _truncate(request.POST.get(f'{prefix}date_revision_doc', '').strip(), 20)
                config.version_doc = _truncate(request.POST.get(f'{prefix}version_doc', '').strip(), 10)
                config.ps2_label = _truncate(request.POST.get(f'{prefix}ps2_label', '').strip(), 100)

                config.afficher_logo = request.POST.get(f'{prefix}afficher_logo') == 'on'
                config.afficher_cc = request.POST.get(f'{prefix}afficher_cc') == 'on'
                config.afficher_ifu = request.POST.get(f'{prefix}afficher_ifu') == 'on'
                config.afficher_rccm = request.POST.get(f'{prefix}afficher_rccm') == 'on'
                config.afficher_telephone = request.POST.get(f'{prefix}afficher_telephone') == 'on'
                config.afficher_signatures = request.POST.get(f'{prefix}afficher_signatures') == 'on'

                config.save()

        messages.success(request, "✅ Configuration globale des documents PDF sauvegardée.")
    except Exception as e:
        messages.error(request, f"❌ Erreur lors de la sauvegarde : {e}")

    return redirect('accounts:config_documents_globaux')


def _truncate(value, max_length):
    return value[:max_length] if value else ''


def _validate_hex_color(value):
    import re
    return bool(re.match(r'^#[0-9A-Fa-f]{3}([0-9A-Fa-f]{3})?$', value)) if value else False