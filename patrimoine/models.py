# -*- coding: utf-8 -*-
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ValidationError
from decimal import Decimal
from django.contrib.auth.models import User


# ═══════════════════════════════════════════════════════════
# SOCLE COMMUN
# ═══════════════════════════════════════════════════════════

class TracabiliteModel(models.Model):
    date_creation     = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)
    cree_par          = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="%(class)s_cree"
    )
    modifie_par       = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="%(class)s_modifie"
    )
    class Meta:
        abstract = True


# ═══════════════════════════════════════════════════════════
# 1. PARAMÉTRAGE — CATÉGORIES & TYPES
# ═══════════════════════════════════════════════════════════

class CategoriePatrimoine(TracabiliteModel):
    """
    Ex : Informatique, Reseau, Biomedical, Mobilier, Électrique, Vehicule...
    Parametrable par l'admin — zero hardcode.
    """
    code       = models.CharField(max_length=20, unique=True)
    nom        = models.CharField(max_length=100)
    icone      = models.CharField(max_length=50, blank=True, default='fas fa-box',
                                  help_text="Classe FontAwesome, ex: fas fa-desktop")
    couleur    = models.CharField(max_length=20, blank=True, default='#1c5b96',
                                  help_text="Couleur hex pour l'interface, ex: #1c5b96")
    ordre      = models.PositiveSmallIntegerField(default=0)
    est_active = models.BooleanField(default=True)

    def __str__(self):
        return self.nom

    class Meta:
        verbose_name          = "Categorie patrimoine"
        verbose_name_plural   = "Categories patrimoine"
        ordering              = ['ordre', 'nom']


class TypeEquipement(TracabiliteModel):
    """
    Ex : UC, Imprimante, Climatiseur, Camera IP, Porte automatique...
    Le specs_schema definit les colonnes propres a ce type (pour formulaire + import Excel).

    specs_schema exemple pour UC :
    [
      {"key": "cpu",      "label": "Processeur (CPU)",     "type": "text",   "required": false},
      {"key": "ram",      "label": "Memoire RAM",          "type": "text",   "required": false},
      {"key": "stockage", "label": "Stockage",             "type": "text",   "required": false},
      {"key": "os",       "label": "Systeme exploitation", "type": "text",   "required": false},
      {"key": "ip",       "label": "Adresse IP",           "type": "text",   "required": false},
      {"key": "mac",      "label": "Adresse MAC",          "type": "text",   "required": false}
    ]

    specs_schema pour Climatiseur :
    [
      {"key": "puissance_btu",  "label": "Puissance (BTU)",      "type": "number", "required": false},
      {"key": "refrigerant",    "label": "Type refrigerant",     "type": "text",   "required": false},
      {"key": "type_clim",      "label": "Type (Split/Central)", "type": "text",   "required": false}
    ]
    """
    MODE_AMORT_CHOICES = [
        ('LINEAIRE',   'Lineaire'),
        ('DEGRESSIF',  'Degressif'),
    ]

    categorie                   = models.ForeignKey(
        CategoriePatrimoine, on_delete=models.PROTECT, related_name='types_equipements'
    )
    code                        = models.CharField(max_length=30, unique=True)
    nom                         = models.CharField(max_length=100)
    duree_amortissement_defaut  = models.PositiveSmallIntegerField(
        default=5,
        help_text="Duree d'amortissement par defaut en annees (modifiable par bien)"
    )
    mode_amortissement          = models.CharField(
        max_length=10, choices=MODE_AMORT_CHOICES, default='LINEAIRE'
    )
    valeur_residuelle_pct       = models.DecimalField(
        max_digits=5, decimal_places=2, default=Decimal('0.00'),
        help_text="% de valeur residuelle a la fin (ex: 10 = 10% de la valeur initiale)"
    )
    specs_schema                = models.JSONField(
        default=list, blank=True,
        help_text="Definition des champs techniques propres a ce type"
    )
    est_actif                   = models.BooleanField(default=True)
    ordre                       = models.PositiveSmallIntegerField(default=0)

    def __str__(self):
        return f"{self.categorie.nom} — {self.nom}"

    def get_colonnes_import(self):
        """Retourne les labels des colonnes techniques pour le template Excel."""
        return [s['label'] for s in self.specs_schema]

    class Meta:
        verbose_name        = "Type d'equipement"
        verbose_name_plural = "Types d'equipements"
        ordering            = ['categorie', 'ordre', 'nom']


# ═══════════════════════════════════════════════════════════
# 2. LOCALISATION : Bâtiment → Étage → Bureau ↔ Services
# ═══════════════════════════════════════════════════════════

class Batiment(TracabiliteModel):
    # On enleve le default='X' et on met blank=True pour autoriser un champ vide
    code = models.CharField(max_length=20, unique=True, blank=True,
                            help_text="Genere automatiquement si vide (ex: BAT-001)")
    nom     = models.CharField(max_length=100)
    adresse = models.CharField(max_length=255, blank=True)

    services = models.ManyToManyField('core.Service', blank=True, related_name='batiments_occupes')

    def save(self, *args, **kwargs):
        # Code généré si vide. NB : le premier INSERT ne doit JAMAIS écrire
        # code='' (unique=True) : le 2e bâtiment sans code violait la
        # contrainte. On insère un placeholder unique, puis on règle le
        # code canonique BAT-<pk>.
        update_fields_demandes = kwargs.get('update_fields')
        if not self.code:
            if not self.pk:
                import uuid
                self.code = f"TMP-{uuid.uuid4().hex[:12]}"
                super().save(*args, **kwargs)
                self.code = f"BAT-{self.pk:03d}"
                super().save(update_fields=['code'])
            elif not self.code.startswith('TMP-'):
                # Existant sans code (données anciennes) : régénérer
                self.code = f"BAT-{self.pk:03d}"
                super().save(update_fields=update_fields_demandes or ['code'])
            else:
                super().save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)

    def __str__(self):
        # Fini le "Bât. X" ! On n'affiche que le vrai nom du bâtiment.
        return self.nom

    class Meta:
        verbose_name = "Bâtiment"
        ordering     = ['nom'] # On trie par ordre alphabetique du nom


class Etage(TracabiliteModel):
    batiment = models.ForeignKey(Batiment, on_delete=models.PROTECT, related_name='etages')
    nom      = models.CharField(max_length=50, help_text="Ex: RDC, 1er Étage, Sous-sol")
    ordre    = models.PositiveSmallIntegerField(default=0)
    services = models.ManyToManyField('core.Service', blank=True, related_name='etages_occupes')

    def __str__(self):
        return self.nom  

    class Meta:
        verbose_name        = "Étage"
        unique_together     = ('batiment', 'nom')
        ordering            = ['batiment', 'ordre']


class Bureau(TracabiliteModel):
    """
    Un bureau peut accueillir plusieurs services (ex: salle de reunion partagee).
    Un service peut avoir des bureaux dans plusieurs bâtiments.
    """
    etage    = models.ForeignKey(Etage, on_delete=models.PROTECT, related_name='bureaux')
    nom      = models.CharField(max_length=100)
    services = models.ManyToManyField(
        'core.Service', blank=True, related_name='bureaux_occupes'
    )
    superficie_m2 = models.PositiveSmallIntegerField(null=True, blank=True)

    def __str__(self):
        # Affichage super propre : "Bâtiment A / 1ER / DAF"
        return f"{self.etage.batiment.nom} / {self.etage.nom} / {self.nom}"

    @property
    def batiment(self):
        return self.etage.batiment

    class Meta:
        verbose_name    = "Bureau / Salle"
        unique_together = ('etage', 'nom')
        ordering        = ['etage', 'nom']

# ═══════════════════════════════════════════════════════════
# 3. NOMENCLATURE MATÉRIEL
# ═══════════════════════════════════════════════════════════

class Marque(TracabiliteModel):
    nom = models.CharField(max_length=100, unique=True)

    def __str__(self):
        return self.nom

    class Meta:
        ordering = ['nom']


class Modele(TracabiliteModel):
    marque = models.ForeignKey(Marque, on_delete=models.PROTECT, related_name='modeles')
    nom    = models.CharField(max_length=150)

    def __str__(self):
        return f"{self.marque.nom} {self.nom}"

    class Meta:
        unique_together = ('marque', 'nom')
        ordering        = ['marque', 'nom']


# ═══════════════════════════════════════════════════════════
# 4. IMMOBILISATION — BIEN PRINCIPAL
# ═══════════════════════════════════════════════════════════

class Immobilisation(TracabiliteModel):

    STATUT_CHOICES = [
        ('EN_ATTENTE',  'En attente d\'immatriculation (Sas)'),
        ('ACTIF',       'En service / Actif'),
        ('EN_PANNE',    'En reparation / Panne'),
        ('REFORME',     'Reforme / Mis au rebut'),
        ('CEDE',        'Cede / Transfere'),
        ('DISPARU',     'Disparu / Perdu'), # 🟢 LA NOUVELLE LIGNE EST ICI
    ]

    ACTION_CHOICES = [
        ('RAS',          'Aucune action requise'),
        ('MAINTENANCE',  'Maintenance preventive a planifier'),
        ('REPARATION',   'Reparation urgente'),
        ('REMPLACEMENT', 'Remplacement a prevoir'),
        ('REFORME',      'Mise au rebut a valider'),
        ('INVENTAIRE',   'À verifier a l\'inventaire'),
    ]

    MODE_AMORT_CHOICES = [
        ('LINEAIRE',  'Lineaire'),
        ('DEGRESSIF', 'Degressif'),
    ]

    # ── Identification ────────────────────────────────────
    type_equipement = models.ForeignKey(TypeEquipement, on_delete=models.PROTECT, null=True, blank=True)
    code_patrimoine   = models.CharField(
        max_length=60, unique=True, null=True, blank=True,
        verbose_name="Code / Asset Tag"
    )
    numero_serie      = models.CharField(
        max_length=100, blank=True, null=True, verbose_name="N° de serie"
    )
    nom_affichage     = models.CharField(
        max_length=200, blank=True,
        help_text="Nom lisible, auto-genere si vide (ex: UC HP SDPCE)"
    )
    marque            = models.ForeignKey(
        Marque, on_delete=models.SET_NULL, null=True, blank=True
    )
    modele            = models.ForeignKey(
        Modele, on_delete=models.SET_NULL, null=True, blank=True
    )

    # ── Acquisition ───────────────────────────────────────
    date_acquisition  = models.DateField(null=True, blank=True)
    valeur_acquisition = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal('0.00'),
        verbose_name="Valeur d'acquisition (FCFA)"
    )
    prix_depuis_stock = models.BooleanField(
        default=False,
        help_text="True si le prix vient automatiquement d'une LigneBon"
    )
    garantie_expiration = models.DateField(null=True, blank=True,
                                           verbose_name="Fin de garantie")
    fournisseur       = models.ForeignKey(
        'stock.Fournisseur', on_delete=models.SET_NULL, null=True, blank=True
    )

    # ── Pont avec le stock ────────────────────────────────
    bon_sortie_origine = models.ForeignKey(
        'stock.BonMouvement', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='immobilisations_creees',
        verbose_name="Bon de sortie d'origine"
    )
    article_stock     = models.ForeignKey(
        'stock.Article', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='immobilisations'
    )

    # ── Localisation & affectation ────────────────────────
    bureau            = models.ForeignKey(
        Bureau, on_delete=models.SET_NULL, null=True, blank=True
    )
    service_affectation = models.ForeignKey(
        'core.Service', on_delete=models.SET_NULL, null=True, blank=True
    )
    emplacement_exact = models.CharField(
        max_length=255, blank=True,
        help_text="Ex: Sur le bureau a gauche, Baie n°3 rack n°2"
    )

    # ── Amortissement ─────────────────────────────────────
    date_mise_en_service     = models.DateField(
        null=True, blank=True,
        help_text="Date reelle d'utilisation (= date_acquisition si non renseignee)"
    )
    duree_amortissement_ans  = models.PositiveSmallIntegerField(
        default=5,
        help_text="Heritee du TypeEquipement, modifiable par bien"
    )
    mode_amortissement       = models.CharField(
        max_length=10, choices=MODE_AMORT_CHOICES, default='LINEAIRE'
    )
    valeur_residuelle        = models.DecimalField(
        max_digits=14, decimal_places=2, default=Decimal('0.00'),
        verbose_name="Valeur residuelle (FCFA)"
    )

    # ── État & actions ────────────────────────────────────
    statut            = models.CharField(
        max_length=20, choices=STATUT_CHOICES, default='EN_ATTENTE'
    )
    action_requise    = models.CharField(
        max_length=20, choices=ACTION_CHOICES, default='RAS'
    )
    notes             = models.TextField(blank=True)

    # ── Specs techniques (dynamiques selon TypeEquipement) ─
    specs_techniques  = models.JSONField(
        default=dict, blank=True,
        help_text="Valeurs selon le specs_schema du TypeEquipement"
    )

    # ── Contrat de maintenance ────────────────────────────
    contrat_maintenance = models.ForeignKey(
        'ContratMaintenance', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='equipements'
    )

    # ── Import ────────────────────────────────────────────
    reference_inventaire = models.CharField(max_length=50, blank=True,
                                            help_text="Reference du fichier d'inventaire source")

    # ── Proprietes calculees ──────────────────────────────

    @property
    def date_debut_amort(self):
        return self.date_mise_en_service or self.date_acquisition

    @property
    def annees_ecoulees(self):
        if not self.date_debut_amort:
            return Decimal('0')
        delta = (timezone.now().date() - self.date_debut_amort).days
        return Decimal(str(round(delta / 365, 4)))

    @property
    def amortissement_annuel(self):
        if not self.duree_amortissement_ans:
            return Decimal('0')
        base = self.valeur_acquisition - self.valeur_residuelle
        return base / Decimal(str(self.duree_amortissement_ans))

    @property
    def vnc(self):
        """Valeur Nette Comptable — lineaire."""
        if self.mode_amortissement == 'LINEAIRE':
            vnc = self.valeur_acquisition - self.amortissement_annuel * self.annees_ecoulees
            return max(self.valeur_residuelle, vnc)
        # Degressif (taux = 1/duree × coeff 1.5 si duree <= 5 ans, sinon 2)
        # CORRECTION : garde anti-DivisionByZero - duree absente, nulle ou negative
        duree = self.duree_amortissement_ans
        if not duree or Decimal(str(duree)) <= 0:
            return max(self.valeur_residuelle, self.valeur_acquisition)

        coeff = Decimal('1.5') if duree <= 5 else Decimal('2.0')
        taux  = coeff / Decimal(str(duree))
        vnc   = self.valeur_acquisition * (1 - taux) ** int(self.annees_ecoulees)
        return max(self.valeur_residuelle, vnc)

    @property
    def taux_amorti_pct(self):
        """Pourcentage amorti."""
        if not self.valeur_acquisition:
            return Decimal('0')
        amorti = self.valeur_acquisition - self.vnc
        return round(amorti / self.valeur_acquisition * 100, 1)

    @property
    def est_totalement_amorti(self):
        return self.vnc <= self.valeur_residuelle

    @property
    def categorie(self):
        return self.type_equipement.categorie

    def save(self, *args, **kwargs):
        # Auto-remplir les parametres d'amortissement depuis le TypeEquipement si non modifies
        if not self.pk and self.type_equipement_id:
            te = self.type_equipement
            if self.duree_amortissement_ans == 5:  # valeur par defaut = pas encore modifie
                self.duree_amortissement_ans = te.duree_amortissement_defaut
            if self.mode_amortissement == 'LINEAIRE':
                self.mode_amortissement = te.mode_amortissement
            if not self.valeur_residuelle and te.valeur_residuelle_pct:
                self.valeur_residuelle = (
                    self.valeur_acquisition * te.valeur_residuelle_pct / 100
                )
        super().save(*args, **kwargs)

    def __str__(self):
        return self.nom_affichage or self.code_patrimoine or f"Immo #{self.pk}"

    class Meta:
        verbose_name        = "Immobilisation"
        verbose_name_plural = "Immobilisations"
        ordering            = ['-date_creation']


# ═══════════════════════════════════════════════════════════
# 5. CYCLE DE VIE — MOUVEMENTS
# ═══════════════════════════════════════════════════════════

class MouvementPatrimoine(TracabiliteModel):

    TYPE_CHOICES = [
        ('AFFECTATION',        'Affectation initiale'),
        ('MUTATION',           'Mutation (changement de bureau)'),
        ('REPARATION',         'Sortie en reparation'),
        ('RETOUR_REPARATION',  'Retour apres reparation'),
        ('REFORME',            'Mise au rebut / Reforme'),
        ('REMPLACEMENT',       'Remplacement par un autre bien'),
        ('CESSION',            'Cession / Don'),
        ('PERTE',              'Perte / Vol constate'),
    ]

    immobilisation          = models.ForeignKey(
        Immobilisation, on_delete=models.CASCADE, related_name='mouvements'
    )
    type_mouvement          = models.CharField(max_length=25, choices=TYPE_CHOICES)

    # Localisation avant/apres
    bureau_depart           = models.ForeignKey(
        Bureau, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='departs_patrimoine'
    )
    bureau_arrivee          = models.ForeignKey(
        Bureau, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='arrivees_patrimoine'
    )
    service_depart          = models.ForeignKey(
        'core.Service', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='departs_patrimoine'
    )
    service_arrivee         = models.ForeignKey(
        'core.Service', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='arrivees_patrimoine'
    )

    # Remplacement
    immobilisation_remplace = models.ForeignKey(
        Immobilisation, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='remplacements',
        help_text="Bien remplace (si type = REMPLACEMENT)"
    )

    date_mouvement          = models.DateField(default=timezone.now)
    motif                   = models.TextField(blank=True)
    effectue_par            = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='mouvements_patrimoine_effectues'
    )
    valide_par              = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='mouvements_patrimoine_valides'
    )

    def __str__(self):
        return f"{self.get_type_mouvement_display()} — {self.immobilisation} ({self.date_mouvement})"

    class Meta:
        verbose_name        = "Mouvement patrimoine"
        verbose_name_plural = "Mouvements patrimoine"
        ordering            = ['-date_mouvement']




# ═══════════════════════════════════════════════════════════
# 6. CONTRATS DE MAINTENANCE
# ═══════════════════════════════════════════════════════════

# 1️⃣ D'ABORD : Le modele TypeContrat
class TypeContrat(TracabiliteModel):
    nom = models.CharField(max_length=100, unique=True, verbose_name="Nom du type (ex: Bronze, Constructeur)")
    description = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.nom

    class Meta:
        verbose_name = "Type de Contrat"
        verbose_name_plural = "Types de Contrat"
        ordering = ['nom']


# 2️⃣ ENSUITE SEULEMENT : Le modele ContratMaintenance
class ContratMaintenance(TracabiliteModel):

    STATUT_CHOICES = [
        ('ACTIF',    'Actif'),
        ('EXPIRE',   'Expire'),
        ('SUSPENDU', 'Suspendu'),
        ('RESILIE',  'Resilie'),
    ]

    reference       = models.CharField(max_length=80, unique=True, verbose_name="Reference contrat")
    prestataire     = models.ForeignKey('stock.Fournisseur', on_delete=models.PROTECT, related_name='contrats_maintenance')
    
    type_contrat = models.ForeignKey(TypeContrat, on_delete=models.PROTECT, null=True, blank=True)
    
    description     = models.TextField(blank=True)
    date_debut      = models.DateField()
    date_fin        = models.DateField()
    cout_annuel     = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'), verbose_name="Coût annuel (FCFA)")
    conditions_sla  = models.TextField(blank=True, verbose_name="Conditions SLA / Delais d'intervention")
    document_scan   = models.FileField(upload_to='contrats_maintenance/%Y/', null=True, blank=True)
    statut          = models.CharField(max_length=10, choices=STATUT_CHOICES, default='ACTIF')
    alerte_expiration_jours = models.PositiveSmallIntegerField(
        default=30,
        help_text="Nombre de jours avant expiration pour declencher une alerte"
    )
    frequence_mois = models.PositiveSmallIntegerField(
        default=12,
        help_text="Fréquence des maintenances préventives (en mois, ex. 12 = annuelle, 6 = semestrielle)"
    )

    @property
    def est_expire(self):
        return self.date_fin < timezone.now().date()

    @property
    def jours_restants(self):
        return (self.date_fin - timezone.now().date()).days

    @property
    def nb_equipements(self):
        return self.equipements.count()

    def __str__(self):
        return f"{self.reference} — {self.prestataire.raison_sociale}"

    class Meta:
        verbose_name        = "Contrat de maintenance"
        verbose_name_plural = "Contrats de maintenance"
        ordering            = ['date_fin']


# ═══════════════════════════════════════════════════════════
# 7. INTERVENTIONS
# ═══════════════════════════════════════════════════════════

class Intervention(TracabiliteModel):
    
    # 🟢 1. AJOUT DES CHOIX D'URGENCE
    URGENCE_CHOICES = [
        ('FAIBLE', 'Faible'),
        ('MOYENNE', 'Moyenne'),
        ('HAUTE', 'Haute'),
        ('CRITIQUE', 'Critique'),
    ]

    TYPE_CHOICES = [
        ('PREVENTIVE', 'Maintenance preventive'),
        ('CURATIVE',   'Maintenance curative (panne)'),
        ('URGENCE',    'Intervention urgente'),
        ('INVENTAIRE', 'Passage inventaire'),
        ('INSTALLATION','Installation / Mise en service'),
    ]

    # 🟢 2. AJOUT DES STATUTS MANQUANTS ('NOUVELLE' et 'ANNULEE')
    STATUT_CHOICES = [
        ('NOUVELLE',            'Nouvelle demande'),
        ('PLANIFIEE',           'Planifiee'),
        ('EN_COURS',            'En cours'),
        ('EN_ATTENTE_PIECES',   'En attente de pieces'),
        ('EN_ATTENTE_VALIDATION', 'En attente de validation (Cloture)'),
        ('EN_ATTENTE_DEVIS',    'Attente validation Devis (Frais)'), # 🟢 Le nouveau statut est ici
        ('RESOLUE',             'Resolue'),
        ('ESCALADEE',           'Escaladee / Non resolue'),
        ('ANNULEE',             'Annulee'),
    ]

    # Lien principal
    immobilisation          = models.ForeignKey(
        Immobilisation, on_delete=models.CASCADE, related_name='interventions'
    )
    contrat                 = models.ForeignKey(
        'ContratMaintenance', on_delete=models.SET_NULL,
        null=True, blank=True, related_name='interventions'
    )

    diagnostic = models.TextField(blank=True, null=True, verbose_name="Diagnostic de la panne")

    # Champs pour le workflow devis (BUG-06 corrig)
    frais_hors_contrat = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name='Montant devis hors contrat')
    motif_frais_hors_contrat = models.TextField(blank=True, default='', verbose_name='Motif des frais hors contrat')
    devis_accepte = models.BooleanField(null=True, blank=True, default=None, verbose_name='Devis accept ?')
    demandes_pieces = models.ManyToManyField(
        'stock.DemandeMateriel', 
        blank=True, 
        verbose_name="Demandes de pieces liees"
    )

    # Qui ?
    type_intervention       = models.CharField(max_length=15, choices=TYPE_CHOICES)
    
    # 🟢 3. LE FAMEUX CHAMP URGENCE !
    degre_urgence = models.CharField(
        max_length=15, 
        choices=URGENCE_CHOICES, 
        default='MOYENNE'
    )
    
    intervenant             = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='interventions_effectuees',
        help_text="Agent interne ou compte prestataire"
    )
    est_prestataire_externe = models.BooleanField(
        default=False,
        help_text="True si saisie par le portail prestataire"
    )

    # Quand ?
    date_signalement        = models.DateTimeField(default=timezone.now)
    date_debut_intervention = models.DateTimeField(null=True, blank=True)
    date_fin_intervention   = models.DateTimeField(null=True, blank=True)

    # ── 🌐 GESTION DES PRESTATAIRES EXTERNES (TRAÇABILITÉ) ──
    prestataire_concerne = models.ForeignKey(
        'stock.Fournisseur', on_delete=models.SET_NULL, null=True, blank=True,
        verbose_name="Entreprise Prestataire"
    )
    # Qui a-t-on appele au telephone ?
    technicien_appele = models.ForeignKey(
        'TechnicienPrestataire', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='appels_recus', verbose_name="Contacte par telephone"
    )
    date_appel_prestataire = models.DateTimeField(null=True, blank=True)
    
    # Qui est venu faire le travail ?
    technicien_intervenu = models.ForeignKey(
        'TechnicienPrestataire', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='interventions_physiques', verbose_name="Intervenu sur place"
    )
    
    # Preuve papier (Rapport)
    rapport_prestataire_scan = models.FileField(
        upload_to='scans/rapports_prestataires/%Y/%m/', null=True, blank=True,
        verbose_name="Scan du rapport d'intervention"
    )

    # ── 🚚 SORTIE MATÉRIEL POUR RÉPARATION ──
    necessite_sortie_reparation = models.BooleanField(
        default=False, verbose_name="Le materiel doit sortir du CHU"
    )
    bon_sortie_pdf = models.FileField(
        upload_to='bons_sortie/generes/%Y/%m/', null=True, blank=True,
        verbose_name="Bon de sortie genere (PDF)"
    )
    bon_sortie_signe_scan = models.FileField(
        upload_to='bons_sortie/signes/%Y/%m/', null=True, blank=True,
        verbose_name="Bon de sortie signe par la securite/prestataire"
    )
    date_retour_prevue = models.DateField(null=True, blank=True)
    date_retour_reelle = models.DateTimeField(null=True, blank=True)

    @property
    def duree_heures(self):
        if self.date_debut_intervention and self.date_fin_intervention:
            delta = self.date_fin_intervention - self.date_debut_intervention
            return round(delta.total_seconds() / 3600, 2)
        return None

    photo = models.ImageField(upload_to='interventions_photos/', null=True, blank=True, verbose_name="Photo du probleme")
    
    # Quoi ?
    description_probleme    = models.TextField(verbose_name="Description du probleme")
    actions_effectuees      = models.TextField(blank=True,
                                               verbose_name="Actions effectuees")
    pieces_remplacees       = models.JSONField(
        default=list, blank=True,
        help_text='[{"reference": "...", "designation": "...", "qte": 1, "prix_unit": 0}]'
    )

    # Coûts
    cout_main_oeuvre        = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00')
    )
    cout_pieces             = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00')
    )
    cout_deplacement        = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00')
    )

    @property
    def cout_total(self):
        return self.cout_main_oeuvre + self.cout_pieces + self.cout_deplacement

    # Validation
    statut                  = models.CharField(
        max_length=25, choices=STATUT_CHOICES, default='NOUVELLE' # Mis a jour sur NOUVELLE par defaut
    )
    valide_par              = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='interventions_validees'
    )
    date_validation         = models.DateTimeField(null=True, blank=True)
    commentaire_validation  = models.TextField(blank=True)
    signature_prestataire   = models.ImageField(
        upload_to='signatures/interventions/%Y/%m/',
        null=True, blank=True
    )

    def __str__(self):
        return f"{self.get_type_intervention_display()} — {self.immobilisation} ({self.date_signalement.date()})"

    class Meta:
        verbose_name        = "Intervention"
        verbose_name_plural = "Interventions"
        ordering            = ['-date_signalement']

# ═══════════════════════════════════════════════════════════
# 8. PORTAIL PRESTATAIRE
# ═══════════════════════════════════════════════════════════

class ComptePrestataire(TracabiliteModel):
    """
    Compte limite permettant a un prestataire de saisir ses propres interventions.
    Il ne voit que les equipements couverts par ses contrats.
    """
    user                = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='compte_prestataire'
    )
    fournisseur         = models.ForeignKey(
        'stock.Fournisseur', on_delete=models.CASCADE, related_name='comptes_portail'
    )
    contrats_autorises  = models.ManyToManyField(
        ContratMaintenance, blank=True, related_name='intervenants_autorises'
    )
    est_actif           = models.BooleanField(default=True)
    note_interne        = models.TextField(blank=True)

    def __str__(self):
        return f"Prestataire: {self.user.get_full_name()} ({self.fournisseur.raison_sociale})"

    class Meta:
        verbose_name = "Compte prestataire"



class TechnicienPrestataire(TracabiliteModel):
    """
    Repertoire des contacts/techniciens travaillant pour un fournisseur externe.
    (Pour les prestataires qui n'ont pas acces a l'application).
    """
    fournisseur = models.ForeignKey(
        'stock.Fournisseur', on_delete=models.PROTECT, related_name='techniciens_contacts'
    )
    nom = models.CharField(max_length=100)
    prenom = models.CharField(max_length=100, blank=True)
    telephone = models.CharField(max_length=30)
    specialite = models.CharField(max_length=100, blank=True, help_text="Ex: Frigoriste, Électronicien...")
    est_actif = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.nom} {self.prenom} ({self.fournisseur.raison_sociale})"

    class Meta:
        verbose_name = "Contact Prestataire"
        verbose_name_plural = "Contacts Prestataires"
        ordering = ['fournisseur', 'nom']


# ═══════════════════════════════════════════════════════════
# 9. IMPORT EXCEL — LOG
# ═══════════════════════════════════════════════════════════

class ImportPatrimoine(TracabiliteModel):
    """
    Trace chaque import Excel : qui, quand, quel type, combien de lignes.
    """
    type_equipement     = models.ForeignKey(
        TypeEquipement, on_delete=models.SET_NULL, null=True, blank=True,
        help_text="Type cible par cet import (None = import generique)"
    )
    fichier_original    = models.FileField(
        upload_to='imports_patrimoine/%Y/%m/',
        null=True, blank=True
    )
    nb_lignes_traitees  = models.PositiveIntegerField(default=0)
    nb_crees            = models.PositiveIntegerField(default=0)
    nb_mis_a_jour       = models.PositiveIntegerField(default=0)
    nb_erreurs          = models.PositiveIntegerField(default=0)
    log_erreurs         = models.JSONField(default=list, blank=True,
                                           help_text="Liste des lignes en erreur avec message")
    statut              = models.CharField(
        max_length=10,
        choices=[('OK', 'Succes'), ('PARTIEL', 'Partiel'), ('ECHEC', 'Échec')],
        default='OK'
    )

    def __str__(self):
        te = self.type_equipement.nom if self.type_equipement else "Generique"
        return f"Import {te} — {self.date_creation.strftime('%d/%m/%Y %H:%M')}"

    class Meta:
        verbose_name        = "Import patrimoine"
        verbose_name_plural = "Imports patrimoine"
        ordering            = ['-date_creation']


class ParametresPatrimoine(models.Model):
    MODE_CHOICES = [
        ('GLOBAL',  "Mode Global : Tout le monde voit toutes les demandes d'intervention."),
        ('DIRECT',  "Mode Direct : Les demandes sont vues directement par le technicien concerne (selon sa specialite/domaine)."),
        ('DISPATCH',"Mode Dispatch : Seul le chef voit les nouvelles demandes et les attribue aux techniciens."),
    ]
    
    # 🟢 AJOUTE CES CHOIX POUR LE PÉRIMÈTRE
    PERIMETRE_CHOICES = [
        ('LIBRE', 'Libre (Tout le parc)'),
        ('SERVICE', 'Limite au Service'),
        ('BUREAU', 'Limite au Bureau'),
    ]
    
    magasin_pieces = models.ForeignKey(
        'stock.Magasin', 
        on_delete=models.SET_NULL, 
        null=True, blank=True, 
        verbose_name="Magasin par defaut pour les pieces detachees"
    )
    
    mode_visibilite_interventions = models.CharField(
        max_length=20, 
        choices=MODE_CHOICES, 
        default='GLOBAL',
        verbose_name="Workflow de gestion des interventions"
    )

    # === MOTEUR DE VALIDATION ===
    validation_inventaire_active = models.BooleanField(default=False, verbose_name="Activer la validation des inventaires")
    validateurs_inventaire = models.ManyToManyField(User, blank=True, related_name="validateurs_inventaire_parc", verbose_name="Utilisateurs pouvant valider")

    # 🟢 VOICI LE CHAMP QUI MANQUAIT DANS TA BASE DE DONNÉES !
    perimetre_declaration = models.CharField(
        max_length=20,
        choices=PERIMETRE_CHOICES,
        default='LIBRE',
        verbose_name="Perimetre de declaration des pannes"
    )

    class Meta:
        verbose_name = "Parametres du Patrimoine"
        verbose_name_plural = "Parametres du Patrimoine"

    def __str__(self):
        return "Configuration Generale"

    @classmethod
    def get_parametres(cls):
        obj, created = cls.objects.get_or_create(pk=1)
        return obj
    

# ═══════════════════════════════════════════════════════════
# 7. GESTION DES INVENTAIRES PHYSIQUES
# ═══════════════════════════════════════════════════════════

class CampagneInventairePatrimoine(TracabiliteModel): # 🟢 ON A RENOMMÉ ICI
    STATUT_CHOICES = [
        ('BROUILLON', 'Brouillon'),
        ('EN_COURS', 'En cours'),
        ('EN_ATTENTE_VALIDATION', 'En attente de validation'), # 🟢 NOUVEAU STATUT
        ('TERMINEE', 'Terminee'),
    ]
    
    reference = models.CharField(max_length=50, unique=True, verbose_name="Ref. Inventaire")
    titre = models.CharField(max_length=150, verbose_name="Titre de la campagne (Ex: Inventaire Info 2026)")
    date_debut = models.DateField()
    date_fin_prevue = models.DateField(null=True, blank=True)
    
    # Perimetre de l'inventaire
    categorie_cible = models.ForeignKey(CategoriePatrimoine, on_delete=models.SET_NULL, null=True, blank=True, help_text="Laisser vide pour un inventaire global")
    batiment_cible = models.ForeignKey(Batiment, on_delete=models.SET_NULL, null=True, blank=True, help_text="Laisser vide pour tout le CHU")
    
    statut = models.CharField(max_length=50, choices=STATUT_CHOICES, default='BROUILLON')
    responsable = models.ForeignKey(User, on_delete=models.PROTECT, related_name='inventaires_patrimoine_supervises') # 🟢 On a change le related_name

    

    def __str__(self):
        return f"{self.reference} - {self.titre}"

    class Meta:
        verbose_name = "Campagne d'Inventaire Patrimoine"
        verbose_name_plural = "Campagnes d'Inventaire Patrimoine"
        ordering = ['-date_debut']


class LigneInventairePatrimoine(TracabiliteModel): # 🟢 ON A RENOMMÉ ICI AUSSI
    ETAT_CONSTATE_CHOICES = [
        ('PRESENT', 'Present et conforme'),
        ('DEPLACE', 'Present mais dans un autre bureau'),
        ('MANQUANT', 'Introuvable / Perdu'),
        ('A_REFORMER', 'Present mais hors d\'usage (À jeter)')
    ]

    campagne = models.ForeignKey(CampagneInventairePatrimoine, on_delete=models.CASCADE, related_name='lignes') # 🟢 On pointe vers le nouveau nom
    immobilisation = models.ForeignKey(Immobilisation, on_delete=models.CASCADE, related_name='historique_inventaires')
    
    etat_constate = models.CharField(max_length=20, choices=ETAT_CONSTATE_CHOICES, null=True, blank=True)
    bureau_constate = models.ForeignKey(Bureau, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Bureau ou la machine a ete vue")
    
    scanne_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    date_scan = models.DateTimeField(null=True, blank=True)
    commentaire = models.TextField(blank=True)

    def __str__(self):
        return f"{self.immobilisation.code_patrimoine} - {self.get_etat_constate_display()}"

    class Meta:
        verbose_name = "Ligne d'Inventaire Patrimoine"
        verbose_name_plural = "Lignes d'Inventaire Patrimoine"
        unique_together = ('campagne', 'immobilisation')



# ═══════════════════════════════════════════════════════════
# 10. GESTION DES VEHICULES
# ═══════════════════════════════════════════════════════════


class Vehicule(TracabiliteModel):
    """
    Gestion des vehicules du CHU : immatriculation, assurance, maintenance, etc.
    """
    STATUT_CHOICES = [
        ('DISPONIBLE',  'Disponible'),
        ('EN_SERVICE',  'En service / En mission'),
        ('EN_MAINTENANCE', 'En maintenance'),
        ('HORS_SERVICE', 'Hors service'),
    ]

    TYPE_VEHICULE_CHOICES = [
        ('BERLINE',    'Berline'),
        ('SUV',        'SUV'),
        ('PICKUP',     'Pick-up'),
        ('VAN',        'Van / Utilitaire'),
        ('CAMION',     'Camion'),
        ('MOTO',       'Moto'),
        ('AMBULANCE',  'Ambulance'),
        ('AUTRE',      'Autre'),
    ]

    # Identification
    immatriculation = models.CharField(max_length=30, unique=True, verbose_name="Immatriculation")
    marque          = models.ForeignKey(Marque, on_delete=models.SET_NULL, null=True, blank=True)
    modele          = models.ForeignKey(Modele, on_delete=models.SET_NULL, null=True, blank=True)
    type_vehicule   = models.CharField(max_length=20, choices=TYPE_VEHICULE_CHOICES, default='BERLINE')
    couleur         = models.CharField(max_length=30, blank=True)
    numero_chassis  = models.CharField(max_length=50, blank=True, verbose_name="N° de châssis")
    kilometrage     = models.PositiveIntegerField(default=0, verbose_name="Kilométrage actuel (km)")

    # Caractéristiques
    carburant       = models.CharField(max_length=20, choices=[('ESSENCE', 'Essence'), ('DIESEL', 'Diesel'), ('ELECTRIQUE', 'Électrique'), ('HYBRIDE', 'Hybride')], default='DIESEL')
    puissance_cv    = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="Puissance (CV)")
    date_premiere_circulation = models.DateField(null=True, blank=True, verbose_name="1ère mise en circulation")

    # Acquisition
    date_acquisition    = models.DateField(null=True, blank=True)
    valeur_acquisition  = models.DecimalField(max_digits=14, decimal_places=2, default=Decimal('0.00'), verbose_name="Valeur d'acquisition (FCFA)")
    fournisseur         = models.ForeignKey('stock.Fournisseur', on_delete=models.SET_NULL, null=True, blank=True)

    # Assurance
    assurance_compagnie  = models.CharField(max_length=150, blank=True, verbose_name="Compagnie d'assurance")
    assurance_numero     = models.CharField(max_length=100, blank=True, verbose_name="N° de police")
    assurance_debut      = models.DateField(null=True, blank=True, verbose_name="Début assurance")
    assurance_fin        = models.DateField(null=True, blank=True, verbose_name="Fin assurance")
    assurance_premium    = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), verbose_name="Prime annuelle (FCFA)")

    # Contrôle technique
    ct_dernier_date      = models.DateField(null=True, blank=True, verbose_name="Date dernier CT")
    ct_prochaine_date    = models.DateField(null=True, blank=True, verbose_name="Prochain CT")

    # Affectation
    service_affectation  = models.ForeignKey('core.Service', on_delete=models.SET_NULL, null=True, blank=True)
    conducteur_titulaire = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='vehicules_conduits')
    garage               = models.CharField(max_length=200, blank=True, verbose_name="Garage / Stationnement")

    # Statut
    statut               = models.CharField(max_length=20, choices=STATUT_CHOICES, default='DISPONIBLE')
    notes                = models.TextField(blank=True)
    photo                = models.ImageField(upload_to='vehicules/', null=True, blank=True)

    # Immobilisation liée (optionnel)
    immobilisation       = models.ForeignKey(Immobilisation, on_delete=models.SET_NULL, null=True, blank=True, related_name='vehicules')

    @property
    def assurance_valide(self):
        if not self.assurance_fin:
            return None
        return self.assurance_fin >= timezone.now().date()

    @property
    def jours_avant_assurance(self):
        if not self.assurance_fin:
            return None
        return (self.assurance_fin - timezone.now().date()).days

    @property
    def ct_a_jour(self):
        if not self.ct_prochaine_date:
            return None
        return self.ct_prochaine_date >= timezone.now().date()

    @property
    def age_annees(self):
        if not self.date_premiere_circulation:
            return None
        delta = (timezone.now().date() - self.date_premiere_circulation).days
        return round(delta / 365, 1)

    def __str__(self):
        return f"{self.immatriculation} ({self.marque or ''} {self.modele or ''})".strip()

    class Meta:
        verbose_name = "Véhicule"
        verbose_name_plural = "Véhicules"
        ordering = ['immatriculation']


class InterventionVehicule(TracabiliteModel):
    """
    Interventions / maintenances sur un véhicule.
    """
    TYPE_CHOICES = [
        ('ENTRETIEN',     'Entretien courant'),
        ('REPARATION',    'Réparation'),
        ('VIDANGE',       'Vidange'),
        ('PNEU',          'Changement pneus'),
        ('ASSURANCE',     'Renouvellement assurance'),
        ('CT',            'Contrôle technique'),
        ('CARROSSERIE',   'Carrosserie / Peinture'),
        ('ELECTRIQUE',    'Électronique / Électrique'),
        ('AUTRE',         'Autre'),
    ]
    STATUT_CHOICES = [
        ('PLANIFIEE',  'Planifiée'),
        ('EN_COURS',   'En cours'),
        ('TERMINEE',   'Terminée'),
        ('ANNULEE',    'Annulée'),
    ]

    vehicule         = models.ForeignKey(Vehicule, on_delete=models.CASCADE, related_name='interventions_vehicule')
    type_intervention = models.CharField(max_length=20, choices=TYPE_CHOICES)
    statut            = models.CharField(max_length=15, choices=STATUT_CHOICES, default='PLANIFIEE')
    date_prevue       = models.DateField(null=True, blank=True)
    date_realisation  = models.DateField(null=True, blank=True)
    garage_prestataire = models.CharField(max_length=200, blank=True, verbose_name="Garage / Prestataire")
    description       = models.TextField(blank=True)
    cout              = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'), verbose_name="Coût (FCFA)")
    kilometrage       = models.PositiveIntegerField(null=True, blank=True, verbose_name="Kilométrage au moment de l'intervention")
    kilometre_prochaine_vidange = models.PositiveIntegerField(null=True, blank=True, verbose_name="Prochaine vidange à (km)")

    @property
    def duree_jours(self):
        if self.date_prevue and self.date_realisation:
            return (self.date_realisation - self.date_prevue).days
        return None

    def __str__(self):
        return f"{self.get_type_intervention_display()} — {self.vehicule.immatriculation}"

    class Meta:
        verbose_name = "Intervention véhicule"
        verbose_name_plural = "Interventions véhicules"
        ordering = ['-date_prevue']


class MissionVehicule(TracabiliteModel):
    """
    Enregistrement des missions / déplacements effectués avec un véhicule.
    """
    STATUT_CHOICES = [
        ('EN_COURS',  'En cours'),
        ('TERMINEE',  'Terminée'),
        ('ANNULEE',   'Annulée'),
    ]

    vehicule        = models.ForeignKey(Vehicule, on_delete=models.CASCADE, related_name='missions')
    chauffeur        = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    objet            = models.CharField(max_length=255, verbose_name="Objet de la mission")
    destination      = models.CharField(max_length=255, verbose_name="Destination")
    date_depart      = models.DateTimeField()
    date_retour      = models.DateTimeField(null=True, blank=True)
    km_depart        = models.PositiveIntegerField(null=True, blank=True, verbose_name="KM au départ")
    km_retour        = models.PositiveIntegerField(null=True, blank=True, verbose_name="KM au retour")
    statut           = models.CharField(max_length=15, choices=STATUT_CHOICES, default='EN_COURS')
    demandeur        = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='missions_demandees')
    service_demandeur = models.ForeignKey('core.Service', on_delete=models.SET_NULL, null=True, blank=True)
    observation      = models.TextField(blank=True)

    @property
    def km_parcourus(self):
        if self.km_depart and self.km_retour:
            return self.km_retour - self.km_depart
        return None

    @property
    def duree_heures(self):
        if self.date_depart and self.date_retour:
            delta = self.date_retour - self.date_depart
            return round(delta.total_seconds() / 3600, 1)
        return None

    def __str__(self):
        return f"{self.vehicule.immatriculation} — {self.objet} ({self.date_depart.date()})"

    class Meta:
        verbose_name = "Mission véhicule"
        verbose_name_plural = "Missions véhicules"
        ordering = ['-date_depart']



# ═══════════════════════════════════════════════════════════
# 11. GESTION DES SALLES DE CONFÉRENCE
# ═══════════════════════════════════════════════════════════


class SalleConference(TracabiliteModel):
    """
    Salle de conférence / réunion avec réservation.
    """
    STATUT_CHOICES = [
        ('DISPONIBLE',   'Disponible'),
        ('INDISPONIBLE', 'Indisponible'),
        ('EN_MAINTENANCE', 'En maintenance'),
    ]

    nom             = models.CharField(max_length=150, verbose_name="Nom de la salle")
    code            = models.CharField(max_length=20, unique=True, verbose_name="Code salle")
    batiment        = models.ForeignKey(Batiment, on_delete=models.SET_NULL, null=True, blank=True)
    etage           = models.ForeignKey(Etage, on_delete=models.SET_NULL, null=True, blank=True)
    bureau          = models.ForeignKey(Bureau, on_delete=models.SET_NULL, null=True, blank=True)
    capacite        = models.PositiveSmallIntegerField(default=10, verbose_name="Capacité (personnes)")
    superficie_m2   = models.PositiveSmallIntegerField(null=True, blank=True)
    description     = models.TextField(blank=True)

    # Équipements
    videoconf       = models.BooleanField(default=False, verbose_name="Vidéoconférence")
    ecran_projecteur = models.BooleanField(default=False, verbose_name="Écran / Vidéoprojecteur")
    tableau_blanc   = models.BooleanField(default=False, verbose_name="Tableau blanc")
    wifi            = models.BooleanField(default=True, verbose_name="WiFi")
    climatisation   = models.BooleanField(default=False, verbose_name="Climatisation")
    sonorisation    = models.BooleanField(default=False, verbose_name="Système son")
    micro           = models.BooleanField(default=False, verbose_name="Micro")
    equipements_supplementaires = models.JSONField(default=list, blank=True, help_text='["Rétroprojecteur", "Podium"]')

    # Statut
    statut          = models.CharField(max_length=20, choices=STATUT_CHOICES, default='DISPONIBLE')
    image           = models.ImageField(upload_to='salles/', null=True, blank=True)
    notes           = models.TextField(blank=True)

    # Service responsable
    service_gestionnaire = models.ForeignKey('core.Service', on_delete=models.SET_NULL, null=True, blank=True, related_name='salles_gerees')

    @property
    def equipements_liste(self):
        """Liste des équipements disponibles dans la salle."""
        eq = []
        if self.videoconf: eq.append('Vidéoconférence')
        if self.ecran_projecteur: eq.append('Écran/Vidéoprojecteur')
        if self.tableau_blanc: eq.append('Tableau blanc')
        if self.wifi: eq.append('WiFi')
        if self.climatisation: eq.append('Climatisation')
        if self.sonorisation: eq.append('Sonorisation')
        if self.micro: eq.append('Micro')
        if self.equipements_supplementaires:
            eq.extend(self.equipements_supplementaires)
        return eq

    def __str__(self):
        return f"{self.nom} ({self.capacite} places)"

    class Meta:
        verbose_name = "Salle de conférence"
        verbose_name_plural = "Salles de conférence"
        ordering = ['nom']


class ReservationSalle(TracabiliteModel):
    """
    Réservation d'une salle de conférence.
    """
    STATUT_CHOICES = [
        ('EN_ATTENTE', 'En attente de validation'),
        ('CONFIRMEE',  'Confirmée'),
        ('ANNULEE',    'Annulée'),
        ('TERMINEE',   'Terminée'),
    ]

    salle           = models.ForeignKey(SalleConference, on_delete=models.CASCADE, related_name='reservations')
    demandeur       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='reservations_salle')
    service_demandeur = models.ForeignKey('core.Service', on_delete=models.SET_NULL, null=True, blank=True)

    objet           = models.CharField(max_length=255, verbose_name="Objet de la réunion")
    description     = models.TextField(blank=True)
    nb_participants  = models.PositiveSmallIntegerField(default=1, verbose_name="Nombre de participants")

    date_debut      = models.DateTimeField(verbose_name="Date/heure début")
    date_fin        = models.DateTimeField(verbose_name="Date/heure fin")

    recurrente      = models.BooleanField(default=False, verbose_name="Réservation récurrente")
    frequence       = models.CharField(
        max_length=20, blank=True,
        choices=[('HEBDOMADAIRE', 'Hebdomadaire'), ('BIMENSUEL', 'Bimensuel'), ('MENSUEL', 'Mensuel')],
        help_text="Fréquence si récurrente"
    )

    statut          = models.CharField(max_length=15, choices=STATUT_CHOICES, default='EN_ATTENTE')
    valide_par      = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='reservations_validees')
    date_validation = models.DateTimeField(null=True, blank=True)
    motif_refus     = models.TextField(blank=True)

    # Équipements demandés
    besoin_videoconf  = models.BooleanField(default=False)
    besoin_video      = models.BooleanField(default=False)
    besoin_son        = models.BooleanField(default=False)
    notes_equipement  = models.TextField(blank=True, verbose_name="Notes équipements")

    @property
    def duree_heures(self):
        if self.date_debut and self.date_fin:
            delta = self.date_fin - self.date_debut
            return round(delta.total_seconds() / 3600, 1)
        return None

    @property
    def est_active(self):
        now = timezone.now()
        return self.date_debut <= now <= self.date_fin and self.statut == 'CONFIRMEE'

    @property
    def conflits(self):
        """Vérifie les conflits de réservation pour cette salle."""
        return ReservationSalle.objects.filter(
            salle=self.salle,
            statut__in=['EN_ATTENTE', 'CONFIRMEE'],
            date_debut__lt=self.date_fin,
            date_fin__gt=self.date_debut
        ).exclude(pk=self.pk)

    def clean(self):
        if self.date_debut and self.date_fin and self.date_fin <= self.date_debut:
            raise ValidationError('La date de fin doit être postérieure à la date de début.')
        if self.nb_participants and self.salle and self.nb_participants > self.salle.capacite:
            raise ValidationError(f'Le nombre de participants ({self.nb_participants}) dépasse la capacité de la salle ({self.salle.capacite}).')

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.salle.nom} — {self.objet} ({self.date_debut})"

    class Meta:
        verbose_name = "Réservation salle"
        verbose_name_plural = "Réservations salles"
        ordering = ['-date_debut']



# ═══════════════════════════════════════════════════════════
# 12. DEMANDES DE VÉHICULES
# ═══════════════════════════════════════════════════════════


class DemandeVehicule(TracabiliteModel):
    """
    Demande d'affectation temporaire d'un véhicule par un utilisateur.
    """
    STATUT_CHOICES = [
        ('EN_ATTENTE',  'En attente de validation'),
        ('VALIDEE',     'Validée — véhicule affecté'),
        ('REFUSEE',     'Refusée'),
        ('ANNULEE',     'Annulée par le demandeur'),
        ('TERMINEE',    'Terminée — véhicule rendu'),
    ]

    URGENCY_CHOICES = [
        ('NORMALE',  'Normale'),
        ('URGENTE',  'Urgente'),
        ('CRITIQUE', 'Critique'),
    ]

    # Demande
    demandeur          = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='demandes_vehicule')
    service_demandeur  = models.ForeignKey('core.Service', on_delete=models.SET_NULL, null=True, blank=True)
    date_demande       = models.DateTimeField(auto_now_add=True)
    
    # Mission
    objet              = models.CharField(max_length=255, verbose_name="Objet de la mission")
    destination        = models.CharField(max_length=255, verbose_name="Destination")
    date_depart        = models.DateTimeField(verbose_name="Date/heure de départ souhaitée")
    date_retour_prevue = models.DateTimeField(verbose_name="Date/heure de retour prévue")
    nb_passagers       = models.PositiveSmallIntegerField(default=1, verbose_name="Nombre de passagers")
    urgency            = models.CharField(max_length=10, choices=URGENCY_CHOICES, default='NORMALE')
    motif              = models.TextField(blank=True, verbose_name="Motif détaillé")

    # Véhicule affecté (rempli à la validation)
    vehicule           = models.ForeignKey(Vehicule, on_delete=models.SET_NULL, null=True, blank=True, related_name='demandes')
    chauffeur          = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='chauffeur_demandes')
    km_depart          = models.PositiveIntegerField(null=True, blank=True)
    km_retour          = models.PositiveIntegerField(null=True, blank=True)

    # Validation
    statut             = models.CharField(max_length=15, choices=STATUT_CHOICES, default='EN_ATTENTE')
    valide_par         = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='demandes_vehicule_validees')
    date_validation    = models.DateTimeField(null=True, blank=True)
    motif_refus        = models.TextField(blank=True)
    commentaire_valider = models.TextField(blank=True)
    observation_retour  = models.TextField(blank=True)

    @property
    def duree_heures(self):
        if self.date_depart and self.date_retour_prevue:
            delta = self.date_retour_prevue - self.date_depart
            return round(delta.total_seconds() / 3600, 1)
        return None

    @property
    def km_parcourus(self):
        if self.km_depart and self.km_retour:
            return self.km_retour - self.km_depart
        return None

    def __str__(self):
        return f"{self.objet} — {self.demandeur.get_full_name()} ({self.get_statut_display()})"

    class Meta:
        verbose_name = "Demande de véhicule"
        verbose_name_plural = "Demandes de véhicules"
        ordering = ['-date_demande']


# ═══════════════════════════════════════════════════════════
# 13. DEMANDES DE SALLES SIMPLIFIÉES
# ═══════════════════════════════════════════════════════════


class DemandeSalle(TracabiliteModel):
    """
    Demande simplifiée de salle de conférence pour les utilisateurs.
    """
    STATUT_CHOICES = [
        ('EN_ATTENTE',  'En attente'),
        ('VALIDEE',     'Validée'),
        ('REFUSEE',     'Refusée'),
        ('ANNULEE',     'Annulée'),
    ]

    # Demande
    demandeur          = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='demandes_salle')
    service_demandeur  = models.ForeignKey('core.Service', on_delete=models.SET_NULL, null=True, blank=True)
    date_demande       = models.DateTimeField(auto_now_add=True)

    # Réunion
    objet              = models.CharField(max_length=255, verbose_name="Objet de la réunion")
    description        = models.TextField(blank=True)
    date_debut         = models.DateTimeField(verbose_name="Date/heure début souhaitée")
    date_fin           = models.DateTimeField(verbose_name="Date/heure fin souhaitée")
    nb_participants    = models.PositiveSmallIntegerField(default=1)

    # Salle préférée (optionnel)
    salle_preferee     = models.ForeignKey(SalleConference, on_delete=models.SET_NULL, null=True, blank=True, related_name='demandes')

    # Équipements souhaités
    besoin_videoconf   = models.BooleanField(default=False)
    besoin_video       = models.BooleanField(default=False)
    besoin_son         = models.BooleanField(default=False)
    notes_equipement   = models.TextField(blank=True)

    # Validation
    statut             = models.CharField(max_length=15, choices=STATUT_CHOICES, default='EN_ATTENTE')
    salle_attribuee    = models.ForeignKey(SalleConference, on_delete=models.SET_NULL, null=True, blank=True, related_name='attributions')
    valide_par         = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='demandes_salle_validees')
    date_validation    = models.DateTimeField(null=True, blank=True)
    motif_refus        = models.TextField(blank=True)

    @property
    def duree_heures(self):
        if self.date_debut and self.date_fin:
            delta = self.date_fin - self.date_debut
            return round(delta.total_seconds() / 3600, 1)
        return None

    def __str__(self):
        return f"{self.objet} — {self.demandeur.get_full_name()} ({self.get_statut_display()})"

    class Meta:
        verbose_name = "Demande de salle"
        verbose_name_plural = "Demandes de salles"
        ordering = ['-date_demande']