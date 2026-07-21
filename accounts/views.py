# accounts/views.py — IMPORTS CORRIGÉS
import json

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User, Group, Permission
from django.db import transaction, IntegrityError
from django.db.models import Q
from django.core.paginator import Paginator
from django.utils import timezone
from django.contrib.auth import login, logout
from django.utils.text import slugify
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from core.models import ConfigurationHopital, Service
from .models import (
    Entreprise, Profil, Specialite, MenuAccess, 
    Notification, JournalAudit, RoleEntreprise, Fonction
)
from .permissions import verifier_permission
from .forms import ProfilForm, EntrepriseConfigForm

from stock.models import Magasin  


# ==========================================================
# 🔐 UTILITAIRES
# ==========================================================
def paginer(queryset, request, per_page_key='per_page', default=15, max_all=500):
    """Pagination sécurisée (supporte QuerySet ET list)."""
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
    """Récupère l'IP réelle même derrière un proxy."""
    x_forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded:
        return x_forwarded.split(',')[0].strip()
    return request.META.get('REMOTE_ADDR')


def log_audit(request, action, type_action='UPDATE', modele_concerne='', id_objet=None, details=None):
    """Crée une entrée dans le Journal d'Audit."""
    JournalAudit.objects.create(
        utilisateur=request.user if request.user.is_authenticated else None,
        entreprise=getattr(request, 'entreprise', None),
        action=action,
        type_action=type_action,
        modele_concerne=modele_concerne,
        id_objet=id_objet,
        details=details,
        adresse_ip=get_client_ip(request),
    )


# ==========================================================
# 🔑 CONNEXION / DÉCONNEXION
# ==========================================================
def custom_login(request):
    """Authentification avec support multi-tenant (username@entreprise)."""
    if request.user.is_authenticated:
        return redirect('/')

    if request.method == 'POST':
        username = request.POST.get('username', '').lower().strip()
        password = request.POST.get('password', '')
        entreprise_slug = request.POST.get('entreprise_slug', '').lower().strip()

        # Support suffixe @entreprise
        if '@' in username:
            username, entreprise_slug = username.split('@', 1)

        username_brut = username
        entreprise = None

        if entreprise_slug:
            entreprise = Entreprise.objects.filter(slug__iexact=entreprise_slug, est_active=True).first()

        # ── RECHERCHE UTILISATEUR ──
        user = None

        if entreprise:
            # 1) Essayer avec le suffixe @entreprise (utilisateur normal)
            username_complet = f"{username_brut}@{entreprise.slug}"
            user = User.objects.filter(
                username__iexact=username_complet,
                profil__entreprise=entreprise,
                is_active=True
            ).first()

            # Fallback : si pas trouvé, username brut pour superuser
            if not user:
                user = User.objects.filter(username__iexact=username_brut, is_active=True).first()
                if user and not user.is_superuser:
                    user = None
        else:
            # Pas d'entreprise : uniquement superuser autorisé
            user = User.objects.filter(username__iexact=username_brut, is_active=True).first()
            if user and not user.is_superuser:
                user = None

        if user and user.check_password(password):
            # 🔧 DÉTECTION PREMIÈRE CONNEXION (avant login qui met à jour last_login)
            must_change = (user.last_login is None) and not user.is_superuser

            # Backend obligatoire
            user.backend = 'django.contrib.auth.backends.ModelBackend'
            login(request, user, backend='django.contrib.auth.backends.ModelBackend')

            if must_change:
                request.session['must_change_password'] = True
                messages.warning(request, "🔒 Vous devez changer votre mot de passe avant de continuer.")
                return redirect('accounts:changer_mdp_obligatoire')

            if user.is_superuser:
                request.session['entreprise_id'] = entreprise.id if entreprise else None
            else:
                try:
                    profil = user.profil
                    if profil and profil.entreprise:
                        request.session['entreprise_id'] = profil.entreprise.id
                    else:
                        logout(request)
                        messages.error(request, "⛔ Compte incomplet : aucune entreprise associée.")
                        return redirect('accounts:custom_login')
                except Profil.DoesNotExist:
                    logout(request)
                    messages.error(request, "⛔ Compte incomplet : profil manquant.")
                    return redirect('accounts:custom_login')

            log_audit(request, f"Connexion de {user.username}", type_action='LOGIN')
            messages.success(request, f"✅ Bienvenue {user.get_full_name() or user.username} !")

            # TOUS les utilisateurs arrivent sur la page d'accueil personnalisée
            return redirect(request.GET.get('next', 'accounts:accueil_personnalise'))
        else:
            messages.error(request, "⛔ Identifiants incorrects, compte désactivé ou entreprise invalide.")

    entreprises = Entreprise.objects.filter(est_active=True).order_by('nom')
    return render(request, 'accounts/login.html', {'entreprises': entreprises})


def custom_logout(request):
    """Déconnexion propre avec nettoyage session."""
    if request.user.is_authenticated:
        log_audit(request, f"Déconnexion de {request.user.username}", type_action='LOGOUT')
    logout(request)
    request.session.flush()
    messages.success(request, "👋 Vous avez été déconnecté avec succès.")
    return redirect('accounts:custom_login')


# ==========================================================
# 👤 PROFIL UTILISATEUR
# ==========================================================
@login_required(login_url='/accounts/login/')
def profil_utilisateur(request):
    """Affichage et édition du profil connecté."""
    try:
        profil = request.user.profil
    except Profil.DoesNotExist:
        if request.entreprise:
            profil = Profil.objects.create(
                user=request.user,
                entreprise=request.entreprise,
                cree_par=request.user,
                modifie_par=request.user,
            )
            messages.warning(request, "⚠️ Votre profil a été créé automatiquement.")
        else:
            messages.error(request, "⛔ Aucune entreprise sélectionnée. Impossible de créer un profil.")
            return redirect('/')

    # RÉCUPÈRE L'ONGLET ACTIF (défaut: infos)
    onglet = request.GET.get('onglet', 'infos')

    # GÈRE LES 3 ACTIONS POST DISTINCTES DU TEMPLATE
    if request.method == 'POST':
        action = request.POST.get('action', '')

        if action == 'photo':
            if not profil.peut_changer_photo:
                minutes_restantes = (profil.temps_restant_photo // 60) + 1
                messages.error(
                    request,
                    f"⛔ Vous devez attendre encore environ {minutes_restantes} minute(s) avant de changer votre photo."
                )
                return redirect(f'{request.path}?onglet=infos')

            if request.FILES.get('photo'):
                profil.photo = request.FILES['photo']
                profil.nb_changements_photo += 1
                profil.date_derniere_photo = timezone.now()
                profil.save()
                messages.success(request, "✅ Photo de profil mise à jour.")
            else:
                messages.error(request, "⛔ Aucune photo sélectionnée.")
            return redirect(f'{request.path}?onglet=infos')

        elif action == 'signature':
            # BLOQUÉ : seul un admin peut modifier la signature
            messages.error(request, "⛔ Vous ne pouvez pas modifier votre signature. Contactez un administrateur.")
            return redirect(f'{request.path}?onglet=signature')

        elif action == 'password':
            old = request.POST.get('old_password', '')
            new1 = request.POST.get('new_password1', '')
            new2 = request.POST.get('new_password2', '')

            if not request.user.check_password(old):
                messages.error(request, "❌ Mot de passe actuel incorrect.")
            elif new1 != new2:
                messages.error(request, "❌ Les nouveaux mots de passe ne correspondent pas.")
            elif len(new1) < 8:
                messages.error(request, "❌ Le mot de passe doit contenir au moins 8 caractères.")
            else:
                request.user.set_password(new1)
                request.user.save()
                messages.success(request, "✅ Mot de passe modifié. Veuillez vous reconnecter.")
                logout(request)
                return redirect('accounts:custom_login')
            return redirect(f'{request.path}?onglet=securite')

        else:
            # Formulaire profil standard (fallback)
            form = ProfilForm(request.POST, request.FILES, instance=profil)
            if form.is_valid():
                form.save()
                log_audit(request, "Mise à jour du profil", modele_concerne='Profil', id_objet=profil.id)
                messages.success(request, "✅ Profil mis à jour avec succès.")
                return redirect('accounts:profil_utilisateur')
    else:
        form = ProfilForm(instance=profil)

    return render(request, 'accounts/profil.html', {
        'profil': profil,
        'form': form,
        'onglet': onglet,
    })


# ==========================================================
# 👥 GESTION DES UTILISATEURS
# ==========================================================
@login_required(login_url='/accounts/login/')
@verifier_permission('accounts.menu_utilisateurs')
def page_utilisateurs(request):
    """Hub de gestion des utilisateurs de l'entreprise active."""
    entreprise = request.entreprise

    if not entreprise:
        messages.error(request, "⛔ Aucune entreprise sélectionnée.")
        return redirect('/')

    # ── FILTRE STATUT ──
    statut_filtre = request.GET.get('statut_filtre', 'actif')

    if statut_filtre == 'actif':
        utilisateurs_qs = User.objects.filter(profil__entreprise=entreprise, is_active=True)
    elif statut_filtre == 'inactif':
        utilisateurs_qs = User.objects.filter(profil__entreprise=entreprise, is_active=False)
    else:
        utilisateurs_qs = User.objects.filter(profil__entreprise=entreprise)

    # ── RECHERCHE ──
    q = request.GET.get('q', '')
    if q:
        utilisateurs_qs = utilisateurs_qs.filter(
            Q(username__icontains=q) | 
            Q(first_name__icontains=q) | 
            Q(last_name__icontains=q) |
            Q(email__icontains=q)
        )

    utilisateurs_qs = utilisateurs_qs.select_related(
        'profil', 'profil__specialite', 'profil__service'
    ).order_by('last_name', 'first_name')

    utilisateurs_pagines, per_page = paginer(utilisateurs_qs, request)

    # ── DONNÉES POUR LES FILTRES & MODAL ──
    specialites = Specialite.objects.filter(entreprise=entreprise).order_by('nom')

    # CORRECTION : tous les services de l'entreprise
    services_tous = Service.objects.filter(entreprise=entreprise).order_by('nom')

    # CORRECTION : tous les magasins de l'entreprise
    magasins_tous = Magasin.objects.filter(entreprise=entreprise).order_by('nom')

    # Groupes filtrés par entreprise
    groupes = Group.objects.filter(
        roleentreprise__entreprise=entreprise
    ).order_by('name')

    # ── POST : CRÉATION / MODIFICATION / TOGGLE ──
    if request.method == 'POST':
        action = request.POST.get('action', '')

        # 1) CRÉATION (bouton rapide)
        if action == 'creer':
            username_brut = request.POST.get('username', '').lower().strip()
            email = request.POST.get('email', '').lower().strip()
            password = request.POST.get('password', '')
            first_name = request.POST.get('first_name', '').strip()
            last_name = request.POST.get('last_name', '').strip()
            groupe_id = request.POST.get('groupe_id')

            username = f"{username_brut}@{entreprise.slug}"

            if User.objects.filter(username__iexact=username).exists():
                messages.error(request, f"⛔ Le nom d'utilisateur '{username_brut}' existe déjà dans cette entreprise.")
            else:
                try:
                    with transaction.atomic():
                        user = User.objects.create_user(
                            username=username,
                            email=email,
                            password=password,
                            first_name=first_name,
                            last_name=last_name,
                        )
                        profil, created = Profil.objects.get_or_create(
                            user=user,
                            defaults={
                                'entreprise': entreprise,
                                'cree_par': request.user,
                                'modifie_par': request.user,
                            }
                        )
                        if not created:
                            profil.entreprise = entreprise
                            profil.modifie_par = request.user
                            profil.save()

                        if groupe_id:
                            groupe = get_object_or_404(
                                Group.objects.filter(roleentreprise__entreprise=entreprise),
                                id=groupe_id
                            )
                            user.groups.set([groupe])

                        log_audit(request, f"Création utilisateur {username}", type_action='CREATE',
                                  modele_concerne='User', id_objet=user.id)
                    messages.success(request, f"✅ Utilisateur '{username_brut}' créé avec succès.")
                except Exception as e:
                    messages.error(request, f"❌ Erreur : {str(e)}")
            return redirect('accounts:page_utilisateurs')

        # 2) ACTIVER / DÉSACTIVER (toggle)
        elif request.POST.get('toggle_statut') == '1':
            user_id = request.POST.get('user_id')
            user = get_object_or_404(User, id=user_id, profil__entreprise=entreprise)
            user.is_active = not user.is_active
            user.save()
            statut = "activé" if user.is_active else "désactivé"
            log_audit(request, f"Compte {user.username} {statut}", type_action='UPDATE',
                      modele_concerne='User', id_objet=user.id)
            messages.success(request, f"🔓 Compte de {user.get_full_name() or user.username} {statut}.")
            return redirect('accounts:page_utilisateurs')

        # 3) MISE À JOUR PROFIL (depuis le modal)
        elif request.POST.get('enregistrer_user') == '1':
            user_id = request.POST.get('user_id')

            if user_id:
                # MODIFICATION
                user = get_object_or_404(User, id=user_id, profil__entreprise=entreprise)
                user.first_name = request.POST.get('first_name', user.first_name).strip()
                user.last_name = request.POST.get('last_name', user.last_name).strip()
                user.email = request.POST.get('email', user.email).strip()

                # Mise à jour du login (username)
                username_brut = request.POST.get('username', '').lower().strip()
                if username_brut:
                    if '@' in username_brut:
                        new_username = username_brut
                    else:
                        new_username = f"{username_brut}@{entreprise.slug}"
                    if new_username != user.username:
                        if User.objects.filter(username__iexact=new_username).exclude(id=user.id).exists():
                            messages.error(request, f"⛔ Le login '{username_brut}' existe déjà.")
                            return redirect('accounts:page_utilisateurs')
                        user.username = new_username

                user.save()

                profil = user.profil
                profil.contact = request.POST.get('contact', profil.contact)

                spe_id = request.POST.get('specialite')
                if spe_id:
                    profil.specialite_id = spe_id

                service_id = request.POST.get('service')
                if service_id:
                    profil.service_id = service_id

                fonction_id = request.POST.get('fonction')
                if fonction_id:
                    profil.fonction_id = fonction_id
                else:
                    profil.fonction = None

                magasins_ids = request.POST.getlist('magasins')
                if magasins_ids:
                    profil.magasins_autorises.set(magasins_ids)
                else:
                    profil.magasins_autorises.clear()

                if request.FILES.get('photo'):
                    profil.photo = request.FILES['photo']
                if request.FILES.get('signature_officielle'):
                    profil.signature = request.FILES['signature_officielle']
                    profil.a_signature = True

                profil.modifie_par = request.user
                profil.save()

                groupe_id = request.POST.get('groupe')
                if groupe_id:
                    groupe = get_object_or_404(
                        Group.objects.filter(roleentreprise__entreprise=entreprise),
                        id=groupe_id
                    )
                    user.groups.set([groupe])

                log_audit(request, f"Modification utilisateur {user.username}", type_action='UPDATE',
                          modele_concerne='User', id_objet=user.id)
                messages.success(request, f"✅ Utilisateur '{user.username}' mis à jour.")
            else:
                # CRÉATION VIA MODAL
                username_brut = request.POST.get('username', '').lower().strip()

                # Récupérer la politique de mot de passe
                config = ConfigurationHopital.objects.filter(entreprise=entreprise).first()

                if config and config.type_mot_de_passe == 'FIXE' and config.mot_de_passe_defaut:
                    password = config.mot_de_passe_defaut
                else:
                    import secrets, string
                    password = ''.join(secrets.choice(string.ascii_letters + string.digits + "!@#$%&*") for _ in range(14))

                username = f"{username_brut}@{entreprise.slug}"

                if User.objects.filter(username__iexact=username).exists():
                    messages.error(request, f"⛔ '{username_brut}' existe déjà.")
                    return redirect('accounts:page_utilisateurs')

                with transaction.atomic():
                    user = User.objects.create_user(
                        username=username,
                        email=request.POST.get('email', ''),
                        password=password,
                        first_name=request.POST.get('first_name', ''),
                        last_name=request.POST.get('last_name', ''),
                    )
                    profil = Profil.objects.create(
                        user=user,
                        entreprise=entreprise,
                        contact=request.POST.get('contact', ''),
                        cree_par=request.user,
                        modifie_par=request.user,
                    )

                    spe_id = request.POST.get('specialite')
                    if spe_id:
                        profil.specialite_id = spe_id

                    service_id = request.POST.get('service')
                    if service_id:
                        profil.service_id = service_id

                    magasins_ids = request.POST.getlist('magasins')
                    if magasins_ids:
                        profil.magasins_autorises.set(magasins_ids)


                    fonction_id = request.POST.get('fonction')
                    if fonction_id:
                        profil.fonction_id = fonction_id
                    else:
                        profil.fonction = None
                    if request.FILES.get('photo'):
                        profil.photo = request.FILES['photo']
                    if request.FILES.get('signature_officielle'):
                        profil.signature = request.FILES['signature_officielle']
                        profil.a_signature = True

                    profil.save()

                    groupe_id = request.POST.get('groupe')
                    if groupe_id:
                        groupe = get_object_or_404(
                            Group.objects.filter(roleentreprise__entreprise=entreprise),
                            id=groupe_id
                        )
                        user.groups.set([groupe])

                    log_audit(request, f"Création utilisateur {username}", type_action='CREATE',
                              modele_concerne='User', id_objet=user.id)

                # Message adapté selon le mode (mot de passe jamais affiché en clair dans messages)
                if config and config.type_mot_de_passe == 'FIXE':
                    messages.success(request, f"✅ Utilisateur '{username_brut}' créé. Mot de passe fixe configuré.")
                else:
                    messages.success(request, f"✅ Utilisateur '{username_brut}' créé. Mot de passe aléatoire généré (transmis séparément).")

            return redirect('accounts:page_utilisateurs')

    context = {
        'utilisateurs': utilisateurs_pagines,
        'specialites': specialites,
        'services_tous': services_tous,
        'magasins_tous': magasins_tous,
        'groupes': groupes,
        'q': q,
        'per_page': per_page,
        'statut_filtre': statut_filtre,
        'fonctions': Fonction.objects.filter(entreprise=entreprise).order_by('nom'),
    }
    return render(request, 'accounts/utilisateurs.html', context)


# ==========================================================
# 🔑 GESTION DES RÔLES (GROUPES)
# ==========================================================
from collections import OrderedDict
from .menus import ARCHITECTURE_MENU, MENU_ITEMS_META, MODULE_ICONS, ROLE_ARCHITECTURE_MENU, flatten_role_permissions

@login_required(login_url='/accounts/login/')
@verifier_permission('accounts.menu_roles')
def page_roles(request):
    entreprise = request.entreprise
    if not entreprise:
        messages.error(request, "⛔ Aucune entreprise sélectionnée.")
        return redirect('/')

    # ── Groupes ──
    groupes_qs = Group.objects.filter(
        Q(roleentreprise__entreprise=entreprise) |
        Q(name__iendswith=f"@{entreprise.slug}")
    ).distinct().prefetch_related('permissions').order_by('name')

    for groupe in groupes_qs:
        if not hasattr(groupe, 'roleentreprise'):
            RoleEntreprise.objects.create(groupe=groupe, entreprise=entreprise)

    groupes = Group.objects.filter(
        roleentreprise__entreprise=entreprise
    ).prefetch_related('permissions').order_by('name')

    for groupe in groupes:
        groupe.users_count = User.objects.filter(
            groups=groupe, profil__entreprise=entreprise
        ).count()
        groupe.users_list = list(User.objects.filter(
            groups=groupe, profil__entreprise=entreprise
        ).select_related('profil')[:4])
        groupe.users_more = max(0, groupe.users_count - 4)

    # ── Permissions MENU ──
    menu_codenames = flatten_role_permissions(ROLE_ARCHITECTURE_MENU)

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
    sous_codenames = [c for perms in SOUS_PERMISSIONS.values() for c in perms]
    legacy_codenames = [c for perms in ARCHITECTURE_MENU.values() for c in perms]
    all_codenames = list(set(menu_codenames + sous_codenames + legacy_codenames))

    # Récupération en base (accounts + stock)
    perms_disponibles = Permission.objects.filter(
        codename__in=all_codenames,
        content_type__app_label__in=['accounts', 'stock']
    ).distinct().order_by('codename')

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
                groupe = get_object_or_404(
                    Group.objects.filter(roleentreprise__entreprise=entreprise), id=role_id
                )
                ancien_nom = groupe.name.split('@')[0] if '@' in groupe.name else groupe.name
                groupe.name = f"{nom}@{entreprise.slug}"
                groupe.save()
                messages.success(request, f"✅ Rôle '{ancien_nom}' renommé en '{nom}'.")
            else:
                nom_interne = f"{nom}@{entreprise.slug}"
                if Group.objects.filter(name__iexact=nom_interne).exists():
                    messages.error(request, f"⛔ Le rôle '{nom}' existe déjà.")
                    return redirect('accounts:page_roles')
                with transaction.atomic():
                    groupe = Group.objects.create(name=nom_interne)
                    RoleEntreprise.objects.create(groupe=groupe, entreprise=entreprise)
                    log_audit(request, f"Création rôle {nom}", type_action='CREATE',
                              modele_concerne='Group', id_objet=groupe.id)
                messages.success(request, f"✅ Rôle '{nom}' créé.")

            if perm_ids:
                perms = Permission.objects.filter(
                    id__in=perm_ids,
                    content_type__app_label__in=['accounts', 'stock']
                )
                groupe.permissions.set(perms)
                log_audit(request, f"Permissions mises à jour pour {nom}", type_action='PERMISSION',
                          modele_concerne='Group', id_objet=groupe.id)

            return redirect('accounts:page_roles')

        if action == 'supprimer':
            groupe_id = request.POST.get('groupe_id')
            groupe = get_object_or_404(
                Group.objects.filter(roleentreprise__entreprise=entreprise), id=groupe_id
            )
            if User.objects.filter(groups=groupe, profil__entreprise=entreprise).exists():
                messages.error(request, "⛔ Impossible : des utilisateurs sont attachés.")
            else:
                nom_affiche = groupe.name.split('@')[0] if '@' in groupe.name else groupe.name
                RoleEntreprise.objects.filter(groupe=groupe).delete()
                groupe.delete()
                log_audit(request, f"Suppression rôle {nom_affiche}", type_action='DELETE',
                          modele_concerne='Group')
                messages.success(request, f"🗑️ Rôle '{nom_affiche}' supprimé.")
            return redirect('accounts:page_roles')

    context = {
        'groupes': groupes,
        'perms_disponibles': perms_disponibles,
        'perms_by_codename': perms_by_codename,
        'modules_permissions': ROLE_ARCHITECTURE_MENU,
        'sous_permissions_map': SOUS_PERMISSIONS,
        'sous_perm_labels': SOUS_PERM_LABELS,
        'entreprise': entreprise,
        'menu_items_meta': MENU_ITEMS_META,
        'module_icons': MODULE_ICONS,
    }
    return render(request, 'accounts/roles.html', context)


# ==========================================================
# 🔒 PARAMÈTRES DE SÉCURITÉ
# ==========================================================
@login_required(login_url='/accounts/login/')
@verifier_permission('accounts.menu_utilisateurs')
def parametres_securite(request):
    """Configuration des mots de passe et sécurité."""
    entreprise = request.entreprise

    if not entreprise:
        messages.error(request, "⛔ Aucune entreprise sélectionnée.")
        return redirect('/')

    config, created = ConfigurationHopital.objects.get_or_create(
        entreprise=entreprise,
        defaults={
            'nom': entreprise.nom,
            'type_mot_de_passe': 'ALEATOIRE',
            'mot_de_passe_defaut': '',
        }
    )

    if request.method == 'POST':
        config.type_mot_de_passe = request.POST.get('type_mot_de_passe', config.type_mot_de_passe)

        # Sauvegarder aussi le mot de passe par défaut
        mdp_defaut = request.POST.get('mot_de_passe_defaut', '')
        if config.type_mot_de_passe == 'FIXE':
            config.mot_de_passe_defaut = mdp_defaut
        else:
            config.mot_de_passe_defaut = ''

        config.save()

        log_audit(request, "Modification paramètres sécurité", type_action='UPDATE',
                  modele_concerne='ConfigurationHopital', id_objet=config.id)
        messages.success(request, "✅ Configuration de sécurité mise à jour.")
        return redirect('accounts:parametres_securite')

    return render(request, 'accounts/parametres_securite.html', {
        'config': config,
    })


# ==========================================================
# 🏢 GESTION DES ENTREPRISES (SUPERUSER SEUL)
# ==========================================================
@login_required(login_url='/accounts/login/')
def page_entreprises(request):
    """Gestion des entreprises (superuser uniquement)."""
    if not request.user.is_superuser:
        messages.error(request, "⛔ Accès réservé aux super-administrateurs.")
        return redirect('/')

    entreprises = Entreprise.objects.all().order_by('nom')

    # 🔧 CORRECTION : calcul des stats et nb_users par entreprise
    total_actives = sum(1 for e in entreprises if e.est_active)
    total_inactives = len(entreprises) - total_actives

    for e in entreprises:
        e.nb_users = User.objects.filter(profil__entreprise=e).count()

    if request.method == 'POST':
        action = request.POST.get('action', '')

        if action == 'creer':
            nom = request.POST.get('nom', '').strip()
            slug_brut = request.POST.get('slug', '').lower().strip()
            # SLUGIFY OBLIGATOIRE
            slug = slugify(slug_brut) or slugify(nom)
            if not slug:
                messages.error(request, "⛔ Impossible de générer un slug valide.")
            elif Entreprise.objects.filter(slug__iexact=slug).exists():
                messages.error(request, f"⛔ Le slug '{slug}' existe déjà.")
            else:
                Entreprise.objects.create(nom=nom, slug=slug)
                log_audit(request, f"Création entreprise {nom}", type_action='CREATE',
                          modele_concerne='Entreprise')
                messages.success(request, f"✅ Entreprise '{nom}' créée.")
        elif action == 'toggle_active':
            entreprise_id = request.POST.get('entreprise_id')
            entreprise = get_object_or_404(Entreprise, id=entreprise_id)
            entreprise.est_active = not entreprise.est_active
            entreprise.save()
            statut = "activée" if entreprise.est_active else "désactivée"
            log_audit(request, f"Entreprise {entreprise.nom} {statut}", type_action='UPDATE',
                      modele_concerne='Entreprise', id_objet=entreprise.id)
            messages.success(request, f"🔄 Entreprise '{entreprise.nom}' {statut}.")

        elif action == 'modifier':
            entreprise_id = request.POST.get('entreprise_id')
            nom = request.POST.get('nom', '').strip()
            email = request.POST.get('email', '').strip()
            telephone = request.POST.get('telephone', '').strip()
            adresse = request.POST.get('adresse', '').strip()
            if not nom:
                messages.error(request, "⛔ Le nom de l'entreprise est obligatoire.")
                return redirect('accounts:page_entreprises')
            entreprise = get_object_or_404(Entreprise, id=entreprise_id)
            entreprise.nom = nom
            # 🔧 CORRECTION : email_contact (pas email)
            entreprise.email_contact = email
            entreprise.telephone = telephone
            entreprise.adresse = adresse
            entreprise.save()
            log_audit(request, f"Modification entreprise {nom}", type_action='UPDATE',
                      modele_concerne='Entreprise', id_objet=entreprise.id)
            messages.success(request, f"✅ Entreprise '{nom}' modifiée.")

        elif action == 'supprimer':
            entreprise_id = request.POST.get('entreprise_id')
            entreprise = get_object_or_404(Entreprise, id=entreprise_id)
            nom = entreprise.nom
            entreprise.delete()
            log_audit(request, f"Suppression entreprise {nom}", type_action='DELETE',
                      modele_concerne='Entreprise')
            messages.success(request, f"🗑️ Entreprise '{nom}' supprimée.")

        return redirect('accounts:page_entreprises')

    return render(request, 'accounts/entreprises.html', {
        'entreprises': entreprises,
        'total_actives': total_actives,
        'total_inactives': total_inactives,
    })


# ==========================================================
# 🔔 NOTIFICATIONS
# ==========================================================
@login_required(login_url='/accounts/login/')
def mes_notifications(request):
    """Liste des notifications de l'utilisateur connecté."""
    notifs = Notification.objects.filter(
        utilisateur=request.user,
        est_lue=False
    ).order_by('-date_creation')[:50]

    return render(request, 'accounts/notifications.html', {
        'notifications': notifs,
    })


@login_required(login_url='/accounts/login/')
def marquer_notification_lue(request, notif_id):
    """Marque une notification comme lue."""
    notif = get_object_or_404(Notification, id=notif_id, utilisateur=request.user)
    notif.est_lue = True
    notif.save()
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return JsonResponse({'success': True})
    return redirect('accounts:mes_notifications')


# ==========================================================
# 📝 JOURNAL D'AUDIT (SUPERUSER)
# ==========================================================
@login_required(login_url='/accounts/login/')
def journal_audit(request):
    """Vision globale des actions (superuser)."""
    if not request.user.is_superuser:
        messages.error(request, "⛔ Accès réservé aux administrateurs.")
        return redirect('/')

    journal = JournalAudit.objects.select_related('utilisateur').order_by('-date_action')[:200]

    q = request.GET.get('q', '')
    if q:
        journal = journal.filter(
            Q(action__icontains=q) | Q(utilisateur__username__icontains=q)
        )

    journal_pagines, per_page = paginer(journal, request)

    return render(request, 'accounts/audit.html', {
        'journal': journal_pagines,
        'q': q,
        'per_page': per_page,
    })


# ==========================================================
# 🔄 CHANGER D'ENTREPRISE (SUPERUSER)
# ==========================================================
@login_required(login_url='/accounts/login/')
def changer_entreprise_session(request):
    """Permet aux superusers de switcher d'entreprise."""
    if not request.user.is_superuser:
        messages.error(request, "⛔ Action réservée aux super-administrateurs.")
        return redirect('/')

    if request.method == 'POST':
        entreprise_id = request.POST.get('entreprise_id')
        if entreprise_id:
            # Vérification que l'entreprise est active
            entreprise = get_object_or_404(Entreprise, id=entreprise_id, est_active=True)
            request.session['entreprise_id'] = entreprise.id
            messages.success(request, f"🔄 Entreprise changée : {entreprise.nom}")
        next_url = request.POST.get('next', '/')
        return redirect(next_url)
    return redirect('/')


# ==========================================================
# 🔑 CHANGEMENT MOT DE PASSE OBLIGATOIRE
# ==========================================================
@login_required(login_url='/accounts/login/')
def changer_mdp_obligatoire(request):
    """Force le changement de mot de passe au premier login."""

    if not request.session.get('must_change_password'):
        return redirect('/')

    if request.method == 'POST':
        # MATCH avec le template forcer_mdp.html (new_password1 / new_password2)
        nouveau = request.POST.get('new_password1', '')
        confirmer = request.POST.get('new_password2', '')

        if not nouveau:
            messages.error(request, "❌ Veuillez saisir un nouveau mot de passe.")
        elif nouveau != confirmer:
            messages.error(request, "❌ Les mots de passe ne correspondent pas.")
        elif len(nouveau) < 8:
            messages.error(request, "❌ Le mot de passe doit contenir au moins 8 caractères.")
        else:
            request.user.set_password(nouveau)
            request.user.save()

            # Libère le blocage
            request.session.pop('must_change_password', None)

            log_audit(request, "Changement mot de passe obligatoire", type_action='UPDATE')
            messages.success(request, "✅ Mot de passe changé. Veuillez vous reconnecter.")
            logout(request)
            return redirect('accounts:custom_login')

    return render(request, 'accounts/forcer_mdp.html')


# ==========================================================
# 🔄 RÉINITIALISATION MOT DE PASSE (ADMIN)
# ==========================================================
@login_required(login_url='/accounts/login/')
@verifier_permission('accounts.menu_utilisateurs')
def reinitialiser_mdp(request, user_id):
    """Réinitialise le mot de passe d'un utilisateur (admin uniquement)."""
    from django.contrib.sessions.models import Session

    entreprise = request.entreprise
    user = get_object_or_404(User, id=user_id, profil__entreprise=entreprise)

    if request.method == 'POST':
        nouveau = request.POST.get('nouveau_mdp', '')
        confirmer = request.POST.get('confirmer_mdp', '')

        erreurs = []
        if len(nouveau) < 8:
            erreurs.append("Au moins 8 caractères")
        if not any(c.isupper() for c in nouveau):
            erreurs.append("Une lettre majuscule")
        if not any(c.isdigit() for c in nouveau):
            erreurs.append("Un chiffre")
        if not any(c in '!@#$%&*' for c in nouveau):
            erreurs.append("Un caractère spécial (!@#$%&*)")
        if nouveau != confirmer:
            erreurs.append("Les deux saisies doivent être identiques")

        if erreurs:
            messages.error(request, "❌ " + " | ".join(erreurs))
        else:
            user.set_password(nouveau)
            user.last_login = None
            user.save()

            # ── CAS 1 : L'admin réinitialise SON propre mot de passe ──
            if request.user == user:
                messages.success(
                    request,
                    "✅ Votre mot de passe a été réinitialisé. Veuillez vous reconnecter avec votre nouveau mot de passe."
                )
                logout(request)
                response = redirect('accounts:custom_login')
                response.session_interrupted = True  # ← évite SessionInterrupted
                return response

            # ── CAS 2 : L'admin réinitialise un AUTRE utilisateur ──
            sessions_supprimees = 0
            for session in Session.objects.filter(expire_date__gte=timezone.now()):
                data = session.get_decoded()
                if str(data.get('_auth_user_id')) == str(user.id):
                    session.delete()
                    sessions_supprimees += 1

            log_audit(request, f"Réinitialisation mdp {user.username}", type_action='UPDATE',
                      modele_concerne='User', id_objet=user.id)

            msg = f"✅ Mot de passe de {user.username} réinitialisé."
            if sessions_supprimees > 0:
                msg += f" Déconnecté de {sessions_supprimees} session(s)."
            msg += " L'utilisateur devra choisir un nouveau mot de passe à sa prochaine connexion."
            messages.success(request, msg)
            return redirect('accounts:page_utilisateurs')

    return render(request, 'accounts/reinitialiser_mdp.html', {'utilisateur': user})


# ==========================================================
# 🏠 ACCUEIL PERSONNALISÉ
# ==========================================================
@login_required(login_url='/accounts/login/')
@verifier_permission('accounts.menu_accueil')
def accueil_personnalise(request):
    """Page d'accueil par défaut pour tous les utilisateurs."""
    entreprise = request.entreprise

    MODULES = {
        'menu_demandes':        {'url': '/mes-demandes/', 'icon': 'fa-clipboard-list', 'color': '#17a2b8', 'label': 'Mes Demandes'},
        'menu_guichet':         {'url': '/gestion-demandes/', 'icon': 'fa-desktop', 'color': '#6f42c1', 'label': 'Traiter Demandes'},
        'menu_entrees':         {'url': '/entrees/', 'icon': 'fa-arrow-down', 'color': '#28a745', 'label': 'Entrées Stock'},
        'menu_reception_commande': {'url': '/receptions/', 'icon': 'fa-truck-loading', 'color': '#28a745', 'label': 'Réceptions Commandes'},
        'menu_sorties':         {'url': '/sorties/', 'icon': 'fa-arrow-up', 'color': '#dc3545', 'label': 'Bons de Sortie'},
        'menu_livraisons':      {'url': '/livraisons/', 'icon': 'fa-truck', 'color': '#fd7e14', 'label': 'Livraisons'},
        'menu_sorties_hors_stock': {'url': '/bons/hors-stock/', 'icon': 'fa-external-link-alt', 'color': '#e83e8c', 'label': 'Sorties Hors Stock'},
        'menu_retours_services': {'url': '/stock/retours-services/', 'icon': 'fa-undo', 'color': '#20c997', 'label': 'Retours Services'},
        'menu_stock':           {'url': '/etat-stock/', 'icon': 'fa-boxes', 'color': '#1c5b96', 'label': 'État du Stock'},
        'menu_peremptions':     {'url': '/stock/peremptions/', 'icon': 'fa-calendar-times', 'color': '#ffc107', 'label': 'Péremptions'},
        'menu_destructions':    {'url': '/stock/peremptions/historique/', 'icon': 'fa-trash-alt', 'color': '#dc3545', 'label': 'Destructions'},
        'menu_ajustements':     {'url': '/ajustements/', 'icon': 'fa-sliders-h', 'color': '#6f42c1', 'label': 'Ajustements'},
        'menu_inventaires':     {'url': '/inventaires/', 'icon': 'fa-clipboard-check', 'color': '#28a745', 'label': 'Inventaires'},
        'menu_historique':      {'url': '/administration/historique/', 'icon': 'fa-history', 'color': '#6c757d', 'label': 'Historique'},
        'menu_commandes':       {'url': '/commandes/', 'icon': 'fa-shopping-cart', 'color': '#e83e8c', 'label': 'Commandes'},
        'menu_articles':        {'url': '/articles/', 'icon': 'fa-barcode', 'color': '#0d47a1', 'label': 'Catalogue Articles'},
        'menu_familles':        {'url': '/familles/', 'icon': 'fa-folder-open', 'color': '#fd7e14', 'label': 'Familles'},
        'menu_pat_tickets':     {'url': '/patrimoine/', 'icon': 'fa-tools', 'color': '#20c997', 'label': 'Patrimoine & SAV'},
        'menu_rapports':        {'url': '/rapports/', 'icon': 'fa-chart-line', 'color': '#28a745', 'label': 'Rapports & Exports'},
        'menu_magasins':        {'url': '/parametres/logistique/?open=magasins', 'icon': 'fa-store', 'color': '#ffc107', 'label': 'Magasins'},
        'menu_fournisseurs':    {'url': '/parametres/logistique/?open=fournisseurs', 'icon': 'fa-truck-loading', 'color': '#fd7e14', 'label': 'Fournisseurs'},
        'menu_motifs_annulation': {'url': '/parametres/logistique/motifs-annulation/', 'icon': 'fa-ban', 'color': '#dc3545', 'label': 'Motifs Annulation'},
        'menu_utilisateurs':    {'url': '/accounts/utilisateurs/', 'icon': 'fa-users', 'color': '#1c5b96', 'label': 'Utilisateurs'},
        'menu_roles':           {'url': '/accounts/roles/', 'icon': 'fa-user-shield', 'color': '#0d47a1', 'label': 'Rôles & Accès'},
        'menu_circuits_validation': {'url': '/administration/circuits-validation/', 'icon': 'fa-project-diagram', 'color': '#6f42c1', 'label': 'Circuits Validation'},
        'menu_specialites':     {'url': '/parametres/administratifs/?open=specialites', 'icon': 'fa-user-md', 'color': '#17a2b8', 'label': 'Spécialités'},
        'menu_services':        {'url': '/parametres/administratifs/?open=services', 'icon': 'fa-hospital', 'color': '#28a745', 'label': 'Services'},
        'menu_param_admin':     {'url': '/parametres/administratifs/?open=entreprise', 'icon': 'fa-building', 'color': '#1c5b96', 'label': 'Paramètres Admin'},
    }

    # Superuser = voit tout, utilisateur normal = selon permissions
    if request.user.is_superuser:
        perms_menu = list(MODULES.keys())
    else:
        perms_user = request.user.user_permissions.all() | Permission.objects.filter(group__user=request.user)
        perms_menu = perms_user.filter(codename__startswith='menu_').values_list('codename', flat=True)

    modules_accessibles = []
    for codename in perms_menu:
        if codename in MODULES:
            modules_accessibles.append({**MODULES[codename], 'codename': codename})

    return render(request, 'accounts/accueil.html', {
        'entreprise': entreprise,
        'modules': modules_accessibles,
        'total_modules': len(modules_accessibles),
    })


# ==========================================================
# 🌙 THÈME (API)
# ==========================================================
@login_required
@csrf_exempt
def save_theme_preference(request):
    """Sauvegarde la préférence de thème en BDD + cookie"""
    if request.method != 'POST':
        return JsonResponse({'error': 'Méthode non autorisée'}, status=405)

    try:
        data = json.loads(request.body)
        theme = data.get('theme', 'light')

        if theme not in ['light', 'dark']:
            return JsonResponse({'error': 'Thème invalide'}, status=400)

        # 🔧 CORRECTION : Utiliser Profil (pas UserProfile)
        profil = request.user.profil
        profil.theme_preference = theme
        profil.save(update_fields=['theme_preference'])

        # Crée le cookie de session (30 jours)
        response = JsonResponse({'success': True, 'theme': theme})
        response.set_cookie(
            'theme_pref', 
            theme, 
            max_age=30*24*60*60,
            httponly=False,
            samesite='Lax'
        )
        return response

    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)


# ==========================================================
# 🏢 PARAMÈTRES ENTREPRISE (PERSONNALISATION PDF)
# ==========================================================
@login_required(login_url='/accounts/login/')
def parametres_entreprise(request):
    if not (request.user.is_superuser or request.user.has_perm('accounts.menu_param_admin')):
        messages.error(request, "⛔ Accès réservé.")
        return redirect('/')

    entreprise = request.entreprise
    if not entreprise:
        messages.error(request, "⛔ Aucune entreprise active.")
        return redirect('/')

    if request.method == 'POST':
        form = EntrepriseConfigForm(request.POST, request.FILES, instance=entreprise)
        if form.is_valid():
            instance = form.save(commit=False)
            instance.est_active = True  # FORCE l'activation
            instance.save()
            form.save_m2m()
            messages.success(request, "✅ Configuration entreprise mise à jour avec succès.")
            return redirect('accounts:parametres_entreprise')
        else:
            import json
            erreurs_detail = json.loads(form.errors.as_json())
            for champ, errs in erreurs_detail.items():
                for e in errs:
                    messages.error(request, f"❌ [{champ}] {e['message']}")
    else:
        form = EntrepriseConfigForm(instance=entreprise)

    return render(request, 'accounts/parametres_entreprise.html', {
        'form': form,
        'entreprise': entreprise,
    })
