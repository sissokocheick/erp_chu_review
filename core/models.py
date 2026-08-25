# core/models.py — MONO-TENANT v1
"""
Module core (mono-tenant).

ConfigurationHopital est le singleton de configuration de l'établissement
(identité visuelle, coordonnées légales, numérotation, signataires, PDF).
"""
from django.db import models, transaction
from django.contrib.auth.models import User
from django.utils import timezone
from simple_history.models import HistoricalRecords

from .crypto import SecretCharFieldMixin


class SecretCharField(SecretCharFieldMixin, models.CharField):
    """CharField chiffré en base (secrets SMTP/SMS) — voir core/crypto.py."""
    pass


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
# 📄 TYPES DE DOCUMENTS PDF
# ==========================================================
class TypeDocument(models.TextChoices):
    BS = 'BS', 'Bon de Sortie'
    BE = 'BE', "Bon d'Entrée"
    BR = 'BR', 'Bon de Retour'
    BSHS = 'BSHS', 'Bon Hors Stock'
    BDM = 'BDM', 'Bon de Demande de Matériel'
    BC = 'BC', 'Bon de Commande'

# ==========================================================
# 🏥 CONFIGURATION UNIQUE DE L'ÉTABLISSEMENT (SINGLETON)
# ==========================================================
class ConfigurationHopital(TraceabiliteMixin):
    """
    Singleton de configuration de l'établissement (mono-tenant).

    Regroupe :
    - les paramètres fonctionnels (mots de passe, confidentialité, délais)
    - l'identité visuelle PDF (logo, cachet, couleur)  ← hérité de l'ancien modèle
    - les coordonnées légales (CC, IFU, RCCM)          ← hérité de l'ancien modèle
    - la numérotation des documents (préfixes)          ← hérité de l'ancien modèle
    - les labels des 6 signataires                      ← hérité de l'ancien modèle

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

    # ── Identité visuelle (hérité de l'ancien modèle) ──
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

    # ── Coordonnées légales (hérité de l'ancien modèle) ──
    cc = models.CharField(max_length=50, blank=True, verbose_name="Compte Contribuable (CC)")
    ifu = models.CharField(max_length=50, blank=True, verbose_name="IFU")
    rccm = models.CharField(max_length=50, blank=True, verbose_name="RCCM")

    # ── Hiérarchie affichée sur les documents (hérité de l'ancien modèle) ──
    direction_label = models.CharField(max_length=200, default="DIRECTION DES AFFAIRES FINANCIÈRES", verbose_name="Label Direction", blank=True)
    sous_direction_label = models.CharField(max_length=200, default="SOUS-DIRECTION DE LA LOGISTIQUE", verbose_name="Label Sous-Direction", blank=True)
    service_label = models.CharField(max_length=200, default="SERVICE APPROVISIONNEMENT ET GESTION DES STOCKS", verbose_name="Label Service", blank=True)
    pied_page_pdf = models.TextField(default="Document gǸnǸrǸ par NexusERP \u2014 Tous droits rǸservǸs.", verbose_name="Pied de page PDF", blank=True)

    # 🔧 Affichage global PDF 🔧
    afficher_logo = models.BooleanField(default=True, verbose_name="Afficher le logo sur les PDF")
    afficher_cachet = models.BooleanField(default=True, verbose_name="Afficher le cachet sur les PDF")
    afficher_cc = models.BooleanField(default=True, verbose_name="Afficher le CC sur les PDF")
    afficher_ifu = models.BooleanField(default=True, verbose_name="Afficher l'IFU sur les PDF")
    afficher_rccm = models.BooleanField(default=True, verbose_name="Afficher le RCCM sur les PDF")
    afficher_telephone = models.BooleanField(default=True, verbose_name="Afficher le téléphone sur les PDF")
    afficher_republique = models.BooleanField(default=True, verbose_name="Afficher la République")
    afficher_devise = models.BooleanField(default=True, verbose_name="Afficher la Devise")
    afficher_direction = models.BooleanField(default=True, verbose_name="Afficher la Direction")
    afficher_sous_direction = models.BooleanField(default=True, verbose_name="Afficher la Sous-Direction")
    afficher_service = models.BooleanField(default=True, verbose_name="Afficher le Service")

    # ── Numérotation personnalisable (hérité de l'ancien modèle) ──
    prefixe_bon_sortie = models.CharField(max_length=10, default="BS", verbose_name="Préfixe Bon de Sortie", blank=True)
    prefixe_bon_entree = models.CharField(max_length=10, default="BE", verbose_name="Préfixe Bon d'Entrée", blank=True)
    prefixe_bon_retour = models.CharField(max_length=10, default="BR", verbose_name="Préfixe Bon de Retour", blank=True)
    prefixe_bon_hors_stock = models.CharField(max_length=10, default="BSHS", verbose_name="Préfixe Bon Hors Stock", blank=True)
    prefixe_commande = models.CharField(max_length=10, default="BC", verbose_name="Préfixe Commande", blank=True)

    # ── Labels des 6 emplacements de signature (hérité de l'ancien modèle) ──
    @property
    def labels_signatures(self):
        """Retourne les labels des 6 emplacements de signature.

        Les champs label_signataire_1..6 ont été supprimés lors de la
        migration vers ModeleDocumentMagasin (stock) : valeurs par défaut.
        """
        return [
            "Le Demandeur",
            "Le Magasinier",
            "Le Responsable Service",
            "Le Directeur",
            "Le Contrôleur",
            "Le Réceptionnaire",
        ]

    # Métadonnées documentaires par défaut (ex-ConfigDocument, supprimé) :
    # la personnalisation par type de document vit désormais dans
    # stock.ModeleDocumentMagasin (config JSON par magasin).
    METADONNEES_DOCUMENTS_DEFAUT = {
        'BS':   {'code_document': 'ENR-BSM/DAF-001',  'date_creation_doc': '10/06/2024', 'date_revision_doc': '19/05/2025', 'version_doc': '002', 'ps2_label': 'PS2 : GERER LES PRESTATIONS EXTERNES'},
        'BE':   {'code_document': 'ENR-BEM/DAF-001',  'date_creation_doc': '10/06/2024', 'date_revision_doc': '19/05/2025', 'version_doc': '001', 'ps2_label': 'PS2 : GERER LES APPROVISIONNEMENTS'},
        'BR':   {'code_document': 'ENR-BRM/DAF-001',  'date_creation_doc': '10/06/2024', 'date_revision_doc': '19/05/2025', 'version_doc': '001', 'ps2_label': 'PS2 : GERER LE STOCK'},
        'BSHS': {'code_document': 'ENR-BHSM/DAF-001', 'date_creation_doc': '10/06/2024', 'date_revision_doc': '19/05/2025', 'version_doc': '001', 'ps2_label': 'PS2 : GERER LES PRESTATIONS EXTERNES'},
        'BC':   {'code_document': 'ENR-BCM/DAF-001',  'date_creation_doc': '10/06/2024', 'date_revision_doc': '19/05/2025', 'version_doc': '001', 'ps2_label': 'PS2 : GERER LES APPROVISIONNEMENTS'},
        'BDM':  {'code_document': 'ENR-BDM/DAF-001',  'date_creation_doc': '10/06/2024', 'date_revision_doc': '19/05/2025', 'version_doc': '001', 'ps2_label': 'PS2 : GERER LES APPROVISIONNEMENTS'},
    }

    def _map_type_doc(self, type_doc):
        """Mappe un type legacy / TextChoices vers le code court utilisé par ModeleDocumentMagasin."""
        mapping = {
            'BS': 'BS', 'BE': 'BE', 'BR': 'BR', 'BSHS': 'BSHS', 'BC': 'BC', 'BDM': 'BDM',
            'BON_SORTIE': 'BS', 'BON_ENTREE': 'BE', 'BON_RETOUR': 'BR',
            'BON_HS': 'BSHS', 'COMMANDE': 'BC', 'DEMANDE': 'BDM',
        }
        try:
            type_doc = type_doc.value if hasattr(type_doc, 'value') else str(type_doc)
        except Exception:
            type_doc = str(type_doc)
        return mapping.get(type_doc, 'BS')

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
    # VALIDATIONS (hérité de l'ancien modèle)
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
    # NUMÉROTATION DES DOCUMENTS (hérité de l'ancien modèle)
    # ======================================================
    def generer_numero(self, type_doc, annee=None):
        """
        Génère le prochain numéro de document.
        """
        from stock.models import CompteurDocument
        if annee is None:
            annee = timezone.now().year

        prefix_map = {
            TypeDocument.BS: self.prefixe_bon_sortie,
            TypeDocument.BE: self.prefixe_bon_entree,
            TypeDocument.BR: self.prefixe_bon_retour,
            TypeDocument.BSHS: self.prefixe_bon_hors_stock,
            TypeDocument.BC: self.prefixe_commande,
            TypeDocument.BDM: 'DM',
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
    # CONFIGURATION PDF (hérité de l'ancien modèle)
    # ======================================================

    def get_pdf_config(self, type_doc=TypeDocument.BS):
        """Retourne toute la config personnalisable pour les templates PDF.

        ConfigDocument a été supprimé : les métadonnées par type de document
        sont désormais résolues via ModeleDocumentMagasin (par magasin) ou
        les valeurs par défaut METADONNEES_DOCUMENTS_DEFAUT.
        """
        code = self._map_type_doc(type_doc)
        config_doc = None
        try:
            from stock.models import ModeleDocumentMagasin
            modele = ModeleDocumentMagasin.objects.filter(
                type_document=code, est_actif=True
            ).first()
            if modele:
                config_complete = modele.get_config_complete()
                metas = config_complete.get('metadonnees', {}) if isinstance(config_complete, dict) else {}
                if metas:
                    config_doc = metas
        except Exception:
            config_doc = None

        metas_defaut = self.METADONNEES_DOCUMENTS_DEFAUT.get(code, {})

        def _meta(champ):
            if config_doc and config_doc.get(champ):
                return config_doc[champ]
            return metas_defaut.get(champ, '')

        return {
            'afficher_logo': getattr(self, 'afficher_logo', True),
            'afficher_cachet': getattr(self, 'afficher_cachet', True),
            'afficher_signatures': True,
            'afficher_cc': getattr(self, 'afficher_cc', True),
            'afficher_ifu': getattr(self, 'afficher_ifu', True),
            'afficher_rccm': getattr(self, 'afficher_rccm', True),
            'afficher_telephone': getattr(self, 'afficher_telephone', True),
            'afficher_republique': getattr(self, 'afficher_republique', True),
            'afficher_devise': getattr(self, 'afficher_devise', True),
            'afficher_direction': getattr(self, 'afficher_direction', True),
            'afficher_sous_direction': getattr(self, 'afficher_sous_direction', True),
            'afficher_service': getattr(self, 'afficher_service', True),
            'republique_label': "RÉPUBLIQUE DE CÔTE D'IVOIRE",
            'devise_label': "Union - Discipline - Travail",
            'direction_label': self.direction_label,
            'sous_direction_label': self.sous_direction_label,
            'service_label': self.service_label,
            'pied_page_pdf': self.pied_page_pdf,
            'couleur_principale': self.couleur_principale or "#1c5b96",
            'signataires': self._build_signataires_config(),
            'code_document': _meta('code_document'),
            'date_creation_doc': _meta('date_creation_doc'),
            'date_revision_doc': _meta('date_revision_doc'),
            'version_doc': _meta('version_doc'),
            'ps2_label': _meta('ps2_label'),
        }

    def _build_signataires_config(self):
        labels = self.labels_signatures
        roles = ['demandeur', 'magasinier', 'responsable', 'directeur', 'controleur', 'receptionnaire']
        return [
            {'ordre': i + 1, 'label': label, 'role': role}
            for i, (label, role) in enumerate(zip(labels, roles))
        ]

    def creer_configs_documents_par_defaut(self):
        """Compatibilité : ConfigDocument a été supprimé.

        Les configurations documentaires sont désormais portées par
        stock.ModeleDocumentMagasin (config JSON par magasin). Cette méthode
        ne crée plus rien et retourne simplement les valeurs par défaut.
        """
        return dict(self.METADONNEES_DOCUMENTS_DEFAUT)


def get_config():
    """Raccourci pratique : retourne le singleton ConfigurationHopital."""
    return ConfigurationHopital.get_instance()


# ==========================================================
# 🏢 SERVICE HOSPITALIER
# ==========================================================
class Service(TraceabiliteMixin):
    """Service hospitalier."""

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

# ==========================================================
# 🔔 CONFIGURATION DES NOTIFICATIONS (email + SMS)
# ==========================================================
class ConfigurationNotification(models.Model):
    """
    Configuration des canaux d'envoi des notifications (mono-tenant).

    Deux canaux :
    - Email : via un serveur SMTP (Django send_mail).
    - SMS   : via une API HTTP générique (URL + clé + expéditeur) ou Twilio,
              avec un mode test qui journalise au lieu d'envoyer.

    Accès : toujours passer par ConfigurationNotification.get_instance()
    """

    # ── Canal Email ──
    activer_email = models.BooleanField(
        default=False, verbose_name="Activer les notifications par email"
    )
    smtp_host = models.CharField(
        max_length=200, blank=True, default="",
        verbose_name="Serveur SMTP (hôte)", help_text="Ex: smtp.gmail.com"
    )
    smtp_port = models.PositiveIntegerField(default=587, verbose_name="Port SMTP")
    smtp_user = models.CharField(
        max_length=200, blank=True, default="", verbose_name="Utilisateur SMTP"
    )
    smtp_password = SecretCharField(
        max_length=512, blank=True, default="", verbose_name="Mot de passe SMTP",
        help_text="Stocké chiffré en base."
    )
    email_expediteur = models.EmailField(
        max_length=254, blank=True, default="",
        verbose_name="Email expéditeur",
        help_text="Adresse affichée comme expéditeur des notifications."
    )
    smtp_use_tls = models.BooleanField(
        default=True, verbose_name="Utiliser TLS (STARTTLS)"
    )

    # ── Canal SMS ──
    activer_sms = models.BooleanField(
        default=False, verbose_name="Activer les notifications par SMS"
    )
    SMS_PROVIDER_CHOICES = [
        ('GENERIQUE', 'API HTTP générique (URL + clé)'),
        ('TWILIO', 'Twilio'),
        ('TEST', 'Mode test (journal uniquement)'),
    ]
    sms_provider = models.CharField(
        max_length=20, choices=SMS_PROVIDER_CHOICES, default='TEST',
        verbose_name="Fournisseur SMS"
    )
    sms_api_url = models.URLField(
        max_length=300, blank=True, default="",
        verbose_name="URL de l'API SMS",
        help_text="Endpoint HTTP appelé pour envoyer un SMS (méthode POST)."
    )
    sms_api_key = SecretCharField(
        max_length=512, blank=True, default="",
        verbose_name="Clé API / Token",
        help_text="Envoyée dans l'en-tête 'Authorization: Bearer <clé>'. Stockée chiffrée en base."
    )
    sms_expediteur = models.CharField(
        max_length=20, blank=True, default="",
        verbose_name="Expéditeur (sender ID)"
    )
    sms_twilio_template = models.CharField(
        max_length=100, blank=True, default="",
        verbose_name="Modèle Twilio (compte trial)",
        help_text="Nom d'un modèle prédéfini Twilio (ex: sms_appointment_reminders). "
                  "Obligatoire en compte trial : le texte libre est refusé (erreur 572006). "
                  "Laisser vide en compte payant pour envoyer le vrai texte de la notification."
    )
    sms_param_numero = models.CharField(
        max_length=50, default="to",
        verbose_name="Paramètre du numéro",
        help_text="Nom du champ JSON contenant le numéro de téléphone (ex: 'to')."
    )
    sms_param_message = models.CharField(
        max_length=50, default="message",
        verbose_name="Paramètre du message",
        help_text="Nom du champ JSON contenant le texte du SMS (ex: 'message')."
    )
    sms_mode_test = models.BooleanField(
        default=True,
        verbose_name="Mode test",
        help_text="Si actif, les SMS sont journalisés dans les logs au lieu d'être réellement envoyés."
    )

    date_modification = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuration des notifications"
        verbose_name_plural = "Configuration des notifications"

    def __str__(self):
        return "Configuration des notifications"

    # ======================================================
    # SINGLETON
    # ======================================================
    @classmethod
    def get_instance(cls):
        """Retourne l'unique instance de configuration (la crée si absente)."""
        instance = cls.objects.first()
        if instance is None:
            instance = cls.objects.create()
        return instance
