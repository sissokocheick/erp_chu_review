# accounts/models.py — MONO-TENANT v1
"""
Module accounts (mono-tenant).

La personnalisation de l'établissement (logo, cachet, préfixes, signataires,
PDF) vit dans core.ConfigurationHopital ; les rôles sont des Group Django
globaux et les profils sont créés automatiquement par signal.
"""
from django.db import models
from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone
from core.models import Service
from simple_history.models import HistoricalRecords


# ==========================================================
# 🏥 SPÉCIALITÉ
# ==========================================================
class Specialite(models.Model):
    """Spécialités médicales de l'établissement."""
    nom = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    # 💡 Après déduplication éventuelle, tu pourras passer nom en unique=True.

    # Traçabilité
    cree_par = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='specialites_creees')
    modifie_par = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='specialites_modifiees')
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "Spécialité"
        verbose_name_plural = "Spécialités"
        ordering = ['nom']

    def __str__(self):
        return self.nom


# ==========================================================
# 💼 FONCTION
# ==========================================================
class Fonction(models.Model):
    """Fonctions / Titres professionnels (affichés sous les signatures PDF)."""
    nom = models.CharField(max_length=150, unique=True, verbose_name="Nom de la fonction")
    description = models.TextField(blank=True, null=True, verbose_name="Description")
    # 💡 Après déduplication éventuelle, tu pourras passer nom en unique=True.

    cree_par = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='fonctions_creees')
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "Fonction"
        verbose_name_plural = "Fonctions"
        ordering = ['nom']

    def __str__(self):
        return self.nom


# ==========================================================
# 👤 PROFIL UTILISATEUR
# ==========================================================
class Profil(models.Model):
    """Profil étendu d'un User Django."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='profil')

    # Informations professionnelles
    service = models.ForeignKey(Service, on_delete=models.SET_NULL, null=True, blank=True, related_name='profils')
    specialite = models.ForeignKey(Specialite, on_delete=models.SET_NULL, null=True, blank=True, related_name='profils')
    contact = models.CharField(max_length=50, blank=True, null=True, verbose_name="Téléphone")

    # Photo et signature
    photo = models.ImageField(upload_to='photos_profils/%Y/%m/', null=True, blank=True)
    signature = models.ImageField(upload_to='signatures/%Y/%m/', null=True, blank=True)
    a_signature = models.BooleanField(default=False, verbose_name="Signature enregistrée")

    fonction = models.ForeignKey(
        'accounts.Fonction',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='utilisateurs_fonction',
        verbose_name="Fonction / Titre"
    )

    # 🌙 Thème préféré
    theme_preference = models.CharField(
        max_length=10,
        choices=[('light', 'Clair'), ('dark', 'Sombre')],
        default='light',
        verbose_name='Thème préféré'
    )

    # Permissions stock
    magasins_autorises = models.ManyToManyField('stock.Magasin', blank=True, related_name='utilisateurs_autorises')

    # Bureau physique (pour le périmètre de déclaration des pannes)
    bureau = models.ForeignKey(
        'patrimoine.Bureau',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='occupants',
        verbose_name='Bureau physique'
    )

    # Domaines d'intervention (techniciens patrimoine)
    domaines_intervention = models.ManyToManyField(
        'patrimoine.CategoriePatrimoine',
        blank=True,
        related_name='techniciens',
        verbose_name="Domaines d'intervention"
    )

    # Traçabilité
    cree_par = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='profils_cree')
    modifie_par = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='profils_modifie')
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)

    # 🔒 Cooldown photo de profil
    date_derniere_photo = models.DateTimeField(null=True, blank=True, verbose_name="Dernier changement de photo")
    nb_changements_photo = models.PositiveSmallIntegerField(default=0, verbose_name="Nombre de changements de photo")

    est_chef_service = models.BooleanField(
        default=False,
        verbose_name='Chef de service'
    )
    doit_changer_mdp = models.BooleanField(
    default=True,
    verbose_name="Doit changer le mot de passe"
    )

    @property
    def delai_attente_photo_minutes(self):
        """Calcule le délai d'attente : 10 min × nb changements, plafonné à 60 min."""
        return min(10 * self.nb_changements_photo, 60)

    @property
    def peut_changer_photo(self):
        """Vérifie si le cooldown est écoulé."""
        if not self.date_derniere_photo:
            return True
        from datetime import timedelta
        delai = timedelta(minutes=self.delai_attente_photo_minutes)
        return timezone.now() >= self.date_derniere_photo + delai

    @property
    def temps_restant_photo(self):
        """Retourne le temps restant en secondes (0 si dépassé)."""
        if not self.date_derniere_photo:
            return 0
        from datetime import timedelta
        delai = timedelta(minutes=self.delai_attente_photo_minutes)
        fin_cooldown = self.date_derniere_photo + delai
        reste = (fin_cooldown - timezone.now()).total_seconds()
        return max(0, int(reste))

    def get_fonction_display(self):
        """Retourne la fonction complète pour affichage PDF (snapshot).

        Priorité :
        1. FK Fonction personnalisée (Profil.fonction)
        2. Chef de Service + Service
        3. Service seul
        4. Spécialité
        5. Fallback
        """
        # 1. Fonction personnalisée (prioritaire)
        if self.fonction:
            return self.fonction.nom

        fonctions = []
        if self.est_chef_service and self.service:
            fonctions.append(f"Chef de Service {self.service.nom}")
        elif self.service:
            fonctions.append(self.service.nom)
        if self.specialite:
            fonctions.append(self.specialite.nom)

        result = " / ".join(fonctions)
        return result if result else "Non spécifié"

    @property
    def fonction_complete(self):
        return self.get_fonction_display()

    history = HistoricalRecords()

    class Meta:
        verbose_name = "Profil"
        verbose_name_plural = "Profils"

    def __str__(self):
        nom = self.user.get_full_name() or self.user.username
        return f"{nom} ({self.service.nom})" if self.service else nom


# ==========================================================
# 📋 MENU ACCESS (Permissions personnalisées par module)
# ==========================================================
# Constante partagée pour éviter la duplication entre choices et Meta.permissions
MENU_ACCESS_PERMISSIONS = [
    # === MODULE CORE ===
    ('menu_accueil', 'Accueil'),
    ('menu_dashboard', 'Tableau de bord'),
    
    # === MODULE STOCK - DEMANDES ===
    ('menu_demandes', 'Demandes'),
    ('menu_valider_demandes', 'Valider Demandes'),
    ('menu_guichet', 'Guichet'),
    
    # === MODULE STOCK - MOUVEMENTS ===
    ('menu_livraisons', 'Livraisons'),
    ('menu_entrees', 'Entrées en Stock'),
    ('menu_reception_commande', 'Réceptions de commandes'),
    ('menu_sorties', 'Bons de Sortie'),
    ('menu_sorties_hors_stock', 'Sorties Hors Stock'),
    ('menu_retours_services', 'Retours Services'),
    ('menu_retours_fournisseurs', 'Retours Fournisseurs'),
    ('menu_transferts', 'Transferts inter-Magasins'),
    
    # === MODULE STOCK - GESTION STOCK ===
    ('menu_stock', 'État du Stock'),
    ('menu_peremptions', 'Péremptions'),
    ('menu_destructions', 'Destructions'),
    ('menu_ajustements', 'Ajustements'),
    ('menu_inventaires', 'Inventaires'),
    ('menu_historique', 'Historique'),
    ('menu_commandes', 'Commandes'),
    
    # === MODULE STOCK - CATALOGUE ===
    ('menu_articles', 'Articles'),
    ('menu_familles', 'Familles'),
    ('menu_fournisseurs', 'Fournisseurs'),
    ('menu_beneficiaires', 'Bénéficiaires'),
    ('menu_motifs_annulation', 'Motifs Annulation'),
    ('menu_magasins', 'Magasins'),
    
    # === MODULE STOCK - RAPPORTS ===
        ('menu_rapports', 'Rapports'),
      ('menu_rapport_conso_service', 'Consommation par Service'),
    ('menu_stats_demandes', 'Stats Demandes'),
    ('menu_stats_sondages', 'Stats Sondages'),
    ('menu_stats_satisfaction', 'Stats Satisfaction'),
    
    # === MODULE PATRIMOINE - REGISTRE & IMMOBILISATIONS ===
    ('menu_pat_registre', 'Registre Patrimoine'),
    ('menu_pat_sas', 'SAS (Zone d\'attente)'),
    ('menu_pat_fiche_detail', 'Fiches Détaillées'),
    ('menu_pat_modifier_immo', 'Modifier Immobilisations'),
    ('menu_pat_mouvements', 'Mouvements Patrimoine'),
    ('menu_pat_eclatement', 'Éclatement Biens'),
    ('menu_pat_immatriculation', 'Immatriculation Directe'),
    ('menu_pat_qr_codes', 'Gestion QR Codes'),
    ('menu_pat_export_registre', 'Export Registre Excel'),
    ('menu_pat_import', 'Import Excel Patrimoine'),
    
    # === MODULE PATRIMOINE - CONTRATS ===
    ('menu_pat_contrats', 'Contrats'),
    ('menu_pat_contrat_detail', 'Détail Contrats'),
    ('menu_pat_assigner_equipements', 'Assigner Équipements aux Contrats'),
    
    # === MODULE PATRIMOINE - MAINTENANCE & INTERVENTIONS ===
    ('menu_pat_interventions', 'Interventions'),
    ('menu_pat_intervention_detail', 'Détail Interventions'),
    ('menu_pat_signaler_panne', 'Signaler Panne'),
    ('menu_pat_creer_intervention', 'Créer Intervention'),
    ('menu_pat_valider_intervention', 'Valider Intervention'),
    ('menu_pat_portail_prestataire', 'Portail Prestataire'),
    ('menu_pat_schema_maintenance', 'Schémas Maintenance'),
    ('menu_pat_types_equipements', 'Types d\'Équipements'),
    
    # === MODULE PATRIMOINE - TICKETS & SUPPORT ===
    ('menu_pat_tickets', 'Tickets SAV'),
    ('menu_pat_mes_tickets', 'Mes Tickets'),
    ('menu_pat_dispatch', 'Dispatch Interventions'),
    ('menu_pat_tech', 'Espace Technicien'),
    ('menu_pat_suivi_ticket', 'Suivi Ticket'),
    ('menu_pat_bon_sortie_reparation', 'Bon Sortie Réparation'),
    
    # === MODULE PATRIMOINE - INVENTAIRES PARC ===
    ('menu_pat_inventaire', 'Inventaire Parc'),
    ('menu_pat_campagnes_inventaire', 'Campagnes Inventaire'),
    ('menu_pat_detail_campagne', 'Détail Campagne'),
    ('menu_pat_reconciliation', 'Réconciliation Inventaire'),
    ('menu_pat_audit_scan', 'Audit Scan Inventaire'),
    ('menu_pat_fiche_comptage', 'Fiche Comptage'),
    
    # === MODULE PATRIMOINE - REBUTS & PERTES ===
    ('menu_pat_rebuts', 'Rebuts'),
    ('menu_pat_pertes', 'Pertes'),
    
    # === MODULE PATRIMOINE - VÉHICULES ===
    ('menu_pat_vehicules', 'Parc Véhicules'),
    ('menu_pat_vehicules_demander', 'Demander Véhicule'),
    ('menu_pat_vehicules_valider', 'Valider Demandes Véhicule'),
    ('menu_pat_vehicules_missions', 'Missions Véhicule'),
    ('menu_pat_vehicules_interventions', 'Interventions Véhicule'),
    
    # === MODULE PATRIMOINE - SALLES ===
    ('menu_pat_salles', 'Salles de Conférence'),
    ('menu_pat_salles_demander', 'Demander Salle'),
    ('menu_pat_salles_valider', 'Valider Demandes Salle'),
    ('menu_pat_salles_calendrier', 'Calendrier Réservations'),
    ('menu_pat_salles_reservations', 'Réservations Salle'),
    
    # === MODULE PATRIMOINE - PARAMÈTRES ===
    ('menu_pat_parametres', 'Paramètres Patrimoine'),
    ('menu_pat_historique', 'Historique Patrimoine'),
    
    # === MODULE ACCOUNTS - ADMINISTRATION ===
    ('menu_utilisateurs', 'Utilisateurs'),
    ('menu_roles', 'Rôles'),
    ('menu_param_admin', 'Paramètres Admin'),
    ('menu_param_logistique', 'Paramètres Logistique'),
    ('menu_circuits_validation', 'Circuits Validation'),
    ('menu_securite_mdp', 'Sécurité MDP'),
    ('menu_journal_audit', 'Journal Audit'),
    ('menu_parametres', 'Paramètres Système'),
    
    # === MODULE ACCOUNTS - CONFIGURATION ===
    ('menu_services', 'Services'),
    ('menu_specialites', 'Spécialités'),
    ('menu_fonctions', 'Fonctions & Titres'),
    ('menu_modeles_pdf', 'Modèles de documents PDF'),
    ('menu_parametres_doc', 'Configuration Documents PDF'),
    ('menu_lots', 'Gestion des Lots'),
    ('menu_notifications_config', 'Configuration Notifications'),
]


class MenuAccess(models.Model):
    nom = models.CharField(max_length=100)
    code = models.CharField(max_length=50, unique=True, help_text="Code unique pour les permissions (ex: menu_pat_registre)")
    url = models.CharField(max_length=200, blank=True, null=True, help_text="URL de la page")
    icone = models.CharField(max_length=50, default="fa-circle", help_text="Classe FontAwesome (ex: fa-box)")
    ordre = models.IntegerField(default=100)
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='sous_menus', help_text="Menu parent (laisser vide pour un menu racine)")
    actif = models.BooleanField(default=True)
    description = models.TextField(blank=True, null=True)

    class Meta:
        verbose_name = "Accès Menu / Permission"
        verbose_name_plural = "Accès Menus / Permissions"
        ordering = ['ordre', 'nom']
        # ✅ Déclarer toutes les permissions menu_* pour qu'elles soient créées en base par migrate
        permissions = tuple(
            (code, label) for code, label in MENU_ACCESS_PERMISSIONS
        )

    def __str__(self):
        return self.nom

# ==========================================================
# 🔔 NOTIFICATIONS
# ==========================================================
class Notification(models.Model):
    """Notifications utilisateur."""
    TYPE_CHOICES = [
        ('INFO', 'Information'),
        ('SUCCESS', 'Succès'),
        ('WARNING', 'Avertissement'),
        ('DANGER', 'Danger'),
    ]

    CATEGORIE_CHOICES = [
        ('DEMANDE', 'Demandes'),
        ('STOCK', 'Stock'),
        ('ACHAT', 'Achats'),
        ('PATRIMOINE', 'Patrimoine & SAV'),
        ('SECURITE', 'Sécurité & Comptes'),
        ('SYSTEME', 'Système'),
    ]

    utilisateur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    titre = models.CharField(max_length=200)
    message = models.TextField()
    type_notif = models.CharField(max_length=20, choices=TYPE_CHOICES, default='INFO', db_index=True)
    categorie = models.CharField(
        max_length=20, choices=CATEGORIE_CHOICES, default='SYSTEME', db_index=True,
        verbose_name="Catégorie",
        help_text="Regroupe les notifications par module (Demandes, Stock, …)."
    )
    url = models.URLField(blank=True, null=True, help_text="Lien de redirection au clic")
    est_lue = models.BooleanField(default=False, db_index=True)
    date_creation = models.DateTimeField(auto_now_add=True, db_index=True)
    date_lecture = models.DateTimeField(null=True, blank=True)
    icon = models.CharField(max_length=50, default='fa-bell')
    color = models.CharField(max_length=7, default='#1c5b96')
    est_importante = models.BooleanField(
        default=False,
        verbose_name="Notification importante",
        help_text="Si activée, la notification est aussi envoyée par SMS. Les notifications ordinaires ne partent que par email et dans la cloche (les SMS coûtent de l'argent : réservés aux cas importants)."
    )

    class Meta:
        verbose_name = "Notification"
        verbose_name_plural = "Notifications"
        ordering = ['-date_creation']

    def __str__(self):
        return f"[{self.get_type_notif_display()}] {self.titre} - {self.utilisateur.username}"

    def marquer_lue(self):
        self.est_lue = True
        self.date_lecture = timezone.now()
        self.save(update_fields=['est_lue', 'date_lecture'])

    @classmethod
    def marquer_toutes_lues(cls, utilisateur):
        """Marque TOUTES les notifications non lues de l'utilisateur comme lues."""
        now = timezone.now()
        return cls.objects.filter(
            utilisateur=utilisateur, est_lue=False
        ).update(est_lue=True, date_lecture=now)

    @classmethod
    def tout_effacer(cls, utilisateur):
        """Supprime toutes les notifications de l'utilisateur."""
        return cls.objects.filter(utilisateur=utilisateur).delete()


# ==========================================================
# 📝 JOURNAL D'AUDIT
# ==========================================================
class JournalAudit(models.Model):
    """Journal global des actions (créations, modifications, suppressions)."""
    TYPE_ACTION_CHOICES = [
        ('CREATE', 'Création'),
        ('UPDATE', 'Modification'),
        ('DELETE', 'Suppression'),
        ('LOGIN', 'Connexion'),
        ('LOGOUT', 'Déconnexion'),
        ('EXPORT', 'Export'),
        ('PERMISSION', 'Changement Permission'),
    ]

    utilisateur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='actions_audit')
    action = models.CharField(max_length=200)
    type_action = models.CharField(max_length=20, choices=TYPE_ACTION_CHOICES, default='UPDATE')
    modele_concerne = models.CharField(max_length=100, blank=True, null=True)
    id_objet = models.PositiveIntegerField(null=True, blank=True)
    details = models.JSONField(null=True, blank=True)
    adresse_ip = models.GenericIPAddressField(null=True, blank=True)
    date_action = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "Entrée d'audit"
        verbose_name_plural = "Journal d'audit"
        ordering = ['-date_action']

    def __str__(self):
        return f"[{self.date_action:%d/%m/%Y %H:%M}] {self.utilisateur} - {self.action}"


# ==========================================================
# 📝 JOURNAL DE SÉCURITÉ CONNEXIONS
# ==========================================================
class AuditConnexion(models.Model):
    """Journal des événements de connexion/déconnexion pour la sécurité."""
    TYPE_CHOICES = [
        ('CONNEXION', 'Connexion réussie'),
        ('DECONNEXION', 'Déconnexion'),
        ('ECHEC', 'Échec de connexion'),
        ('PASSWORD_CHANGE', 'Changement de mot de passe'),
        ('ADMIN', 'Action administrative'),
    ]

    utilisateur = models.ForeignKey(User, on_delete=models.SET_NULL, related_name='audits_connexion', null=True, blank=True)
    type_action = models.CharField(max_length=20, choices=TYPE_CHOICES)
    description = models.TextField(blank=True)
    adresse_ip = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    date_creation = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-date_creation']
        verbose_name = "Événement de connexion"
        verbose_name_plural = "Journal de sécurité connexions"

    def __str__(self):
        return f"[{self.type_action}] {self.utilisateur} — {self.date_creation.strftime('%d/%m/%Y %H:%M')}"


# ==========================================================
# 🔑 JETON DE RÉINITIALISATION DU MOT DE PASSE (MOT DE PASSE OUBLIÉ)
# ==========================================================
class MotDePasseResetToken(models.Model):
    """Jeton à usage unique pour la réinitialisation du mot de passe par l'utilisateur.

    Créé quand l'utilisateur clique « Mot de passe oublié » :
    - le lien complet (token) est envoyé par email,
    - le code court (6 chiffres) est envoyé par SMS.
    Les deux mènent au même formulaire de nouveau mot de passe.
    """
    DUREE_VALIDITE_MINUTES = 30

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='tokens_reset_mdp'
    )
    token = models.CharField(max_length=64, unique=True)
    code = models.CharField(max_length=8, db_index=True, verbose_name="Code SMS")
    cree_le = models.DateTimeField(auto_now_add=True)
    expire_le = models.DateTimeField(verbose_name="Expiration")
    utilise = models.BooleanField(default=False, verbose_name="Déjà utilisé")

    class Meta:
        verbose_name = "Jeton de réinitialisation de mot de passe"
        verbose_name_plural = "Jetons de réinitialisation de mot de passe"
        ordering = ['-cree_le']

    def __str__(self):
        return f"Token {self.user.username} — {self.cree_le:%d/%m/%Y %H:%M}"

    @property
    def est_valide(self):
        """Vrai si le jeton n'est ni utilisé ni expiré."""
        return not self.utilise and timezone.now() <= self.expire_le

    def invalider(self):
        self.utilise = True
        self.save(update_fields=['utilise'])


# ==========================================================
# 🔄 SIGNAL : CRÉER LE PROFIL À LA CRÉATION D'UN USER
# ==========================================================


# ==========================================================
# CONFIG SECURITE (singleton mono-tenant)
# ==========================================================
class ConfigSecurite(models.Model):
    """Configuration unique de la politique de mots de passe."""
    TYPE_CHOICES = [
        ('ALEATOIRE', 'Aléatoire (recommandé)'),
        ('FIXE', 'Mot de passe fixe'),
    ]
    type_mot_de_passe = models.CharField(
        max_length=20, choices=TYPE_CHOICES, default='ALEATOIRE',
        verbose_name="Mode d'attribution"
    )
    mot_de_passe_defaut = models.CharField(
        max_length=128, blank=True, default='',
        verbose_name="Mot de passe par défaut (mode fixe)"
    )
    date_modification = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Configuration sécurité"
        verbose_name_plural = "Configuration sécurité"

    def __str__(self):
        return f"Sécurité — {self.get_type_mot_de_passe_display()}"

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass

    @classmethod
    def get_solo(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender=User)
def creer_profil_utilisateur(sender, instance, created, **kwargs):
    """Le Profil est créé automatiquement à la création d'un User (get_or_create par sécurité)."""
    if created:
        Profil.objects.get_or_create(user=instance)