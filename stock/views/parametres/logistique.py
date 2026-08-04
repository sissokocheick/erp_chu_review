from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.contrib import messages

from accounts.permissions import verifier_permission
from ...decorators import catch_errors
from ...services.parametre_service import (
    get_or_create_logistique_config,
    paginer_donnees,
    get_dependances,
    redirect_url_with_tab,
    save_delai_remplacement,
    save_confidentialite_demandes,
    toggle_motif,
    parse_optional_id,
    safe_delete_entity,
    save_famille,
    save_fournisseur,
    save_magasin_logistique,
    save_beneficiaire,
    save_motif,
)
from ...models import FamilleArticle, Fournisseur, MotifAnnulation, Magasin, Beneficiaire
from core.models import Service
from ...forms import FamilleArticleForm, MagasinForm
from accounts.models import ConfigDocument


@login_required(login_url='/auth/login/')
@verifier_permission(
    'accounts.menu_parametres',
    'accounts.menu_param_logistique',
    'accounts.menu_magasins',
    'accounts.menu_fournisseurs',
    'accounts.menu_motifs_annulation')
@catch_errors(redirect_url='/')
def parametres_logistique(request):
    if request.method == 'POST':
        return _handle_post(request)
    return _handle_get(request)


def _handle_get(request):
    config = get_or_create_logistique_config()

    q_famille = request.GET.get('q_famille', '').strip()
    q_fournisseur = request.GET.get('q_fournisseur', '').strip()
    q_motif = request.GET.get('q_motif', '').strip()
    q_magasin = request.GET.get('q_magasin', '').strip()
    q_beneficiaire = request.GET.get('q_beneficiaire', '').strip()

    familles = FamilleArticle.objects.all().order_by('intitule')
    if q_famille:
        familles = familles.filter(intitule__icontains=q_famille)

    fournisseurs = Fournisseur.objects.all().order_by('raison_sociale')
    if q_fournisseur:
        fournisseurs = fournisseurs.filter(raison_sociale__icontains=q_fournisseur)

    motifs = MotifAnnulation.objects.all().order_by('libelle')
    if q_motif:
        motifs = motifs.filter(libelle__icontains=q_motif)

    magasins = Magasin.objects.all().order_by('nom')
    if q_magasin:
        magasins = magasins.filter(nom__icontains=q_magasin)

    beneficiaires = Beneficiaire.objects.all().order_by('nom_complet')
    if q_beneficiaire:
        beneficiaires = beneficiaires.filter(
            Q(nom_complet__icontains=q_beneficiaire) | Q(poste__icontains=q_beneficiaire)
        )

    familles_paginees, per_page_famille = paginer_donnees(familles, request, 'famille')
    fournisseurs_pagines, per_page_fournisseur = paginer_donnees(fournisseurs, request, 'fournisseur')
    motifs_pagines, per_page_motif = paginer_donnees(motifs, request, 'motif')
    magasins_pagines, per_page_magasin = paginer_donnees(magasins, request, 'magasin')
    beneficiaires_pagines, per_page_beneficiaire = paginer_donnees(beneficiaires, request, 'beneficiaire')

    for page in (magasins_pagines, fournisseurs_pagines, beneficiaires_pagines, motifs_pagines, familles_paginees):
        for obj in page:
            obj._deps = get_dependances(obj)
            obj.is_deletable = not bool(obj._deps)

    edit_famille_id = request.GET.get('edit_famille', '').strip()
    instance_famille = get_object_or_404(FamilleArticle, id=edit_famille_id) if edit_famille_id else None
    form_famille = FamilleArticleForm(instance=instance_famille)

    edit_fournisseur_id = request.GET.get('edit_fournisseur', '').strip()
    instance_fournisseur = get_object_or_404(Fournisseur, id=edit_fournisseur_id) if edit_fournisseur_id else None

    edit_magasin_id = request.GET.get('edit_magasin', '').strip()
    instance_magasin = get_object_or_404(Magasin, id=edit_magasin_id) if edit_magasin_id else None
    form_magasin = MagasinForm(instance=instance_magasin)

    # Config documents (mono-tenant)
    configs_documents = {c.type_doc: c for c in ConfigDocument.objects.all()}

    context = {
        'familles': familles_paginees,
        'form_famille': form_famille,
        'q_famille': q_famille,
        'per_page_famille': per_page_famille,
        'fournisseurs': fournisseurs_pagines,
        'q_fournisseur': q_fournisseur,
        'per_page_fournisseur': per_page_fournisseur,
        'instance_fournisseur': instance_fournisseur,
        'motifs': motifs_pagines,
        'q_motif': q_motif,
        'per_page_motif': per_page_motif,
        'magasins': magasins_pagines,
        'form_magasin': form_magasin,
        'q_magasin': q_magasin,
        'per_page_magasin': per_page_magasin,
        'instance_magasin': instance_magasin,
        'beneficiaires': beneficiaires_pagines,
        'q_beneficiaire': q_beneficiaire,
        'per_page_beneficiaire': per_page_beneficiaire,
        'services': Service.objects.all().order_by('nom'),
        'config': config,
        'configs_documents': configs_documents,
        'perm_config': request.user.has_perm('accounts.menu_parametres') or request.user.is_superuser,
        'perm_fournisseurs': request.user.has_perm('accounts.menu_fournisseurs') or request.user.is_superuser,
        'perm_magasins': request.user.has_perm('accounts.menu_magasins') or request.user.is_superuser,
        'perm_motifs': request.user.has_perm('accounts.menu_motifs_annulation') or request.user.is_superuser,
        'perm_beneficiaires': request.user.has_perm('accounts.menu_param_logistique') or request.user.is_superuser,
        'peut_creer_fournisseurs': request.user.has_perm('accounts.menu_fournisseurs') or request.user.is_superuser,
        'peut_creer_magasins': request.user.has_perm('accounts.menu_magasins') or request.user.is_superuser,
        'peut_creer_motifs': request.user.has_perm('accounts.menu_motifs_annulation') or request.user.is_superuser,
        'peut_creer_beneficiaires': request.user.has_perm('accounts.menu_param_logistique') or request.user.is_superuser,
        'peut_annuler_fournisseurs': request.user.has_perm('accounts.menu_fournisseurs') or request.user.is_superuser,
        'peut_annuler_magasins': request.user.has_perm('accounts.menu_magasins') or request.user.is_superuser,
        'peut_annuler_motifs': request.user.has_perm('accounts.menu_motifs_annulation') or request.user.is_superuser,
        'peut_annuler_beneficiaires': request.user.has_perm('accounts.menu_param_logistique') or request.user.is_superuser,
    }

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return render(request, 'stock/parametres_logistique_lignes.html', context)
    return render(request, 'stock/parametres_logistique.html', context)


def _handle_post(request):
    dispatch = {
        'enregistrer_famille': _post_famille,
        'enregistrer_fournisseur': _post_fournisseur,
        'enregistrer_magasin': _post_magasin,
        'enregistrer_beneficiaire': _post_beneficiaire,
        'enregistrer_motif': _post_motif,
        'enregistrer_config': _post_config,
    }
    for key, handler in dispatch.items():
        if key in request.POST:
            return handler(request)

    action = request.POST.get('action', '').strip()
    if action == 'supprimer_motif':
        return _post_supprimer_motif(request)
    if action == 'toggle_motif':
        return _post_toggle_motif(request)

    if 'supprimer_famille' in request.POST:
        return _post_supprimer_famille(request)
    if 'supprimer_fournisseur' in request.POST:
        return _post_supprimer_fournisseur(request)
    if 'supprimer_magasin' in request.POST:
        return _post_supprimer_magasin(request)
    if 'supprimer_beneficiaire' in request.POST:
        return _post_supprimer_beneficiaire(request)

    return redirect('parametres_logistique')


def _post_famille(request):
    if not request.user.has_perm('accounts.menu_fournisseurs') and not request.user.is_superuser:
        messages.error(request, "⛔ Accès refusé.")
        return redirect('parametres_logistique')

    edit_id = parse_optional_id(request, 'famille_id', 'edit_famille')
    instance = None
    if edit_id:
        try:
            instance = FamilleArticle.objects.get(id=edit_id)
        except FamilleArticle.DoesNotExist:
            instance = None

    form = FamilleArticleForm(request.POST, instance=instance)
    ok, msg, _ = save_famille(form, request.user)  # version mono-tenant
    if ok:
        messages.success(request, msg)
        return redirect(redirect_url_with_tab('parametres_logistique', 'familles'))
    messages.error(request, msg)
    return redirect('parametres_logistique')


def _post_fournisseur(request):
    if not request.user.has_perm('accounts.menu_fournisseurs') and not request.user.is_superuser:
        messages.error(request, "⛔ Accès refusé.")
        return redirect('parametres_logistique')

    edit_id = parse_optional_id(request, 'fournisseur_id', 'edit_fournisseur')
    instance = None
    if edit_id:
        try:
            instance = Fournisseur.objects.get(id=edit_id)
        except Fournisseur.DoesNotExist:
            instance = None

    ok, msg, _ = save_fournisseur(request.POST, instance, request.user)
    if ok:
        messages.success(request, msg)
        return redirect(redirect_url_with_tab('parametres_logistique', 'fournisseurs'))
    messages.error(request, msg)
    return redirect('parametres_logistique')


def _post_magasin(request):
    if not request.user.has_perm('accounts.menu_magasins') and not request.user.is_superuser:
        messages.error(request, "⛔ Accès refusé.")
        return redirect('parametres_logistique')

    edit_id = parse_optional_id(request, 'magasin_id', 'edit_magasin')
    instance = None
    if edit_id:
        try:
            instance = Magasin.objects.get(id=edit_id)
        except Magasin.DoesNotExist:
            instance = None

    form = MagasinForm(request.POST, instance=instance)
    ok, msg, _ = save_magasin_logistique(form, instance, request.user)
    if ok:
        messages.success(request, msg)
        return redirect(redirect_url_with_tab('parametres_logistique', 'magasins'))
    messages.error(request, msg)
    return redirect('parametres_logistique')


def _post_beneficiaire(request):
    if not request.user.has_perm('accounts.menu_param_logistique') and not request.user.is_superuser:
        messages.error(request, "⛔ Accès refusé.")
        return redirect('parametres_logistique')

    edit_id = parse_optional_id(request, 'beneficiaire_id')
    instance = None
    if edit_id:
        try:
            instance = Beneficiaire.objects.get(id=edit_id)
        except Beneficiaire.DoesNotExist:
            instance = None

    ok, msg, _ = save_beneficiaire(request.POST, instance)
    if ok:
        messages.success(request, msg)
        return redirect(redirect_url_with_tab('parametres_logistique', 'beneficiaires'))
    messages.error(request, msg)
    return redirect('parametres_logistique')


def _post_motif(request):
    if not request.user.has_perm('accounts.menu_motifs_annulation') and not request.user.is_superuser:
        messages.error(request, "⛔ Accès refusé.")
        return redirect('parametres_logistique')

    edit_id = parse_optional_id(request, 'motif_id')
    instance = None
    if edit_id:
        try:
            instance = MotifAnnulation.objects.get(id=edit_id)
        except MotifAnnulation.DoesNotExist:
            instance = None

    ok, msg, _ = save_motif(request.POST, instance, request.user)
    if ok:
        messages.success(request, msg)
        return redirect(redirect_url_with_tab('parametres_logistique', 'motifs'))
    messages.error(request, msg)
    return redirect('parametres_logistique')


def _post_config(request):
    if not request.user.has_perm('accounts.menu_parametres') and not request.user.is_superuser:
        messages.error(request, "⛔ Accès refusé.")
        return redirect(redirect_url_with_tab('parametres_logistique', 'config'))

    config = get_or_create_logistique_config()

    delai = request.POST.get('delai_remplacement_bon_jours', '2').strip()
    ok_delai, msg_delai, _ = save_delai_remplacement(config, delai)

    conf_value = request.POST.get('confidentialite_demandes', 'PERSONNELLE').strip()
    ok_conf, msg_conf, _ = save_confidentialite_demandes(config, conf_value)

    if ok_delai and ok_conf:
        config.obliger_reception_precedente = request.POST.get('obliger_reception_precedente', '') == '1'
        fields_to_update = ['obliger_reception_precedente', 'delai_remplacement_bon_jours']
        if hasattr(config, 'confidentialite_demandes'):
            fields_to_update.append('confidentialite_demandes')
        config.save(update_fields=fields_to_update)
        messages.success(request, "✅ Configuration logistique mise à jour avec succès.")
    else:
        if not ok_delai:
            messages.error(request, msg_delai)
        if not ok_conf:
            messages.error(request, msg_conf)

    return redirect(redirect_url_with_tab('parametres_logistique', 'config'))


def _post_supprimer_motif(request):
    if not request.user.has_perm('accounts.menu_motifs_annulation') and not request.user.is_superuser:
        messages.error(request, "⛔ Accès refusé.")
        return redirect('parametres_logistique')

    raw_id = request.POST.get('motif_id', '').strip()
    if not raw_id:
        messages.error(request, "❌ Identifiant du motif manquant.")
        return redirect(redirect_url_with_tab('parametres_logistique', 'motifs'))
    try:
        pk = int(raw_id)
    except (ValueError, TypeError):
        messages.error(request, "❌ Identifiant du motif invalide.")
        return redirect(redirect_url_with_tab('parametres_logistique', 'motifs'))

    motif = get_object_or_404(MotifAnnulation, id=pk)
    deps = get_dependances(motif)
    if deps:
        messages.error(request, f"⛔ Impossible de supprimer : utilisé par {', '.join(deps)}.")
    else:
        safe_delete_entity(motif, request.user)
        messages.success(request, "🗑️ Motif supprimé.")
    return redirect(redirect_url_with_tab('parametres_logistique', 'motifs'))


def _post_toggle_motif(request):
    if not request.user.has_perm('accounts.menu_motifs_annulation') and not request.user.is_superuser:
        messages.error(request, "⛔ Accès refusé.")
        return redirect('parametres_logistique')

    raw_id = request.POST.get('motif_id', '').strip()
    if not raw_id:
        messages.error(request, "❌ Identifiant du motif manquant.")
        return redirect(redirect_url_with_tab('parametres_logistique', 'motifs'))
    try:
        pk = int(raw_id)
    except (ValueError, TypeError):
        messages.error(request, "❌ Identifiant du motif invalide.")
        return redirect(redirect_url_with_tab('parametres_logistique', 'motifs'))

    motif = get_object_or_404(MotifAnnulation, id=pk)
    ok, msg, _ = toggle_motif(motif, request.user)
    messages.success(request, msg)
    return redirect(redirect_url_with_tab('parametres_logistique', 'motifs'))


def _post_supprimer_famille(request):
    if not request.user.has_perm('accounts.menu_fournisseurs') and not request.user.is_superuser:
        messages.error(request, "⛔ Accès refusé.")
        return redirect('parametres_logistique')

    raw_id = request.POST.get('famille_id', '').strip()
    if not raw_id:
        messages.error(request, "❌ Identifiant de la famille manquant.")
        return redirect(redirect_url_with_tab('parametres_logistique', 'familles'))
    try:
        pk = int(raw_id)
    except (ValueError, TypeError):
        messages.error(request, "❌ Identifiant de la famille invalide.")
        return redirect(redirect_url_with_tab('parametres_logistique', 'familles'))

    famille = get_object_or_404(FamilleArticle, id=pk)
    deps = get_dependances(famille)
    if deps:
        messages.error(request, f"⛔ Impossible de supprimer : utilisée par {', '.join(deps)}.")
    else:
        safe_delete_entity(famille, request.user)
        messages.success(request, "🗑️ La famille a été supprimée.")
    return redirect(redirect_url_with_tab('parametres_logistique', 'familles'))


def _post_supprimer_fournisseur(request):
    if not request.user.has_perm('accounts.menu_fournisseurs') and not request.user.is_superuser:
        messages.error(request, "⛔ Accès refusé.")
        return redirect('parametres_logistique')

    raw_id = request.POST.get('fournisseur_id', '').strip()
    if not raw_id:
        messages.error(request, "❌ Identifiant du fournisseur manquant.")
        return redirect(redirect_url_with_tab('parametres_logistique', 'fournisseurs'))
    try:
        pk = int(raw_id)
    except (ValueError, TypeError):
        messages.error(request, "❌ Identifiant du fournisseur invalide.")
        return redirect(redirect_url_with_tab('parametres_logistique', 'fournisseurs'))

    fournisseur = get_object_or_404(Fournisseur, id=pk)
    deps = get_dependances(fournisseur)
    if deps:
        messages.error(request, f"⛔ Impossible de supprimer : utilisé par {', '.join(deps)}.")
    else:
        safe_delete_entity(fournisseur, request.user)
        messages.success(request, "🗑️ Le fournisseur a été supprimé.")
    return redirect(redirect_url_with_tab('parametres_logistique', 'fournisseurs'))


def _post_supprimer_magasin(request):
    if not request.user.has_perm('accounts.menu_magasins') and not request.user.is_superuser:
        messages.error(request, "⛔ Accès refusé.")
        return redirect('parametres_logistique')

    raw_id = request.POST.get('magasin_id', '').strip()
    if not raw_id:
        messages.error(request, "❌ Identifiant du magasin manquant.")
        return redirect(redirect_url_with_tab('parametres_logistique', 'magasins'))
    try:
        pk = int(raw_id)
    except (ValueError, TypeError):
        messages.error(request, "❌ Identifiant du magasin invalide.")
        return redirect(redirect_url_with_tab('parametres_logistique', 'magasins'))

    magasin = get_object_or_404(Magasin, id=pk)
    deps = get_dependances(magasin)
    if deps:
        messages.error(request, f"⛔ Impossible de supprimer : utilisé par {', '.join(deps)}.")
    else:
        safe_delete_entity(magasin, request.user)
        messages.success(request, "🗑️ Le magasin a été supprimé.")
    return redirect(redirect_url_with_tab('parametres_logistique', 'magasins'))


def _post_supprimer_beneficiaire(request):
    if not request.user.has_perm('accounts.menu_param_logistique') and not request.user.is_superuser:
        messages.error(request, "⛔ Accès refusé.")
        return redirect('parametres_logistique')

    raw_id = request.POST.get('beneficiaire_id', '').strip()
    if not raw_id:
        messages.error(request, "❌ Identifiant du bénéficiaire manquant.")
        return redirect(redirect_url_with_tab('parametres_logistique', 'beneficiaires'))
    try:
        pk = int(raw_id)
    except (ValueError, TypeError):
        messages.error(request, "❌ Identifiant du bénéficiaire invalide.")
        return redirect(redirect_url_with_tab('parametres_logistique', 'beneficiaires'))

    benef = get_object_or_404(Beneficiaire, id=pk)
    deps = get_dependances(benef)
    if deps:
        messages.error(request, f"⛔ Impossible de supprimer : utilisé par {', '.join(deps)}.")
    else:
        safe_delete_entity(benef, request.user)
        messages.success(request, "🗑️ Le bénéficiaire a été supprimé.")
    return redirect(redirect_url_with_tab('parametres_logistique', 'beneficiaires'))