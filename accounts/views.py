# accounts/views.py — MONO-TENANT (corrigé)
import json
import logging
from datetime import timedelta

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.models import User, Group, Permission
from django.contrib.auth import login, logout, update_session_auth_hash
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

from core.models import ConfigurationHopital, Service
from .models import (
    Profil, Specialite, Notification, JournalAudit, Fonction, AuditConnexion,
    ConfigSecurite,
)
from .permissions import verifier_permission
from .utils import valider_mot_de_passe, generer_mot_de_passe_aleatoire
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
    x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded:
        return x_forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


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
    }


# ==========================================================
# CONNEXION / DÉCONNEXION
# ==========================================================
def custom_login(request):
    """Connexion mono-tenant."""
    if request.user.is_authenticated:
        return redirect('accounts:accueil_personnalise')

    if request.method == 'POST':
        username = request.POST.get('username', '').lower().strip().replace(' ', '')
        password = request.POST.get('password', '')

        # Nettoyer ancien format username@entreprise
        if '@' in username:
            username = username.split('@', 1)[0]

        user = User.objects.filter(username__iexact=username, is_active=True).first()

        # DEBUG — a supprimer en production
        if user:
            logger.info(f"[LOGIN] username={username!r} check={user.check_password(password)} active={user.is_active}")
        else:
            logger.info(f"[LOGIN] username={username!r} => aucun user trouve")

        if user and user.check_password(password):
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')

            # Force changement MDP premiere connexion
            try:
                profil = user.profil
                if profil.doit_changer_mdp:
                    request.session['must_change_password'] = True
                    messages.warning(request, "🔒 Vous devez changer votre mot de passe avant de continuer.")
                    return redirect('accounts:changer_mdp_obligatoire')
            except Exception:
                pass

            log_audit(request, f"Connexion de {user.username}", type_action='LOGIN')
            try:
                AuditConnexion.objects.create(
                    utilisateur=user,
                    type_action='CONNEXION',
                    description=f"Connexion réussie de {user.username}",
                    adresse_ip=get_client_ip(request),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
                )
            except Exception:
                pass
            messages.success(request, f"✅ Bienvenue {user.get_full_name() or user.username} !")

            next_url = request.POST.get('next') or request.GET.get('next')
            if next_url and url_has_allowed_host_and_scheme(next_url, allowed_hosts={request.get_host()}):
                return redirect(next_url)
            return redirect('accounts:accueil_personnalise')
        else:
            messages.error(request, "⛔ Identifiants incorrects ou compte désactivé.")
            try:
                AuditConnexion.objects.create(
                    type_action='ECHEC',
                    description=f"Tentative échouée pour {username}",
                    adresse_ip=get_client_ip(request),
                    user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
                )
            except Exception:
                pass

    return render(request, 'accounts/login.html')


def custom_logout(request):
    if request.user.is_authenticated:
        log_audit(request, f"Déconnexion de {request.user.username}", type_action='LOGOUT')
        try:
            AuditConnexion.objects.create(
                utilisateur=request.user,
                type_action='DECONNEXION',
                description=f"Déconnexion de {request.user.username}",
                adresse_ip=get_client_ip(request),
                user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
            )
        except Exception:
            pass
    logout(request)
    messages.success(request, "👋 Vous avez été déconnecté.")
    return redirect('accounts:custom_login')


@login_required(login_url='/auth/login/')
def changer_mdp_obligatoire(request):
    """Force le changement de mot de passe à la première connexion."""
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

        # CORRECTION : vérification de l'ancien MDP est OBLIGATOIRE
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
        messages.success(request, "✅ Mot de passe changé avec succès !")
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
        'menu_entrees':         {'url': '/entrees/', 'icon': 'fa-arrow-down', 'color': '#28a745', 'label': 'Entrées Stock'},
        'menu_reception_commande': {'url': '/receptions/', 'icon': 'fa-truck-loading', 'color': '#28a745', 'label': 'Réceptions'},
        'menu_sorties':         {'url': '/sorties/', 'icon': 'fa-arrow-up', 'color': '#dc3545', 'label': 'Bons de Sortie'},
        'menu_livraisons':      {'url': '/livraisons/', 'icon': 'fa-truck', 'color': '#fd7e14', 'label': 'Livraisons'},
        'menu_sorties_hors_stock': {'url': '/bons/hors-stock/', 'icon': 'fa-external-link-alt', 'color': '#e83e8c', 'label': 'Sorties Hors Stock'},
        'menu_retours_services': {'url': '/stock/retours-services/', 'icon': 'fa-undo', 'color': '#20c997', 'label': 'Retours Services'},
        'menu_stock':           {'url': '/etat-stock/', 'icon': 'fa-boxes', 'color': '#1c5b96', 'label': 'État du Stock'},
        'menu_peremptions':     {'url': '/stock/peremptions/', 'icon': 'fa-calendar-times', 'color': '#ffc107', 'label': 'Péremptions'},
        'menu_articles':        {'url': '/articles/', 'icon': 'fa-barcode', 'color': '#0d47a1', 'label': 'Catalogue Articles'},
        'menu_familles':        {'url': '/familles/', 'icon': 'fa-folder-open', 'color': '#fd7e14', 'label': 'Familles'},
        'menu_commandes':       {'url': '/commandes/', 'icon': 'fa-shopping-cart', 'color': '#e83e8c', 'label': 'Commandes'},
        'menu_rapports':        {'url': '/rapports/', 'icon': 'fa-chart-line', 'color': '#28a745', 'label': 'Rapports'},
        'menu_utilisateurs':    {'url': '/auth/utilisateurs/', 'icon': 'fa-users', 'color': '#1c5b96', 'label': 'Utilisateurs'},
        'menu_roles':           {'url': '/auth/roles/', 'icon': 'fa-user-shield', 'color': '#0d47a1', 'label': 'Rôles & Accès'},
        'menu_param_admin':     {'url': '/parametres/administratifs/', 'icon': 'fa-building', 'color': '#1c5b96', 'label': 'Paramètres Admin'},
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
        messages.warning(request, "⚠️ Profil créé automatiquement.")

    onglet = request.GET.get('onglet', 'infos')

    if request.method == 'POST':
        action = request.POST.get('action', '')

        if action == 'photo':
            photo = request.FILES.get('photo')
            if photo:
                # CORRECTION : vérification MIME
                if photo.content_type not in ('image/jpeg', 'image/png'):
                    messages.error(request, "⛔ Seuls les formats JPG et PNG sont acceptés.")
                    return redirect(f'{request.path}?onglet=infos')
                if photo.size > 2 * 1024 * 1024:
                    messages.error(request, "⛔ L'image ne doit pas dépasser 2 Mo.")
                    return redirect(f'{request.path}?onglet=infos')
                profil.photo = photo
                profil.nb_changements_photo = getattr(profil, 'nb_changements_photo', 0) + 1
                profil.date_derniere_photo = timezone.now()
                profil.save()
                messages.success(request, "✅ Photo mise à jour.")
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
                    update_session_auth_hash(request, request.user)  # CORRECTION : ne pas déconnecter
                    log_audit(request, "Changement mot de passe profil", type_action='UPDATE',
                              modele_concerne='User', id_objet=request.user.id)
                    messages.success(request, "✅ Mot de passe modifié.")
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
            log_audit(request, "Mise à jour profil", type_action='UPDATE',
                      modele_concerne='Profil', id_objet=profil.id)
            messages.success(request, "✅ Profil mis à jour.")
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
            # CORRECTION : conversion sécurisée de l'ID
            try:
                uid = int(request.POST.get('user_id', ''))
            except (ValueError, TypeError):
                messages.error(request, "⛔ Identifiant utilisateur invalide.")
                return redirect('accounts:page_utilisateurs')
            user = get_object_or_404(User, id=uid)
            if user == request.user:
                messages.error(request, "❌ Vous ne pouvez pas vous désactiver.")
            else:
                user.is_active = not user.is_active
                user.save()
                messages.success(request, f"{'Activé' if user.is_active else 'Désactivé'} : {user.username}")
            return redirect('accounts:page_utilisateurs')

        if request.POST.get('enregistrer_user') == '1':
            user_id = request.POST.get('user_id')
            # NOTE : les uploads photo/signature ne sont PAS gérés ici.
            # Ils doivent être modifiés via le profil utilisateur.
            # Normalisation format champs
            first_name = request.POST.get('first_name', '').strip().title()
            last_name = request.POST.get('last_name', '').strip().upper()
            email = request.POST.get('email', '').strip().lower()
            contact_raw = request.POST.get('contact', '').strip()
            contact = ''.join(c for c in contact_raw if c.isdigit())  # stocke chiffres seuls
            if contact and len(contact) != 10:
                err = "⛔ Le numéro de téléphone doit contenir exactement 10 chiffres."
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
                return render(request, 'accounts/utilisateurs.html',
                              _ctx_utilisateurs(request, page_obj, q, statut, form_data_tmp, show_modal=True, form_error=err))
            # Affichage formaté XX XX XX XX XX pour form_data
            contact_display = ' '.join(contact[i:i+2] for i in range(0, len(contact), 2)) if contact else ''
            groupe_id = request.POST.get('groupe')
            service_id = request.POST.get('service')
            specialite_id = request.POST.get('specialite')
            fonction_id = request.POST.get('fonction')
            magasin_ids = request.POST.getlist('magasins')

            # Données du formulaire pour pré-remplissage en cas d'erreur
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
                    err = f"⛔ Le login doit contenir au moins {MIN_USERNAME_LENGTH} caractères."
                    return render(request, 'accounts/utilisateurs.html',
                                  _ctx_utilisateurs(request, page_obj, q, statut, form_data, show_modal=True, form_error=err))

                # Vérification doublon username
                if User.objects.filter(username__iexact=username).exists():
                    err = f"⛔ Le nom d'utilisateur '{username}' est déjà utilisé par un autre compte."
                    return render(request, 'accounts/utilisateurs.html',
                                  _ctx_utilisateurs(request, page_obj, q, statut, form_data, show_modal=True, form_error=err))

                # Email : format @ obligatoire si renseigné
                if email and '@' not in email:
                    err = "⛔ L'adresse email doit contenir un @ (ex: nom@domaine.com)."
                    return render(request, 'accounts/utilisateurs.html',
                                  _ctx_utilisateurs(request, page_obj, q, statut, form_data, show_modal=True, form_error=err))

                # Vérification doublon email (si renseigné)
                if email:
                    if User.objects.filter(email__iexact=email).exists():
                        err = f"⛔ L'adresse email '{email}' est déjà associée à un autre compte."
                        return render(request, 'accounts/utilisateurs.html',
                                      _ctx_utilisateurs(request, page_obj, q, statut, form_data, show_modal=True, form_error=err))

                # Vérification doublon contact / téléphone (si renseigné)
                # CORRECTION : chercher dans plusieurs formats pour compatibilité
                if contact:
                    contact_variants = [contact]
                    contact_variants.append(' '.join(contact[i:i+2] for i in range(0, len(contact), 2)))
                    if Profil.objects.filter(contact__in=contact_variants).exists():
                        err = f"⛔ Le numéro de téléphone '{contact}' est déjà associé à un autre compte."
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

                # MDP temporaire affiché une seule fois (modale new_credentials)
                request.session['new_user_credentials'] = {
                    'username': username,
                    'password': password,
                    'full_name': (f"{last_name} {first_name}").strip() or username,
                }
                messages.success(request, f"✅ Utilisateur '{username}' créé.")

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

            if user_id:
                log_audit(request, f"Mise à jour utilisateur {user.username}", type_action='UPDATE',
                          modele_concerne='User', id_objet=user.id)
                messages.success(request, f"✅ {user.username} mis à jour.")
            else:
                log_audit(request, f"Création utilisateur {user.username}", type_action='CREATE',
                          modele_concerne='User', id_objet=user.id)
            return redirect('accounts:page_utilisateurs')

    new_credentials = request.session.pop('new_user_credentials', None)
    ctx = _ctx_utilisateurs(request, page_obj, q, statut)
    ctx['new_credentials'] = new_credentials
    return render(request, 'accounts/utilisateurs.html', ctx)


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_utilisateurs')
def reinitialiser_mdp(request, user_id):
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
                log_audit(request, f"Réinitialisation mdp {user.username}", type_action='UPDATE',
                          modele_concerne='User', id_objet=user.id)
                messages.success(request, f"✅ Mot de passe de {user.username} réinitialisé.")
                return redirect('accounts:page_utilisateurs')
    return render(request, 'accounts/reinitialiser_mdp.html', {'utilisateur': user})


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_utilisateurs')
def api_verifier_champ_utilisateur(request):
    """
    Vérifie en AJAX la disponibilité d'un login / email / téléphone.
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
                'message': f"Le login doit contenir au moins {MIN_USERNAME_LENGTH} caractères.",
            })
        qs = User.objects.filter(username__iexact=value)
        if qs_exclude:
            qs = qs.exclude(**qs_exclude)
        if qs.exists():
            return JsonResponse({
                'ok': True, 'available': False,
                'message': "Ce login est déjà utilisé — choisissez-en un autre.",
            })
        return JsonResponse({'ok': True, 'available': True, 'message': 'Login disponible.'})

    if champ == 'email':
        value = value.lower()
        if '@' not in value:
            return JsonResponse({
                'ok': True, 'available': False,
                'message': "L'email doit contenir un @ (ex: nom@domaine.com).",
            })
        qs = User.objects.filter(email__iexact=value).exclude(email='')
        if qs_exclude:
            qs = qs.exclude(**qs_exclude)
        if qs.exists():
            return JsonResponse({
                'ok': True, 'available': False,
                'message': "Cet email est déjà associé à un autre compte.",
            })
        return JsonResponse({'ok': True, 'available': True, 'message': 'Email disponible.'})

    if champ == 'contact':
        digits = ''.join(c for c in value if c.isdigit())
        if digits and len(digits) != 10:
            return JsonResponse({
                'ok': True, 'available': False,
                'message': "Le numéro doit contenir exactement 10 chiffres.",
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
                'message': "Ce numéro est déjà associé à un autre compte.",
            })
        return JsonResponse({'ok': True, 'available': True, 'message': 'Numéro disponible.'})

    return JsonResponse({'ok': False, 'error': 'Type invalide'}, status=400)


# ==========================================================
# RÔLES & PERMISSIONS
# ==========================================================
SOUS_PERMISSIONS = {
    'menu_entrees':            ['can_add_bon_entree', 'can_change_bon_entree', 'can_delete_bon_entree'],
    'menu_sorties':            ['can_add_bon_sortie', 'can_change_bon_sortie', 'can_delete_bon_sortie'],
    'menu_retours_services':   ['can_add_bon_retour', 'can_change_bon_retour', 'can_delete_bon_retour'],
    'menu_sorties_hors_stock': ['can_add_bon_hors_stock', 'can_change_bon_hors_stock', 'can_delete_bon_hors_stock'],
    'menu_commandes':          ['add_commande', 'change_commande', 'delete_commande'],
    'menu_reception_commande': ['change_commande'],
    'menu_ajustements':        ['add_ajustement', 'change_ajustement'],
    'menu_inventaires':        ['add_campagneinventaire', 'change_campagneinventaire'],
    'menu_articles':           ['add_article', 'change_article', 'delete_article'],
    'menu_familles':           ['add_famillearticle', 'change_famillearticle'],
    'menu_fournisseurs':       ['add_fournisseur', 'change_fournisseur'],
    'menu_magasins':           ['add_magasin', 'change_magasin'],
    'menu_beneficiaires':      ['add_beneficiaire', 'change_beneficiaire'],
    'menu_motifs_annulation':  ['add_motifannulation', 'change_motifannulation'],
    'menu_services':           ['add_service', 'change_service'],
    'menu_demandes':           ['add_demandemateriel', 'change_demandemateriel', 'delete_demandemateriel'],
    'menu_guichet':            ['change_demandemateriel', 'add_livraisonpartielle', 'change_livraisonpartielle'],
    'menu_livraisons':         ['change_livraisonpartielle'],
    'menu_specialites':        ['add_specialite', 'change_specialite'],
}

SOUS_PERM_LABELS = {
    'can_add_bon_entree':       {'label': 'Créer', 'icon': 'fa-plus', 'color': '#28a745'},
    'can_change_bon_entree':    {'label': 'Modifier / Annuler', 'icon': 'fa-edit', 'color': '#ffc107'},
    'can_delete_bon_entree':    {'label': 'Supprimer', 'icon': 'fa-trash', 'color': '#dc3545'},
    'can_add_bon_sortie':       {'label': 'Créer', 'icon': 'fa-plus', 'color': '#28a745'},
    'can_change_bon_sortie':    {'label': 'Modifier / Annuler', 'icon': 'fa-edit', 'color': '#ffc107'},
    'can_delete_bon_sortie':    {'label': 'Supprimer', 'icon': 'fa-trash', 'color': '#dc3545'},
    'can_add_bon_retour':       {'label': 'Créer', 'icon': 'fa-plus', 'color': '#28a745'},
    'can_change_bon_retour':    {'label': 'Modifier / Annuler', 'icon': 'fa-edit', 'color': '#ffc107'},
    'can_delete_bon_retour':    {'label': 'Supprimer', 'icon': 'fa-trash', 'color': '#dc3545'},
    'can_add_bon_hors_stock':   {'label': 'Créer', 'icon': 'fa-plus', 'color': '#28a745'},
    'can_change_bon_hors_stock':{'label': 'Modifier / Annuler', 'icon': 'fa-edit', 'color': '#ffc107'},
    'can_delete_bon_hors_stock':{'label': 'Supprimer', 'icon': 'fa-trash', 'color': '#dc3545'},
    'add_commande':           {'label': 'Créer', 'icon': 'fa-plus', 'color': '#28a745'},
    'change_commande':        {'label': 'Modifier / Valider', 'icon': 'fa-edit', 'color': '#ffc107'},
    'delete_commande':        {'label': 'Supprimer', 'icon': 'fa-trash', 'color': '#dc3545'},
    'add_ajustement':         {'label': 'Créer', 'icon': 'fa-plus', 'color': '#28a745'},
    'change_ajustement':      {'label': 'Modifier', 'icon': 'fa-edit', 'color': '#ffc107'},
    'add_campagneinventaire': {'label': 'Créer', 'icon': 'fa-plus', 'color': '#28a745'},
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
    'add_demandemateriel':    {'label': 'Créer', 'icon': 'fa-plus', 'color': '#28a745'},
    'change_demandemateriel': {'label': 'Modifier / Traiter', 'icon': 'fa-edit', 'color': '#ffc107'},
    'delete_demandemateriel': {'label': 'Supprimer', 'icon': 'fa-trash', 'color': '#dc3545'},
    'add_livraisonpartielle': {'label': 'Créer livraisons', 'icon': 'fa-plus', 'color': '#28a745'},
    'change_livraisonpartielle': {'label': 'Modifier livraisons', 'icon': 'fa-edit', 'color': '#ffc107'},
    'add_specialite':         {'label': 'Ajouter', 'icon': 'fa-plus', 'color': '#28a745'},
    'change_specialite':      {'label': 'Modifier', 'icon': 'fa-edit', 'color': '#ffc107'},
}

ROLE_ARCHITECTURE_MENU = {
    'ACCUEIL & TABLEAU DE BORD': ['menu_accueil', 'menu_dashboard'],
    'DEMANDES': ['menu_demandes', 'menu_guichet'],
    'MOUVEMENTS DE STOCK': ['menu_entrees', 'menu_sorties', 'menu_retours_services', 'menu_sorties_hors_stock', 'menu_livraisons', 'menu_reception_commande'],
    'GESTION DES STOCKS': ['menu_stock', 'menu_peremptions', 'menu_destructions', 'menu_ajustements', 'menu_inventaires', 'menu_historique'],
    'ACHATS & CATALOGUE': ['menu_commandes', 'menu_articles', 'menu_familles'],
    'PATRIMOINE & SAV': {
        'SAV': ['menu_pat_tickets', 'menu_pat_tech', 'menu_pat_dispatch', 'menu_pat_historique'],
        'Gestion du Parc': ['menu_pat_registre', 'menu_pat_sas', 'menu_pat_contrats', 'menu_pat_import', 'menu_pat_inventaire', 'menu_pat_rebuts', 'menu_pat_pertes', 'menu_pat_parametres'],
    },
    'RAPPORTS & EXPORTS': ['menu_rapports', 'menu_stats_demandes', 'menu_stats_sondages', 'menu_stats_satisfaction'],
    'PARAMÈTRES': {
        'Administratif': ['menu_param_admin', 'menu_services', 'menu_specialites', 'menu_parametres'],
        'Logistique': ['menu_magasins', 'menu_fournisseurs', 'menu_motifs_annulation', 'menu_param_logistique', 'menu_modeles_pdf'],
    },
    'SÉCURITÉ & ACCÈS': ['menu_utilisateurs', 'menu_roles', 'menu_circuits_validation', 'menu_journal_audit'],
}

MODULE_ICONS = {
    'ACCUEIL & TABLEAU DE BORD': 'fa-home',
    'DEMANDES': 'fa-clipboard-list',
    'MOUVEMENTS DE STOCK': 'fa-exchange-alt',
    'GESTION DES STOCKS': 'fa-boxes',
    'ACHATS & CATALOGUE': 'fa-shopping-cart',
    'PATRIMOINE & SAV': 'fa-building',
    'RAPPORTS & EXPORTS': 'fa-chart-pie',
    'PARAMÈTRES': 'fa-cogs',
    'SÉCURITÉ & ACCÈS': 'fa-shield-alt',
}

MENU_ITEMS_META = {
    'menu_dashboard': {'label': 'Tableau de bord', 'icon': 'fa-tachometer-alt', 'color': '#1c5b96'},
    'menu_accueil': {'label': 'Accueil', 'icon': 'fa-home', 'color': '#17a2b8'},
    'menu_demandes': {'label': 'Mes Demandes', 'icon': 'fa-clipboard-list', 'color': '#17a2b8'},
    'menu_guichet': {'label': 'Traiter Demandes', 'icon': 'fa-desktop', 'color': '#6f42c1'},
    'menu_entrees': {'label': 'Entrées Stock', 'icon': 'fa-arrow-down', 'color': '#28a745'},
    'menu_sorties': {'label': 'Bons de Sortie', 'icon': 'fa-arrow-up', 'color': '#dc3545'},
    'menu_retours_services': {'label': 'Retours Services', 'icon': 'fa-undo', 'color': '#20c997'},
    'menu_sorties_hors_stock': {'label': 'Sorties Hors Stock', 'icon': 'fa-external-link-alt', 'color': '#e83e8c'},
    'menu_stock': {'label': 'État du Stock', 'icon': 'fa-boxes', 'color': '#1c5b96'},
    'menu_peremptions': {'label': 'Péremptions', 'icon': 'fa-calendar-times', 'color': '#ffc107'},
    'menu_destructions': {'label': 'Destructions', 'icon': 'fa-trash-alt', 'color': '#dc3545'},
    'menu_ajustements': {'label': 'Ajustements', 'icon': 'fa-sliders-h', 'color': '#6f42c1'},
    'menu_inventaires': {'label': 'Inventaires', 'icon': 'fa-clipboard-check', 'color': '#28a745'},
    'menu_articles': {'label': 'Catalogue Articles', 'icon': 'fa-barcode', 'color': '#0d47a1'},
    'menu_familles': {'label': 'Familles', 'icon': 'fa-folder-open', 'color': '#fd7e14'},
    'menu_commandes': {'label': 'Commandes', 'icon': 'fa-shopping-cart', 'color': '#e83e8c'},
    'menu_reception_commande': {'label': 'Réceptions', 'icon': 'fa-truck-loading', 'color': '#28a745'},
    'menu_livraisons': {'label': 'Livraisons', 'icon': 'fa-truck', 'color': '#fd7e14'},
    'menu_rapports': {'label': 'Rapports', 'icon': 'fa-chart-line', 'color': '#28a745'},
    'menu_historique': {'label': 'Historique', 'icon': 'fa-history', 'color': '#6c757d'},
    'menu_magasins': {'label': 'Magasins', 'icon': 'fa-store', 'color': '#ffc107'},
    'menu_fournisseurs': {'label': 'Fournisseurs', 'icon': 'fa-truck', 'color': '#fd7e14'},
    'menu_motifs_annulation': {'label': 'Motifs Annulation', 'icon': 'fa-ban', 'color': '#dc3545'},
    'menu_param_logistique': {'label': 'Param. Logistique', 'icon': 'fa-cogs', 'color': '#6c757d'},
    'menu_services': {'label': 'Services', 'icon': 'fa-hospital', 'color': '#28a745'},
    'menu_specialites': {'label': 'Spécialités', 'icon': 'fa-user-md', 'color': '#17a2b8'},
    'menu_param_admin': {'label': 'Param. Admin', 'icon': 'fa-building', 'color': '#1c5b96'},
    'menu_parametres': {'label': 'Paramètres Généraux', 'icon': 'fa-sliders-h', 'color': '#6c757d'},
    'menu_modeles_pdf': {'label': 'Modèles PDF', 'icon': 'fa-file-pdf', 'color': '#dc3545'},
    'menu_utilisateurs': {'label': 'Utilisateurs', 'icon': 'fa-users', 'color': '#1c5b96'},
    'menu_roles': {'label': 'Rôles & Accès', 'icon': 'fa-user-shield', 'color': '#0d47a1'},
    'menu_circuits_validation': {'label': 'Circuits Validation', 'icon': 'fa-project-diagram', 'color': '#6f42c1'},
    'menu_journal_audit': {'label': 'Journal Audit', 'icon': 'fa-history', 'color': '#6c757d'},
    'menu_pat_tickets': {'label': 'Tickets SAV', 'icon': 'fa-ticket-alt', 'color': '#20c997'},
    'menu_pat_tech': {'label': 'Espace Tech', 'icon': 'fa-clipboard-list', 'color': '#6f42c1'},
    'menu_pat_dispatch': {'label': 'Dispatch Pannes', 'icon': 'fa-satellite-dish', 'color': '#fd7e14'},
    'menu_pat_historique': {'label': 'Historique Global', 'icon': 'fa-history', 'color': '#b6c2c9'},
    'menu_pat_registre': {'label': 'Registre Matériel', 'icon': 'fa-layer-group', 'color': '#1c5b96'},
    'menu_pat_sas': {'label': 'Sas Immatriculation', 'icon': 'fa-clock', 'color': '#ffc107'},
    'menu_pat_contrats': {'label': 'Contrats', 'icon': 'fa-file-contract', 'color': '#17a2b8'},
    'menu_pat_import': {'label': 'Import Excel', 'icon': 'fa-file-import', 'color': '#28a745'},
    'menu_pat_inventaire': {'label': 'Inventaire Parc', 'icon': 'fa-barcode', 'color': '#28a745'},
    'menu_pat_rebuts': {'label': 'Registre Rebuts', 'icon': 'fa-trash-alt', 'color': '#ef4444'},
    'menu_pat_pertes': {'label': 'Équipements Perdus', 'icon': 'fa-search-minus', 'color': '#f59e0b'},
    'menu_pat_parametres': {'label': 'Paramètres Patrimoine', 'icon': 'fa-sliders-h', 'color': '#ffda6a'},

    'menu_stats_demandes': {'label': 'Stats Demandes', 'icon': 'fa-chart-bar', 'color': '#0d6efd'},
    'menu_stats_sondages': {'label': 'Stats Sondages', 'icon': 'fa-smile', 'color': '#198754'},
    'menu_stats_satisfaction': {'label': 'Stats Satisfaction', 'icon': 'fa-star-half-alt', 'color': '#6f42c1'},}

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_roles')
def page_roles(request):
    """Gestion des rôles et permissions (mono-tenant)."""

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
        result = []
        for v in arch.values():
            if isinstance(v, dict):
                for sub in v.values():
                    result.extend(sub)
            elif isinstance(v, list):
                result.extend(v)
        return result

    menu_codenames = _flatten_role_permissions(ROLE_ARCHITECTURE_MENU)

    # [MONO-TENANT] SOUS_PERMISSIONS et SOUS_PERM_LABELS déplacés au niveau module


    sous_codenames = [c for perms in SOUS_PERMISSIONS.values() for c in perms]
    all_codenames = list(set(menu_codenames + sous_codenames))

    # Récupération en base — déduplication par codename (évite les doublons multi-ContentType)
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

    # ── POST : Création / Modif / Suppr ──
    if request.method == 'POST':
        action = request.POST.get('action', '')

        if not action and request.POST.get('enregistrer_role') == '1':
            role_id = request.POST.get('role_id', '').strip()
            nom = request.POST.get('libelle', '').strip().upper()
            perm_ids = request.POST.getlist('fonctionnalites')

            if not nom:
                messages.error(request, "⛔ Le libellé du rôle est obligatoire.")
                return redirect('accounts:page_roles')

            if role_id:
                groupe = get_object_or_404(Group, id=role_id)
                groupe.name = nom
                groupe.save()
                messages.success(request, f"✅ Rôle '{nom}' mis à jour.")
            else:
                if Group.objects.filter(name__iexact=nom).exists():
                    messages.error(request, f"⛔ Le rôle '{nom}' existe déjà.")
                    return redirect('accounts:page_roles')
                groupe = Group.objects.create(name=nom)
                log_audit(request, f"Création rôle {nom}", type_action='CREATE',
                          modele_concerne='Group', id_objet=groupe.id)
                messages.success(request, f"✅ Rôle '{nom}' créé.")

            if perm_ids:
                perms = Permission.objects.filter(id__in=perm_ids)
                groupe.permissions.set(perms)
                log_audit(request, f"Permissions mises à jour pour {nom}", type_action='PERMISSION',
                          modele_concerne='Group', id_objet=groupe.id)

            return redirect('accounts:page_roles')

        if action == 'supprimer':
            groupe_id = request.POST.get('groupe_id')
            groupe = get_object_or_404(Group, id=groupe_id)
            if User.objects.filter(groups=groupe).exists():
                messages.error(request, "⛔ Impossible : des utilisateurs sont attachés.")
            else:
                nom = groupe.name
                groupe.delete()
                log_audit(request, f"Suppression rôle {nom}", type_action='DELETE',
                          modele_concerne='Group')
                messages.success(request, f"🗑️ Rôle '{nom}' supprimé.")
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
    notif.est_lue = True
    notif.save()
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'success': True})
    return redirect('accounts:mes_notifications')


# ==========================================================
# JOURNAL D'AUDIT
# ==========================================================
@login_required(login_url='/auth/login/')
def journal_audit(request):
    """Journal d'audit sécurité (AuditConnexion + KPIs + panneau latéral)."""
    if not request.user.is_superuser and not request.user.has_perm('accounts.view_journalaudit'):
        if not request.user.has_perm('accounts.menu_journal_audit'):
            messages.error(request, "⛔ Accès réservé.")
            return redirect('accounts:accueil_personnalise')

    q = request.GET.get('q', '').strip()
    type_filtre = request.GET.get('type_filtre', '').strip()
    periode = request.GET.get('periode', '30').strip() or '30'
    date_debut = request.GET.get('date_debut', '').strip()
    date_fin = request.GET.get('date_fin', '').strip()

    qs = AuditConnexion.objects.select_related('utilisateur').order_by('-date_creation')

    # Période
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

    # KPIs (sur le queryset filtré hors pagination)
    total_connexions = qs.filter(type_action='CONNEXION').count()
    total_echecs = qs.filter(type_action='ECHEC').count()
    total_admin = qs.filter(type_action='ADMIN').count()

    # Alertes simples
    alertes = []
    if total_echecs >= 5:
        alertes.append({
            'niveau': 'danger',
            'icone': 'fa-exclamation-triangle',
            'message': f"{total_echecs} échec(s) de connexion sur la période sélectionnée.",
        })
    elif total_echecs >= 1:
        alertes.append({
            'niveau': 'warning',
            'icone': 'fa-exclamation-circle',
            'message': f"{total_echecs} échec(s) de connexion détecté(s).",
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

    # ── Durées de session : associer CONNEXION → prochaine DECONNEXION ──
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

    # CORRECTION [Perf] : limiter les déconnexions à la période pertinente
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
    # PANNEAU LATÉRAL — données réelles (optimisées)
    # ═══════════════════════════════════════════════════════════════════

    # Source de vérité unique : sessions Django actives
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

    # 1. TOP UTILISATEURS (par nombre de connexions sur la période) — CORRECTION N+1
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
    # Précharger les déconnexions pour ces utilisateurs
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
    """Sauvegarde la préférence de thème (light/dark)."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée'}, status=405)
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError) as e:
        return JsonResponse({'error': 'JSON invalide'}, status=400)

    theme = data.get('theme', 'light')
    if theme not in ('light', 'dark'):
        return JsonResponse({'error': 'Thème invalide'}, status=400)

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
def page_entreprises(request):
    messages.info(request, "Mode mono-tenant : gestion multi-entreprises désactivée.")
    return redirect('accounts:accueil_personnalise')


@login_required(login_url='/auth/login/')
def changer_entreprise_session(request):
    return redirect('accounts:accueil_personnalise')


@login_required(login_url='/auth/login/')
def parametres_entreprise(request):
    return redirect('/parametres/administratifs/')


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
                messages.error(request, "⛔ Le mot de passe par défaut est obligatoire en mode fixe.")
                return redirect('accounts:parametres_securite')
            erreurs = valider_mot_de_passe(mdp_fixe, contexte='default')
            if erreurs:
                messages.error(
                    request,
                    "❌ Mot de passe par défaut invalide : " + ", ".join(erreurs) + "."
                )
                return redirect('accounts:parametres_securite')

        config.type_mot_de_passe = mode
        config.mot_de_passe_defaut = mdp_fixe if mode == 'FIXE' else ''
        config.save()

        log_audit(
            request,
            f"Config sécurité : mode={mode}",
            type_action='UPDATE',
            modele_concerne='ConfigSecurite',
            id_objet=1,
        )
        messages.success(request, "✅ Paramètres de sécurité enregistrés.")
        return redirect('accounts:parametres_securite')

    return render(request, 'accounts/parametres_securite.html', {
        'config': config,
    })


# ==========================================================
# SIGNATURE
# ==========================================================
@login_required(login_url='/auth/login/')
def enregistrer_signature(request):
    """Enregistrer / mettre à jour la signature numérique du profil."""
    try:
        profil = request.user.profil
    except Profil.DoesNotExist:
        profil = Profil.objects.create(user=request.user)

    if request.method == 'POST':
        signature = request.FILES.get('signature')
        if signature:
            # CORRECTION : vérification MIME
            if signature.content_type not in ('image/jpeg', 'image/png'):
                messages.error(request, "⛔ Seuls les formats JPG et PNG sont acceptés.")
                return redirect('accounts:profil_utilisateur')
            if signature.size > 2 * 1024 * 1024:
                messages.error(request, "⛔ La signature ne doit pas dépasser 2 Mo.")
                return redirect('accounts:profil_utilisateur')
            profil.signature = signature
            profil.a_signature = True
            profil.save(update_fields=['signature', 'a_signature'])
            messages.success(request, "✅ Signature enregistrée.")
        else:
            messages.error(request, "⛔ Aucun fichier signature fourni.")
        return redirect('accounts:profil_utilisateur')


# ==========================================================
# CIRCUITS DE VALIDATION
# ==========================================================
@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_circuits_validation')
def circuits_validation(request):
    """Liste + mise à jour inline des circuits de validation (mono-tenant)."""
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
            messages.warning(request, "⚠️ Aucun validateur sélectionné — le circuit est vide.")

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
            messages.error(request, "❌ Erreur lors de la mise à jour du circuit.")
            return redirect('accounts:circuits_validation')

        log_audit(
            request,
            f"Circuit validation mis à jour : {getattr(circuit, 'type_document', circuit_id)}",
            type_action='UPDATE',
            modele_concerne='CircuitValidation',
            id_objet=circuit.id,
        )
        messages.success(request, "✅ Circuit mis à jour.")
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
    """Créer un circuit de validation."""
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
                messages.success(request, "✅ Circuit de validation créé.")
                return redirect('accounts:circuits_validation')
        except ValueError as e:
            messages.error(request, f"❌ {e}")
        except Exception:
            messages.error(request, "❌ Erreur lors de la création du circuit.")

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
            messages.success(request, "✅ Circuit modifié.")
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