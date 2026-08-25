from core.utils import paginer
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.http import JsonResponse

from accounts.permissions import verifier_permission
from ...decorators import catch_errors
from ...services.parametre_service import (
    get_dependances,
    get_dependances_batch,
    redirect_url_with_tab,
    parse_optional_id,
    safe_delete_entity,
    save_specialite,
    save_service,
)
from core.models import Service, ConfigurationHopital
from core.forms import ConfigurationHopitalForm
from stock.forms import ServiceForm, SpecialiteForm
from accounts.models import Specialite, Fonction


@login_required(login_url='/auth/login/')
@verifier_permission(
    'accounts.menu_param_admin',
    'accounts.menu_services',
    'accounts.menu_specialites',
    'accounts.menu_fonctions')
@catch_errors(redirect_url='/')
def parametres_administratifs(request):
    if request.method == 'POST':
        return _handle_post(request)
    return _handle_get(request)


def _handle_get(request):
    services = Service.objects.all().order_by('nom')
    specialites = Specialite.objects.all().order_by('nom')
    fonctions = Fonction.objects.all().order_by('nom')

    q_service = request.GET.get('q_service', '').strip()
    q_specialite = request.GET.get('q_specialite', '').strip()
    q_fonction = request.GET.get('q_fonction', '').strip()

    if q_service:
        services = services.filter(nom__icontains=q_service)
    if q_specialite:
        specialites = specialites.filter(nom__icontains=q_specialite)
    if q_fonction:
        fonctions = fonctions.filter(nom__icontains=q_fonction)

    services_pagines, per_page_service = paginer(services, request, per_page_key='service')
    specialites_pagines, per_page_specialite = paginer(specialites, request, per_page_key='specialite')
    fonctions_paginees, per_page_fonction = paginer(fonctions, request, per_page_key='fonction')

    for page in (services_pagines, specialites_pagines, fonctions_paginees):
        deps_map = get_dependances_batch(list(page))
        for obj in page:
            obj._deps = deps_map.get(obj.pk, {})
            obj.is_deletable = not bool(obj._deps)

    # --- Forms d'édition ---
    edit_service_id = request.GET.get('edit_service', '').strip()
    instance_service = get_object_or_404(Service, id=edit_service_id) if edit_service_id else None
    form_service = ServiceForm(instance=instance_service)

    edit_specialite_id = request.GET.get('edit_specialite', '').strip()
    instance_specialite = get_object_or_404(Specialite, id=edit_specialite_id) if edit_specialite_id else None
    form_specialite = SpecialiteForm(instance=instance_specialite)

    edit_fonction_id = request.GET.get('edit_fonction', '').strip()
    instance_fonction = get_object_or_404(Fonction, id=edit_fonction_id) if edit_fonction_id else None

    # --- Configuration de l'établissement ---
    config = ConfigurationHopital.get_instance()
    form_config = ConfigurationHopitalForm(instance=config)
    historique_config = config.history.all()[:10] if hasattr(config, 'history') else []

    context = {
        'services': services_pagines,
        'q_service': q_service,
        'per_page_service': per_page_service,
        'specialites': specialites_pagines,
        'q_specialite': q_specialite,
        'per_page_specialite': per_page_specialite,
        'fonctions': fonctions_paginees,
        'q_fonction': q_fonction,
        'per_page_fonction': per_page_fonction,
        'instance_fonction': instance_fonction,
        'form_service': form_service,
        'form_specialite': form_specialite,
        'instance_service': instance_service,
        'instance_specialite': instance_specialite,
        'perm_config': request.user.has_perm('accounts.menu_param_admin') or request.user.is_superuser,
        'perm_fonctions': request.user.has_perm('accounts.menu_fonctions') or request.user.is_superuser,
        'perm_services': request.user.has_perm('accounts.menu_services') or request.user.is_superuser,
        'perm_specialites': request.user.has_perm('accounts.menu_specialites') or request.user.is_superuser,
        'peut_creer_services': request.user.has_perm('accounts.menu_services') or request.user.is_superuser,
        'peut_creer_specialites': request.user.has_perm('accounts.menu_specialites') or request.user.is_superuser,
        'peut_creer_fonctions': request.user.has_perm('accounts.menu_fonctions') or request.user.is_superuser,
        'peut_annuler_services': request.user.has_perm('accounts.menu_services') or request.user.is_superuser,
        'peut_annuler_specialites': request.user.has_perm('accounts.menu_specialites') or request.user.is_superuser,
        'peut_annuler_fonctions': request.user.has_perm('accounts.menu_fonctions') or request.user.is_superuser,
        # Configuration de l'établissement
        'config_hopital': config,
        'form_config': form_config,
        'historique_config': historique_config,
    }

    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return render(request, 'stock/parametres_administratifs_lignes.html', context)
    return render(request, 'stock/parametres_administratifs.html', context)


def _handle_post(request):
    dispatch = {
        'enregistrer_config': _post_config,
        'enregistrer_specialite': _post_specialite,
        'enregistrer_fonction': _post_fonction,
        'enregistrer_service': _post_service,
    }
    for key, handler in dispatch.items():
        if key in request.POST:
            return handler(request)

    if 'supprimer_specialite' in request.POST:
        return _post_supprimer_specialite(request)
    if 'supprimer_fonction' in request.POST:
        return _post_supprimer_fonction(request)
    if 'supprimer_service' in request.POST:
        return _post_supprimer_service(request)

    return redirect('parametres_administratifs')


def _post_config(request):
    """Enregistre la configuration de l'établissement."""
    # La config de l'établissement est sensible : permission dédiée requise
    # (les autres permissions du dispatcher ne doivent pas y donner accès).
    if not request.user.has_perm('accounts.menu_param_admin') and not request.user.is_superuser:
        messages.error(request, "⛔ Accès refusé.")
        return redirect('parametres_administratifs')

    config = ConfigurationHopital.get_instance()
    form = ConfigurationHopitalForm(request.POST, request.FILES, instance=config)
    if form.is_valid():
        form.save()
        return JsonResponse({'success': True, 'message': "✅ Configuration de l'établissement enregistrée."})
    erreurs = [f"{champ}: {' '.join(msgs)}" for champ, msgs in form.errors.items()]
    return JsonResponse({'success': False, 'message': "❌ " + ' | '.join(erreurs)})


def _ajax_response(request, ok, msg, errors=None):
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        data = {'success': ok, 'message': msg}
        if errors:
            data['errors'] = errors
        return JsonResponse(data)
    return None


def _post_specialite(request):
    if not request.user.has_perm('accounts.menu_specialites') and not request.user.is_superuser:
        messages.error(request, "⛔ Accès refusé.")
        return redirect('parametres_administratifs')

    edit_id = parse_optional_id(request, 'specialite_id', 'edit_specialite')
    instance = None
    if edit_id:
        try:
            instance = Specialite.objects.get(id=edit_id)
        except Specialite.DoesNotExist:
            instance = None

    # Note : save_specialite doit aussi être adapté (plus de paramètre tenant)
    ok, msg, _ = save_specialite(request.POST, instance, request.user)
    if ok:
        messages.success(request, msg)
        return redirect(redirect_url_with_tab('parametres_administratifs', 'specialites'))
    messages.error(request, msg)
    return redirect('parametres_administratifs')


def _post_service(request):
    if not request.user.has_perm('accounts.menu_services') and not request.user.is_superuser:
        messages.error(request, "⛔ Accès refusé.")
        return redirect('parametres_administratifs')

    edit_id = parse_optional_id(request, 'service_id', 'edit_service')
    instance = None
    if edit_id:
        try:
            instance = Service.objects.get(id=edit_id)
        except Service.DoesNotExist:
            instance = None

    ok, msg, _ = save_service(request.POST, instance, request.user)
    if ok:
        messages.success(request, msg)
        return redirect(redirect_url_with_tab('parametres_administratifs', 'services'))
    messages.error(request, msg)
    return redirect('parametres_administratifs')


def _post_fonction(request):
    if not request.user.has_perm('accounts.menu_fonctions') and not request.user.is_superuser:
        messages.error(request, "⛔ Accès refusé.")
        return redirect('parametres_administratifs')

    edit_id = parse_optional_id(request, 'fonction_id', 'edit_fonction')
    instance = None
    if edit_id:
        try:
            instance = Fonction.objects.get(id=edit_id)
        except Fonction.DoesNotExist:
            instance = None

    nom = request.POST.get('nom', '').strip()
    if not nom:
        messages.error(request, "❌ Le nom de la fonction est obligatoire.")
        return redirect('parametres_administratifs')

    nom = ' '.join(nom.split())
    if len(nom) > 100:
        messages.error(request, "❌ Le nom ne doit pas dépasser 100 caractères.")
        return redirect('parametres_administratifs')

    if instance:
        if Fonction.objects.filter(nom__iexact=nom).exclude(id=instance.id).exists():
            messages.error(request, f"⛔ Le nom '{nom}' est déjà utilisé.")
            return redirect('parametres_administratifs')
    else:
        if Fonction.objects.filter(nom__iexact=nom).exists():
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
            nom=nom,
            description=description,
            cree_par=request.user,
        )
        action = "ajoutée"

    messages.success(request, f"✅ Fonction '{nom}' {action} avec succès !")
    return redirect(redirect_url_with_tab('parametres_administratifs', 'fonctions'))


def _post_supprimer_specialite(request):
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

    spe = get_object_or_404(Specialite, id=pk)
    deps = get_dependances(spe)
    if deps:
        messages.error(request, f"⛔ Impossible de supprimer : utilisée par {', '.join(deps)}.")
    else:
        safe_delete_entity(spe, request.user)
        messages.success(request, "🗑️ Spécialité supprimée.")
    return redirect(redirect_url_with_tab('parametres_administratifs', 'specialites'))


def _post_supprimer_service(request):
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

    service = get_object_or_404(Service, id=pk)
    deps = get_dependances(service)
    if deps:
        messages.error(request, f"⛔ Impossible de supprimer : utilisé par {', '.join(deps)}.")
    else:
        safe_delete_entity(service, request.user)
        messages.success(request, "🗑️ Service supprimé.")
    return redirect(redirect_url_with_tab('parametres_administratifs', 'services'))


def _post_supprimer_fonction(request):
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

    fct = get_object_or_404(Fonction, id=pk)
    deps = get_dependances(fct)
    if deps:
        messages.error(request, f"⛔ Impossible de supprimer : utilisée par {', '.join(deps)}.")
    else:
        safe_delete_entity(fct, request.user)
        messages.success(request, "🗑️ Fonction supprimée.")
    return redirect(redirect_url_with_tab('parametres_administratifs', 'fonctions'))