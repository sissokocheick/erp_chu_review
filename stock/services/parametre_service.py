"""
Service unifié pour la gestion des paramètres (logistique, administratif,
circuits, motifs, suppression, audit).
"""
import re
from datetime import timedelta
from django.utils import timezone
from django.db.models import ProtectedError, Q
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.core.validators import EmailValidator
from urllib.parse import urlencode

from accounts.models import Specialite
from core.models import ConfigurationHopital
from django.db import transaction



# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def get_dependances(instance):
    """Retourne la liste des dépendances d'une instance sous forme de strings."""
    import logging
    from django.core.exceptions import ObjectDoesNotExist
    logger = logging.getLogger(__name__)

    dependances = []
    for rel in instance._meta.related_objects:
        if rel.related_model.__name__.startswith('Historical'):
            continue
        if rel.related_model._meta.app_label in ('admin', 'sessions', 'contenttypes'):
            continue
        accessor = rel.get_accessor_name()
        try:
            obj = getattr(instance, accessor)
            if hasattr(obj, 'count'):
                count = obj.count()
            else:
                # OneToOneField retourne un objet directement, pas un manager
                count = 1 if obj is not None else 0
        except ObjectDoesNotExist:
            count = 0
        except Exception as e:
            # ✅ CORRECTION : logger l'erreur au lieu de silencier
            logger.warning(
                f"Erreur lors du comptage des dépendances pour {instance.__class__.__name__}: {e}"
            )
            continue
        if count > 0:
            nom = getattr(
                rel.related_model._meta,
                'verbose_name_plural',
                rel.related_model.__name__
            )
            dependances.append(f"{nom} ({count})")
    return dependances


def paginer_donnees(queryset, request, prefixe):
    """Paginate a queryset with per-page control via GET parameters."""
    from django.core.paginator import Paginator
    per_page = request.GET.get(f'per_page_{prefixe}', '10')
    try:
        if per_page == 'all':
            # ✅ CORRECTION : plafonner à 1000 pour éviter OOM
            count = queryset.count()
            limite = min(count, 1000) if count > 0 else 1
        else:
            limite = int(per_page)
    except ValueError:
        limite = 10
    paginator = Paginator(queryset, limite)
    page_number = request.GET.get(f'page_{prefixe}')
    return paginator.get_page(page_number), per_page


def redirect_url_with_tab(url_name, tab, base_url=None):
    """Build a redirect URL with an 'open' query param."""
    url = base_url or reverse(url_name)
    return f"{url}?{urlencode({'open': tab})}"


def check_unique_intitule(model_class, intitule, entreprise, exclude_pk=None):
    """Vérifie qu'un intitulé n'existe pas déjà pour cette entreprise."""
    qs = model_class.objects.filter(entreprise=entreprise, intitule__iexact=intitule)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return not qs.exists()


def check_unique_nom(model_class, nom, entreprise, exclude_pk=None):
    """Vérifie qu'un nom n'existe pas déjà pour cette entreprise."""
    qs = model_class.objects.filter(entreprise=entreprise, nom__iexact=nom)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return not qs.exists()


def check_unique_raison_sociale(entreprise, raison, exclude_pk=None):
    from ..models import Fournisseur
    qs = Fournisseur.objects.filter(entreprise=entreprise, raison_sociale__iexact=raison)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return not qs.exists()


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

def get_or_create_logistique_config(entreprise):
    """Récupère ou crée la ConfigurationHopital pour l'entreprise."""
    config = ConfigurationHopital.objects.filter(entreprise=entreprise).first()
    if not config:
        config = ConfigurationHopital.objects.filter(entreprise__isnull=True).first()
        if config:
            config.entreprise = entreprise
            config.save()
    if not config:
        config = ConfigurationHopital.objects.create(entreprise=entreprise, nom='Configuration')
    return config


def save_delai_remplacement(config, delai_str):
    """Valide et sauvegarde le délai de remplacement (jours)."""
    try:
        delai_int = int(delai_str)
        if delai_int < 0 or delai_int > 365:
            raise ValueError
        config.delai_remplacement_bon_jours = delai_int
        config.save()
        return True, f"✅ Délai de remplacement mis à jour : {delai_int} jour(s).", None
    except ValueError:
        return False, "⛔ Le délai doit être un nombre entier entre 0 et 365.", None


def save_confidentialite_demandes(config, valeur):
    """Valide et sauvegarde le paramètre de confidentialité des demandes."""
    choix_valides = dict(ConfigurationHopital.CONFIDENTIALITE_CHOICES)
    if valeur not in choix_valides:
        return False, "⛔ Valeur de confidentialité invalide.", None
    config.confidentialite_demandes = valeur
    config.save(update_fields=['confidentialite_demandes'])
    label = choix_valides.get(valeur, valeur)
    return True, f"✅ Confidentialité des demandes mise à jour : {label}.", None


# ═══════════════════════════════════════════════════════════════════════════════
# LOGISTIQUE — CRUD
# ═══════════════════════════════════════════════════════════════════════════════

@transaction.atomic
def save_famille(form, entreprise, user):
    from ..models import FamilleArticle
    if not form.is_valid():
        return False, "❌ Veuillez corriger les erreurs.", None
    famille = form.save(commit=False)
    famille.entreprise = entreprise
    if not famille.pk:
        famille.cree_par = user
    famille.modifie_par = user
    if not check_unique_intitule(FamilleArticle, famille.intitule, entreprise, famille.pk):
        return False, f"⛔ La famille '{famille.intitule}' existe déjà.", None
    famille.save()
    return True, "✅ Famille enregistrée.", famille


@transaction.atomic
def save_fournisseur(data, instance, entreprise, user):
    from ..models import Fournisseur
    raison = data.get('raison_sociale', '').strip()
    if not raison:
        return False, "⛔ La raison sociale est obligatoire.", None
    if instance:
        fourn = instance
    else:
        fourn = Fournisseur()
        fourn.entreprise = entreprise
        fourn.cree_par = user
    fourn.raison_sociale = raison
    # ✅ CORRECTION : nettoyer tous les caractères non numériques
    telephone_brut = data.get('telephone', '').strip()
    fourn.telephone = re.sub(r'[^\d+]', '', telephone_brut) if telephone_brut else ''
    fax_brut = data.get('fax', '').strip()
    fourn.fax = re.sub(r'[^\d+]', '', fax_brut) if fax_brut else ''

    # ✅ CORRECTION : validation email avec EmailValidator Django
    email = data.get('email', '').strip()
    if email:
        validator = EmailValidator()
        try:
            validator(email)
        except ValidationError:
            return False, f"⛔ L'email '{email}' n'est pas valide.", None
    fourn.email = email

    fourn.adresse = data.get('adresse', '').strip()
    fourn.modifie_par = user
    if not check_unique_raison_sociale(entreprise, raison, fourn.pk):
        return False, f"⛔ Le fournisseur '{raison}' existe déjà.", None
    fourn.save()
    return True, "✅ Fournisseur enregistré.", fourn


@transaction.atomic
def save_magasin_logistique(form, instance, entreprise, user):
    if not form.is_valid():
        return False, "❌ Veuillez corriger les erreurs.", None
    magasin = form.save(commit=False)
    magasin.entreprise = entreprise
    if not magasin.pk:
        magasin.cree_par = user
    magasin.modifie_par = user
    magasin.save()
    return True, "✅ Magasin enregistré.", magasin


def save_beneficiaire(data, instance, entreprise):
    from ..models import Beneficiaire
    nom = data.get('nom_complet', '').strip()
    poste = data.get('poste', '').strip()
    service_id = data.get('service') or None
    if instance:
        instance.nom_complet = nom
        instance.poste = poste
        instance.service_id = service_id
        instance.save()
        return True, "✅ Bénéficiaire mis à jour.", instance
    b = Beneficiaire.objects.create(
        nom_complet=nom, poste=poste, service_id=service_id, entreprise=entreprise
    )
    return True, "✅ Bénéficiaire ajouté.", b


@transaction.atomic
def save_motif(data, instance, entreprise, user):
    from ..models import MotifAnnulation
    libelle = data.get('libelle', '').strip().upper()
    if not libelle:
        return False, "⛔ Le libellé est obligatoire.", None
    if instance:
        instance.libelle = libelle
        instance.modifie_par = user
        instance.save()
        return True, "✅ Motif modifié.", instance
    m = MotifAnnulation.objects.create(
        libelle=libelle, entreprise=entreprise, cree_par=user, modifie_par=user
    )
    return True, "✅ Nouveau motif ajouté.", m


def toggle_motif(motif, user):
    motif.actif = not motif.actif
    motif.modifie_par = user
    motif.save()
    statut = "activé" if motif.actif else "désactivé"
    return True, f"✅ Le motif '{motif.libelle}' a été {statut}.", motif


# ═══════════════════════════════════════════════════════════════════════════════
# ADMINISTRATIF — CRUD
# ═══════════════════════════════════════════════════════════════════════════════

@transaction.atomic
def save_specialite(data, instance, entreprise, user):
    nom = data.get('nom', '').strip().upper()
    if not nom:
        return False, "⛔ Le nom de la spécialité est obligatoire.", None
    # ✅ CORRECTION : vérification de longueur dynamique via max_length du modèle
    max_length = getattr(Specialite._meta.get_field('nom'), 'max_length', 100)
    if len(nom) > max_length:
        return False, f"⛔ Le nom de la spécialité ne doit pas dépasser {max_length} caractères.", None
    if instance:
        spe = instance
    else:
        spe = Specialite()
        spe.entreprise = entreprise
        spe.cree_par = user
    spe.nom = nom
    spe.modifie_par = user
    if Specialite.objects.filter(entreprise=entreprise, nom__iexact=nom).exclude(id=spe.id).exists():
        return False, f"⛔ La spécialité '{nom}' existe déjà.", None
    spe.save()
    return True, "✅ Spécialité enregistrée.", spe


@transaction.atomic
def save_service(data, instance, entreprise, user):
    from ..models import Service
    code = data.get('code', '').strip().upper()
    nom = data.get('nom', '').strip()
    if not code or not nom:
        return False, "⛔ Le code et le nom du service sont obligatoires.", None
    if instance:
        service = instance
    else:
        service = Service()
        service.entreprise = entreprise
        service.cree_par = user
    service.code = code
    service.nom = nom
    service.poste_telephone = data.get('poste_telephone', '').strip()
    service.telecopie = data.get('telecopie', '').strip()
    service.modifie_par = user
    if Service.objects.filter(entreprise=entreprise, nom__iexact=nom).exclude(id=service.id).exists():
        return False, f"⛔ Le service '{nom}' existe déjà.", None
    if Service.objects.filter(entreprise=entreprise, code=code).exclude(id=service.id).exists():
        return False, f"⛔ Le code '{code}' est déjà utilisé.", None
    service.save()
    return True, "✅ Service enregistré.", service


@transaction.atomic
def save_magasin_admin(form, instance, entreprise, user):
    from ..models import Magasin
    if not form.is_valid():
        return False, "❌ Veuillez corriger les erreurs.", None
    magasin = form.save(commit=False)
    magasin.entreprise = entreprise
    if not magasin.pk:
        magasin.cree_par = user
    magasin.modifie_par = user
    if Magasin.objects.filter(entreprise=entreprise, nom__iexact=magasin.nom).exclude(id=magasin.id).exists():
        return False, f"⛔ Le magasin '{magasin.nom}' existe déjà.", None
    magasin.save()
    return True, "✅ Magasin enregistré.", magasin


def save_config_document(request, entreprise_obj):
    from accounts.models import ConfigDocument
    doc_type = request.POST.get('doc_type')
    try:
        config = ConfigDocument.objects.get(entreprise=entreprise_obj, type_doc=doc_type)
        config.code_document = request.POST.get(f'code_document_{doc_type}', '').strip()
        config.date_creation_doc = request.POST.get(f'date_creation_doc_{doc_type}', '').strip()
        config.date_revision_doc = request.POST.get(f'date_revision_doc_{doc_type}', '').strip()
        config.version_doc = request.POST.get(f'version_doc_{doc_type}', '').strip()
        config.ps2_label = request.POST.get(f'ps2_label_{doc_type}', '').strip()
        config.afficher_logo = request.POST.get(f'afficher_logo_{doc_type}') == 'on'
        config.afficher_cachet = request.POST.get(f'afficher_cachet_{doc_type}') == 'on'
        config.afficher_cc = request.POST.get(f'afficher_cc_{doc_type}') == 'on'
        config.afficher_ifu = request.POST.get(f'afficher_ifu_{doc_type}') == 'on'
        config.afficher_rccm = request.POST.get(f'afficher_rccm_{doc_type}') == 'on'
        config.afficher_telephone = request.POST.get(f'afficher_telephone_{doc_type}') == 'on'
        config.afficher_signatures = request.POST.get(f'afficher_signatures_{doc_type}') == 'on'
        config.save()
        return True, f"✅ Configuration {config.get_type_doc_display()} enregistrée.", None
    except ConfigDocument.DoesNotExist:
        return False, "Configuration introuvable.", None


def save_entreprise_form(form, request):
    if form.is_valid():
        form.save()
        return True, "✅ Identité et cartouche PDF de l'entreprise mises à jour.", None
    return False, "❌ Veuillez corriger les erreurs dans le formulaire entreprise.", form.errors


# ═══════════════════════════════════════════════════════════════════════════════
# SUPPRESSION GÉNÉRIQUE
# ═══════════════════════════════════════════════════════════════════════════════

def supprimer_entite(type_entite, pk, entreprise, user):
    """
    Supprime une entité selon son type.
    Retourne (success, message, redirect_view_name, redirect_tab).
    """
    from ..models import FamilleArticle, Fournisseur, Service, Article

    mapping = {
        'famille': (FamilleArticle, 'liste_familles', None, True),
        'fournisseur': (Fournisseur, 'parametres_logistique', 'fournisseurs', True),
        'service': (Service, 'parametres_administratifs', 'services', False),
        'article': (Article, 'liste_articles', None, True),
    }

    if type_entite not in mapping:
        return False, "⛔ Type d'entité non reconnu.", None, None

    model_class, url_name, tab, soft = mapping[type_entite]
    instance = get_object_or_404(model_class, id=pk, entreprise=entreprise)
    deps = get_dependances(instance)
    if deps:
        return False, f"⛔ Impossible de supprimer : utilisé par {', '.join(deps)}.", url_name, tab

    try:
        # ✅ CORRECTION : vérifier que soft_delete existe avant d'appeler
        if soft and hasattr(instance, 'soft_delete') and callable(getattr(instance, 'soft_delete')):
            instance.soft_delete(user)
        else:
            instance.delete()
    except ProtectedError:
        return False, "⛔ Suppression impossible : Cet élément est déjà utilisé dans le système.", url_name, tab

    labels = {
        'famille': "Famille supprimée",
        'fournisseur': "Fournisseur supprimé",
        'service': "Service supprimé",
        'article': "Article supprimé du catalogue",
    }
    return True, f"🗑️ {labels[type_entite]} avec succès.", url_name, tab


# ═══════════════════════════════════════════════════════════════════════════════
# CIRCUITS DE VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════

@transaction.atomic
def update_circuit(circuit_id, est_actif, valideurs_ids, entreprise):
    from ..models import CircuitValidation
    from django.contrib.auth.models import User
    circuit = get_object_or_404(CircuitValidation, id=circuit_id, entreprise=entreprise)
    circuit.est_actif = est_actif
    circuit.save()
    if valideurs_ids:
        utilisateurs = User.objects.filter(
            id__in=valideurs_ids, is_active=True, profil__entreprise=entreprise
        )
        circuit.valideurs.set(utilisateurs)
    else:
        circuit.valideurs.clear()
    return circuit


# ═══════════════════════════════════════════════════════════════════════════════
# AUDIT
# ═══════════════════════════════════════════════════════════════════════════════

class AuditDataBuilder:
    """
    ✅ CORRECTION : Classe builder pour découper get_audit_data en méthodes cohérentes.
    """

    def __init__(self, request):
        self.request = request
        self.aujourdhui = timezone.now()
        self.trente_jours = self.aujourdhui - timedelta(days=30)
        self.entreprise_user = self._get_entreprise_user()

    def _get_entreprise_user(self):
        try:
            return self.request.user.profil.entreprise
        except Exception:
            return None

    def build_evenements_queryset(self):
        from accounts.models import AuditConnexion
        qs = AuditConnexion.objects.select_related('utilisateur').filter(
            date_creation__gte=self.trente_jours
        )
        if self.entreprise_user:
            qs = qs.filter(utilisateur__profil__entreprise=self.entreprise_user)

        q = self.request.GET.get('q', '')
        type_filtre = self.request.GET.get('type_filtre', '')
        if q:
            qs = qs.filter(
                Q(utilisateur__username__icontains=q) |
                Q(utilisateur__first_name__icontains=q) |
                Q(utilisateur__last_name__icontains=q) |
                Q(adresse_ip__icontains=q) |
                Q(description__icontains=q)
            )
        if type_filtre:
            qs = qs.filter(type_action=type_filtre)
        return qs.order_by('-date_creation')

    def build_base_audit_qs(self):
        from accounts.models import AuditConnexion
        qs = AuditConnexion.objects.filter(date_creation__gte=self.trente_jours)
        if self.entreprise_user:
            qs = qs.filter(utilisateur__profil__entreprise=self.entreprise_user)
        return qs

    def build_log_entries(self):
        from django.contrib.admin.models import LogEntry
        qs = LogEntry.objects.select_related('user', 'content_type').filter(
            action_time__gte=self.trente_jours
        )
        if self.entreprise_user:
            qs = qs.filter(user__profil__entreprise=self.entreprise_user)
        return qs.order_by('-action_time')

    def paginate(self, queryset, per_page_key='per_page', default=25):
        from django.core.paginator import Paginator
        per_page = self.request.GET.get(per_page_key, str(default))
        if per_page == 'all':
            # ✅ CORRECTION : plafonner pour éviter OOM
            count = queryset.count()
            limite = min(count, 1000) if count > 0 else 1
        elif per_page.isdigit():
            limite = int(per_page)
        else:
            limite = default
        paginator = Paginator(queryset, limite)
        page_number = self.request.GET.get('page')
        return paginator.get_page(page_number)

    def build(self):
        from django.core.paginator import Paginator

        evenements = self.build_evenements_queryset()
        base_audit = self.build_base_audit_qs()
        log_entries_qs = self.build_log_entries()

        total_connexions = base_audit.filter(type_action='CONNEXION').count()
        total_echecs = base_audit.filter(type_action='ECHEC').count()
        total_admin = base_audit.filter(type_action='ADMIN').count()
        utilisateurs_actifs = base_audit.filter(
            type_action='CONNEXION'
        ).values('utilisateur').distinct().count()

        log_paginator = Paginator(log_entries_qs, 50)
        log_page = log_paginator.get_page(self.request.GET.get('page_log'))

        page_obj = self.paginate(evenements)

        return {
            'page_obj': page_obj,
            'q': self.request.GET.get('q', ''),
            'type_filtre': self.request.GET.get('type_filtre', ''),
            'total_connexions': total_connexions,
            'total_echecs': total_echecs,
            'total_admin': total_admin,
            'utilisateurs_actifs': utilisateurs_actifs,
            'log_entries': log_page.object_list,
            'log_page_obj': log_page,
        }


def get_audit_data(request):
    """
    ✅ CORRECTION : Délègue à AuditDataBuilder pour réduire la complexité.
    """
    builder = AuditDataBuilder(request)
    return builder.build()


# ═══════════════════════════════════════════════════════════════════════════════
# UTILITAIRES TRANSVERSES (ajoutés pour factoriser les vues)
# ═══════════════════════════════════════════════════════════════════════════════

def parse_optional_id(request, post_key, get_key=None):
    """
    Parse un ID optionnel depuis POST puis GET en fallback.
    Gère les valeurs 'none', 'null', 'undefined', ''.

    Args:
        request: HttpRequest
        post_key: Clé dans request.POST (ex: 'service_id')
        get_key: Clé optionnelle dans request.GET (ex: 'edit_service')

    Returns:
        int or None: L'ID parsé ou None
    """
    raw_id = request.POST.get(post_key, '').strip()
    edit_id = None
    if raw_id and raw_id.lower() not in ('none', 'null', 'undefined', ''):
        try:
            edit_id = int(raw_id)
        except ValueError:
            edit_id = None
    if not edit_id and get_key:
        raw_get = request.GET.get(get_key, '').strip()
        if raw_get and raw_get.lower() not in ('none', 'null', 'undefined', ''):
            try:
                edit_id = int(raw_get)
            except ValueError:
                edit_id = None
    return edit_id


def safe_delete_entity(obj, user=None):
    """
    Supprime ou désactive un objet selon ses capacités, en privilégiant
    le soft delete.

    Ordre de priorité:
    1. soft_delete() si disponible
    2. is_deleted = True
    3. est_actif / actif / is_active = False
    4. delete() en dernier recours (hard delete)

    Args:
        obj: Instance de modèle à supprimer/désactiver
        user: Utilisateur effectuant l'action (pour audit)

    Returns:
        bool: True si l'opération a réussi
    """
    import logging
    logger = logging.getLogger(__name__)

    try:
        if hasattr(obj, 'soft_delete') and callable(getattr(obj, 'soft_delete')):
            obj.soft_delete(user)
            logger.info(f"Soft delete sur {obj.__class__.__name__} #{obj.pk} par {user}")
            return True
        if hasattr(obj, 'is_deleted'):
            obj.is_deleted = True
            obj.save(update_fields=['is_deleted'])
            logger.info(f"Flag is_deleted sur {obj.__class__.__name__} #{obj.pk} par {user}")
            return True
        for attr in ('est_actif', 'actif', 'is_active'):
            if hasattr(obj, attr):
                setattr(obj, attr, False)
                obj.save(update_fields=[attr])
                logger.info(f"Desactivation ({attr}) sur {obj.__class__.__name__} #{obj.pk} par {user}")
                return True
        obj.delete()
        logger.warning(f"Hard delete sur {obj.__class__.__name__} #{obj.pk} par {user}")
        return True
    except Exception as e:
        logger.error(f"Erreur lors de la suppression de {obj.__class__.__name__} #{obj.pk}: {e}")
        raise
