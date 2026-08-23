"""
Service unifié pour la gestion des paramètres (logistique, administratif,
circuits, motifs, suppression, audit).
Version mono-tenant.
"""
import re
import logging
from datetime import timedelta
from django.utils import timezone
from django.db.models import ProtectedError, Q
from django.shortcuts import get_object_or_404
from django.urls import reverse
from django.core.validators import EmailValidator
from django.core.exceptions import ValidationError
from urllib.parse import urlencode
from django.db import transaction
from core.utils import paginer

from accounts.models import Specialite
from core.models import ConfigurationHopital

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def get_dependances(instance):
    """Retourne la liste des dépendances d'une instance sous forme de strings."""
    from django.core.exceptions import ObjectDoesNotExist

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
                count = 1 if obj is not None else 0
        except ObjectDoesNotExist:
            count = 0
        except Exception as e:
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


def redirect_url_with_tab(url_name, tab, base_url=None):
    """Build a redirect URL with an 'open' query param."""
    url = base_url or reverse(url_name)
    return f"{url}?{urlencode({'open': tab})}"


def check_unique_intitule(model_class, intitule, exclude_pk=None):
    """Vérifie qu'un intitulé n'existe pas déjà."""
    qs = model_class.objects.filter(intitule__iexact=intitule)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return not qs.exists()


def check_unique_nom(model_class, nom, exclude_pk=None):
    """Vérifie qu'un nom n'existe pas déjà."""
    qs = model_class.objects.filter(nom__iexact=nom)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return not qs.exists()


def check_unique_raison_sociale(raison, exclude_pk=None):
    from ..models import Fournisseur
    qs = Fournisseur.objects.filter(raison_sociale__iexact=raison)
    if exclude_pk:
        qs = qs.exclude(pk=exclude_pk)
    return not qs.exists()


# ═══════════════════════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

def get_or_create_logistique_config():
    """Récupère ou crée la ConfigurationHopital (mono-tenant)."""
    config = ConfigurationHopital.objects.first()
    if not config:
        config = ConfigurationHopital.objects.create(nom='Configuration')
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
def save_famille(form, user):
    from ..models import FamilleArticle
    if not form.is_valid():
        return False, "❌ Veuillez corriger les erreurs.", None
    famille = form.save(commit=False)
    if not famille.pk:
        famille.cree_par = user
    famille.modifie_par = user
    if not check_unique_intitule(FamilleArticle, famille.intitule, famille.pk):
        return False, f"⛔ La famille '{famille.intitule}' existe déjà.", None
    famille.save()
    return True, "✅ Famille enregistrée.", famille


@transaction.atomic
def save_fournisseur(data, instance, user):
    from ..models import Fournisseur
    raison = data.get('raison_sociale', '').strip()
    if not raison:
        return False, "⛔ La raison sociale est obligatoire.", None

    if instance:
        fourn = instance
    else:
        fourn = Fournisseur()
        fourn.cree_par = user

    fourn.raison_sociale = raison
    telephone_brut = data.get('telephone', '').strip()
    fourn.telephone = re.sub(r'[^\d+]', '', telephone_brut) if telephone_brut else ''
    fax_brut = data.get('fax', '').strip()
    fourn.fax = re.sub(r'[^\d+]', '', fax_brut) if fax_brut else ''

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

    if not check_unique_raison_sociale(raison, fourn.pk):
        return False, f"⛔ Le fournisseur '{raison}' existe déjà.", None

    fourn.save()
    return True, "✅ Fournisseur enregistré.", fourn


@transaction.atomic
def save_magasin_logistique(form, instance, user):
    if not form.is_valid():
        return False, "❌ Veuillez corriger les erreurs.", None
    magasin = form.save(commit=False)
    if not magasin.pk:
        magasin.cree_par = user
    magasin.modifie_par = user
    magasin.save()
    return True, "✅ Magasin enregistré.", magasin


def save_beneficiaire(data, instance):
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
        nom_complet=nom, poste=poste, service_id=service_id
    )
    return True, "✅ Bénéficiaire ajouté.", b


@transaction.atomic
def save_motif(data, instance, user):
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
        libelle=libelle, cree_par=user, modifie_par=user
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
def save_specialite(data, instance, user):
    nom = data.get('nom', '').strip().upper()
    if not nom:
        return False, "⛔ Le nom de la spécialité est obligatoire.", None

    max_length = getattr(Specialite._meta.get_field('nom'), 'max_length', 100)
    if len(nom) > max_length:
        return False, f"⛔ Le nom de la spécialité ne doit pas dépasser {max_length} caractères.", None

    if instance:
        spe = instance
    else:
        spe = Specialite()
        spe.cree_par = user

    spe.nom = nom
    spe.modifie_par = user

    qs = Specialite.objects.filter(nom__iexact=nom)
    if spe.pk:
        qs = qs.exclude(id=spe.pk)
    if qs.exists():
        return False, f"⛔ La spécialité '{nom}' existe déjà.", None

    spe.save()
    return True, "✅ Spécialité enregistrée.", spe


@transaction.atomic
def save_service(data, instance, user):
    from core.models import Service
    code = data.get('code', '').strip().upper()
    nom = data.get('nom', '').strip()
    if not code or not nom:
        return False, "⛔ Le code et le nom du service sont obligatoires.", None

    if instance:
        service = instance
    else:
        service = Service()
        service.cree_par = user

    service.code = code
    service.nom = nom
    service.poste_telephone = data.get('poste_telephone', '').strip()
    service.telecopie = data.get('telecopie', '').strip()
    service.modifie_par = user

    if Service.objects.filter(nom__iexact=nom).exclude(id=service.id or 0).exists():
        return False, f"⛔ Le service '{nom}' existe déjà.", None
    if Service.objects.filter(code=code).exclude(id=service.id or 0).exists():
        return False, f"⛔ Le code '{code}' est déjà utilisé.", None

    service.save()
    return True, "✅ Service enregistré.", service


@transaction.atomic
def save_magasin_admin(form, instance, user):
    from stock.models import Magasin
    if not form.is_valid():
        return False, "❌ Veuillez corriger les erreurs.", None

    magasin = form.save(commit=False)
    if not magasin.pk:
        magasin.cree_par = user
    magasin.modifie_par = user

    if Magasin.objects.filter(nom__iexact=magasin.nom).exclude(id=magasin.id or 0).exists():
        return False, f"⛔ Le magasin '{magasin.nom}' existe déjà.", None

    magasin.save()
    return True, "✅ Magasin enregistré.", magasin


# ═══════════════════════════════════════════════════════════════════════════════
# SUPPRESSION GÉNÉRIQUE
# ═══════════════════════════════════════════════════════════════════════════════

def supprimer_entite(type_entite, pk, user):
    """
    Supprime une entité selon son type.
    Retourne (success, message, redirect_view_name, redirect_tab).

    NB : le mapping couvre les 9 types acceptés par la vue
    parametres/suppression.py (perm_map) — sinon un type autorisé côté
    permission échouait systématiquement côté service.
    """
    from ..models import (
        FamilleArticle, Fournisseur, Article, Magasin,
        MotifAnnulation, Beneficiaire,
    )
    from core.models import Service
    from accounts.models import Specialite, Fonction

    mapping = {
        'famille': (FamilleArticle, 'liste_familles', None, True),
        'fournisseur': (Fournisseur, 'parametres_logistique', 'fournisseurs', True),
        'service': (Service, 'parametres_administratifs', 'services', False),
        'article': (Article, 'liste_articles', None, True),
        'magasin': (Magasin, 'parametres_logistique', 'magasins', True),
        'specialite': (Specialite, 'parametres_administratifs', 'specialites', True),
        'fonction': (Fonction, 'parametres_administratifs', 'fonctions', True),
        'beneficiaire': (Beneficiaire, 'parametres_logistique', 'beneficiaires', True),
        'motif': (MotifAnnulation, 'parametres_logistique', 'motifs', True),
    }

    if type_entite not in mapping:
        return False, "⛔ Type d'entité non reconnu.", None, None

    model_class, url_name, tab, soft = mapping[type_entite]
    instance = get_object_or_404(model_class, id=pk)
    deps = get_dependances(instance)
    if deps:
        return False, f"⛔ Impossible de supprimer : utilisé par {', '.join(deps)}.", url_name, tab

    try:
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
        'magasin': "Magasin supprimé",
        'specialite': "Spécialité supprimée",
        'fonction': "Fonction supprimée",
        'beneficiaire': "Bénéficiaire supprimé",
        'motif': "Motif d'annulation supprimé",
    }
    return True, f"🗑️ {labels[type_entite]} avec succès.", url_name, tab


# ═══════════════════════════════════════════════════════════════════════════════
# CIRCUITS DE VALIDATION
# ═══════════════════════════════════════════════════════════════════════════════

@transaction.atomic
def update_circuit(circuit_id, est_actif, valideurs_ids):
    from ..models import CircuitValidation, CircuitValidateur
    from django.contrib.auth.models import User

    circuit = get_object_or_404(CircuitValidation, id=circuit_id)
    circuit.est_actif = est_actif
    circuit.save()

    # M2M avec through explicite (CircuitValidateur) : .set()/.clear() interdits
    # -> gérer les lignes through directement, avec ordre incrémental
    CircuitValidateur.objects.filter(circuit=circuit).delete()
    if valideurs_ids:
        utilisateurs = User.objects.filter(id__in=valideurs_ids, is_active=True)
        CircuitValidateur.objects.bulk_create([
            CircuitValidateur(circuit=circuit, valideur=u, ordre=i + 1)
            for i, u in enumerate(utilisateurs)
        ])
    return circuit


# ═══════════════════════════════════════════════════════════════════════════════
# AUDIT
# ═══════════════════════════════════════════════════════════════════════════════

class AuditDataBuilder:
    def __init__(self, request):
        self.request = request
        self.aujourdhui = timezone.now()
        self.trente_jours = self.aujourdhui - timedelta(days=30)

    def build_evenements_queryset(self):
        from accounts.models import AuditConnexion
        qs = AuditConnexion.objects.select_related('utilisateur').filter(
            date_creation__gte=self.trente_jours
        )
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
        return AuditConnexion.objects.filter(date_creation__gte=self.trente_jours)

    def build_log_entries(self):
        from django.contrib.admin.models import LogEntry
        return LogEntry.objects.select_related('user', 'content_type').filter(
            action_time__gte=self.trente_jours
        ).order_by('-action_time')

    def paginate(self, queryset, per_page_key='per_page', default=25):
        from django.core.paginator import Paginator
        per_page = self.request.GET.get(per_page_key, str(default))
        if per_page == 'all':
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
    builder = AuditDataBuilder(request)
    return builder.build()


# ═══════════════════════════════════════════════════════════════════════════════
# UTILITAIRES TRANSVERSES
# ═══════════════════════════════════════════════════════════════════════════════

def parse_optional_id(request, post_key, get_key=None):
    """Parse un ID optionnel depuis POST puis GET en fallback."""
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
    Supprime ou désactive un objet selon ses capacités.
    Ordre de priorité : soft_delete → is_deleted → est_actif/actif/is_active → delete()
    """
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