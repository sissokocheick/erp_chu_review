# core/models.py — MONO-TENANT v1
"""
MIGRATION MONO-TENANT — Résumé des changements :
1. Le champ `entreprise` est supprimé de ConfigurationHopital et Service.
2. ConfigurationHopital absorbe TOUTE la personnalisation qui était dans
   accounts.Entreprise (logo, cachet, couleurs, préfixes, signataires, PDF).
   Elle devient le SINGLETON de configuration de l'établissement.
3. TenantManager / GlobalManager ne sont plus utilisés ici.
   ⚠️ NE PAS supprimer core/managers.py ni core/signals.py tant que le
   module stock n'est pas migré (il les utilise encore).
4. Les contraintes unique restent gérées manuellement en base (cf. note v5).
"""
from django.db import models, transaction
from django.contrib.auth.models import User
from django.utils import timezone
from simple_history.models import HistoricalRecords


class TraceabiliteMixin(models.Model):
    """
    Mixin abstrait pour la traçabilité.

    ⚠️ LEGACY : date_creation/date_modification sont des CharField pour
    compatibilité avec les données existantes.
    Utiliser created_at/updated_at pour les nouvelles données DateTime.
    """
    date_creation = models.CharField(
        max_length=50, null=True, blank=True,
        verbose_name="Date de création (legacy)"
    )
    date_modification = models.CharField(
        max_length=50, null=True, blank=True,
        verbose_name="Dernière modification (legacy)"
    )

    created_at = models.DateTimeField(
        auto_now_add=True, null=True, blank=True,
        verbose_name="Date de création"
    )
    updated_at = models.DateTimeField(
        auto_now=True, null=True, blank=True,
        verbose_name="Dernière modification"
    )

    cree_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='%(class)s_crees', verbose_name="Créé par"
    )
    modifie_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='%(class)s_modifies', verbose_name="Modifié par"
    )

    class Meta:
        abstract = True


# ==========================================================
# 🏥 CONFIGURATION UNIQUE DE L'ÉTABLISSEMENT (SINGLETON)
# ==========================================================
class ConfigurationHopital(TraceabiliteMixin):
    """
    Singleton de configuration de l'établissement (mono-tenant).

    Regroupe :
    - les paramètres fonctionnels (mots de passe, confidentialité, délais)
    - l'identité visuelle PDF (logo, cachet, couleur)  ← ex-Entreprise
    - les coordonnées légales (CC, IFU, RCCM)          ← ex-Entreprise
    - la numérotation des documents (préfixes)          ← ex-Entreprise
    - les labels des 6 signataires                      ← ex-Entreprise

    Accès : toujours passer par ConfigurationHopital.get_instance()
    """

    # ── Identité ──
    nom = models.CharField(max_length=200, default="CHU - Centre Hospitalier")
    adresse = models.TextField(blank=True, null=True)
    telephone = models.CharField(max_length=50, blank=True, null=True)
    email_contact = models.EmailField(max_length=254, blank=True, null=True, verbose_name="Email de contact")
    ville = models.CharField(max_length=100, blank=True, null=True)
    pays = models.CharField(max_length=100, blank=True, default="Côte d'Ivoire")

    # ── Paramètres fonctionnels ──
    TYPE_MDP_CHOICES = [
        ('ALEATOIRE', '🔀 Aléatoire (sécurisé) — Le système génère un mot de passe fort'),
        ('FIXE', "🔒 Mot de passe fixe — L'admin définit un mot de passe par défaut"),
    ]

    type_mot_de_passe = models.CharField(
        max_length=20,
        choices=TYPE_MDP_CHOICES,
        default='ALEATOIRE',
        verbose_name="Politique de mot de passe pour les nouveaux utilisateurs",
        help_text="Choisissez comment les mots de passe sont attribués lors de la création de comptes."
    )

    mot_de_passe_defaut = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name="Mot de passe par défaut (si mode 'Fixe' choisit)",
        help_text="Ce mot de passe sera utilisé pour tous les nouveaux comptes créés par les admins."
    )

    delai_remplacement_bon_jours = models.PositiveIntegerField(
        default=2,
        verbose_name="Delai remplacement bon livraison (jours)"
    )

    obliger_reception_precedente = models.BooleanField(
        default=False,
        verbose_name="Obliger la reception de la livraison precedente",
        help_text="Si active, un utilisateur ne peut pas faire une nouvelle demande tant qu il n a pas signe l accuse de reception de sa livraison precedente."
    )

    CONFIDENTIALITE_CHOICES = [
        ('PERSONNELLE', '👤 Personnelle — Chaque agent ne voit que SES propres demandes'),
        ('SERVICE',     '👥 Par Service — Tous les agents du même service voient les demandes de leurs collègues'),
    ]

    confidentialite_demandes = models.CharField(
        max_length=20,
        choices=CONFIDENTIALITE_CHOICES,
        default='PERSONNELLE',
        verbose_name="Confidentialité des demandes de matériel",
        help_text="Définit qui peut voir les demandes dans 'Mes Demandes' : seulement le demandeur, ou tous les agents du même service."
    )

    # ── Identité visuelle (ex-Entreprise) ──
    logo = models.ImageField(
        upload_to='config/logos/%Y/%m/',
        null=True, blank=True,
        verbose_name="Logo (PDF & UI)",
        help_text="Format PNG/JPG, max 2 Mo. Recommandé : 300×120 px."
    )
    cachet = models.ImageField(
        upload_to='config/cachets/%Y/%m/',
        null=True, blank=True,
        verbose_name="Cachet / Tampon",
        help_text="Format PNG transparent, max 2 Mo."
    )
    couleur_principale = models.CharField(
        max_length=7,
        default='#1c5b96',
        help_text="Code hexadécimal (ex: #1c5b96)",
        verbose_name="Couleur principale"
    )

    # ── Coordonnées légales (ex-Entreprise) ──
    cc = models.CharField(max_length=50, blank=True, verbose_name="Compte Contribuable (CC)")
    ifu = models.CharField(max_length=50, blank=True, verbose_name="IFU")
    rccm = models.CharField(max_length=50, blank=True, verbose_name="RCCM")

    # ── Hiérarchie affichée sur les documents (ex-Entreprise) ──
    direction_label = models.CharField(max_length=200, default="DIRECTION DES AFFAIRES FINANCIÈRES", verbose_name="Label Direction")
    sous_direction_label = models.CharField(max_length=200, default="SOUS-DIRECTION DE LA LOGISTIQUE", verbose_name="Label Sous-Direction")
    service_label = models.CharField(max_length=200, default="SERVICE APPROVISIONNEMENT ET GESTION DES STOCKS", verbose_name="Label Service")
    pied_page_pdf = models.TextField(default="Document généré par NexusERP – Tous droits réservés.", verbose_name="Pied de page PDF")

    # ── Numérotation personnalisable (ex-Entreprise) ──
    prefixe_bon_sortie = models.CharField(max_length=10, default="BS", verbose_name="Préfixe Bon de Sortie")
    prefixe_bon_entree = models.CharField(max_length=10, default="BE", verbose_name="Préfixe Bon d'Entrée")
    prefixe_bon_retour = models.CharField(max_length=10, default="BR", verbose_name="Préfixe Bon de Retour")
    prefixe_bon_hors_stock = models.CharField(max_length=10, default="BSHS", verbose_name="Préfixe Bon Hors Stock")
    prefixe_commande = models.CharField(max_length=10, default="BC", verbose_name="Préfixe Commande")

    # ── Labels des 6 emplacements de signature (ex-Entreprise) ──
    label_signataire_1 = models.CharField(max_length=100, default="Le Demandeur", verbose_name="Signataire 1")
    label_signataire_2 = models.CharField(max_length=100, default="Le Magasinier", verbose_name="Signataire 2")
    label_signataire_3 = models.CharField(max_length=100, default="Le Responsable Service", verbose_name="Signataire 3")
    label_signataire_4 = models.CharField(max_length=100, default="Le Directeur", verbose_name="Signataire 4")
    label_signataire_5 = models.CharField(max_length=100, default="Le Contrôleur", verbose_name="Signataire 5")
    label_signataire_6 = models.CharField(max_length=100, default="Le Réceptionnaire", verbose_name="Signataire 6")

    history = HistoricalRecords()

    class Meta:
        verbose_name = "Configuration de l'établissement"
        verbose_name_plural = "Configuration de l'établissement"
        # ✅ Pas de constraints ici — gérées manuellement en SQL

    def __str__(self):
        return self.nom

    # ======================================================
    # SINGLETON
    # ======================================================
    @classmethod
    def get_instance(cls):
        """Retourne l'unique instance de configuration (la crée si absente)."""
        instance = cls.objects.first()
        if instance is None:
            instance = cls.objects.create(nom="CHU - Centre Hospitalier")
        return instance

    # ======================================================
    # VALIDATIONS (ex-Entreprise.clean)
    # ======================================================
    def clean(self):
        import os, re
        from django.core.exceptions import ValidationError
        # ── Validation logo ──
        if self.logo:
            if not self.logo.name:
                raise ValidationError({'logo': "Aucun fichier logo sélectionné."})
            ext = os.path.splitext(self.logo.name)[1].lower()
            if ext not in ['.png', '.jpg', '.jpeg']:
                raise ValidationError({'logo': "Le logo doit être au format PNG ou JPG."})
            if self.logo.size > 2 * 1024 * 1024:
                raise ValidationError({'logo': "Le logo ne doit pas dépasser 2 Mo."})
        # ── Validation cachet ──
        if self.cachet:
            if not self.cachet.name:
                raise ValidationError({'cachet': "Aucun fichier cachet sélectionné."})
            ext = os.path.splitext(self.cachet.name)[1].lower()
            if ext not in ['.png', '.jpg', '.jpeg']:
                raise ValidationError({'cachet': "Le cachet doit être au format PNG ou JPG."})
            if self.cachet.size > 2 * 1024 * 1024:
                raise ValidationError({'cachet': "Le cachet ne doit pas dépasser 2 Mo."})
        # ── Validation couleur ──
        if self.couleur_principale:
            if not re.match(r'^#[0-9A-Fa-f]{6}$', self.couleur_principale):
                raise ValidationError({'couleur_principale': "La couleur doit être un code hexadécimal valide (ex: #1c5b96)."})

    # ======================================================
    # NUMÉROTATION DES DOCUMENTS (ex-Entreprise)
    # ======================================================
    def generer_numero(self, type_doc, annee=None):
        """
        Génère le prochain numéro de document.

        ⚠️ DÉPENDANCE : fonctionnera après migration du modèle
        stock.CompteurDocument (le champ `entreprise` y sera supprimé
        au module stock). Le suffixe "-E{id}" disparaît du format.
        """
        from stock.models import CompteurDocument
        if annee is None:
            annee = timezone.now().year

        prefix_map = {
            'BON_SORTIE': self.prefixe_bon_sortie,
            'BON_ENTREE': self.prefixe_bon_entree,
            'BON_RETOUR': self.prefixe_bon_retour,
            'BON_HS': self.prefixe_bon_hors_stock,
            'COMMANDE': self.prefixe_commande,
            'DEMANDE': 'DM',
        }
        prefixe = prefix_map.get(type_doc, 'DOC')

        with transaction.atomic():
            compteur, created = CompteurDocument.objects.select_for_update().get_or_create(
                type_doc=type_doc,
                annee=annee,
                defaults={'dernier_numero': 0}
            )
            compteur.dernier_numero += 1
            compteur.save(update_fields=['dernier_numero'])

        return f"{prefixe} {compteur.dernier_numero:03d}-{annee}"

    # ======================================================
    # CONFIGURATION PDF (ex-Entreprise)
    # ======================================================
    @property
    def labels_signatures(self):
        """Retourne la liste des labels des 6 signataires."""
        return [
            self.label_signataire_1, self.label_signataire_2, self.label_signataire_3,
            self.label_signataire_4, self.label_signataire_5, self.label_signataire_6,
        ]

    def get_pdf_config(self, type_doc='BON_SORTIE'):
        """Retourne toute la config personnalisable pour les templates PDF."""
        # Import lazy pour éviter la dépendance circulaire core <-> accounts
        from accounts.models import ConfigDocument

        config_doc = ConfigDocument.objects.filter(
            type_doc=self._map_type_doc(type_doc)
        ).first()

        return {
            'afficher_logo': getattr(config_doc, 'afficher_logo', True) if config_doc else True,
            'afficher_cachet': getattr(config_doc, 'afficher_cachet', True) if config_doc else True,
            'afficher_signatures': getattr(config_doc, 'afficher_signatures', True) if config_doc else True,
            'afficher_cc': getattr(config_doc, 'afficher_cc', True) if config_doc else True,
            'afficher_ifu': getattr(config_doc, 'afficher_ifu', True) if config_doc else True,
            'afficher_rccm': getattr(config_doc, 'afficher_rccm', True) if config_doc else True,
            'afficher_telephone': getattr(config_doc, 'afficher_telephone', True) if config_doc else True,
            'afficher_republique': True,
            'republique_label': "RÉPUBLIQUE DE CÔTE D'IVOIRE",
            'devise_label': "Union - Discipline - Travail",
            'direction_label': self.direction_label,
            'sous_direction_label': self.sous_direction_label,
            'service_label': self.service_label,
            'pied_page_pdf': self.pied_page_pdf,
            'couleur_principale': self.couleur_principale or "#1c5b96",
            'signataires': self._build_signataires_config(),
            'code_document': getattr(config_doc, 'code_document', '') if config_doc else '',
            'date_creation_doc': getattr(config_doc, 'date_creation_doc', '') if config_doc else '',
            'date_revision_doc': getattr(config_doc, 'date_revision_doc', '') if config_doc else '',
            'version_doc': getattr(config_doc, 'version_doc', '') if config_doc else '',
            'ps2_label': getattr(config_doc, 'ps2_label', '') if config_doc else '',
        }

    def _map_type_doc(self, type_doc):
        mapping = {
            'BON_SORTIE': 'BS',
            'BON_ENTREE': 'BE',
            'BON_RETOUR': 'BR',
            'BON_HS': 'BSHS',
            'COMMANDE': 'BC',
            'DEMANDE': 'BDM',
        }
        return mapping.get(type_doc, 'BS')

    def _build_signataires_config(self):
        labels = self.labels_signatures
        roles = ['demandeur', 'magasinier', 'responsable', 'directeur', 'controleur', 'receptionnaire']
        return [
            {'ordre': i + 1, 'label': label, 'role': role}
            for i, (label, role) in enumerate(zip(labels, roles))
        ]

    def creer_configs_documents_par_defaut(self):
        """Crée les 6 configurations documentaires par défaut si elles n'existent pas."""
        from accounts.models import ConfigDocument

        defaults = {
            'BS':   {'code_document': 'ENR-BSM/DAF-001',  'date_creation_doc': '10/06/2024', 'date_revision_doc': '19/05/2025', 'version_doc': '002', 'ps2_label': 'PS2 : GERER LES PRESTATIONS EXTERNES'},
            'BE':   {'code_document': 'ENR-BEM/DAF-001',  'date_creation_doc': '10/06/2024', 'date_revision_doc': '19/05/2025', 'version_doc': '001', 'ps2_label': 'PS2 : GERER LES APPROVISIONNEMENTS'},
            'BR':   {'code_document': 'ENR-BRM/DAF-001',  'date_creation_doc': '10/06/2024', 'date_revision_doc': '19/05/2025', 'version_doc': '001', 'ps2_label': 'PS2 : GERER LE STOCK'},
            'BSHS': {'code_document': 'ENR-BHSM/DAF-001', 'date_creation_doc': '10/06/2024', 'date_revision_doc': '19/05/2025', 'version_doc': '001', 'ps2_label': 'PS2 : GERER LES PRESTATIONS EXTERNES'},
            'BC':   {'code_document': 'ENR-BCM/DAF-001',  'date_creation_doc': '10/06/2024', 'date_revision_doc': '19/05/2025', 'version_doc': '001', 'ps2_label': 'PS2 : GERER LES APPROVISIONNEMENTS'},
            'BDM':  {'code_document': 'ENR-BDM/DAF-001',  'date_creation_doc': '10/06/2024', 'date_revision_doc': '19/05/2025', 'version_doc': '001', 'ps2_label': 'PS2 : GERER LES APPROVISIONNEMENTS'},
        }
        for code, vals in defaults.items():
            ConfigDocument.objects.get_or_create(
                type_doc=code,
                defaults=vals
            )


def get_config():
    """Raccourci pratique : retourne le singleton ConfigurationHopital."""
    return ConfigurationHopital.get_instance()


# ==========================================================
# 🏢 SERVICE HOSPITALIER
# ==========================================================
class Service(TraceabiliteMixin):
    """Service hospitalier (mono-tenant : plus de FK entreprise)."""

    code = models.CharField(max_length=20, help_text="Ex: SA17")
    nom = models.CharField(max_length=200, help_text="Ex: CARDIOLOGIE, URGENCES")

    poste = models.CharField(
        max_length=20,
        blank=True,
        default="",
        verbose_name="Poste / Extension",
        help_text="Ex: 231, 200, etc."
    )
    poste_telephone = models.CharField(
        max_length=20, blank=True, null=True,
        verbose_name="Poste téléphonique",
        help_text="Ex: 200, 256"
    )

    telephone = models.CharField(max_length=50, blank=True, null=True, verbose_name="Téléphone")

    telecopie = models.CharField(
        max_length=50, blank=True, null=True,
        verbose_name="Télécopie / Fax"
    )

    history = HistoricalRecords()

    class Meta:
        verbose_name = "Service Hospitalier"
        verbose_name_plural = "Services Hospitaliers"
        # ✅ Pas de constraints ici — gérées manuellement en SQL
        # 💡 Après déduplication éventuelle des données, tu pourras ajouter
        #    unique=True sur `code` (unicité naturelle en mono-tenant).

    def __str__(self):
        return f"{self.code} - {self.nom}"