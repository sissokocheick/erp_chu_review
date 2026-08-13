# -*- coding: utf-8 -*-


# accounts/views.py — MONO-TENANT (corrigé)



import json



import logging



from datetime import timedelta







from django.shortcuts import render, redirect, get_object_or_404



from django.contrib import messages



from django.contrib.auth.decorators import login_required, permission_required



from django.contrib.auth.models import User, Group, Permission



from django.contrib.auth import login, logout, update_session_auth_hash

# ── Anti brute-force login ──────────────────────────────────────────────
LOGIN_MAX_ECHECS = 5
LOGIN_FENETRE_ECHECS = 900  # 15 minutes
# Hash factice pour neutraliser le timing oracle (existence des usernames)
LOGIN_DUMMY_HASH = 'pbkdf2_sha256$1200000$xdDS6X68UY4iCXOi0MGJzc$mQSKndcmo+OVhY7lI+83K03w6ZxDTVEjxVLuMWL96Hs='




from django.db import transaction



from django.db.models import Q, Count



from django.core.paginator import Paginator



from django.utils import timezone



from django.http import JsonResponse



from django.views.decorators.csrf import csrf_exempt



from django.views.decorators.http import require_POST



from django.utils.http import url_has_allowed_host_and_scheme



from django.contrib.admin.models import LogEntry



from django.contrib.sessions.models import Session
from accounts.menus import ROLE_ARCHITECTURE_MENU, MODULE_ICONS, MENU_ITEMS_META as MENU_ITEMS_META_MENUS







from core.models import ConfigurationHopital, Service, ConfigurationNotification



from .models import (



    Profil, Specialite, Notification, JournalAudit, Fonction, AuditConnexion,



    ConfigSecurite,



)



from .permissions import verifier_permission



from .utils import (
    valider_mot_de_passe,
    generer_mot_de_passe_aleatoire,
    canaux_notification_actifs,
)



from stock.models import Magasin







logger = logging.getLogger(__name__)







# Politique login



MIN_USERNAME_LENGTH = 3











# ==========================================================



# UTILITAIRES



# ==========================================================



def paginer(queryset, request, per_page_key='per_page', default=15, max_all=500):



    per_page = request.GET.get(per_page_key, str(default))



    is_list = isinstance(queryset, list)



    if per_page == 'all':



        count = len(queryset) if is_list else queryset.count()



        limite = min(count, max_all) if count > 0 else 1



    else:



        try:



            limite = int(per_page)



        except ValueError:



            limite = default



    page = request.GET.get('page')



    return Paginator(queryset, limite).get_page(page), per_page











def get_client_ip(request):



    """IP réelle du client.

    Ne fait confiance à HTTP_X_FORWARDED_FOR que si le déploiement est
    explicitement derrière un proxy (config.USE_X_FORWARDED_FOR=True) :
    sinon l'en-tête est spoofable et permet de contourner l'anti brute-force
    par IP. Derrière un proxy, on prend l'entrée la plus à droite (celle
    ajoutée par le proxy de confiance le plus proche de l'application).
    """

    from django.conf import settings
    if getattr(settings, 'USE_X_FORWARDED_FOR', False):
        x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded:
            ips = [ip.strip() for ip in x_forwarded.split(',') if ip.strip()]
            if ips:
                return ips[-1]
    return request.META.get('REMOTE_ADDR', '')











def log_audit(request, action, type_action='UPDATE', modele_concerne='', id_objet=None, details=None):



    try:



        JournalAudit.objects.create(



            utilisateur=request.user if request.user.is_authenticated else None,



            action=action[:200],



            type_action=type_action,



            modele_concerne=modele_concerne or '',



            id_objet=id_objet,



            details=details,



            adresse_ip=get_client_ip(request),



        )



    except Exception as e:



        logger.error(f"Erreur log_audit: {e}")











def _ctx_utilisateurs(request, page_obj, q, statut, form_data=None, show_modal=False, form_error=None):



    """Contexte commun pour le template utilisateurs.html"""



    users_qs = User.objects.select_related('profil').prefetch_related('groups')



    if statut == 'actif':



        users_qs = users_qs.filter(is_active=True)



    elif statut == 'inactif':



        users_qs = users_qs.filter(is_active=False)



    if q:



        users_qs = users_qs.filter(



            Q(username__icontains=q) |



            Q(first_name__icontains=q) |



            Q(last_name__icontains=q) |



            Q(email__icontains=q)



        )



    # La réinitialisation admin n'est désactivée que si un canal est réellement
    # livrable (sinon les utilisateurs seraient bloqués sans aucune issue).
    email_ok, sms_ok = canaux_notification_actifs()
    reinit_mdp_desactive = bool(email_ok or sms_ok)

    return {



        'utilisateurs': page_obj,



        'page_obj': page_obj,



        'q': q,



        'statut_filtre': statut,



        'groupes': Group.objects.all().order_by('name'),



        'services_tous': Service.objects.all().order_by('nom'),



        'specialites': Specialite.objects.all().order_by('nom'),



        'fonctions': Fonction.objects.all().order_by('nom'),



        'magasins_tous': Magasin.objects.all().order_by('nom'),



        'total_users': users_qs.count(),



        'form_data': form_data or {},



        'show_modal': show_modal,



        'form_error': form_error,



        'reinit_mdp_desactive': reinit_mdp_desactive,



    }











# ==========================================================



# CONNEXION / DÉCONNEXION



# ==========================================================



def custom_login(request):



    """Connexion mono-tenant."""



    if request.user.is_authenticated:



        return redirect('accounts:accueil_personnalise')



    # « Mot de passe oublié » visible seulement si un canal email/SMS est livrable
    email_ok, sms_ok = canaux_notification_actifs()
    reinit_mdp_active = bool(email_ok or sms_ok)
    _login_ctx = {'reinit_mdp_active': reinit_mdp_active}



    if request.method == 'POST':



        # ── Anti brute-force : blocage temporaire après trop d'échecs (par IP) ──
        nb_echecs = AuditConnexion.objects.filter(
            type_action='ECHEC',
            adresse_ip=get_client_ip(request),
            date_creation__gte=timezone.now() - timedelta(seconds=LOGIN_FENETRE_ECHECS),
        ).count()
        if nb_echecs >= LOGIN_MAX_ECHECS:
            messages.error(
                request,
                '⛔ Trop de tentatives échouées. Connexion temporairement bloquée — réessayez dans 15 minutes.',
            )
            return render(request, 'accounts/login.html', _login_ctx)



        username = request.POST.get('username', '').lower().strip().replace(' ', '')



        password = request.POST.get('password', '')







        # Nettoyer le username (minuscules, sans espaces)



        if '@' in username:



            username = username.split('@', 1)[0]







        user = User.objects.filter(username__iexact=username, is_active=True).first()

        # Vérification neutre en timing : on hache le mot de passe même si le compte
        # n'existe pas, pour ne pas révéler l'existence des usernames (timing oracle).
        if user is not None:
            password_ok = user.check_password(password)
        else:
            from django.contrib.auth.hashers import check_password as _check_password
            password_ok = False
            _check_password(password, LOGIN_DUMMY_HASH)

        logger.info(f"[LOGIN] tentative pour username={username!r}")








        if user and password_ok:



            login(request, user, backend='django.contrib.auth.backends.ModelBackend')



            # Journaliser la connexion IMMEDIATEMENT apres login() :
            # le retour anticipe must_change_password court-circuitait
            # log_audit/AuditConnexion -> trou d'audit sur les comptes neufs.
            log_audit(request, f"Connexion de {user.username}", type_action='LOGIN')
            try:
                AuditConnexion.objects.create(
                    utilisateur=user,
                    type_action='CONNEXION',
                    description=f"Connexion reussie de {user.username}",
                    adresse_ip=get_client_ip(request),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
                )
            except Exception:
                logger.exception("AuditConnexion impossible pour %s", user.username)



            # Force changement MDP premiere connexion



            try:



                profil = user.profil



                if profil.doit_changer_mdp:



                    request.session['must_change_password'] = True



                    messages.warning(request, "🔒 Vous devez changer votre mot de passe avant de continuer.")



                    return redirect('accounts:changer_mdp_obligatoire')



            except Exception:



                pass







            messages.success(request, f"✅ Bienvenue {user.get_full_name() or user.username} !")







            next_url = request.POST.get('next') or request.GET.get('next')



            if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):



                return redirect(next_url)



            return redirect('accounts:accueil_personnalise')



        else:



            messages.error(request, "⛔ Identifiants incorrects ou compte desactive.")



            try:



                AuditConnexion.objects.create(



                    type_action='ECHEC',



                    description=f"Tentative echouee pour {username}",



                    adresse_ip=get_client_ip(request),



                    user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],



                )



            except Exception:



                pass







    return render(request, 'accounts/login.html', _login_ctx)











@require_POST
def custom_logout(request):



    if request.user.is_authenticated:



        log_audit(request, f"Deconnexion de {request.user.username}", type_action='LOGOUT')



        try:



            AuditConnexion.objects.create(



                utilisateur=request.user,



                type_action='DECONNEXION',



                description=f"Deconnexion de {request.user.username}",



                adresse_ip=get_client_ip(request),



                user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],



            )



        except Exception:



            pass



    logout(request)



    messages.success(request, "👋 Vous avez ete deconnecte.")



    return redirect('accounts:custom_login')











@login_required(login_url='/auth/login/')



def changer_mdp_obligatoire(request):



    """Force le changement de mot de passe a la premiere connexion."""



    if not request.session.get('must_change_password'):



        try:



            if not request.user.profil.doit_changer_mdp:



                return redirect('accounts:accueil_personnalise')



        except Exception:



            return redirect('accounts:accueil_personnalise')







    if request.method == 'POST':



        ancien = request.POST.get('ancien_mdp') or request.POST.get('old_password', '')



        nouveau = request.POST.get('nouveau_mdp') or request.POST.get('new_password1', '')



        confirmer = request.POST.get('confirmation') or request.POST.get('new_password2', '')







        # CORRECTION : verification de l'ancien MDP est OBLIGATOIRE



        if not request.user.check_password(ancien):



            messages.error(request, "❌ Ancien mot de passe incorrect.")



            return redirect('accounts:changer_mdp_obligatoire')







        if nouveau != confirmer:



            messages.error(request, "❌ Les mots de passe ne correspondent pas.")



            return redirect('accounts:changer_mdp_obligatoire')







        erreurs = valider_mot_de_passe(nouveau, contexte='obligatoire')



        if erreurs:



            messages.error(request, "❌ Mot de passe invalide : " + ", ".join(erreurs) + ".")



            return redirect('accounts:changer_mdp_obligatoire')







        request.user.set_password(nouveau)



        request.user.save()







        try:



            profil = request.user.profil



            profil.doit_changer_mdp = False



            profil.save(update_fields=['doit_changer_mdp'])



        except Exception:



            pass







        request.session.pop('must_change_password', None)



        update_session_auth_hash(request, request.user)



        log_audit(request, "Changement mot de passe obligatoire", type_action='UPDATE')

        try:
            AuditConnexion.objects.create(
                utilisateur=request.user,
                type_action='PASSWORD_CHANGE',
                description="Changement de mot de passe obligatoire",
                adresse_ip=get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
            )
        except Exception:
            logger.exception("AuditConnexion PASSWORD_CHANGE impossible")

        messages.success(request, "✅ Mot de passe change avec succes !")



        return redirect('accounts:accueil_personnalise')







    return render(request, 'accounts/changer_mdp_obligatoire.html')











# ==========================================================



# ACCUEIL



# ==========================================================



@login_required(login_url='/auth/login/')



def accueil_personnalise(request):



    MODULES = {



        'menu_demandes':        {'url': '/mes-demandes/', 'icon': 'fa-clipboard-list', 'color': '#17a2b8', 'label': 'Mes Demandes'},



        'menu_guichet':         {'url': '/gestion-demandes/', 'icon': 'fa-desktop', 'color': '#6f42c1', 'label': 'Traiter Demandes'},



        'menu_entrees':         {'url': '/entrees/', 'icon': 'fa-arrow-down', 'color': '#28a745', 'label': 'Entrees Stock'},



        'menu_reception_commande': {'url': '/receptions/', 'icon': 'fa-truck-loading', 'color': '#28a745', 'label': 'Receptions'},



        'menu_sorties':         {'url': '/sorties/', 'icon': 'fa-arrow-up', 'color': '#dc3545', 'label': 'Bons de Sortie'},



        'menu_livraisons':      {'url': '/livraisons/', 'icon': 'fa-truck', 'color': '#fd7e14', 'label': 'Livraisons'},



        'menu_sorties_hors_stock': {'url': '/bons/hors-stock/', 'icon': 'fa-external-link-alt', 'color': '#e83e8c', 'label': 'Sorties Hors Stock'},



        'menu_retours_services': {'url': '/stock/retours-services/', 'icon': 'fa-undo', 'color': '#20c997', 'label': 'Retours Services'},



        'menu_stock':           {'url': '/etat-stock/', 'icon': 'fa-boxes', 'color': '#1c5b96', 'label': 'État du Stock'},



        'menu_peremptions':     {'url': '/stock/peremptions/', 'icon': 'fa-calendar-times', 'color': '#ffc107', 'label': 'Peremptions'},



        'menu_articles':        {'url': '/articles/', 'icon': 'fa-barcode', 'color': '#0d47a1', 'label': 'Catalogue Articles'},



        'menu_familles':        {'url': '/familles/', 'icon': 'fa-folder-open', 'color': '#fd7e14', 'label': 'Familles'},



        'menu_commandes':       {'url': '/commandes/', 'icon': 'fa-shopping-cart', 'color': '#e83e8c', 'label': 'Commandes'},



        'menu_rapports':        {'url': '/rapports/', 'icon': 'fa-chart-line', 'color': '#28a745', 'label': 'Rapports'},



        'menu_utilisateurs':    {'url': '/auth/utilisateurs/', 'icon': 'fa-users', 'color': '#1c5b96', 'label': 'Utilisateurs'},



        'menu_roles':           {'url': '/auth/roles/', 'icon': 'fa-user-shield', 'color': '#0d47a1', 'label': 'Roles & Acces'},



        'menu_param_admin':     {'url': '/parametres/administratifs/', 'icon': 'fa-building', 'color': '#1c5b96', 'label': 'Parametres Admin'},



        'menu_param_logistique': {'url': '/parametres/logistique/', 'icon': 'fa-cogs', 'color': '#6c757d', 'label': 'Param. Logistique'},



    }







    if request.user.is_superuser:



        perms_menu = list(MODULES.keys())



    else:



        perms_user = request.user.get_all_permissions()



        perms_menu = [p.split('.')[-1] for p in perms_user if p.startswith('accounts.menu_') or p.startswith('stock.menu_')]







    modules_accessibles = []



    for codename in perms_menu:



        if codename in MODULES:



            modules_accessibles.append({**MODULES[codename], 'codename': codename})







    return render(request, 'accounts/accueil.html', {



        'modules': modules_accessibles,



        'total_modules': len(modules_accessibles),



    })











# ==========================================================



# PROFIL



# ==========================================================



@login_required(login_url='/auth/login/')



def profil_utilisateur(request):



    try:



        profil = request.user.profil



    except Profil.DoesNotExist:



        profil = Profil.objects.create(user=request.user)



        messages.warning(request, "⚠️ Profil cree automatiquement.")







    onglet = request.GET.get('onglet', 'infos')
    if onglet not in ('infos', 'signature', 'securite'):
        onglet = 'infos'







    if request.method == 'POST':



        action = request.POST.get('action', '')







        if action == 'photo':



            photo = request.FILES.get('photo')



            if photo:



                # CORRECTION : verification MIME



                if photo.content_type not in ('image/jpeg', 'image/png'):



                    messages.error(request, "⛔ Seuls les formats JPG et PNG sont acceptes.")



                    return redirect(f'{request.path}?onglet=infos')



                if photo.size > 2 * 1024 * 1024:



                    messages.error(request, "⛔ L'image ne doit pas depasser 2 Mo.")



                    return redirect(f'{request.path}?onglet=infos')



                profil.photo = photo



                profil.nb_changements_photo = getattr(profil, 'nb_changements_photo', 0) + 1



                profil.date_derniere_photo = timezone.now()



                profil.save()



                messages.success(request, "✅ Photo mise a jour.")



            return redirect(f'{request.path}?onglet=infos')







        elif action == 'password':



            old = request.POST.get('old_password', '')



            new1 = request.POST.get('new_password1', '')



            new2 = request.POST.get('new_password2', '')



            if not request.user.check_password(old):



                messages.error(request, "❌ Mot de passe actuel incorrect.")



            elif new1 != new2:



                messages.error(request, "❌ Les mots de passe ne correspondent pas.")



            else:



                erreurs = valider_mot_de_passe(new1, contexte='profil')



                if erreurs:



                    messages.error(request, "❌ Mot de passe invalide : " + ", ".join(erreurs) + ".")



                else:



                    request.user.set_password(new1)



                    request.user.save()



                    update_session_auth_hash(request, request.user)  # CORRECTION : ne pas deconnecter



                    log_audit(request, "Changement mot de passe profil", type_action='UPDATE',

                              modele_concerne='User', id_objet=request.user.id)

                    try:
                        AuditConnexion.objects.create(
                            utilisateur=request.user,
                            type_action='PASSWORD_CHANGE',
                            description="Changement de mot de passe (profil)",
                            adresse_ip=get_client_ip(request),
                            user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
                        )
                    except Exception:
                        logger.exception("AuditConnexion PASSWORD_CHANGE profil impossible")

                    messages.success(request, "✅ Mot de passe modifie.")



            return redirect(f'{request.path}?onglet=securite')







        else:



            # CORRECTION : normalisation conforme UX_POLICY §3



            request.user.first_name = request.POST.get('first_name', '').strip().title()



            request.user.last_name = request.POST.get('last_name', '').strip().upper()



            request.user.email = request.POST.get('email', '').strip().lower()



            request.user.save()



            contact_raw = request.POST.get('contact', '').strip()



            profil.contact = ''.join(c for c in contact_raw if c.isdigit())



            profil.save()
            log_audit(request, "Mise a jour profil", type_action='UPDATE',
                      modele_concerne='Profil', id_objet=profil.id)
            messages.success(request, "✅ Profil mis a jour.")
            return redirect('accounts:profil_utilisateur')








    return render(request, 'accounts/profil.html', {



        'profil': profil,



        'onglet': onglet,



    })











# ==========================================================



# UTILISATEURS



# ==========================================================



@login_required(login_url='/auth/login/')



@verifier_permission('accounts.menu_utilisateurs')



def page_utilisateurs(request):



    statut = request.GET.get('statut_filtre', 'actif')



    q = request.GET.get('q', '').strip()







    users = User.objects.select_related('profil').prefetch_related('groups')



    if statut == 'actif':



        users = users.filter(is_active=True)



    elif statut == 'inactif':



        users = users.filter(is_active=False)







    if q:



        users = users.filter(



            Q(username__icontains=q) |



            Q(first_name__icontains=q) |



            Q(last_name__icontains=q) |



            Q(email__icontains=q)



        )







    users = users.order_by('last_name', 'first_name', 'username')



    page_obj, per_page = paginer(users, request, default=20)







    if request.method == 'POST':



        action = request.POST.get('action', '')







        if request.POST.get('toggle_statut') == '1':



            # CORRECTION : conversion securisee de l'ID



            try:



                uid = int(request.POST.get('user_id', ''))



            except (ValueError, TypeError):



                messages.error(request, "⛔ Identifiant utilisateur invalide.")



                return redirect('accounts:page_utilisateurs')



            user = get_object_or_404(User, id=uid)



            if user == request.user:



                messages.error(request, "❌ Vous ne pouvez pas vous desactiver.")



            else:



                user.is_active = not user.is_active

                user.save()

                # Purger les sessions existantes d'un compte désactivé
                if not user.is_active:
                    from django.contrib.sessions.models import Session
                    from django.utils import timezone as tz
                    for s in Session.objects.filter(expire_date__gt=tz.now()):
                        try:
                            if str(user.id) == s.get_decoded().get('_auth_user_id'):
                                s.delete()
                        except Exception:
                            continue

                messages.success(request, f"{'Active' if user.is_active else 'Desactive'} : {user.username}")



            return redirect('accounts:page_utilisateurs')







        if request.POST.get('enregistrer_user') == '1':



            user_id = request.POST.get('user_id')



            # NOTE : les uploads photo/signature ne sont PAS geres ici.



            # Ils doivent etre modifies via le profil utilisateur.



            # Normalisation format champs



            first_name = request.POST.get('first_name', '').strip().title()



            last_name = request.POST.get('last_name', '').strip().upper()



            email = request.POST.get('email', '').strip().lower()



            contact_raw = request.POST.get('contact', '').strip()



            contact = ''.join(c for c in contact_raw if c.isdigit())  # stocke chiffres seuls



            # Donnees du formulaire pour pre-remplissage en cas d'erreur



            form_data_tmp = {



                'user_id': user_id or '',



                'username': request.POST.get('username', '').lower().strip().replace(' ', ''),



                'first_name': first_name,



                'last_name': last_name,



                'email': email,



                'contact': contact_raw,



                'groupe': request.POST.get('groupe') or '',



                'service': request.POST.get('service') or '',



                'specialite': request.POST.get('specialite') or '',



                'fonction': request.POST.get('fonction') or '',



                'magasin_ids': request.POST.getlist('magasins'),



            }



            # Telephone : exactement 10 chiffres (format 01 02 03 04 05)



            if contact and len(contact) != 10:



                err = "⛔ Le numero de telephone doit contenir exactement 10 chiffres."



                return render(request, 'accounts/utilisateurs.html',



                              _ctx_utilisateurs(request, page_obj, q, statut, form_data_tmp, show_modal=True, form_error=err))



            # Email : format valide — applique a la creation ET a la modification



            if email:

                from django.core.exceptions import ValidationError as _DjangoValidationError

                from django.core.validators import validate_email as _valider_email

                try:

                    _valider_email(email)

                except _DjangoValidationError:

                    err = "⛔ Adresse email invalide — format attendu : nom@domaine.com."

                    return render(request, 'accounts/utilisateurs.html',

                                  _ctx_utilisateurs(request, page_obj, q, statut, form_data_tmp, show_modal=True, form_error=err))



            # Affichage formate XX XX XX XX XX pour form_data



            contact_display = ' '.join(contact[i:i+2] for i in range(0, len(contact), 2)) if contact else ''



            groupe_id = request.POST.get('groupe')



            service_id = request.POST.get('service')



            specialite_id = request.POST.get('specialite')



            fonction_id = request.POST.get('fonction')



            magasin_ids = request.POST.getlist('magasins')







            # Donnees du formulaire pour pre-remplissage en cas d'erreur



            form_data = {



                'user_id': user_id or '',



                'username': request.POST.get('username', '').lower().strip().replace(' ', ''),



                'first_name': first_name,



                'last_name': last_name,



                'email': email,



                'contact': contact_display,



                'groupe': groupe_id or '',



                'service': service_id or '',



                'specialite': specialite_id or '',



                'fonction': fonction_id or '',



                'magasin_ids': magasin_ids,



            }







            if user_id:



                # === MODIFICATION ===



                try:



                    uid = int(user_id)



                except (ValueError, TypeError):



                    err = "⛔ Identifiant utilisateur invalide."



                    return render(request, 'accounts/utilisateurs.html',



                                  _ctx_utilisateurs(request, page_obj, q, statut, form_data, show_modal=True, form_error=err))



                user = get_object_or_404(User, id=uid)



                user.first_name = first_name



                user.last_name = last_name



                user.email = email



                user.save()



                profil, _ = Profil.objects.get_or_create(user=user)



            else:



                # === CREATION ===



                username = form_data['username']



                if not username:



                    err = "⛔ Le nom d'utilisateur est obligatoire."



                    return render(request, 'accounts/utilisateurs.html',



                                  _ctx_utilisateurs(request, page_obj, q, statut, form_data, show_modal=True, form_error=err))







                if len(username) < MIN_USERNAME_LENGTH:



                    err = f"⛔ Le login doit contenir au moins {MIN_USERNAME_LENGTH} caracteres."



                    return render(request, 'accounts/utilisateurs.html',



                                  _ctx_utilisateurs(request, page_obj, q, statut, form_data, show_modal=True, form_error=err))







                # Verification doublon username



                if User.objects.filter(username__iexact=username).exists():



                    err = f"⛔ Le nom d'utilisateur '{username}' est deja utilise par un autre compte."



                    return render(request, 'accounts/utilisateurs.html',



                                  _ctx_utilisateurs(request, page_obj, q, statut, form_data, show_modal=True, form_error=err))













                # Verification doublon email (si renseigne)



                if email:



                    if User.objects.filter(email__iexact=email).exists():



                        err = f"⛔ L'adresse email '{email}' est deja associee a un autre compte."



                        return render(request, 'accounts/utilisateurs.html',



                                      _ctx_utilisateurs(request, page_obj, q, statut, form_data, show_modal=True, form_error=err))







                # Verification doublon contact / telephone (si renseigne)



                # CORRECTION : chercher dans plusieurs formats pour compatibilite



                if contact:



                    contact_variants = [contact]



                    contact_variants.append(' '.join(contact[i:i+2] for i in range(0, len(contact), 2)))



                    if Profil.objects.filter(contact__in=contact_variants).exists():



                        err = f"⛔ Le numero de telephone '{contact}' est deja associe a un autre compte."



                        return render(request, 'accounts/utilisateurs.html',



                                      _ctx_utilisateurs(request, page_obj, q, statut, form_data, show_modal=True, form_error=err))







                # Respecte ConfigSecurite (ALEATOIRE / FIXE)



                cfg = ConfigSecurite.get_solo()



                if cfg.type_mot_de_passe == 'FIXE' and cfg.mot_de_passe_defaut:



                    password = cfg.mot_de_passe_defaut



                else:



                    password = generer_mot_de_passe_aleatoire(12)







                user = User.objects.create_user(



                    username=username, email=email, password=password,



                    first_name=first_name, last_name=last_name,



                )



                profil, created = Profil.objects.get_or_create(



                    user=user,



                    defaults={



                        'doit_changer_mdp': True,



                        'theme_preference': 'light',



                        'est_chef_service': False,



                        'nb_changements_photo': 0,



                    }



                )



                if not created:



                    profil.doit_changer_mdp = True



                    profil.save(update_fields=['doit_changer_mdp'])







                # MDP temporaire affiche une seule fois (modale new_credentials)



                request.session['new_user_credentials'] = {



                    'username': username,



                    'password': password,



                    'full_name': (f"{last_name} {first_name}").strip() or username,



                }



                messages.success(request, f"✅ Utilisateur '{username}' cree.")







            # Mise a jour du profil (commun creation + modification)



            profil.contact = contact



            if service_id:



                try:



                    profil.service_id = int(service_id)



                except (ValueError, TypeError):



                    profil.service = None



            else:



                profil.service = None



            if specialite_id:



                try:



                    profil.specialite_id = int(specialite_id)



                except (ValueError, TypeError):



                    profil.specialite = None



            else:



                profil.specialite = None



            if fonction_id:



                try:



                    profil.fonction_id = int(fonction_id)



                except (ValueError, TypeError):



                    profil.fonction = None



            else:



                profil.fonction = None



            profil.save()







            if magasin_ids:



                profil.magasins_autorises.set(magasin_ids)



            else:



                profil.magasins_autorises.clear()







            if groupe_id:
                user.groups.set([groupe_id])
            else:
                user.groups.clear()

            # Les droits viennent UNIQUEMENT du rôle (groupe) :
            # purge des permissions directes héritées de l'ancien système
            # (sinon l'utilisateur garde tous les menus malgré un rôle restreint)
            user.user_permissions.clear()







            if user_id:



                log_audit(request, f"Mise a jour utilisateur {user.username}", type_action='UPDATE',



                          modele_concerne='User', id_objet=user.id)



                messages.success(request, f"✅ {user.username} mis a jour.")



            else:



                log_audit(request, f"Creation utilisateur {user.username}", type_action='CREATE',



                          modele_concerne='User', id_objet=user.id)



            return redirect('accounts:page_utilisateurs')







    new_credentials = request.session.pop('new_user_credentials', None)



    ctx = _ctx_utilisateurs(request, page_obj, q, statut)



    ctx['new_credentials'] = new_credentials



    return render(request, 'accounts/utilisateurs.html', ctx)











@login_required(login_url='/auth/login/')



@verifier_permission('accounts.menu_utilisateurs')



def reinitialiser_mdp(request, user_id):



    # Si un canal email/SMS est livrable, la réinitialisation se fait par
    # l'utilisateur lui-même via « Mot de passe oublié » sur la page de connexion.
    email_ok, sms_ok = canaux_notification_actifs()
    if email_ok or sms_ok:
        messages.error(
            request,
            "❌ Réinitialisation manuelle désactivée : un canal email/SMS est "
            "configuré. L'utilisateur doit utiliser « Mot de passe oublié » "
            "depuis la page de connexion.",
        )
        return redirect('accounts:page_utilisateurs')



    user = get_object_or_404(User, id=user_id)



    if request.method == 'POST':



        nouveau = request.POST.get('nouveau_mdp', '')



        confirmer = request.POST.get('confirmer_mdp', '')



        if nouveau != confirmer:



            messages.error(request, "❌ Les mots de passe ne correspondent pas.")



        else:



            erreurs = valider_mot_de_passe(nouveau, contexte='admin_reset')



            if erreurs:



                messages.error(request, "❌ Mot de passe invalide : " + ", ".join(erreurs) + ".")



            else:



                user.set_password(nouveau)



                user.save()



                try:



                    profil, _ = Profil.objects.get_or_create(user=user)



                    profil.doit_changer_mdp = True



                    profil.save(update_fields=['doit_changer_mdp'])



                except Exception:



                    pass



                log_audit(request, f"Reinitialisation mdp {user.username}", type_action='UPDATE',

                          modele_concerne='User', id_objet=user.id)

                try:
                    AuditConnexion.objects.create(
                        utilisateur=user,
                        type_action='ADMIN',
                        description=f"Reinitialisation du mot de passe par {request.user.username}",
                        adresse_ip=get_client_ip(request),
                        user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
                    )
                except Exception:
                    logger.exception("AuditConnexion ADMIN reinitialisation impossible")

                messages.success(request, f"✅ Mot de passe de {user.username} reinitialise.")



                return redirect('accounts:page_utilisateurs')



    return render(request, 'accounts/reinitialiser_mdp.html', {'utilisateur': user})











@login_required(login_url='/auth/login/')



@verifier_permission('accounts.menu_utilisateurs')



def api_verifier_champ_utilisateur(request):



    """



    Verifie en AJAX la disponibilite d'un login / email / telephone.



    GET ?type=username|email|contact&value=...&exclude_id=123



    """



    champ = request.GET.get('type', '').strip().lower()



    value = request.GET.get('value', '').strip()



    exclude_id = request.GET.get('exclude_id', '').strip()







    if champ not in ('username', 'email', 'contact'):



        return JsonResponse({'ok': False, 'error': 'Type invalide'}, status=400)







    if not value:



        return JsonResponse({'ok': True, 'available': True, 'message': ''})







    qs_exclude = {}



    if exclude_id.isdigit():



        qs_exclude['id'] = int(exclude_id)







    if champ == 'username':



        value = value.lower().replace(' ', '')



        if len(value) < MIN_USERNAME_LENGTH:



            return JsonResponse({



                'ok': True, 'available': False,



                'message': f"Le login doit contenir au moins {MIN_USERNAME_LENGTH} caracteres.",



            })



        qs = User.objects.filter(username__iexact=value)



        if qs_exclude:



            qs = qs.exclude(**qs_exclude)



        if qs.exists():



            return JsonResponse({



                'ok': True, 'available': False,



                'message': "Ce login est deja utilise — choisissez-en un autre.",



            })



        return JsonResponse({'ok': True, 'available': True, 'message': 'Login disponible.'})







    if champ == 'email':



        value = value.lower()



        # Format email valide (pas seulement la presence d'un @)



        from django.core.exceptions import ValidationError as _DjangoValidationError



        from django.core.validators import validate_email as _valider_email



        try:



            _valider_email(value)



        except _DjangoValidationError:



            return JsonResponse({



                'ok': True, 'available': False,



                'message': "Adresse email invalide — format attendu : nom@domaine.com.",



            })



        qs = User.objects.filter(email__iexact=value).exclude(email='')



        if qs_exclude:



            qs = qs.exclude(**qs_exclude)



        if qs.exists():



            return JsonResponse({



                'ok': True, 'available': False,



                'message': "Cet email est deja associe a un autre compte.",



            })



        return JsonResponse({'ok': True, 'available': True, 'message': 'Email disponible.'})







    if champ == 'contact':



        digits = ''.join(c for c in value if c.isdigit())



        if digits and len(digits) != 10:



            return JsonResponse({



                'ok': True, 'available': False,



                'message': "Le numero doit contenir exactement 10 chiffres.",



            })



        if not digits:



            return JsonResponse({'ok': True, 'available': True, 'message': ''})



        spaced = ' '.join(digits[i:i+2] for i in range(0, len(digits), 2))



        qs = Profil.objects.filter(contact__in=[digits, spaced, value])



        if exclude_id.isdigit():



            qs = qs.exclude(user_id=int(exclude_id))



        if qs.exists():



            return JsonResponse({



                'ok': True, 'available': False,



                'message': "Ce numero est deja associe a un autre compte.",



            })



        return JsonResponse({'ok': True, 'available': True, 'message': 'Numero disponible.'})







    return JsonResponse({'ok': False, 'error': 'Type invalide'}, status=400)











# ==========================================================



# RÔLES & PERMISSIONS



# ==========================================================



SOUS_PERMISSIONS = {

    # ── DEMANDES ──
    'menu_demandes':           ['add_demandemateriel', 'change_demandemateriel', 'delete_demandemateriel'],
    'menu_guichet':            ['change_demandemateriel', 'add_livraisonpartielle', 'change_livraisonpartielle'],
    'menu_valider_demandes':   ['change_demandemateriel'],

    # ── MOUVEMENTS DE STOCK ──
    'menu_entrees':            ['can_add_bon_entree', 'can_change_bon_entree', 'can_delete_bon_entree'],
    'menu_sorties':            ['can_add_bon_sortie', 'can_change_bon_sortie', 'can_delete_bon_sortie'],
    'menu_sorties_hors_stock': ['can_add_bon_hors_stock', 'can_change_bon_hors_stock', 'can_delete_bon_hors_stock'],
    'menu_retours_services':   ['can_add_bon_retour', 'can_change_bon_retour', 'can_delete_bon_retour'],
    'menu_livraisons':         ['add_livraisonpartielle', 'change_livraisonpartielle', 'delete_livraisonpartielle'],
    'menu_reception_commande': ['change_commande', 'add_accusereception', 'change_accusereception'],

    # ── GESTION DES STOCKS ──
    'menu_ajustements':        ['add_ajustement', 'change_ajustement', 'delete_ajustement'],
    'menu_inventaires':        ['add_campagneinventaire', 'change_campagneinventaire', 'add_ligneinventaire', 'change_ligneinventaire'],

    # ── ACHATS & CATALOGUE ──
    'menu_commandes':          ['add_commande', 'change_commande', 'delete_commande'],
    'menu_articles':           ['add_article', 'change_article', 'delete_article'],
    'menu_familles':           ['add_famillearticle', 'change_famillearticle', 'delete_famillearticle'],

    # ── PATRIMOINE & SAV ──
    'menu_pat_tickets':        ['add_intervention', 'change_intervention', 'delete_intervention'],
    'menu_pat_tech':           ['add_intervention', 'change_intervention', 'add_technicienprestataire', 'change_technicienprestataire'],
    'menu_pat_dispatch':       ['change_intervention'],
    'menu_pat_registre':       ['add_immobilisation', 'change_immobilisation', 'delete_immobilisation', 'add_mouvementpatrimoine', 'change_mouvementpatrimoine'],
    'menu_pat_sas':            ['add_immobilisation', 'change_immobilisation'],
    'menu_pat_contrats':       ['add_contratmaintenance', 'change_contratmaintenance', 'delete_contratmaintenance', 'add_typecontrat', 'change_typecontrat'],
    'menu_pat_import':         ['add_importpatrimoine'],
    'menu_pat_inventaire':     ['add_campagneinventairepatrimoine', 'change_campagneinventairepatrimoine', 'add_ligneinventairepatrimoine', 'change_ligneinventairepatrimoine'],
    'menu_pat_rebuts':         ['change_immobilisation'],
    'menu_pat_pertes':         ['change_immobilisation'],
    'menu_pat_parametres':     ['add_categoriepatrimoine', 'change_categoriepatrimoine', 'add_marque', 'change_marque', 'add_modele', 'change_modele', 'add_batiment', 'change_batiment', 'add_etage', 'change_etage', 'add_bureau', 'change_bureau', 'add_typeequipement', 'change_typeequipement', 'add_parametrespatrimoine', 'change_parametrespatrimoine'],

    # ── PARAMÈTRES (3 pages cochables, fonctionnalités en dessous) ──
    'menu_param_admin':        ['menu_services', 'add_service', 'change_service', 'delete_service',
                                'menu_specialites', 'add_specialite', 'change_specialite', 'delete_specialite',
                                'menu_fonctions', 'add_fonction', 'change_fonction', 'delete_fonction',
                                'change_configurationhopital'],
    'menu_param_logistique':   ['menu_fournisseurs', 'add_fournisseur', 'change_fournisseur', 'delete_fournisseur',
                                'menu_magasins', 'add_magasin', 'change_magasin', 'delete_magasin',
                                'menu_motifs_annulation', 'add_motifannulation', 'change_motifannulation', 'delete_motifannulation',
                                'menu_beneficiaires', 'add_beneficiaire', 'change_beneficiaire', 'delete_beneficiaire',
                                'change_configurationhopital'],
    'menu_modeles_pdf':        ['menu_parametres_doc', 'add_configdocument', 'change_configdocument', 'delete_configdocument',
                                'can_configurer_modeles_pdf', 'add_modeledocumentmagasin', 'change_modeledocumentmagasin'],
    'menu_notifications_config': ['change_configurationnotification'],

    # ── SÉCURITÉ & ACCÈS ──
    'menu_utilisateurs':       ['add_user', 'change_user', 'delete_user', 'add_profil', 'change_profil'],
    'menu_roles':              ['add_group', 'change_group', 'delete_group'],
    'menu_circuits_validation':['add_circuitvalidateur', 'change_circuitvalidateur', 'add_circuitvalidation', 'change_circuitvalidation'],
    'menu_journal_audit':      ['view_journalaudit'],

}


SOUS_PERM_LABELS = {



    'can_add_bon_entree':       {'label': 'Creer', 'icon': 'fa-plus', 'color': '#28a745'},



    'can_change_bon_entree':    {'label': 'Modifier / Annuler', 'icon': 'fa-edit', 'color': '#ffc107'},



    'can_delete_bon_entree':    {'label': 'Supprimer', 'icon': 'fa-trash', 'color': '#dc3545'},



    'can_add_bon_sortie':       {'label': 'Creer', 'icon': 'fa-plus', 'color': '#28a745'},



    'can_change_bon_sortie':    {'label': 'Modifier / Annuler', 'icon': 'fa-edit', 'color': '#ffc107'},



    'can_delete_bon_sortie':    {'label': 'Supprimer', 'icon': 'fa-trash', 'color': '#dc3545'},



    'can_add_bon_retour':       {'label': 'Creer', 'icon': 'fa-plus', 'color': '#28a745'},



    'can_change_bon_retour':    {'label': 'Modifier / Annuler', 'icon': 'fa-edit', 'color': '#ffc107'},



    'can_delete_bon_retour':    {'label': 'Supprimer', 'icon': 'fa-trash', 'color': '#dc3545'},



    'can_add_bon_hors_stock':   {'label': 'Creer', 'icon': 'fa-plus', 'color': '#28a745'},



    'can_change_bon_hors_stock':{'label': 'Modifier / Annuler', 'icon': 'fa-edit', 'color': '#ffc107'},



    'can_delete_bon_hors_stock':{'label': 'Supprimer', 'icon': 'fa-trash', 'color': '#dc3545'},



    'add_commande':           {'label': 'Creer', 'icon': 'fa-plus', 'color': '#28a745'},



    'change_commande':        {'label': 'Modifier / Valider', 'icon': 'fa-edit', 'color': '#ffc107'},



    'delete_commande':        {'label': 'Supprimer', 'icon': 'fa-trash', 'color': '#dc3545'},



    'add_ajustement':         {'label': 'Creer', 'icon': 'fa-plus', 'color': '#28a745'},



    'change_ajustement':      {'label': 'Modifier', 'icon': 'fa-edit', 'color': '#ffc107'},



    'add_campagneinventaire': {'label': 'Creer', 'icon': 'fa-plus', 'color': '#28a745'},



    'change_campagneinventaire': {'label': 'Modifier', 'icon': 'fa-edit', 'color': '#ffc107'},



    'add_article':            {'label': 'Ajouter', 'icon': 'fa-plus', 'color': '#28a745'},



    'change_article':         {'label': 'Modifier', 'icon': 'fa-edit', 'color': '#ffc107'},



    'delete_article':         {'label': 'Supprimer', 'icon': 'fa-trash', 'color': '#dc3545'},



    'add_famillearticle':     {'label': 'Ajouter familles', 'icon': 'fa-plus', 'color': '#fd7e14'},



    'change_famillearticle':  {'label': 'Modifier familles', 'icon': 'fa-edit', 'color': '#ffc107'},



    'add_fournisseur':        {'label': 'Ajouter', 'icon': 'fa-plus', 'color': '#28a745'},



    'change_fournisseur':     {'label': 'Modifier', 'icon': 'fa-edit', 'color': '#ffc107'},



    'add_magasin':            {'label': 'Ajouter', 'icon': 'fa-plus', 'color': '#28a745'},



    'change_magasin':         {'label': 'Modifier', 'icon': 'fa-edit', 'color': '#ffc107'},



    'add_beneficiaire':       {'label': 'Ajouter', 'icon': 'fa-plus', 'color': '#28a745'},



    'change_beneficiaire':    {'label': 'Modifier', 'icon': 'fa-edit', 'color': '#ffc107'},



    'add_motifannulation':    {'label': 'Ajouter', 'icon': 'fa-plus', 'color': '#28a745'},



    'change_motifannulation': {'label': 'Modifier', 'icon': 'fa-edit', 'color': '#ffc107'},



    'add_service':            {'label': 'Ajouter', 'icon': 'fa-plus', 'color': '#28a745'},



    'change_service':         {'label': 'Modifier', 'icon': 'fa-edit', 'color': '#ffc107'},



    'add_demandemateriel':    {'label': 'Creer', 'icon': 'fa-plus', 'color': '#28a745'},



    'change_demandemateriel': {'label': 'Modifier / Traiter', 'icon': 'fa-edit', 'color': '#ffc107'},



    'delete_demandemateriel': {'label': 'Supprimer', 'icon': 'fa-trash', 'color': '#dc3545'},



    'add_livraisonpartielle': {'label': 'Creer livraisons', 'icon': 'fa-plus', 'color': '#28a745'},



    'change_livraisonpartielle': {'label': 'Modifier livraisons', 'icon': 'fa-edit', 'color': '#ffc107'},



    'add_specialite':         {'label': 'Ajouter', 'icon': 'fa-plus', 'color': '#28a745'},



    'change_specialite':      {'label': 'Modifier', 'icon': 'fa-edit', 'color': '#ffc107'},





    'add_ligneinventaire': {'label': 'Ajouter lignes inventaire', 'icon': 'fa-plus', 'color': '#28a745'},


    'change_ligneinventaire': {'label': 'Modifier lignes inventaire', 'icon': 'fa-edit', 'color': '#ffc107'},


    'delete_ajustement': {'label': 'Supprimer', 'icon': 'fa-trash', 'color': '#dc3545'},


    'add_accusereception': {'label': 'Creer accuses reception', 'icon': 'fa-plus', 'color': '#28a745'},


    'change_accusereception': {'label': 'Modifier accuses reception', 'icon': 'fa-edit', 'color': '#ffc107'},


    'delete_livraisonpartielle': {'label': 'Supprimer livraisons', 'icon': 'fa-trash', 'color': '#dc3545'},


    'delete_famillearticle': {'label': 'Supprimer familles', 'icon': 'fa-trash', 'color': '#dc3545'},


    'add_intervention': {'label': 'Creer intervention', 'icon': 'fa-plus', 'color': '#28a745'},


    'change_intervention': {'label': 'Modifier / Traiter', 'icon': 'fa-edit', 'color': '#ffc107'},


    'delete_intervention': {'label': 'Supprimer', 'icon': 'fa-trash', 'color': '#dc3545'},


    'add_technicienprestataire': {'label': 'Ajouter techniciens', 'icon': 'fa-plus', 'color': '#28a745'},


    'change_technicienprestataire': {'label': 'Modifier techniciens', 'icon': 'fa-edit', 'color': '#ffc107'},


    'add_immobilisation': {'label': 'Ajouter equipement', 'icon': 'fa-plus', 'color': '#28a745'},


    'change_immobilisation': {'label': 'Modifier equipement', 'icon': 'fa-edit', 'color': '#ffc107'},


    'delete_immobilisation': {'label': 'Supprimer', 'icon': 'fa-trash', 'color': '#dc3545'},


    'add_mouvementpatrimoine': {'label': 'Ajouter mouvement', 'icon': 'fa-plus', 'color': '#28a745'},


    'change_mouvementpatrimoine': {'label': 'Modifier mouvement', 'icon': 'fa-edit', 'color': '#ffc107'},


    'add_contratmaintenance': {'label': 'Ajouter contrat', 'icon': 'fa-plus', 'color': '#28a745'},


    'change_contratmaintenance': {'label': 'Modifier contrat', 'icon': 'fa-edit', 'color': '#ffc107'},


    'delete_contratmaintenance': {'label': 'Supprimer contrat', 'icon': 'fa-trash', 'color': '#dc3545'},


    'add_typecontrat': {'label': 'Ajouter type contrat', 'icon': 'fa-plus', 'color': '#28a745'},


    'change_typecontrat': {'label': 'Modifier type contrat', 'icon': 'fa-edit', 'color': '#ffc107'},


    'add_importpatrimoine': {'label': 'Importer', 'icon': 'fa-file-import', 'color': '#28a745'},


    'add_campagneinventairepatrimoine': {'label': 'Ajouter campagne', 'icon': 'fa-plus', 'color': '#28a745'},


    'change_campagneinventairepatrimoine': {'label': 'Modifier campagne', 'icon': 'fa-edit', 'color': '#ffc107'},


    'add_ligneinventairepatrimoine': {'label': 'Ajouter lignes comptage', 'icon': 'fa-plus', 'color': '#28a745'},


    'change_ligneinventairepatrimoine': {'label': 'Modifier lignes comptage', 'icon': 'fa-edit', 'color': '#ffc107'},


    'add_categoriepatrimoine': {'label': 'Ajouter categorie', 'icon': 'fa-plus', 'color': '#28a745'},


    'change_categoriepatrimoine': {'label': 'Modifier categorie', 'icon': 'fa-edit', 'color': '#ffc107'},


    'add_marque': {'label': 'Ajouter marque', 'icon': 'fa-plus', 'color': '#28a745'},


    'change_marque': {'label': 'Modifier marque', 'icon': 'fa-edit', 'color': '#ffc107'},


    'add_modele': {'label': 'Ajouter modele', 'icon': 'fa-plus', 'color': '#28a745'},


    'change_modele': {'label': 'Modifier modele', 'icon': 'fa-edit', 'color': '#ffc107'},


    'add_batiment': {'label': 'Ajouter batiment', 'icon': 'fa-plus', 'color': '#28a745'},


    'change_batiment': {'label': 'Modifier batiment', 'icon': 'fa-edit', 'color': '#ffc107'},


    'add_etage': {'label': 'Ajouter etage', 'icon': 'fa-plus', 'color': '#28a745'},


    'change_etage': {'label': 'Modifier etage', 'icon': 'fa-edit', 'color': '#ffc107'},


    'add_bureau': {'label': 'Ajouter bureau', 'icon': 'fa-plus', 'color': '#28a745'},


    'change_bureau': {'label': 'Modifier bureau', 'icon': 'fa-edit', 'color': '#ffc107'},


    'add_typeequipement': {'label': 'Ajouter type equipement', 'icon': 'fa-plus', 'color': '#28a745'},


    'change_typeequipement': {'label': 'Modifier type equipement', 'icon': 'fa-edit', 'color': '#ffc107'},


    'add_parametrespatrimoine': {'label': 'Ajouter parametres', 'icon': 'fa-plus', 'color': '#28a745'},


    'change_parametrespatrimoine': {'label': 'Modifier parametres', 'icon': 'fa-edit', 'color': '#ffc107'},


    'change_configurationhopital': {'label': 'Modifier configuration', 'icon': 'fa-edit', 'color': '#ffc107'},


    'delete_service': {'label': 'Supprimer', 'icon': 'fa-trash', 'color': '#dc3545'},


    'delete_specialite': {'label': 'Supprimer', 'icon': 'fa-trash', 'color': '#dc3545'},


    'add_fonction': {'label': 'Ajouter', 'icon': 'fa-plus', 'color': '#28a745'},


    'change_fonction': {'label': 'Modifier', 'icon': 'fa-edit', 'color': '#ffc107'},


    'delete_fonction': {'label': 'Supprimer', 'icon': 'fa-trash', 'color': '#dc3545'},


    'delete_fournisseur': {'label': 'Supprimer', 'icon': 'fa-trash', 'color': '#dc3545'},


    'delete_magasin': {'label': 'Supprimer', 'icon': 'fa-trash', 'color': '#dc3545'},


    'delete_motifannulation': {'label': 'Supprimer', 'icon': 'fa-trash', 'color': '#dc3545'},


    'delete_beneficiaire': {'label': 'Supprimer', 'icon': 'fa-trash', 'color': '#dc3545'},


    'can_configurer_modeles_pdf': {'label': 'Configurer modeles PDF', 'icon': 'fa-file-pdf', 'color': '#dc3545'},


    'add_modeledocumentmagasin': {'label': 'Ajouter modele PDF', 'icon': 'fa-plus', 'color': '#28a745'},


    'change_modeledocumentmagasin': {'label': 'Modifier modele PDF', 'icon': 'fa-edit', 'color': '#ffc107'},


    'add_configdocument': {'label': 'Ajouter document', 'icon': 'fa-plus', 'color': '#28a745'},


    'change_configdocument': {'label': 'Modifier document', 'icon': 'fa-edit', 'color': '#ffc107'},


    'delete_configdocument': {'label': 'Supprimer document', 'icon': 'fa-trash', 'color': '#dc3545'},


    'add_user': {'label': 'Creer utilisateur', 'icon': 'fa-plus', 'color': '#28a745'},


    'change_user': {'label': 'Modifier utilisateur', 'icon': 'fa-edit', 'color': '#ffc107'},


    'delete_user': {'label': 'Supprimer utilisateur', 'icon': 'fa-trash', 'color': '#dc3545'},


    'add_profil': {'label': 'Ajouter profil', 'icon': 'fa-plus', 'color': '#28a745'},


    'change_profil': {'label': 'Modifier profil', 'icon': 'fa-edit', 'color': '#ffc107'},


    'add_group': {'label': 'Creer role', 'icon': 'fa-plus', 'color': '#28a745'},


    'change_group': {'label': 'Modifier role', 'icon': 'fa-edit', 'color': '#ffc107'},


    'delete_group': {'label': 'Supprimer role', 'icon': 'fa-trash', 'color': '#dc3545'},


    'add_circuitvalidateur': {'label': 'Ajouter validateur', 'icon': 'fa-plus', 'color': '#28a745'},


    'change_circuitvalidateur': {'label': 'Modifier validateur', 'icon': 'fa-edit', 'color': '#ffc107'},


    'add_circuitvalidation': {'label': 'Ajouter circuit', 'icon': 'fa-plus', 'color': '#28a745'},


    'change_circuitvalidation': {'label': 'Modifier circuit', 'icon': 'fa-edit', 'color': '#ffc107'},


    'view_journalaudit': {'label': 'Consulter audit', 'icon': 'fa-eye', 'color': '#6c757d'},

    'menu_services': {'label': 'Services', 'icon': 'fa-hospital', 'color': '#28a745'},
    'menu_specialites': {'label': 'Specialites', 'icon': 'fa-user-md', 'color': '#17a2b8'},
    'menu_fonctions': {'label': 'Fonctions & Titres', 'icon': 'fa-user-tie', 'color': '#0d47a1'},
    'menu_fournisseurs': {'label': 'Fournisseurs', 'icon': 'fa-truck', 'color': '#fd7e14'},
    'menu_magasins': {'label': 'Magasins', 'icon': 'fa-store', 'color': '#ffc107'},
    'menu_motifs_annulation': {'label': 'Motifs Annulation', 'icon': 'fa-ban', 'color': '#dc3545'},
    'menu_beneficiaires': {'label': 'Beneficiaires', 'icon': 'fa-users', 'color': '#6f42c1'},
    'menu_parametres_doc': {'label': 'Documents PDF', 'icon': 'fa-file-invoice', 'color': '#dc3545'},
}







# ═══════════════════════════════════════════════════════════════════════════



# SYNCHRONISÉ avec base_ui.html (sidebar reel)



# ═══════════════════════════════════════════════════════════════════════════





MENU_ITEMS_META = {



    'menu_dashboard': {'label': 'Tableau de bord', 'icon': 'fa-tachometer-alt', 'color': '#1c5b96'},



    'menu_accueil': {'label': 'Accueil', 'icon': 'fa-home', 'color': '#17a2b8'},



    'menu_demandes': {'label': 'Mes Demandes', 'icon': 'fa-clipboard-list', 'color': '#17a2b8'},



    'menu_guichet': {'label': 'Traiter Demandes', 'icon': 'fa-desktop', 'color': '#6f42c1'},



    'menu_valider_demandes': {'label': 'Valider Demandes', 'icon': 'fa-check-circle', 'color': '#28a745'},



    'menu_entrees': {'label': 'Entrees Stock', 'icon': 'fa-arrow-down', 'color': '#28a745'},



    'menu_sorties': {'label': 'Bons de Sortie', 'icon': 'fa-arrow-up', 'color': '#dc3545'},



    'menu_retours_services': {'label': 'Retours Services', 'icon': 'fa-undo', 'color': '#20c997'},



    'menu_sorties_hors_stock': {'label': 'Sorties Hors Stock', 'icon': 'fa-external-link-alt', 'color': '#e83e8c'},



    'menu_stock': {'label': 'État du Stock', 'icon': 'fa-boxes', 'color': '#1c5b96'},



    'menu_peremptions': {'label': 'Peremptions', 'icon': 'fa-calendar-times', 'color': '#ffc107'},



    'menu_destructions': {'label': 'Destructions', 'icon': 'fa-trash-alt', 'color': '#dc3545'},



    'menu_ajustements': {'label': 'Ajustements', 'icon': 'fa-sliders-h', 'color': '#6f42c1'},



    'menu_inventaires': {'label': 'Inventaires', 'icon': 'fa-clipboard-check', 'color': '#28a745'},



    'menu_articles': {'label': 'Catalogue Articles', 'icon': 'fa-barcode', 'color': '#0d47a1'},



    'menu_familles': {'label': 'Familles', 'icon': 'fa-folder-open', 'color': '#fd7e14'},



    'menu_commandes': {'label': 'Commandes', 'icon': 'fa-shopping-cart', 'color': '#e83e8c'},



    'menu_reception_commande': {'label': 'Receptions', 'icon': 'fa-truck-loading', 'color': '#28a745'},



    'menu_livraisons': {'label': 'Livraisons', 'icon': 'fa-truck', 'color': '#fd7e14'},



    'menu_rapports': {'label': 'Rapports', 'icon': 'fa-chart-line', 'color': '#28a745'},



    'menu_historique': {'label': 'Historique', 'icon': 'fa-history', 'color': '#6c757d'},



    'menu_magasins': {'label': 'Magasins', 'icon': 'fa-store', 'color': '#ffc107'},



    'menu_fournisseurs': {'label': 'Fournisseurs', 'icon': 'fa-truck', 'color': '#fd7e14'},



    'menu_motifs_annulation': {'label': 'Motifs Annulation', 'icon': 'fa-ban', 'color': '#dc3545'},



    'menu_param_logistique': {'label': 'Param. Logistique', 'icon': 'fa-cogs', 'color': '#6c757d'},



    'menu_services': {'label': 'Services', 'icon': 'fa-hospital', 'color': '#28a745'},



    'menu_specialites': {'label': 'Specialites', 'icon': 'fa-user-md', 'color': '#17a2b8'},



    'menu_param_admin': {'label': 'Param. Admin', 'icon': 'fa-building', 'color': '#1c5b96'},



    'menu_parametres': {'label': 'Parametres Generaux', 'icon': 'fa-sliders-h', 'color': '#6c757d'},



    'menu_modeles_pdf': {'label': 'Modeles PDF', 'icon': 'fa-file-pdf', 'color': '#dc3545'},



    'menu_utilisateurs': {'label': 'Utilisateurs', 'icon': 'fa-users', 'color': '#1c5b96'},



    'menu_roles': {'label': 'Roles & Acces', 'icon': 'fa-user-shield', 'color': '#0d47a1'},



    'menu_circuits_validation': {'label': 'Circuits Validation', 'icon': 'fa-project-diagram', 'color': '#6f42c1'},



    'menu_journal_audit': {'label': 'Journal Audit', 'icon': 'fa-history', 'color': '#6c757d'},



    'menu_pat_tickets': {'label': 'Tickets SAV', 'icon': 'fa-ticket-alt', 'color': '#20c997'},



    'menu_pat_tech': {'label': 'Espace Tech', 'icon': 'fa-clipboard-list', 'color': '#6f42c1'},



    'menu_pat_dispatch': {'label': 'Dispatch Pannes', 'icon': 'fa-satellite-dish', 'color': '#fd7e14'},



    'menu_pat_historique': {'label': 'Historique Global', 'icon': 'fa-history', 'color': '#b6c2c9'},



    'menu_pat_registre': {'label': 'Registre Materiel', 'icon': 'fa-layer-group', 'color': '#1c5b96'},



    'menu_pat_sas': {'label': 'Sas Immatriculation', 'icon': 'fa-clock', 'color': '#ffc107'},



    'menu_pat_contrats': {'label': 'Contrats', 'icon': 'fa-file-contract', 'color': '#17a2b8'},



    'menu_pat_import': {'label': 'Import Excel', 'icon': 'fa-file-import', 'color': '#28a745'},



    'menu_pat_inventaire': {'label': 'Inventaire Parc', 'icon': 'fa-barcode', 'color': '#28a745'},



    'menu_pat_rebuts': {'label': 'Registre Rebuts', 'icon': 'fa-trash-alt', 'color': '#ef4444'},



    'menu_pat_pertes': {'label': 'Équipements Perdus', 'icon': 'fa-search-minus', 'color': '#f59e0b'},



    'menu_pat_parametres': {'label': 'Parametres Patrimoine', 'icon': 'fa-sliders-h', 'color': '#ffda6a'},



    



    # Permissions Patrimoine detaillees (pour la page Roles)



    'menu_pat_fiche_detail': {'label': 'Fiches Detaillees', 'icon': 'fa-file-alt', 'color': '#1c5b96'},



    'menu_pat_modifier_immo': {'label': 'Modifier Immobilisations', 'icon': 'fa-edit', 'color': '#ffc107'},



    'menu_pat_mouvements': {'label': 'Mouvements Patrimoine', 'icon': 'fa-exchange-alt', 'color': '#20c997'},



    'menu_pat_eclatement': {'label': 'Éclatement Biens', 'icon': 'fa-object-ungroup', 'color': '#fd7e14'},



    'menu_pat_immatriculation': {'label': 'Immatriculation Directe', 'icon': 'fa-id-card', 'color': '#17a2b8'},



    'menu_pat_qr_codes': {'label': 'Gestion QR Codes', 'icon': 'fa-qrcode', 'color': '#28a745'},



    'menu_pat_export_registre': {'label': 'Export Registre Excel', 'icon': 'fa-file-excel', 'color': '#28a745'},



    'menu_pat_contrat_detail': {'label': 'Detail Contrats', 'icon': 'fa-file-contract', 'color': '#17a2b8'},



    'menu_pat_assigner_equipements': {'label': 'Assigner Équipements', 'icon': 'fa-link', 'color': '#6f42c1'},



    'menu_pat_interventions': {'label': 'Interventions', 'icon': 'fa-tools', 'color': '#dc3545'},



    'menu_pat_intervention_detail': {'label': 'Detail Interventions', 'icon': 'fa-clipboard-list', 'color': '#20c997'},



    'menu_pat_signaler_panne': {'label': 'Signaler Panne', 'icon': 'fa-exclamation-triangle', 'color': '#dc3545'},



    'menu_pat_creer_intervention': {'label': 'Creer Intervention', 'icon': 'fa-plus-circle', 'color': '#28a745'},



    'menu_pat_valider_intervention': {'label': 'Valider Intervention', 'icon': 'fa-check-circle', 'color': '#28a745'},



    'menu_pat_portail_prestataire': {'label': 'Portail Prestataire', 'icon': 'fa-user-tie', 'color': '#6f42c1'},



    'menu_pat_schema_maintenance': {'label': 'Schemas Maintenance', 'icon': 'fa-project-diagram', 'color': '#1c5b96'},



    'menu_pat_types_equipements': {'label': "Types d'Équipements", 'icon': 'fa-cogs', 'color': '#6c757d'},



    'menu_pat_mes_tickets': {'label': 'Mes Tickets', 'icon': 'fa-ticket-alt', 'color': '#20c997'},



    'menu_pat_suivi_ticket': {'label': 'Suivi Ticket', 'icon': 'fa-hourglass-half', 'color': '#ffc107'},



    'menu_pat_bon_sortie_reparation': {'label': 'Bon Sortie Reparation', 'icon': 'fa-dolly', 'color': '#fd7e14'},



    'menu_pat_campagnes_inventaire': {'label': 'Campagnes Inventaire', 'icon': 'fa-calendar-check', 'color': '#28a745'},



    'menu_pat_detail_campagne': {'label': 'Detail Campagne', 'icon': 'fa-chart-pie', 'color': '#17a2b8'},



    'menu_pat_reconciliation': {'label': 'Reconciliation Inventaire', 'icon': 'fa-balance-scale', 'color': '#6f42c1'},



    'menu_pat_audit_scan': {'label': 'Audit Scan Inventaire', 'icon': 'fa-barcode', 'color': '#28a745'},



    'menu_pat_fiche_comptage': {'label': 'Fiche Comptage', 'icon': 'fa-clipboard-check', 'color': '#28a745'},







    'menu_stats_demandes': {'label': 'Stats Demandes', 'icon': 'fa-chart-bar', 'color': '#0d6efd'},



    'menu_stats_sondages': {'label': 'Stats Sondages', 'icon': 'fa-smile', 'color': '#198754'},



    'menu_stats_satisfaction': {'label': 'Stats Satisfaction', 'icon': 'fa-star-half-alt', 'color': '#6f42c1'},



    



    # Parametres manquants



    'menu_lots': {'label': 'Gestion des Lots', 'icon': 'fa-boxes', 'color': '#1c5b96'},



    'menu_beneficiaires': {'label': 'Beneficiaires', 'icon': 'fa-users', 'color': '#28a745'},



    'menu_fonctions': {'label': 'Fonctions & Titres', 'icon': 'fa-user-tie', 'color': '#17a2b8'},



    'menu_parametres_doc': {'label': 'Configuration Documents PDF', 'icon': 'fa-file-pdf', 'color': '#dc3545'},



    'menu_securite_mdp': {'label': 'Securite MDP', 'icon': 'fa-lock', 'color': '#dc3545'},



}







@login_required(login_url='/auth/login/')



@verifier_permission('accounts.menu_roles')



def page_roles(request):



    """Gestion des roles et permissions (mono-tenant)."""







    # ── Groupes ──



    groupes = Group.objects.prefetch_related('permissions').order_by('name')







    for groupe in groupes:



        groupe.users_count = User.objects.filter(groups=groupe).count()



        groupe.users_list = list(User.objects.filter(



            groups=groupe



        ).select_related('profil')[:4])



        groupe.users_more = max(0, groupe.users_count - 4)







    # ── Permissions MENU ──

    def _flatten_role_permissions(arch):
        """Aplatit la structure en liste simple de codenames."""
        result = []
        for value in arch.values():
            if isinstance(value, dict):
                for sublist in value.values():
                    result.extend(sublist)
            elif isinstance(value, list):
                result.extend(value)
        return result

    menu_codenames = _flatten_role_permissions(ROLE_ARCHITECTURE_MENU)







    # [MONO-TENANT] SOUS_PERMISSIONS et SOUS_PERM_LABELS deplaces au niveau module











    sous_codenames = [c for perms in SOUS_PERMISSIONS.values() for c in perms]



    all_codenames = list(set(menu_codenames + sous_codenames))







    # Recuperation en base — deduplication par codename (evite les doublons multi-ContentType)



    perms_qs = Permission.objects.filter(



        codename__in=all_codenames,



    ).order_by('codename', 'id')







    seen = set()



    perms_disponibles = []



    for p in perms_qs:



        if p.codename not in seen:



            seen.add(p.codename)



            perms_disponibles.append(p)







    perms_by_codename = {p.codename: p for p in perms_disponibles}







    # ── POST : Creation / Modif / Suppr ──



    if request.method == 'POST':



        action = request.POST.get('action', '')







        if not action and request.POST.get('enregistrer_role') == '1':



            role_id = request.POST.get('role_id', '').strip()



            nom = request.POST.get('libelle', '').strip().upper()



            perm_ids = request.POST.getlist('fonctionnalites')







            if not nom:



                messages.error(request, "⛔ Le libelle du role est obligatoire.")



                return redirect('accounts:page_roles')







            if role_id:

                try:
                    role_id = int(role_id)
                except (ValueError, TypeError):
                    messages.error(request, "⛔ Identifiant de role invalide.")
                    return redirect('accounts:page_roles')

                groupe = get_object_or_404(Group, id=role_id)

                # Contrôle de doublon au renommage (Group.name est unique)
                if Group.objects.filter(name__iexact=nom).exclude(pk=groupe.pk).exists():
                    messages.error(request, f"⛔ Le role '{nom}' existe deja.")
                    return redirect('accounts:page_roles')

                groupe.name = nom

                groupe.save()



                messages.success(request, f"✅ Role '{nom}' mis a jour.")



            else:



                if Group.objects.filter(name__iexact=nom).exists():



                    messages.error(request, f"⛔ Le role '{nom}' existe deja.")



                    return redirect('accounts:page_roles')



                groupe = Group.objects.create(name=nom)



                log_audit(request, f"Creation role {nom}", type_action='CREATE',



                          modele_concerne='Group', id_objet=groupe.id)



                messages.success(request, f"✅ Role '{nom}' cree.")







            if perm_ids:

                perms = Permission.objects.filter(id__in=perm_ids)

            else:

                perms = Permission.objects.none()


            groupe.permissions.set(perms)


            log_audit(request, f"Permissions mises a jour pour {nom}", type_action='PERMISSION',



                          modele_concerne='Group', id_objet=groupe.id)







            return redirect('accounts:page_roles')







        if action == 'supprimer':



            groupe_id = request.POST.get('groupe_id')



            groupe = get_object_or_404(Group, id=groupe_id)



            if User.objects.filter(groups=groupe).exists():



                messages.error(request, "⛔ Impossible : des utilisateurs sont attaches.")



            else:



                nom = groupe.name



                groupe.delete()



                log_audit(request, f"Suppression role {nom}", type_action='DELETE',



                          modele_concerne='Group')



                messages.success(request, f"🗑️ Role '{nom}' supprime.")



            return redirect('accounts:page_roles')







    context = {



        'groupes': groupes,



        'perms_disponibles': perms_disponibles,



        'perms_by_codename': perms_by_codename,



        'modules_permissions': ROLE_ARCHITECTURE_MENU,



        'sous_permissions_map': SOUS_PERMISSIONS,



        'sous_perm_labels': SOUS_PERM_LABELS,



        'menu_items_meta': MENU_ITEMS_META,



        'module_icons': MODULE_ICONS,



    }



    return render(request, 'accounts/roles.html', context)







# ==========================================================



# NOTIFICATIONS



# ==========================================================



@login_required(login_url='/auth/login/')



def mes_notifications(request):



    # CORRECTION : garder le QuerySet pour le count, puis slicer



    notifs_qs = Notification.objects.filter(utilisateur=request.user).order_by('-date_creation')



    notifs = list(notifs_qs[:50])



    non_lues_count = notifs_qs.filter(est_lue=False).count()



    return render(request, 'accounts/notifications.html', {



        'notifications': notifs,



        'non_lues_count': non_lues_count,



    })











@login_required(login_url='/auth/login/')



@require_POST



def marquer_notification_lue(request, notif_id):



    notif = get_object_or_404(Notification, id=notif_id, utilisateur=request.user)



    notif.marquer_lue()



    if request.headers.get('x-requested-with') == 'XMLHttpRequest':



        return JsonResponse({'success': True})



    return redirect('accounts:mes_notifications')











# ==========================================================



# JOURNAL D'AUDIT



# ==========================================================



@login_required(login_url='/auth/login/')



def journal_audit(request):



    """Journal d'audit securite (AuditConnexion + KPIs + panneau lateral)."""



    if not request.user.is_superuser and not request.user.has_perm('accounts.view_journalaudit'):



        if not request.user.has_perm('accounts.menu_journal_audit'):



            messages.error(request, "⛔ Acces reserve.")



            return redirect('accounts:accueil_personnalise')







    q = request.GET.get('q', '').strip()



    type_filtre = request.GET.get('type_filtre', '').strip()



    periode = request.GET.get('periode', '30').strip() or '30'



    date_debut = request.GET.get('date_debut', '').strip()



    date_fin = request.GET.get('date_fin', '').strip()







    qs = AuditConnexion.objects.select_related('utilisateur').order_by('-date_creation')







    # Periode



    now = timezone.now()



    periode_debut = None



    if periode == '7':



        periode_debut = now - timedelta(days=7)



        qs = qs.filter(date_creation__gte=periode_debut)



    elif periode == '30':



        periode_debut = now - timedelta(days=30)



        qs = qs.filter(date_creation__gte=periode_debut)



    elif periode == '90':



        periode_debut = now - timedelta(days=90)



        qs = qs.filter(date_creation__gte=periode_debut)



    elif periode == 'custom' or date_debut or date_fin:



        from datetime import datetime



        if date_debut:



            try:



                d = datetime.strptime(date_debut, '%Y-%m-%d').date()



                qs = qs.filter(date_creation__date__gte=d)



                if periode_debut is None or timezone.make_aware(datetime.combine(d, datetime.min.time())) < periode_debut:



                    periode_debut = timezone.make_aware(datetime.combine(d, datetime.min.time()))



            except ValueError:



                pass



        if date_fin:



            try:



                qs = qs.filter(date_creation__date__lte=datetime.strptime(date_fin, '%Y-%m-%d').date())



            except ValueError:



                pass



    # periode=all → pas de filtre date







    if type_filtre:



        qs = qs.filter(type_action=type_filtre)







    if q:



        qs = qs.filter(



            Q(description__icontains=q) |



            Q(utilisateur__username__icontains=q) |



            Q(utilisateur__first_name__icontains=q) |



            Q(utilisateur__last_name__icontains=q) |



            Q(adresse_ip__icontains=q)



        )







    # KPIs (sur le queryset filtre hors pagination)



    total_connexions = qs.filter(type_action='CONNEXION').count()



    total_echecs = qs.filter(type_action='ECHEC').count()



    total_admin = qs.filter(type_action='ADMIN').count()







    # Alertes simples



    alertes = []



    if total_echecs >= 5:



        alertes.append({



            'niveau': 'danger',



            'icone': 'fa-exclamation-triangle',



            'message': f"{total_echecs} echec(s) de connexion sur la periode selectionnee.",



        })



    elif total_echecs >= 1:



        alertes.append({



            'niveau': 'warning',



            'icone': 'fa-exclamation-circle',



            'message': f"{total_echecs} echec(s) de connexion detecte(s).",



        })







    # Export CSV



    if request.GET.get('export') == 'csv':



        import csv



        from django.http import HttpResponse



        response = HttpResponse(content_type='text/csv; charset=utf-8')



        response['Content-Disposition'] = 'attachment; filename="audit_securite.csv"'



        response.write('\ufeff')  # BOM Excel



        writer = csv.writer(response, delimiter=';')



        writer.writerow(['Date', 'Utilisateur', 'Type', 'Description', 'IP'])



        for evt in qs[:5000]:



            writer.writerow([



                evt.date_creation.strftime('%d/%m/%Y %H:%M:%S') if evt.date_creation else '',



                evt.utilisateur.username if evt.utilisateur else '',



                evt.type_action,



                evt.description or '',



                evt.adresse_ip or '',



            ])



        return response







    page_obj, per_page = paginer(qs, request, default=50)







    # ── Durees de session : associer CONNEXION → prochaine DECONNEXION ──



    def _fmt_duree(seconds):



        if seconds is None or seconds < 0:



            return '—'



        seconds = int(seconds)



        h, rem = divmod(seconds, 3600)



        m, s = divmod(rem, 60)



        if h:



            return f'{h}h {m:02d}min'



        if m:



            return f'{m} min'



        return f'{s} s'







    # CORRECTION [Perf] : limiter les deconnexions a la periode pertinente



    deco_qs = AuditConnexion.objects.filter(type_action='DECONNEXION', utilisateur_id__isnull=False)



    if periode_debut:



        deco_qs = deco_qs.filter(date_creation__gte=periode_debut - timedelta(days=1))



    deconnexions = list(deco_qs.order_by('date_creation').values('utilisateur_id', 'date_creation'))



    deco_by_user = {}



    for d in deconnexions:



        deco_by_user.setdefault(d['utilisateur_id'], []).append(d['date_creation'])







    evenements = list(page_obj.object_list)



    for evt in evenements:



        evt.duree_display = '—'



        evt.duree_en_cours = False



        if evt.type_action != 'CONNEXION' or not evt.utilisateur_id:



            continue



        dates = deco_by_user.get(evt.utilisateur_id, [])



        fin = None



        for d in dates:



            if d > evt.date_creation:



                fin = d



                break



        if fin is None:



            evt.duree_display = 'en cours'



            evt.duree_en_cours = True



        else:



            delta = (fin - evt.date_creation).total_seconds()



            evt.duree_display = _fmt_duree(delta)







    # ═══════════════════════════════════════════════════════════════════



    # PANNEAU LATÉRAL — donnees reelles (optimisees)



    # ═══════════════════════════════════════════════════════════════════







    # Source de verite unique : sessions Django actives



    sessions_actives_qs = Session.objects.filter(expire_date__gt=now)



    user_ids_actifs = set()



    for s in sessions_actives_qs:



        try:



            data = s.get_decoded()



            uid = data.get('_auth_user_id')



            if uid:



                user_ids_actifs.add(int(uid))



        except Exception:



            continue



    utilisateurs_actifs = len(user_ids_actifs)







    # 1. TOP UTILISATEURS (par nombre de connexions sur la periode) — CORRECTION N+1



    top_qs = (



        qs.filter(type_action='CONNEXION', utilisateur__isnull=False)



        .values('utilisateur')



        .annotate(nb=Count('id'))



        .order_by('-nb')[:5]



    )



    user_ids_top = [item['utilisateur'] for item in top_qs]



    users_map = User.objects.in_bulk(user_ids_top)



    top_utilisateurs = []



    for item in top_qs:



        user = users_map.get(item['utilisateur'])



        if user:



            top_utilisateurs.append((user, f"{item['nb']} connexion(s)"))







    # 2. SESSIONS OUVERTES — CORRECTION N+1



    last_conn_map = {}



    for c in AuditConnexion.objects.filter(



        utilisateur_id__in=list(user_ids_actifs),



        type_action='CONNEXION'



    ).order_by('-date_creation').values('utilisateur_id', 'date_creation'):



        if c['utilisateur_id'] not in last_conn_map:



            last_conn_map[c['utilisateur_id']] = c['date_creation']







    sessions_ouvertes = []



    for uid in sorted(user_ids_actifs):



        user = users_map.get(uid) or User.objects.filter(id=uid, is_active=True).first()



        if not user:



            continue



        last_conn = last_conn_map.get(uid)



        if last_conn:



            duree_sec = (now - last_conn).total_seconds()



            sessions_ouvertes.append({



                'utilisateur': user,



                'derniere_connexion': last_conn,



                'duree': _fmt_duree(duree_sec),



            })



        else:



            sessions_ouvertes.append({



                'utilisateur': user,



                'derniere_connexion': None,



                'duree': '—',



            })



        if len(sessions_ouvertes) >= 15:



            break







    # 3. DERNIÈRES SESSIONS TERMINÉES — CORRECTION N+1



    connexions_recentes = list(



        AuditConnexion.objects



        .select_related('utilisateur')



        .filter(type_action='CONNEXION', utilisateur__isnull=False)



        .order_by('-date_creation')[:100]



    )



    user_ids_conn = list({c.utilisateur_id for c in connexions_recentes})



    # Precharger les deconnexions pour ces utilisateurs



    deconnexions_recentes = list(



        AuditConnexion.objects



        .filter(utilisateur_id__in=user_ids_conn, type_action='DECONNEXION')



        .order_by('date_creation')



        .values('utilisateur_id', 'date_creation')



    )



    deco_map = {}



    for d in deconnexions_recentes:



        deco_map.setdefault(d['utilisateur_id'], []).append(d['date_creation'])







    sessions = []



    for c in connexions_recentes:



        dates = deco_map.get(c.utilisateur_id, [])



        fin = None



        for d in dates:



            if d > c.date_creation:



                fin = d



                break



        if fin:



            sessions.append({



                'utilisateur': c.utilisateur,



                'debut': c.date_creation,



                'fin': fin,



                'duree_str': _fmt_duree((fin - c.date_creation).total_seconds()),



            })



        if len(sessions) >= 10:



            break







    # 4. LOG ENTRIES ADMIN DJANGO



    log_entries = list(



        LogEntry.objects



        .select_related('user')



        .order_by('-action_time')[:20]



    )







    return render(request, 'accounts/audit.html', {



        'page_obj': page_obj,



        'evenements': evenements,



        'q': q,



        'type_filtre': type_filtre,



        'periode': periode,



        'date_debut': date_debut,



        'date_fin': date_fin,



        'total_connexions': total_connexions,



        'total_echecs': total_echecs,



        'total_admin': total_admin,



        'utilisateurs_actifs': utilisateurs_actifs,



        'alertes': alertes,



        'top_utilisateurs': top_utilisateurs,



        'sessions_ouvertes': sessions_ouvertes,



        'sessions': sessions,



        'log_entries': log_entries,



        'per_page': per_page,



    })











# ==========================================================



# THÈME



# ==========================================================



@login_required



def save_theme_preference(request):



    """Sauvegarde la preference de theme (light/dark)."""



    if request.method != 'POST':



        return JsonResponse({'error': 'Methode non autorisee'}, status=405)



    try:



        data = json.loads(request.body)



    except (json.JSONDecodeError, ValueError) as e:



        return JsonResponse({'error': 'JSON invalide'}, status=400)







    theme = data.get('theme', 'light')



    if theme not in ('light', 'dark'):



        return JsonResponse({'error': 'Theme invalide'}, status=400)







    try:



        profil = request.user.profil



    except Profil.DoesNotExist:



        profil = Profil.objects.create(user=request.user)







    profil.theme_preference = theme



    profil.save(update_fields=['theme_preference'])



    response = JsonResponse({'success': True, 'theme': theme})



    response.set_cookie('theme_pref', theme, max_age=30*24*60*60, httponly=False, samesite='Lax')



    return response











# ==========================================================



# STUBS (anciennes pages multi-tenant)



# ==========================================================



@login_required(login_url='/auth/login/')




































@login_required(login_url='/auth/login/')



@verifier_permission('accounts.menu_utilisateurs')



def parametres_securite(request):



    """Configuration de la politique de mots de passe (ALEATOIRE / FIXE)."""



    config = ConfigSecurite.get_solo()







    if request.method == 'POST':



        mode = request.POST.get('type_mot_de_passe', 'ALEATOIRE')



        mdp_fixe = request.POST.get('mot_de_passe_defaut', '').strip()







        if mode not in ('ALEATOIRE', 'FIXE'):



            messages.error(request, "⛔ Mode invalide.")



            return redirect('accounts:parametres_securite')







        if mode == 'FIXE':



            if not mdp_fixe:



                messages.error(request, "⛔ Le mot de passe par defaut est obligatoire en mode fixe.")



                return redirect('accounts:parametres_securite')



            erreurs = valider_mot_de_passe(mdp_fixe, contexte='default')



            if erreurs:



                messages.error(



                    request,



                    "❌ Mot de passe par defaut invalide : " + ", ".join(erreurs) + "."



                )



                return redirect('accounts:parametres_securite')







        config.type_mot_de_passe = mode



        config.mot_de_passe_defaut = mdp_fixe if mode == 'FIXE' else ''



        config.save()







        log_audit(



            request,



            f"Config securite : mode={mode}",



            type_action='UPDATE',



            modele_concerne='ConfigSecurite',



            id_objet=1,



        )



        messages.success(request, "✅ Parametres de securite enregistres.")



        return redirect('accounts:parametres_securite')







    return render(request, 'accounts/parametres_securite.html', {



        'config': config,



    })











# ==========================================================



# SIGNATURE



# ==========================================================



@login_required(login_url='/auth/login/')



def enregistrer_signature(request):



    """Enregistrer / mettre a jour la signature numerique du profil."""



    try:



        profil = request.user.profil



    except Profil.DoesNotExist:



        profil = Profil.objects.create(user=request.user)







    if request.method == 'POST':



        signature = request.FILES.get('signature')



        if signature:



            # CORRECTION : verification MIME



            if signature.content_type not in ('image/jpeg', 'image/png'):



                messages.error(request, "⛔ Seuls les formats JPG et PNG sont acceptes.")



                return redirect('accounts:profil_utilisateur')



            if signature.size > 2 * 1024 * 1024:



                messages.error(request, "⛔ La signature ne doit pas depasser 2 Mo.")



                return redirect('accounts:profil_utilisateur')



            profil.signature = signature



            profil.a_signature = True



            profil.save(update_fields=['signature', 'a_signature'])



            messages.success(request, "✅ Signature enregistree.")



        else:



            messages.error(request, "⛔ Aucun fichier signature fourni.")



        return redirect('accounts:profil_utilisateur')











# ==========================================================



# CIRCUITS DE VALIDATION



# ==========================================================



@login_required(login_url='/auth/login/')



@verifier_permission('accounts.menu_circuits_validation')



def circuits_validation(request):



    """Liste + mise a jour inline des circuits de validation (mono-tenant)."""



    from stock.models import CircuitValidation, CircuitValidateur







    if request.method == 'POST':



        try:



            circuit_id = int(request.POST.get('circuit_id', ''))



        except (ValueError, TypeError):



            messages.error(request, "⛔ Identifiant de circuit invalide.")



            return redirect('accounts:circuits_validation')







        circuit = get_object_or_404(CircuitValidation, pk=circuit_id, is_deleted=False)



        circuit.est_actif = request.POST.get('est_actif') == 'on'



        circuit.save(update_fields=['est_actif'])







        valideur_ids = request.POST.getlist('valideurs')



        if not valideur_ids:



            messages.warning(request, "⚠️ Aucun validateur selectionne — le circuit est vide.")







        try:



            with transaction.atomic():



                CircuitValidateur.objects.filter(circuit=circuit).delete()



                for i, vid in enumerate(valideur_ids, start=1):



                    try:



                        vid_int = int(vid)



                        if vid_int <= 0:



                            continue



                        CircuitValidateur.objects.create(



                            circuit=circuit,



                            valideur_id=vid_int,



                            ordre=i,



                        )



                    except (ValueError, TypeError):



                        raise ValueError(f"ID validateur invalide : {vid}")



        except ValueError as e:



            messages.error(request, f"❌ {e}")



            return redirect('accounts:circuits_validation')



        except Exception:



            messages.error(request, "❌ Erreur lors de la mise a jour du circuit.")



            return redirect('accounts:circuits_validation')







        log_audit(



            request,



            f"Circuit validation mis a jour : {getattr(circuit, 'type_document', circuit_id)}",



            type_action='UPDATE',



            modele_concerne='CircuitValidation',



            id_objet=circuit.id,



        )



        messages.success(request, "✅ Circuit mis a jour.")



        return redirect('accounts:circuits_validation')







    circuits = (



        CircuitValidation.objects



        .filter(is_deleted=False)



        .prefetch_related('validateurs', 'validateurs__valideur')



        .order_by('type_document')



    )



    utilisateurs = User.objects.filter(is_active=True).order_by('last_name', 'first_name')



    return render(request, 'accounts/circuits_validation.html', {



        'circuits': circuits,



        'utilisateurs': utilisateurs,



    })











@login_required(login_url='/auth/login/')



@verifier_permission('accounts.menu_circuits_validation')



def creer_circuit(request):



    """Creer un circuit de validation."""



    from stock.models import CircuitValidation, CircuitValidateur







    if request.method == 'POST':



        type_doc = (request.POST.get('type_document') or '').strip()



        est_actif = request.POST.get('est_actif') == 'on'



        valideur_ids = request.POST.getlist('valideurs')







        type_choices = getattr(CircuitValidation, 'TYPE_DOC_CHOICES', [])



        type_codes = [code for code, label in type_choices]



        if not type_doc or type_doc not in type_codes:



            messages.error(request, "⛔ Type de document invalide.")



            return redirect('accounts:creer_circuit')







        try:



            with transaction.atomic():



                circuit = CircuitValidation.objects.create(



                    type_document=type_doc,



                    est_actif=est_actif,



                )



                for i, vid in enumerate(valideur_ids, start=1):



                    try:



                        vid_int = int(vid)



                        if vid_int <= 0:



                            continue



                        CircuitValidateur.objects.create(



                            circuit=circuit,



                            valideur_id=vid_int,



                            ordre=i,



                        )



                    except (ValueError, TypeError):



                        raise ValueError(f"ID validateur invalide : {vid}")



                messages.success(request, "✅ Circuit de validation cree.")



                return redirect('accounts:circuits_validation')



        except ValueError as e:



            messages.error(request, f"❌ {e}")



        except Exception:



            messages.error(request, "❌ Erreur lors de la creation du circuit.")







    from stock.models import CircuitValidation



    return render(request, 'accounts/creer_circuit.html', {



        'type_choices': getattr(CircuitValidation, 'TYPE_DOC_CHOICES', []),



        'users': User.objects.filter(is_active=True).order_by('last_name', 'first_name'),



    })











@login_required(login_url='/auth/login/')



@verifier_permission('accounts.menu_circuits_validation')



def modifier_circuit(request, circuit_id):



    """Modifier un circuit de validation."""



    from stock.models import CircuitValidation, CircuitValidateur







    circuit = get_object_or_404(CircuitValidation, pk=circuit_id, is_deleted=False)







    if request.method == 'POST':



        try:



            with transaction.atomic():



                circuit.est_actif = request.POST.get('est_actif') == 'on'



                circuit.save()



                CircuitValidateur.objects.filter(circuit=circuit).delete()



                for i, vid in enumerate(request.POST.getlist('valideurs'), start=1):



                    try:



                        vid_int = int(vid)



                        if vid_int <= 0:



                            continue



                        CircuitValidateur.objects.create(



                            circuit=circuit,



                            valideur_id=vid_int,



                            ordre=i,



                        )



                    except (ValueError, TypeError):



                        raise ValueError(f"ID validateur invalide : {vid}")



            messages.success(request, "✅ Circuit modifie.")



        except ValueError as e:



            messages.error(request, f"❌ {e}")



        except Exception:



            messages.error(request, "❌ Erreur lors de la modification du circuit.")



        return redirect('accounts:circuits_validation')







    return render(request, 'accounts/modifier_circuit.html', {



        'circuit': circuit,



        'type_choices': getattr(CircuitValidation, 'TYPE_DOC_CHOICES', []),



        'users': User.objects.filter(is_active=True).order_by('last_name', 'first_name'),



        'valideurs_actuels': circuit.validateurs.all(),



    })