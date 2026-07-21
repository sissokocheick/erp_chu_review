from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse

from accounts.permissions import verifier_permission
from ...decorators import catch_errors
from ...services.parametre_service import (
    paginer_donnees,
    get_dependances,
    redirect_url_with_tab,
    save_config_document,
    save_entreprise_form,
    parse_optional_id,
    safe_delete_entity,
    save_specialite,
    save_service,
    save_magasin_admin,
)
from core.models import Service
from stock.models import Magasin
from stock.forms import ServiceForm, MagasinForm, SpecialiteForm
from accounts.models import Specialite, Entreprise, ConfigDocument, Fonction
from accounts.forms import EntrepriseConfigForm


@login_required(login_url='/auth/login/')
@verifier_permission(
    'accounts.menu_param_admin',
    'accounts.menu_services',
    'accounts.menu_specialites',
    'accounts.menu_magasins',
    'accounts.menu_fonctions',
)
@catch_errors(redirect_url='/')
def parametres_administratifs(request):
    entreprise = request.entreprise
    if not entreprise:
        messages.error(request, "❌ Aucune entreprise associée à votre compte.")
        return redirect('dashboard_directeur')

    if request.method == 'POST':
        return _handle_post(request, entreprise)
    return _handle_get(request, entreprise)


def _handle_get(request, entreprise):
    services = Service.objects.filter(entreprise=entreprise).order_by('nom')
    magasins = Magasin.objects.filter(entreprise=entreprise).order_by('nom')
    specialites = Specialite.objects.filter(entreprise=entreprise).order_by('nom')
    fonctions = Fonction.objects.filter(entreprise=entreprise).order_by('nom')

    q_service = request.GET.get('q_service', '').strip()
    q_magasin = request.GET.get('q_magasin', '').strip()
    q_specialite = request.GET.get('q_specialite', '').strip()
    q_fonction = request.GET.get('q_fonction', '').strip()

    if q_service:
        services = services.filter(nom__icontains=q_service)
    if q_magasin:
        magasins = magasins.filter(nom__icontains=q_magasin)
    if q_specialite:
        specialites = specialites.filter(nom__icontains=q_specialite)
    if q_fonction:
        fonctions = fonctions.filter(nom__icontains=q_fonction)

    magasins_pagines, per_page_magasin = paginer_donnees(magasins, request, 'magasin')
    services_pagines, per_page_service = paginer_donnees(services, request, 'service')
    specialites_pagines, per_page_specialite = paginer_donnees(specialites, request, 'specialite')
    fonctions_paginees, per_page_fonction = paginer_donnees(fonctions, request, 'fonction')

    for page in (services_pagines, specialites_pagines, magasins_pagines, fonctions_paginees):
        for obj in page:
            obj._deps = get_dependances(obj)
            obj.is_deletable = not bool(obj._deps)

    edit_service_id = request.GET.get('edit_service', '').strip()
    instance_service = get_object_or_404(Service, id=edit_service_id, entreprise=entreprise) if edit_service_id else None
    form_service = ServiceForm(instance=instance_service)

    edit_magasin_id = request.GET.get('edit_magasin', '').strip()
    instance_magasin = get_object_or_404(Magasin, id=edit_magasin_id, entreprise=entreprise) if edit_magasin_id else None
    form_magasin = MagasinForm(instance=instance_magasin)

    edit_specialite_id = request.GET.get('edit_specialite', '').strip()
    instance_specialite = get_object_or_404(Specialite, id=edit_specialite_id, entreprise=entreprise) if edit_specialite_id else None
    form_specialite = SpecialiteForm(instance=instance_specialite)

    edit_fonction_id = request.GET.get('edit_fonction', '').strip()
    instance_fonction = get_object_or_404(Fonction, id=edit_fonction_id, entreprise=entreprise) if edit_fonction_id else None

    entreprise_obj = entreprise
    form_entreprise = EntrepriseConfigForm(instance=entreprise_obj)

    configs_list = []
    historique_entreprise = []
    entreprise_obj.creer_configs_documents_par_defaut()
    configs_qs = entreprise_obj.configs_documents.all()
    configs_documents = {c.type_doc: c for c in configs_qs}
    for code, label in ConfigDocument.TYPE_DOC_CHOICES:
        configs_list.append({'code': code, 'label': label, 'config': configs_documents.get(code)})
    historique_entreprise = list(entreprise_obj.history.all()[:5])

    context = {
        'services': services_pagines,
        'q_service': q_service,
        'per_page_service': per_page_service,
        'magasins': magasins_pagines,
        'q_magasin': q_magasin,
        'per_page_magasin': per_page_magasin,
        'specialites': specialites_pagines,
        'q_specialite': q_specialite,
        'per_page_specialite': per_page_specialite,
        'fonctions': fonctions_paginees,
        'q_fonction': q_fonction,
        'per_page_fonction': per_page_fonction,
        'instance_fonction': instance_fonction,
        'form_service': form_service,
        'form_magasin': form_magasin,
        'form_specialite': form_specialite,
        'instance_service': instance_service,
        'instance_specialite': instance_specialite,
        'instance_magasin': instance_magasin,
        'form_entreprise': form_entreprise,
        'entreprise_obj': entreprise_obj,
        'configs_list': configs_list,
        'historique_entreprise': historique_entreprise,
        'perm_config': request.user.has_perm('accounts.menu_param_admin') or request.user.is_superuser,
        'perm_fonctions': request.user.has_perm('accounts.menu_fonctions') or request.user.is_superuser,
        'perm_services': request.user.has_perm('accounts.menu_services') or request.user.is_superuser,
        'perm_specialites': request.user.has_perm('accounts.menu_specialites') or request.user.is_superuser,
        'perm_magasins': request.user.has_perm('accounts.menu_magasins') or request.user.is_superuser,
        'peut_creer_services': request.user.has_perm('accounts.menu_services') or request.user.is_superuser,
        'peut_creer_magasins': request.user.has_perm('accounts.menu_magasins') or request.user.is_superuser,
        'peut_creer_specialites': request.user.has_perm('accounts.menu_specialites') or request.user.is_superuser,
        'peut_creer_fonctions': request.user.has_perm('accounts.menu_fonctions') or request.user.is_superuser,
        'peut_annuler_services': request.user.has_perm('accounts.menu_services') or request.user.is_superuser,
        'peut_annuler_magasins': request.user.has_perm('accounts.menu_magasins') or request.user.is_superuser,
        'peut_annuler_specialites': request.user.has_perm('accounts.menu_specialites') or request.user.is_superuser,
        'peut_annuler_fonctions': request.user.has_perm('accounts.menu_fonctions') or request.user.is_superuser,
    }

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return render(request, 'stock/parametres_administratifs_lignes.html', context)
    return render(request, 'stock/parametres_administratifs.html', context)


def _handle_post(request, entreprise):
    entreprise_obj = entreprise or Entreprise.objects.filter(est_active=True).first()
    if not entreprise_obj:
        messages.error(request, "❌ Aucune entreprise disponible.")
        return redirect('dashboard_directeur')

    dispatch = {
        'enregistrer_config_doc': lambda r, e: _post_config_doc(r, e, entreprise_obj),
        'enregistrer_entreprise': lambda r, e: _post_entreprise(r, e, entreprise_obj),
        'enregistrer_specialite': _post_specialite,
        'enregistrer_fonction': _post_fonction,
        'enregistrer_service': _post_service,
        'enregistrer_magasin': _post_magasin,
    }
    for key, handler in dispatch.items():
        if key in request.POST:
            return handler(request, entreprise)

    if 'supprimer_specialite' in request.POST:
        return _post_supprimer_specialite(request, entreprise)
    if 'supprimer_fonction' in request.POST:
        return _post_supprimer_fonction(request, entreprise)
    if 'supprimer_magasin' in request.POST:
        return _post_supprimer_magasin(request, entreprise)
    if 'supprimer_service' in request.POST:
        return _post_supprimer_service(request, entreprise)

    return redirect('parametres_administratifs')


def _ajax_response(request, ok, msg, errors=None):
    """Réponse unifiée pour les requêtes AJAX."""
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        data = {'success': ok, 'message': msg}
        if errors:
            data['errors'] = errors
        return JsonResponse(data)
    return None


def _post_config_doc(request, entreprise, entreprise_obj):
    if not request.user.has_perm('accounts.menu_param_admin') and not request.user.is_superuser:
        msg = "⛔ Accès refusé."
        ajax = _ajax_response(request, False, msg)
        if ajax:
            return ajax
        messages.error(request, msg)
        return redirect('parametres_administratifs')

    ok, msg, _ = save_config_document(request, entreprise_obj)
    ajax = _ajax_response(request, ok, msg)
    if ajax:
        return ajax
    if ok:
        messages.success(request, msg)
    else:
        messages.error(request, msg)
    return redirect(redirect_url_with_tab('parametres_administratifs', 'entreprise'))


def _post_entreprise(request, entreprise, entreprise_obj):
    if not request.user.has_perm('accounts.menu_param_admin') and not request.user.is_superuser:
        msg = "⛔ Accès refusé."
        ajax = _ajax_response(request, False, msg)
        if ajax:
            return ajax
        messages.error(request, msg)
        return redirect('parametres_administratifs')

    form = EntrepriseConfigForm(request.POST, request.FILES, instance=entreprise_obj)
    ok, msg, errors = save_entreprise_form(form, request)
    ajax = _ajax_response(request, ok, msg, errors)
    if ajax:
        return ajax
    if ok:
        messages.success(request, msg)
    else:
        messages.error(request, msg)
    return redirect(redirect_url_with_tab('parametres_administratifs', 'entreprise'))


def _post_specialite(request, entreprise):
    if not request.user.has_perm('accounts.menu_specialites') and not request.user.is_superuser:
        messages.error(request, "⛔ Accès refusé.")
        return redirect('parametres_administratifs')

    edit_id = parse_optional_id(request, 'specialite_id', 'edit_specialite')
    instance = None
    if edit_id:
        try:
            instance = Specialite.objects.get(id=edit_id, entreprise=entreprise)
        except Specialite.DoesNotExist:
            instance = None

    ok, msg, _ = save_specialite(request.POST, instance, entreprise, request.user)
    if ok:
        messages.success(request, msg)
        return redirect(redirect_url_with_tab('parametres_administratifs', 'specialites'))
    messages.error(request, msg)
    return redirect('parametres_administratifs')


def _post_service(request, entreprise):
    if not request.user.has_perm('accounts.menu_services') and not request.user.is_superuser:
        messages.error(request, "⛔ Accès refusé.")
        return redirect('parametres_administratifs')

    edit_id = parse_optional_id(request, 'service_id', 'edit_service')
    instance = None
    if edit_id:
        try:
            instance = Service.objects.get(id=edit_id, entreprise=entreprise)
        except Service.DoesNotExist:
            instance = None

    ok, msg, _ = save_service(request.POST, instance, entreprise, request.user)
    if ok:
        messages.success(request, msg)
        return redirect(redirect_url_with_tab('parametres_administratifs', 'services'))
    messages.error(request, msg)
    return redirect('parametres_administratifs')


def _post_magasin(request, entreprise):
    if not request.user.has_perm('accounts.menu_magasins') and not request.user.is_superuser:
        messages.error(request, "⛔ Accès refusé.")
        return redirect('parametres_administratifs')

    edit_id = parse_optional_id(request, 'magasin_id', 'edit_magasin')
    instance = None
    if edit_id:
        try:
            instance = Magasin.objects.get(id=edit_id, entreprise=entreprise)
        except Magasin.DoesNotExist:
            instance = None

    form = MagasinForm(request.POST, instance=instance)
    ok, msg, _ = save_magasin_admin(form, instance, entreprise, request.user)
    if ok:
        messages.success(request, msg)
        return redirect(redirect_url_with_tab('parametres_administratifs', 'magasins'))
    messages.error(request, msg)
    return redirect('parametres_administratifs')


def _post_fonction(request, entreprise):
    if not request.user.has_perm('accounts.menu_fonctions') and not request.user.is_superuser:
        messages.error(request, "⛔ Accès refusé.")
        return redirect('parametres_administratifs')

    edit_id = parse_optional_id(request, 'fonction_id', 'edit_fonction')
    instance = None
    if edit_id:
        try:
            instance = Fonction.objects.get(id=edit_id, entreprise=entreprise)
        except Fonction.DoesNotExist:
            instance = None

    nom = request.POST.get('nom', '').strip()
    if not nom:
        messages.error(request, "❌ Le nom de la fonction est obligatoire.")
        return redirect('parametres_administratifs')

    nom = ' '.join(nom.split())  # Nettoyage des espaces multiples
    if len(nom) > 100:
        messages.error(request, "❌ Le nom ne doit pas dépasser 100 caractères.")
        return redirect('parametres_administratifs')

    if instance:
        if Fonction.objects.filter(entreprise=entreprise, nom__iexact=nom).exclude(id=instance.id).exists():
            messages.error(request, f"⛔ Le nom '{nom}' est déjà utilisé.")
            return redirect('parametres_administratifs')
    else:
        if Fonction.objects.filter(entreprise=entreprise, nom__iexact=nom).exists():
            messages.error(request, f"⛔ Le nom '{nom}' est déjà utilisé.")
            return redirect('parametres_administratifs')

    description = request.POST.get('description', '').strip() or None
    description = ' '.join(description.split()) if description else None

    if instance:
        instance.nom = nom
        instance.description = description
        instance.modifie_par = request.user
        instance.save()
        action = "modifiée"
    else:
        instance = Fonction.objects.create(
            entreprise=entreprise,
            nom=nom,
            description=description,
            cree_par=request.user,
            modifie_par=request.user,
        )
        action = "ajoutée"

    messages.success(request, f"✅ Fonction '{nom}' {action} avec succès !")
    return redirect(redirect_url_with_tab('parametres_administratifs', 'fonctions'))


def _post_supprimer_specialite(request, entreprise):
    if not request.user.has_perm('accounts.menu_specialites') and not request.user.is_superuser:
        messages.error(request, "⛔ Accès refusé.")
        return redirect('parametres_administratifs')

    raw_id = request.POST.get('specialite_id', '').strip()
    if not raw_id:
        messages.error(request, "❌ Identifiant de la spécialité manquant.")
        return redirect(redirect_url_with_tab('parametres_administratifs', 'specialites'))
    try:
        pk = int(raw_id)
    except (ValueError, TypeError):
        messages.error(request, "❌ Identifiant de la spécialité invalide.")
        return redirect(redirect_url_with_tab('parametres_administratifs', 'specialites'))

    spe = get_object_or_404(Specialite, id=pk, entreprise=entreprise)
    deps = get_dependances(spe)
    if deps:
        messages.error(request, f"⛔ Impossible de supprimer : utilisée par {', '.join(deps)}.")
    else:
        safe_delete_entity(spe, request.user)
        messages.success(request, "🗑️ Spécialité supprimée.")
    return redirect(redirect_url_with_tab('parametres_administratifs', 'specialites'))


def _post_supprimer_magasin(request, entreprise):
    if not request.user.has_perm('accounts.menu_magasins') and not request.user.is_superuser:
        messages.error(request, "⛔ Accès refusé.")
        return redirect('parametres_administratifs')

    raw_id = request.POST.get('magasin_id', '').strip()
    if not raw_id:
        messages.error(request, "❌ Identifiant du magasin manquant.")
        return redirect(redirect_url_with_tab('parametres_administratifs', 'magasins'))
    try:
        pk = int(raw_id)
    except (ValueError, TypeError):
        messages.error(request, "❌ Identifiant du magasin invalide.")
        return redirect(redirect_url_with_tab('parametres_administratifs', 'magasins'))

    magasin = get_object_or_404(Magasin, id=pk, entreprise=entreprise)
    deps = get_dependances(magasin)
    if deps:
        messages.error(request, f"⛔ Impossible de supprimer : utilisé par {', '.join(deps)}.")
    else:
        safe_delete_entity(magasin, request.user)
        messages.success(request, "🗑️ Magasin supprimé.")
    return redirect(redirect_url_with_tab('parametres_administratifs', 'magasins'))


def _post_supprimer_service(request, entreprise):
    if not request.user.has_perm('accounts.menu_services') and not request.user.is_superuser:
        messages.error(request, "⛔ Accès refusé.")
        return redirect('parametres_administratifs')

    raw_id = request.POST.get('service_id', '').strip()
    if not raw_id:
        messages.error(request, "❌ Identifiant du service manquant.")
        return redirect(redirect_url_with_tab('parametres_administratifs', 'services'))
    try:
        pk = int(raw_id)
    except (ValueError, TypeError):
        messages.error(request, "❌ Identifiant du service invalide.")
        return redirect(redirect_url_with_tab('parametres_administratifs', 'services'))

    service = get_object_or_404(Service, id=pk, entreprise=entreprise)
    deps = get_dependances(service)
    if deps:
        messages.error(request, f"⛔ Impossible de supprimer : utilisé par {', '.join(deps)}.")
    else:
        safe_delete_entity(service, request.user)
        messages.success(request, "🗑️ Service supprimé.")
    return redirect(redirect_url_with_tab('parametres_administratifs', 'services'))


def _post_supprimer_fonction(request, entreprise):
    if not request.user.has_perm('accounts.menu_fonctions') and not request.user.is_superuser:
        messages.error(request, "⛔ Accès refusé.")
        return redirect('parametres_administratifs')

    raw_id = request.POST.get('fonction_id', '').strip()
    if not raw_id:
        messages.error(request, "❌ Identifiant de la fonction manquant.")
        return redirect(redirect_url_with_tab('parametres_administratifs', 'fonctions'))
    try:
        pk = int(raw_id)
    except (ValueError, TypeError):
        messages.error(request, "❌ Identifiant de la fonction invalide.")
        return redirect(redirect_url_with_tab('parametres_administratifs', 'fonctions'))

    fct = get_object_or_404(Fonction, id=pk, entreprise=entreprise)
    deps = get_dependances(fct)
    if deps:
        messages.error(request, f"⛔ Impossible de supprimer : utilisée par {', '.join(deps)}.")
    else:
        safe_delete_entity(fct, request.user)
        messages.success(request, "🗑️ Fonction supprimée.")
    return redirect(redirect_url_with_tab('parametres_administratifs', 'fonctions'))
