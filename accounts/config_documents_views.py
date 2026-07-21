# accounts/config_documents_views.py
"""
Configuration globale des documents PDF (niveau entreprise).
Alimente Entreprise.get_pdf_config() et ConfigDocument.
"""

from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.core.exceptions import PermissionDenied

from .permissions import verifier_permission
from .models import Entreprise, ConfigDocument


@login_required(login_url='/accounts/login/')
@verifier_permission('accounts.menu_parametres', 'accounts.menu_param_admin')
def config_documents_globaux(request):
    """Page de configuration globale des documents PDF."""
    entreprise = request.entreprise

    # S'assurer que les configs par défaut existent
    entreprise.creer_configs_documents_par_defaut()

    configs = {c.type_doc: c for c in entreprise.configs_documents.all()}

    if request.method == 'POST':
        return _handle_post(request, entreprise, configs)

    return _handle_get(request, entreprise, configs)


def _handle_get(request, entreprise, configs):
    """Affiche le formulaire pré-rempli."""
    # Préparer les configs pour le template (évite filtres custom)
    type_docs = [
        ('BS', 'Bon de Sortie'),
        ('BE', "Bon d'Entrée"),
        ('BR', 'Bon de Retour'),
        ('BSHS', 'Bon Hors Stock'),
        ('BC', 'Bon de Commande'),
        ('BDM', 'Bon de Demande'),
    ]
    configs_list = []
    for code, label in type_docs:
        c = configs.get(code)
        configs_list.append({
            'code': code,
            'label': label,
            'config': c,
            'code_document': c.code_document if c else '',
            'date_creation_doc': c.date_creation_doc if c else '',
            'date_revision_doc': c.date_revision_doc if c else '',
            'version_doc': c.version_doc if c else '',
            'ps2_label': c.ps2_label if c else '',
            'afficher_logo': c.afficher_logo if c else True,
            'afficher_cachet': c.afficher_cachet if c else True,
            'afficher_cc': c.afficher_cc if c else True,
            'afficher_ifu': c.afficher_ifu if c else True,
            'afficher_rccm': c.afficher_rccm if c else True,
            'afficher_telephone': c.afficher_telephone if c else True,
            'afficher_signatures': c.afficher_signatures if c else True,
        })

    context = {
        'entreprise': entreprise,
        'configs_list': configs_list,
        # Labels signataires
        'label_signataire_1': entreprise.label_signataire_1,
        'label_signataire_2': entreprise.label_signataire_2,
        'label_signataire_3': entreprise.label_signataire_3,
        'label_signataire_4': entreprise.label_signataire_4,
        'label_signataire_5': entreprise.label_signataire_5,
        'label_signataire_6': entreprise.label_signataire_6,
        # Hiérarchie
        'direction_label': entreprise.direction_label,
        'sous_direction_label': entreprise.sous_direction_label,
        'service_label': entreprise.service_label,
        'republique_label': "RÉPUBLIQUE DE CÔTE D'IVOIRE",
        'devise_label': "Union - Discipline - Travail",
        # Pied de page
        'pied_page_pdf': entreprise.pied_page_pdf,
        'couleur_principale': entreprise.couleur_principale,
        # Préfixes
        'prefixe_bon_sortie': entreprise.prefixe_bon_sortie,
        'prefixe_bon_entree': entreprise.prefixe_bon_entree,
        'prefixe_bon_retour': entreprise.prefixe_bon_retour,
        'prefixe_bon_hors_stock': entreprise.prefixe_bon_hors_stock,
        'prefixe_commande': entreprise.prefixe_commande,
    }
    return render(request, 'accounts/config_documents.html', context)


def _handle_post(request, entreprise, configs):
    """Sauvegarde les modifications."""
    # ── SÉCURITÉ : vérification explicite de permission ──
    user = request.user
    if not user.is_superuser and not (
        user.has_perm('accounts.menu_parametres') or 
        user.has_perm('accounts.menu_param_admin')
    ):
        messages.error(request, "⛔ Vous n'avez pas la permission de modifier cette configuration.")
        return redirect('config_documents_globaux')

    try:
        with transaction.atomic():
            # ── 1. Infos entreprise ──
            entreprise.direction_label = _sanitize_text(
                request.POST.get('direction_label', ''), entreprise.direction_label
            )
            entreprise.sous_direction_label = _sanitize_text(
                request.POST.get('sous_direction_label', ''), entreprise.sous_direction_label
            )
            entreprise.service_label = _sanitize_text(
                request.POST.get('service_label', ''), entreprise.service_label
            )
            entreprise.pied_page_pdf = _sanitize_text(
                request.POST.get('pied_page_pdf', ''), entreprise.pied_page_pdf
            )

            # Validation couleur
            couleur = request.POST.get('couleur_principale', '#1c5b96').strip()
            if _validate_hex_color(couleur):
                entreprise.couleur_principale = couleur

            # Labels signataires (limités à 100 caractères)
            entreprise.label_signataire_1 = _truncate(
                request.POST.get('label_signataire_1', 'Le Demandeur').strip(), 100
            )
            entreprise.label_signataire_2 = _truncate(
                request.POST.get('label_signataire_2', 'Le Magasinier').strip(), 100
            )
            entreprise.label_signataire_3 = _truncate(
                request.POST.get('label_signataire_3', 'Le Responsable Service').strip(), 100
            )
            entreprise.label_signataire_4 = _truncate(
                request.POST.get('label_signataire_4', 'Le Directeur').strip(), 100
            )
            entreprise.label_signataire_5 = _truncate(
                request.POST.get('label_signataire_5', 'Le Contrôleur').strip(), 100
            )
            entreprise.label_signataire_6 = _truncate(
                request.POST.get('label_signataire_6', 'Le Réceptionnaire').strip(), 100
            )

            # Préfixes (limités à 10 caractères)
            entreprise.prefixe_bon_sortie = _truncate(
                request.POST.get('prefixe_bon_sortie', 'BS').strip(), 10
            )
            entreprise.prefixe_bon_entree = _truncate(
                request.POST.get('prefixe_bon_entree', 'BE').strip(), 10
            )
            entreprise.prefixe_bon_retour = _truncate(
                request.POST.get('prefixe_bon_retour', 'BR').strip(), 10
            )
            entreprise.prefixe_bon_hors_stock = _truncate(
                request.POST.get('prefixe_bon_hors_stock', 'BSHS').strip(), 10
            )
            entreprise.prefixe_commande = _truncate(
                request.POST.get('prefixe_commande', 'BC').strip(), 10
            )

            entreprise.save()

            # ── 2. Configs par type de document ──
            type_docs = ['BS', 'BE', 'BR', 'BSHS', 'BC', 'BDM']
            for td in type_docs:
                config = configs.get(td)
                if not config:
                    continue

                prefix = f'config_{td}_'
                config.code_document = _truncate(
                    request.POST.get(f'{prefix}code_document', '').strip(), 50
                )
                config.date_creation_doc = _truncate(
                    request.POST.get(f'{prefix}date_creation_doc', '').strip(), 20
                )
                config.date_revision_doc = _truncate(
                    request.POST.get(f'{prefix}date_revision_doc', '').strip(), 20
                )
                config.version_doc = _truncate(
                    request.POST.get(f'{prefix}version_doc', '').strip(), 10
                )
                config.ps2_label = _truncate(
                    request.POST.get(f'{prefix}ps2_label', '').strip(), 100
                )

                # Checkboxes (HTML envoie la valeur uniquement si cochée)
                config.afficher_logo = request.POST.get(f'{prefix}afficher_logo') == 'on'
                config.afficher_cachet = request.POST.get(f'{prefix}afficher_cachet') == 'on'
                config.afficher_cc = request.POST.get(f'{prefix}afficher_cc') == 'on'
                config.afficher_ifu = request.POST.get(f'{prefix}afficher_ifu') == 'on'
                config.afficher_rccm = request.POST.get(f'{prefix}afficher_rccm') == 'on'
                config.afficher_telephone = request.POST.get(f'{prefix}afficher_telephone') == 'on'
                config.afficher_signatures = request.POST.get(f'{prefix}afficher_signatures') == 'on'

                config.save()

        messages.success(request, "✅ Configuration globale des documents PDF sauvegardée avec succès.")
    except Exception as e:
        messages.error(request, f"❌ Erreur lors de la sauvegarde : {e}")

    return redirect('config_documents_globaux')


def _sanitize_text(value, fallback=''):
    """Nettoie une valeur texte, retourne fallback si vide."""
    cleaned = value.strip() if value else ''
    return cleaned if cleaned else fallback


def _truncate(value, max_length):
    """Tronque une valeur à max_length caractères."""
    return value[:max_length] if value else ''


def _validate_hex_color(value):
    """Vérifie qu'une valeur est un code hexadécimal valide."""
    import re
    return bool(re.match(r'^#[0-9A-Fa-f]{6}$', value)) if value else False
