# accounts/models.py — MONO-TENANT v1
"""
MIGRATION MONO-TENANT — Résumé des changements :
1. ❌ Modèle Entreprise SUPPRIMÉ → toute sa personnalisation (logo, cachet,
   préfixes, signataires, PDF) est désormais dans core.ConfigurationHopital.
2. ❌ Modèle RoleEntreprise SUPPRIMÉ → les Group Django redeviennent globaux.
   ⚠️ Les views qui utilisent `groupe.roleentreprise` ou `nom_affiche`
   devront être adaptées (étape views).
3. ConfigDocument, Specialite, Fonction, Profil, JournalAudit :
   champ `entreprise` supprimé.
4. ✅ Le signal creer_profil_utilisateur est RÉACTIVÉ : le Profil n'ayant
   plus de FK entreprise obligatoire, il peut être créé automatiquement.
"""
from django.db import models
from django.conf import settings
from django.contrib.auth.models import User
from django.utils import timezone
from core.models import Service
from simple_history.models import HistoricalRecords


# ==========================================================
# 📄 CONFIGURATION DES DOCUMENTS PDF (MONO-TENANT)
# ==========================================================
class ConfigDocument(models.Model):
    """Configuration personnalisable par type de document PDF."""
    TYPE_DOC_CHOICES = [
        ('BS', 'Bon de Sortie'),
        ('BE', "Bon d'Entrée"),
        ('BR', 'Bon de Retour'),
        ('BSHS', 'Bon Hors Stock'),
        ('BDM', 'Bon de Demande de Matériel'),
        ('BC', 'Bon de Commande'),
    ]

    type_doc = models.CharField(max_length=10, choices=TYPE_DOC_CHOICES, unique=True)
    # 💡 Après déduplication éventuelle des données (si plusieurs entreprises
    #    existaient en base), tu pourras passer type_doc en unique=True.

    # Métadonnées ISO
    code_document = models.CharField(max_length=50, blank=True, verbose_name="Code document")
    date_creation_doc = models.CharField(max_length=20, blank=True, verbose_name="Date création")
    date_revision_doc = models.CharField(max_length=20, blank=True, verbose_name="Date révision")
    version_doc = models.CharField(max_length=10, blank=True, verbose_name="Version")
    ps2_label = models.CharField(max_length=100, blank=True, verbose_name="Label PS2")

    # Affichage conditionnel
    afficher_logo = models.BooleanField(default=True, verbose_name="Afficher le logo")
    afficher_cachet = models.BooleanField(default=True, verbose_name="Afficher le cachet")
    afficher_cc = models.BooleanField(default=True, verbose_name="Afficher le CC")
    afficher_ifu = models.BooleanField(default=True, verbose_name="Afficher l'IFU")
    afficher_rccm = models.BooleanField(default=True, verbose_name="Afficher le RCCM")
    afficher_telephone = models.BooleanField(default=True, verbose_name="Afficher le téléphone")
    afficher_signatures = models.BooleanField(default=True, verbose_name="Afficher les signatures")

    class Meta:
        verbose_name = "Configuration document"
        verbose_name_plural = "Configurations documents"
        ordering = ['type_doc']

    def __str__(self):
        return self.get_type_doc_display()


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
    """Profil étendu d'un User Django (mono-tenant : plus de FK entreprise)."""
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
    ('menu_stats_demandes', 'Stats Demandes'),
    ('menu_stats_sondages', 'Stats Sondages'),
    
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
    ('menu_pat_import_excel', 'Import Excel Patrimoine'),
    
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
]


class MenuAccess(models.Model):
    """Permissions personnalisées par module avec hiérarchie de menu."""
    code = models.CharField(max_length=100, unique=True, default='menu_inconnu', verbose_name="Code permission")
    nom = models.CharField(max_length=150, default='Menu Inconnu', verbose_name="Nom affiché")
    description = models.TextField(blank=True, null=True, verbose_name="Description")
    url = models.CharField(max_length=255, blank=True, default='#', verbose_name="URL cible")
    icone = models.CharField(max_length=50, blank=True, default='fa-circle', verbose_name="Icône FontAwesome")
    ordre = models.PositiveSmallIntegerField(default=100, verbose_name="Ordre d'affichage")
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='sous_menus',
        verbose_name="Menu parent"
    )
    actif = models.BooleanField(default=True, verbose_name="Actif")
    
    # Relation avec les groupes (roles)
    groupes = models.ManyToManyField(
        'auth.Group',
        blank=True,
        related_name='menus_accessibles',
        verbose_name="Groupes autorisés"
    )

    class Meta:
        verbose_name = "Accès Menu"
        verbose_name_plural = "Accès Menus"
        ordering = ['ordre', 'nom']
        # Permissions basées sur la liste existante
        permissions = [
            ('menu_pat_registre', 'Registre Patrimoine'),
            ('menu_pat_sas', 'SAS (Zone d\'attente)'),
            ('menu_pat_fiche_detail', 'Fiches Détaillées'),
            ('menu_pat_modifier_immo', 'Modifier Immobilisations'),
            ('menu_pat_mouvements', 'Mouvements Patrimoine'),
            ('menu_pat_eclatement', 'Éclatement Biens'),
            ('menu_pat_immatriculation', 'Immatriculation Directe'),
            ('menu_pat_qr_codes', 'Gestion QR Codes'),
            ('menu_pat_export_registre', 'Export Registre Excel'),
            ('menu_pat_import_excel', 'Import Excel Patrimoine'),
            ('menu_pat_contrats', 'Contrats'),
            ('menu_pat_contrat_detail', 'Détail Contrats'),
            ('menu_pat_assigner_equipements', 'Assigner Équipements aux Contrats'),
            ('menu_pat_interventions', 'Interventions'),
            ('menu_pat_intervention_detail', 'Détail Interventions'),
            ('menu_pat_signaler_panne', 'Signaler Panne'),
            ('menu_pat_creer_intervention', 'Créer Intervention'),
            ('menu_pat_valider_intervention', 'Valider Intervention'),
            ('menu_pat_portail_prestataire', 'Portail Prestataire'),
            ('menu_pat_schema_maintenance', 'Schémas Maintenance'),
            ('menu_pat_types_equipements', 'Types d\'Équipements'),
            ('menu_pat_tickets', 'Tickets SAV'),
            ('menu_pat_mes_tickets', 'Mes Tickets'),
            ('menu_pat_dispatch', 'Dispatch Interventions'),
            ('menu_pat_tech', 'Espace Technicien'),
            ('menu_pat_suivi_ticket', 'Suivi Ticket'),
            ('menu_pat_bon_sortie_reparation', 'Bon Sortie Réparation'),
            ('menu_pat_inventaire', 'Inventaire Parc'),
            ('menu_pat_campagnes_inventaire', 'Campagnes Inventaire'),
            ('menu_pat_detail_campagne', 'Détail Campagne'),
            ('menu_pat_reconciliation', 'Réconciliation Inventaire'),
            ('menu_pat_audit_scan', 'Audit Scan Inventaire'),
            ('menu_pat_fiche_comptage', 'Fiche Comptage'),
            ('menu_pat_rebuts', 'Rebuts'),
            ('menu_pat_pertes', 'Pertes'),
            ('menu_pat_parametres', 'Paramètres Patrimoine'),
            ('menu_pat_historique', 'Historique Patrimoine'),
        ]

    def __str__(self):
        return f"{self.nom} ({self.code})"
    
    def est_parent(self):
        """Vérifie si ce menu a des sous-menus."""
        return self.sous_menus.exists()


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

    utilisateur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    titre = models.CharField(max_length=200)
    message = models.TextField()
    type_notif = models.CharField(max_length=20, choices=TYPE_CHOICES, default='INFO')
    url = models.URLField(blank=True, null=True, help_text="Lien de redirection au clic")
    est_lue = models.BooleanField(default=False)
    date_creation = models.DateTimeField(auto_now_add=True, db_index=True)
    date_lecture = models.DateTimeField(null=True, blank=True)
    icon = models.CharField(max_length=50, default='fa-bell')
    color = models.CharField(max_length=7, default='#1c5b96')

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
    """✅ RÉACTIVÉ en mono-tenant : le Profil n'a plus de FK entreprise
    obligatoire, il peut donc être créé automatiquement sans risque
    de profil orphelin. get_or_create par sécurité."""
    if created:
        Profil.objects.get_or_create(user=instance)