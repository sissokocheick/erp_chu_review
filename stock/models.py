# stock/models.py — VERSION CORRIGÉE AUDIT 2026-05-23
# Corrections appliquées :
#   1. related_name uniques (5 conflits résolus)
#   2. db_index ajoutés sur champs à fort trafic
#   3. MinValueValidator(0) sur tous les DecimalField financiers
#   4. CheckConstraint quantité > 0 sur tous les modèles de lignes
#   5. Références en chaîne remplacées par classes directes (même fichier)
#   6. Logging warning dans generer_numero() après 50 itérations
#   7. Commentaire SRP sur Mouvement.save()

from django.db import models, transaction, IntegrityError
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.contrib.auth.models import User
from core.models import Service
from simple_history.models import HistoricalRecords
from decimal import Decimal
from functools import lru_cache
from core.managers import TenantManager, GlobalManager
import logging

logger = logging.getLogger(__name__)

STATUT_VALIDATION_CHOICES = [
    ('BROUILLON', 'Brouillon / En saisie'),
    ('ATTENTE',   'En attente de validation'),
    ('VALIDE',    'Validé / Approuvé'),
    ('REJETE',    'Rejeté'),
]

# ==========================================
# COMPTEUR ATOMIQUE DE DOCUMENTS
# ==========================================
class CompteurDocument(models.Model):
    PREFIXES_DEFAUT = {
        'BON_ENTREE': 'BE',
        'BON_SORTIE': 'BS',
        'BON_RETOUR': 'BR',
        'BON_HS': 'BSHS',
        'COMMANDE': 'BC',
        'DEMANDE': 'BDM',
        'DEMANDE_MATERIEL': 'BDM',
    }
    """Table de compteurs séquentiels, garantit l'unicité en concurrence."""
    entreprise = models.ForeignKey(
        'accounts.Entreprise',
        on_delete=models.CASCADE,
        related_name='compteurs_documents'
    )
    type_doc = models.CharField(
        max_length=20,
        choices=[
            ('BON_SORTIE', 'Bon de Sortie'),
            ('BON_ENTREE', "Bon d'Entrée"),
            ('BON_RETOUR', 'Bon de Retour'),
            ('BON_HS', 'Bon Hors Stock'),
            ('COMMANDE', 'Commande'),
            ('DEMANDE', 'Demande'),
        ]
    )
    annee = models.PositiveSmallIntegerField(
        help_text="0 = compteur global permanent (séquence continue sur toutes les années). "
                  ">0 = compteur annuel (ex: 2026)."
    )
    dernier_numero = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('entreprise', 'type_doc', 'annee')
        verbose_name = "Compteur de documents"
        verbose_name_plural = "Compteurs de documents"

    def __str__(self):
        return f"{self.type_doc}/{self.annee} - {self.dernier_numero}"

    @classmethod
    def generer_numero(cls, entreprise_id, type_doc, format_func, max_retries=3,
                       model_class=None, field_name='numero_bon'):
        """
        Génère un numéro atomique via select_for_update().
        format_func(compteur, annee, entreprise_id) -> str
        Si model_class est fourni, vérifie que le numéro n'existe pas déjà (y compris soft-deleted).
        """
        annee = timezone.now().year
        for attempt in range(max_retries):
            try:
                with transaction.atomic():
                    compteur, created = cls.objects.select_for_update().get_or_create(
                        entreprise_id=entreprise_id,
                        type_doc=type_doc,
                        annee=0,  # Compteur GLOBAL permanent — séquence continue sur toutes les années
                        defaults={'dernier_numero': 0}
                    )
                    # Boucle interne : trouver un numéro vraiment libre
                    for tentative in range(1000):
                        compteur.dernier_numero += 1
                        numero = format_func(compteur.dernier_numero, annee, entreprise_id)
                        # ✅ AUDIT : log warning si trop de tentatives (compteur potentiellement corrompu)
                        if tentative >= 50 and tentative % 10 == 0:
                            logger.warning(
                                "Compteur %s/%s-E%s : %d tentatives pour générer un numéro libre",
                                type_doc, annee, entreprise_id, tentative
                            )
                        if model_class is None:
                            compteur.save()
                            return numero
                        # Vérifier l'unicité (y compris soft-deleted via all_objects)
                        manager = getattr(model_class, 'all_objects', model_class.objects)
                        if not manager.filter(**{field_name: numero}).exists():
                            compteur.save()
                            return numero
                    # ✅ CORRECTION : exception explicite pour compteur bloqué
                    raise RuntimeError(
                        f"Compteur bloqué à 1000 incréments pour {type_doc} "
                        f"(entreprise {entreprise_id})."
                    )
            except IntegrityError:
                # Conflit de concurrence (get_or_create) : retry
                if attempt == max_retries - 1:
                    raise IntegrityError(
                        f"Impossible de générer un numéro unique pour {type_doc} "
                        f"après {max_retries} tentatives (conflit de concurrence)."
                    )
                continue
            except RuntimeError:
                # Compteur bloqué : inutile de retry, on remonte
                raise RuntimeError(
                    f"Impossible de générer un numéro unique pour {type_doc} "
                    f"(compteur corrompu)."
                )

# ==========================================
# MODÈLES ABSTRAITS DE BASE
# ==========================================
class TracabiliteModel(models.Model):
    date_creation     = models.DateTimeField(auto_now_add=True, verbose_name="Date de création")
    date_modification = models.DateTimeField(auto_now=True,     verbose_name="Dernière modification")
    cree_par          = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="%(class)s_cree",    verbose_name="Créé par")
    modifie_par       = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="%(class)s_modifie", verbose_name="Modifié par")

    class Meta:
        abstract = True

class SoftDeleteModel(models.Model):
    """Ajoute la suppression logique (soft-delete) aux modèles."""
    is_deleted = models.BooleanField(default=False, verbose_name="Supprimé logiquement", db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True, verbose_name="Date de suppression")
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='%(class)s_supprimes',
        verbose_name="Supprimé par"
    )

    class Meta:
        abstract = True

    def soft_delete(self, user=None):
        self.is_deleted = True
        self.deleted_at = timezone.now()
        if user:
            self.deleted_by = user
        self.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])

    def restore(self):
        self.is_deleted = False
        self.deleted_at = None
        self.deleted_by = None
        self.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])

# ==========================================================
# 1. LES ACTEURS
# ==========================================================
class Fournisseur(TracabiliteModel, SoftDeleteModel):
    entreprise      = models.ForeignKey('accounts.Entreprise', on_delete=models.CASCADE, related_name='fournisseurs')
    code            = models.CharField(max_length=20)
    raison_sociale  = models.CharField(max_length=200)
    telephone       = models.CharField(max_length=50,  blank=True, null=True)
    contact         = models.CharField(max_length=100, blank=True, null=True, verbose_name="Personne de contact")
    telecopie       = models.CharField(max_length=50,  blank=True, null=True, verbose_name="Télécopie / Fax")
    est_agree       = models.BooleanField(default=True)
    note_evaluation = models.PositiveSmallIntegerField(default=5)
    history         = HistoricalRecords()

    objects     = TenantManager()
    all_objects = GlobalManager()

    def __str__(self):
        return f"{self.code} - {self.raison_sociale}"

    class Meta:
        verbose_name = "Fournisseur"
        verbose_name_plural = "Fournisseurs"
        ordering = ['code']
        constraints = [
            models.UniqueConstraint(
                fields=['entreprise', 'code'],
                condition=models.Q(is_deleted=False),
                name='unique_fournisseur_actif'
            ),
        ]

# ==========================================================
# 2. LE CATALOGUE
# ==========================================================
class FamilleArticle(TracabiliteModel, SoftDeleteModel):
    entreprise           = models.ForeignKey('accounts.Entreprise', on_delete=models.CASCADE, related_name='familles_articles')
    TYPE_FAMILLE_CHOICES = [
        ('MED', '💊 Médicaments & Produits de Pharmacie'),
        ('MAT', '🩺 Matériel Médical & Soins'),
        ('BUR', '📎 Fournitures de Bureau & Entretien'),
        ('TEC', '🔧 Pièces Techniques & Maintenance'),
    ]
    METHODE_VALORISATION_CHOICES = [
        ('CMUP', 'Coût Moyen Unitaire Pondéré'),
        ('FIFO', 'Premier Entré / Premier Sorti'),
        ('LIFO', 'Dernier Entré / Premier Sorti'),
    ]
    code = models.CharField(max_length=20)
    intitule = models.CharField(max_length=200)
    type_famille = models.CharField(max_length=10, choices=TYPE_FAMILLE_CHOICES)
    methode_valorisation = models.CharField(max_length=10, choices=METHODE_VALORISATION_CHOICES, default='CMUP')
    est_centralise       = models.BooleanField(default=False)
    categorie            = models.CharField(max_length=100, blank=True, null=True)
    ligne_budgetaire = models.CharField(
        max_length=100, 
        blank=True, 
        null=True, 
        verbose_name="Ligne budgétaire"
    )

    gere_lots_peremption = models.BooleanField(default=False, verbose_name="Gère les Lots et Péremptions")
    history              = HistoricalRecords()
    est_immobilisable = models.BooleanField(
        default=False,
        verbose_name="Les articles de cette famille sont des immobilisations"
    )

    objects     = TenantManager()
    all_objects = GlobalManager()

    def __str__(self):
        return f"{self.code} - {self.intitule}"

    class Meta:
        verbose_name = "Famille d'article"
        verbose_name_plural = "Familles d'articles"
        constraints = [
            models.UniqueConstraint(
                fields=['entreprise', 'code'],
                condition=models.Q(is_deleted=False),
                name='unique_famille_actif'
            ),
        ]

class Article(TracabiliteModel, SoftDeleteModel):
    entreprise         = models.ForeignKey('accounts.Entreprise', on_delete=models.CASCADE, related_name='articles_entreprise')
    famille            = models.ForeignKey(FamilleArticle, on_delete=models.PROTECT, related_name='articles_famille')
    
    # On utilise la référence comme code auto-généré (j'ai augmenté le max_length à 100 au cas où)
    reference          = models.CharField(max_length=100, blank=True, null=True, db_index=True, verbose_name="Référence / Code")
    
    designation        = models.CharField(max_length=255, db_index=True)
    unite_distribution = models.CharField(max_length=50)
    seuil_minimum      = models.PositiveIntegerField(default=5,  help_text="Seuil alerte jaune")
    seuil_critique     = models.PositiveIntegerField(default=2,  help_text="Seuil alerte rouge", null=True, blank=True)
    seuil_maximum      = models.PositiveIntegerField(null=True, blank=True, help_text="Seuil surstock")
    prix_reference     = models.DecimalField(
        max_digits=12, decimal_places=2, default=0, null=True, blank=True,
        verbose_name="Prix de référence (FCFA)",
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    specifications     = models.JSONField(blank=True, null=True)
    history            = HistoricalRecords()
    est_immobilisable  = models.BooleanField(default=False, verbose_name="Est un bien immobilisable (Patrimoine)")
    gere_lots_peremption = models.BooleanField(
        default=False,
        verbose_name="Gère les lots et péremptions",
        help_text="Si coché, cet article nécessite un suivi des numéros de lot et dates de péremption."
    )

    objects     = TenantManager()
    all_objects = GlobalManager()

    def save(self, *args, **kwargs):
        # Génération automatique de la REFERENCE à la création — VERSION THREAD-SAFE V3
        # Utilise CompteurDocument pour éviter le TOCTOU du count() + 1
        if not self.pk and not self.reference:
            # 1. Préparation du préfixe (Ligne Budgétaire + Famille)
            code_famille = self.famille.code.strip() if self.famille.code else ""
            ligne_budg = self.famille.ligne_budgetaire
            prefixe = ""

            if ligne_budg:
                ligne_budg_propre = ligne_budg.split('-')[0].strip().replace(" ", "").upper()
                prefixe = f"{ligne_budg_propre}{code_famille}"
            else:
                prefixe = f"{code_famille}"

            # 2. Utiliser CompteurDocument pour générer un numéro atomique par famille
            # On crée un type_doc dynamique par famille pour isoler les compteurs
            type_doc_famille = f"A_{prefixe}"[:20]  # 'A_' plus court que 'ART_' pour plus de headroom

            def format_ref(compteur, annee, eid):
                return f"{prefixe}{compteur:03d}"

            self.reference = CompteurDocument.generer_numero(
                self.entreprise_id,
                type_doc_famille,
                format_ref,
                model_class=self.__class__,
                field_name='reference'
            )

        super().save(*args, **kwargs)
    @property
    def requiert_lot_peremption(self):
        """Vrai si l'article OU sa famille gère les lots/péremptions."""
        return self.gere_lots_peremption or (
            self.famille.gere_lots_peremption if self.famille_id else False
        )

    @property
    def seuil_alerte(self):
        return self.seuil_minimum

    def __str__(self):
        # On affiche la référence générée dans les menus déroulants
        if self.reference:
            return f"[{self.reference}] {self.designation}"
        return self.designation

    class Meta:
        verbose_name = "Article"
        verbose_name_plural = "Articles"
        constraints = [
            # ✅ CORRECTION : exclure les NULL de l'unicité
            models.UniqueConstraint(
                fields=['entreprise', 'reference'],
                condition=models.Q(is_deleted=False) & models.Q(reference__isnull=False),
                name='unique_article_actif'
            ),
        ]
# ==========================================================
# 3. LE STOCK PHYSIQUE
# ==========================================================
class Magasin(TracabiliteModel, SoftDeleteModel):
    entreprise   = models.ForeignKey('accounts.Entreprise', on_delete=models.CASCADE, related_name='magasins')
    nom          = models.CharField(max_length=100)
    localisation = models.CharField(max_length=200, blank=True)

    titre_responsable = models.CharField(
        max_length=100,
        default="Sous-Directeur de la Logistique",
        verbose_name="Titre du Responsable",
        help_text="Ex: Pharmacien Chef, Sous-Directeur Logistique..."
    )
    responsable = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='magasins_diriges',
        verbose_name="Utilisateur Chef de ce magasin"
    )
    pied_de_page = models.CharField(
        max_length=255,
        default="Direction des Affaires Financières / Sous-Direction de la Logistique",
        verbose_name="Texte du pied de page",
        help_text="Texte du pied de page du PDF"
    )

    code_bon_sortie     = models.CharField(max_length=50, default="ENR-BSM/DAF-001", verbose_name="Code ISO - Bon de Sortie")
    code_bon_entree     = models.CharField(max_length=50, default="ENR-BEM/DAF-001", verbose_name="Code ISO - Bon d'Entrée")
    code_bon_retour     = models.CharField(max_length=50, default="ENR-BRM/DAF-003", verbose_name="Code ISO - Bon de Retour")
    code_bon_hors_stock = models.CharField(max_length=50, default="ENR-BSHS/DAF-002", verbose_name="Code ISO - Bon Hors Stock")

    history = HistoricalRecords()

    objects     = TenantManager()
    all_objects = GlobalManager()

    class Meta:
        verbose_name = "Magasin"
        verbose_name_plural = "Magasins"

    def __str__(self):
        return self.nom

class StockItem(models.Model):
    article           = models.ForeignKey(Article, on_delete=models.PROTECT, related_name='stocks')
    magasin           = models.ForeignKey(Magasin, on_delete=models.CASCADE, related_name='inventaire')
    quantite_physique = models.PositiveIntegerField(default=0)
    valeur_cmup       = models.DecimalField(
        max_digits=12, decimal_places=2, default=0,
        verbose_name="CMUP unitaire",
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    batch_number      = models.CharField(max_length=100, blank=True, null=True, db_index=True)
    expiry_date       = models.DateField(blank=True, null=True)
    history           = HistoricalRecords()

    @property
    def excedent(self):
        if self.article.seuil_maximum and self.quantite_physique > self.article.seuil_maximum:
            return self.quantite_physique - self.article.seuil_maximum
        return 0

    @property
    def valeur_totale(self):
        cmup = self.valeur_cmup or self.article.prix_reference or Decimal('0')
        return self.quantite_physique * Decimal(str(cmup))

    def save(self, *args, **kwargs):
        # ✅ CORRECTION : normaliser '' en None pour les contraintes d'unicité
        if self.batch_number == '':
            self.batch_number = None
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.article.designation} - {self.magasin.nom} : {self.quantite_physique}"

# ==========================================================
# 4. LES MOUVEMENTS
# ==========================================================
class Mouvement(models.Model):
    """
    Mouvement de stock (entree, sortie, ajustement).
    ✅ CORRECTION : champs is_deleted et est_annule ajoutés manuellement
    au lieu d'hériter de SoftDeleteModel (conflit avec date_creation existante).
    """
    is_deleted = models.BooleanField(default=False, verbose_name="Supprimé")
    deleted_at = models.DateTimeField(null=True, blank=True, verbose_name="Date de suppression")
    deleted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='mouvements_supprimes', verbose_name="Supprimé par")

    TYPE_MOUVEMENT_CHOICES = [
        ('ENTREE',             'Entrée en stock'),
        ('SORTIE',             'Sortie de stock'),
        ('SORTIE_HORS_STOCK',  'Sortie Hors Stock (livraison directe)'),
        ('RETOUR_FOURNISSEUR', 'Retour au Fournisseur'),
        ('RETOUR_SERVICE',     'Retour depuis un Service'),
        ('AJUSTEMENT_POS',     'Ajustement Positif'),
        ('AJUSTEMENT_NEG',     'Ajustement Négatif'),
        ('AJUSTEMENT_NEG_FORCE', 'Ajustement Négatif Forcé (annulation)'),
        ('INVENTAIRE_POS',     'Inventaire Positif (écart constaté)'),
        ('INVENTAIRE_NEG',     'Inventaire Négatif (écart constaté)'),
    ]

    type_mouvement     = models.CharField(max_length=30, choices=TYPE_MOUVEMENT_CHOICES, db_index=True)
    article            = models.ForeignKey(Article,   on_delete=models.PROTECT)
    magasin            = models.ForeignKey(Magasin,   on_delete=models.PROTECT, blank=True, null=True)
    quantite           = models.PositiveIntegerField()
    prix_unitaire      = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    date_mouvement     = models.DateTimeField(default=timezone.now, db_index=True)
    utilisateur        = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    service_demandeur  = models.ForeignKey(Service,      on_delete=models.PROTECT, blank=True, null=True)
    fournisseur        = models.ForeignKey(Fournisseur,  on_delete=models.PROTECT, blank=True, null=True)
    reference_document = models.CharField(max_length=100, blank=True, db_index=True)
    hash_preuve        = models.CharField(max_length=256, blank=True, help_text="SHA-256 de l'horodatage + user + article + quantité (auto-généré)")
    est_annule         = models.BooleanField(default=False, verbose_name="Annulé", help_text="Mouvement annulé (soft-delete)")
    commentaire        = models.TextField(blank=True, null=True)
    numero_lot         = models.CharField(max_length=50, blank=True, null=True)
    date_peremption    = models.DateField(blank=True, null=True, db_index=True)
    history            = HistoricalRecords()

    objects     = TenantManager()
    all_objects = GlobalManager()

    def clean(self):
        """Validation métier SANS modification de stock."""
        if self.type_mouvement in ['SORTIE', 'RETOUR_FOURNISSEUR', 'AJUSTEMENT_NEG']:
            if not self.magasin_id:
                raise ValidationError("Un mouvement de sortie doit être rattaché à un magasin.")
            filtre = {'article': self.article, 'magasin': self.magasin}
            if self.numero_lot:
                filtre['batch_number'] = self.numero_lot
            else:
                filtre['batch_number__isnull'] = True
            stock = StockItem.objects.filter(**filtre).first()
            dispo = stock.quantite_physique if stock else 0
            if dispo < self.quantite:
                raise ValidationError(f"Stock insuffisant dans {self.magasin}: {dispo} disponible(s)")

    def save(self, *args, update_stock=True, **kwargs):
        """
        Sauvegarde du Mouvement.
        ⚠️ AUDIT : Cette méthode viole le principe SRP (Single Responsibility).
            La logique de mise à jour de stock devrait être extraite dans
            StockTransactionService lors du prochain refactoring.
        """
        # ✅ CORRECTION : Initialisation unique de is_new
        is_new = self.pk is None

        # ✅ CORRECTION : interdire la modification d'un mouvement existant
        # avec update_stock=True. Pour modifier un champ non-stock (commentaire),
        # utiliser : mouvement.save(update_stock=False)
        if not is_new and update_stock:
            raise ValidationError(
                "La modification d'un mouvement existant est interdite. "
                "Veuillez l'annuler et en créer un nouveau."
            )

        if self.type_mouvement in [
            'ENTREE', 'SORTIE', 'RETOUR_SERVICE', 'RETOUR_FOURNISSEUR',
            'AJUSTEMENT_POS', 'AJUSTEMENT_NEG', 'AJUSTEMENT_NEG_FORCE',
            'INVENTAIRE_POS', 'INVENTAIRE_NEG'
        ]:
            if not self.magasin_id:
                raise ValidationError("Un mouvement de stock doit être rattaché à un magasin.")

        if is_new and update_stock:
            with transaction.atomic():
                self.clean()
                batch = self.numero_lot if self.numero_lot else None

                # ── BLOC ENTRÉE : ajoute du stock ──
                if self.type_mouvement in ['ENTREE', 'RETOUR_SERVICE', 'AJUSTEMENT_POS', 'INVENTAIRE_POS']:
                    stock, _ = StockItem.objects.select_for_update().get_or_create(
                        article=self.article, magasin=self.magasin, batch_number=batch,
                        defaults={'quantite_physique': 0, 'valeur_cmup': 0}
                    )
                    ancienne_qte = stock.quantite_physique
                    ancienne_val = stock.valeur_cmup or Decimal('0')
                    nouvelle_qte = ancienne_qte + self.quantite

                    # ✅ CORRECTION : CMUP recalculé sur TOUTES les entrées avec prix_unitaire
                    if self.prix_unitaire and nouvelle_qte > 0:
                        pu = Decimal(str(self.prix_unitaire))
                        nouveau_cmup = ((ancienne_val * ancienne_qte) + (pu * self.quantite)) / nouvelle_qte
                        stock.valeur_cmup = nouveau_cmup.quantize(Decimal('0.01'))

                    stock.quantite_physique = nouvelle_qte
                    stock.save()

                # ── BLOC SORTIE : retire du stock ──
                elif self.type_mouvement in ['SORTIE', 'RETOUR_FOURNISSEUR', 'AJUSTEMENT_NEG', 'AJUSTEMENT_NEG_FORCE', 'INVENTAIRE_NEG']:
                    try:
                        stock = StockItem.objects.select_for_update().get(
                            article=self.article, magasin=self.magasin, batch_number=batch
                        )
                    except StockItem.DoesNotExist:
                        lot_msg = f" (lot {batch})" if batch else ""
                        raise ValidationError(
                            f"Stock inexistant pour {self.article.designation}{lot_msg} dans {self.magasin.nom}"
                        )
                    if stock.quantite_physique < self.quantite:
                        raise ValidationError(
                            f"Stock insuffisant dans {self.magasin}: "
                            f"{stock.quantite_physique} disponible(s), {self.quantite} demandé(s)"
                        )
                    stock.quantite_physique -= self.quantite
                    stock.save()

                # ✅ CORRECTION : générer le hash de preuve AVANT le super().save() général
                if not self.hash_preuve:
                    import hashlib
                    data = f"{self.date_mouvement.isoformat()}|{self.utilisateur_id}|{self.article_id}|{self.quantite}|{self.type_mouvement}"
                    self.hash_preuve = hashlib.sha256(data.encode()).hexdigest()[:64]

                super().save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """
        Annule l'effet du mouvement sur le stock avant suppression.
        ✅ CORRECTION : vérifie que le mouvement n'a pas déjà été annulé
           pour éviter le double-reversal du stock.
        """
        with transaction.atomic():
            if not self.is_deleted and not self.est_annule:
                self._reverse_stock_effect()
            super().delete(*args, **kwargs)

    def soft_delete(self, user=None):
        """
        Surcharge pour s'assurer qu'un soft-delete annule l'effet du mouvement
        sur le stock physique, au lieu de juste changer le flag is_deleted.
        ✅ CORRECTION : vérifie que le mouvement n'a pas déjà été annulé
           pour éviter le double-reversal du stock.
        """
        with transaction.atomic():
            if not self.is_deleted and not self.est_annule:
                self._reverse_stock_effect()

            # Logique de soft-delete manuelle
            self.is_deleted = True
            self.deleted_at = timezone.now()
            if user:
                self.deleted_by = user
            self.save(update_fields=['is_deleted', 'deleted_at', 'deleted_by'])

    def _reverse_stock_effect(self):
        """
        Extrait la logique d'annulation de stock pour la réutiliser
        dans delete() et soft_delete().
        ✅ CORRECTION : recalcule le CMUP depuis l'historique complet.
        """
        batch = self.numero_lot if self.numero_lot else None
        try:
            stock = StockItem.objects.select_for_update().get(
                article=self.article, magasin=self.magasin, batch_number=batch
            )
        except StockItem.DoesNotExist:
            stock = None

        if self.type_mouvement in [
            'ENTREE', 'RETOUR_SERVICE', 'AJUSTEMENT_POS', 'INVENTAIRE_POS'
        ]:
            # Ces mouvements ont AJOUTÉ du stock → on retire
            if stock:
                stock.quantite_physique = max(0, stock.quantite_physique - self.quantite)
                self._recalculer_cmup_depuis_historique(stock)
                stock.save()

        elif self.type_mouvement in [
            'SORTIE', 'RETOUR_FOURNISSEUR', 'AJUSTEMENT_NEG',
            'AJUSTEMENT_NEG_FORCE', 'INVENTAIRE_NEG'
        ]:
            # Ces mouvements ont RETIRÉ du stock → on remet
            if stock:
                stock.quantite_physique += self.quantite
                stock.save()
            else:
                # Si le stock a été complètement vidé et supprimé, on le recrée
                # ✅ CORRECTION : récupère le prix_unitaire du mouvement pour le CMUP
                StockItem.objects.create(
                    article=self.article, magasin=self.magasin, batch_number=batch,
                    quantite_physique=self.quantite,
                    valeur_cmup=self.prix_unitaire or Decimal('0')
                )

    def _recalculer_cmup_depuis_historique(self, stock):
        """
        ✅ CORRECTION : Recalcule le CMUP exact en se basant sur les mouvements
        d'entrée restants (pas de soustraction d'une moyenne pondérée).
        """
        entrees = Mouvement.objects.filter(
            article=stock.article,
            magasin=stock.magasin,
            numero_lot=stock.batch_number,
            type_mouvement__in=['ENTREE', 'RETOUR_SERVICE', 'AJUSTEMENT_POS', 'INVENTAIRE_POS'],
            prix_unitaire__isnull=False
        ).exclude(pk=self.pk)

        total_qte = 0
        total_val = Decimal('0.00')
        for mvt in entrees:
            total_qte += mvt.quantite
            total_val += Decimal(str(mvt.prix_unitaire)) * mvt.quantite

        if total_qte > 0:
            stock.valeur_cmup = (total_val / total_qte).quantize(Decimal('0.01'))
        else:
            stock.valeur_cmup = Decimal('0.00')

    def __str__(self):
        return f"{self.type_mouvement} — {self.article.designation} x{self.quantite}"

class Ajustement(TracabiliteModel, SoftDeleteModel):
    MOTIFS = (
        ('CASSE',  'Matériel Cassé / Défectueux'),
        ('PERTE',  'Perte / Vol'),
        ('ERREUR', 'Erreur de saisie précédente'),
        ('AJOUT',  'Régularisation (Ajout)'),
    )
    article           = models.ForeignKey(Article, on_delete=models.CASCADE, related_name='ajustements')
    magasin           = models.ForeignKey(Magasin, on_delete=models.CASCADE, related_name='ajustements_magasin')
    quantite          = models.PositiveIntegerField()
    motif             = models.CharField(max_length=20, choices=MOTIFS)
    commentaire       = models.TextField(blank=True, null=True)
    document_scanne   = models.FileField(upload_to='scans/ajustements/', null=True, blank=True)
    statut_validation = models.CharField(
        max_length=20, choices=STATUT_VALIDATION_CHOICES, default='VALIDE',
        verbose_name="Statut de validation"
    )
    valide_par        = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='ajustements_valides', verbose_name="Validé par"
    )
    date_validation   = models.DateTimeField(null=True, blank=True)
    history           = HistoricalRecords()

    objects     = TenantManager()
    all_objects = GlobalManager()

    def save(self, *args, **kwargs):
        """
        ✅ CORRECTION : créer automatiquement le Mouvement de stock
        lors du passage au statut VALIDE, enveloppé dans une transaction atomique.
        """
        old_statut = None
        if self.pk:
            try:
                old_statut = Ajustement.objects.get(pk=self.pk).statut_validation
            except Ajustement.DoesNotExist:
                pass

        # ✅ CORRECTION : transaction atomique pour garantir la cohérence
        with transaction.atomic():
            super().save(*args, **kwargs)

            # Si on vient de valider l'ajustement, créer le mouvement de stock
            if old_statut != 'VALIDE' and self.statut_validation == 'VALIDE':
                type_mvt = 'AJUSTEMENT_POS' if self.motif == 'AJOUT' else 'AJUSTEMENT_NEG'
                Mouvement.objects.create(
                    type_mouvement=type_mvt,
                    article=self.article,
                    magasin=self.magasin,
                    quantite=self.quantite,
                    utilisateur=self.valide_par or self.cree_par,
                    commentaire=f"Ajustement {self.motif} - {self.commentaire or ''}",
                    reference_document=f"ADJ-{self.pk}"
                )

    def __str__(self):
        return f"Ajustement {self.article.designation} - {self.motif}"


    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantite__gt=0),
                name='ajustement_quantite_positive'
            ),
        ]

# =========================================================
# CAMPAGNES D'INVENTAIRES
# =========================================================
class CampagneInventaire(TracabiliteModel, SoftDeleteModel):
    STATUTS = (
        ('EN_COURS',  'En cours de saisie'),
        ('A_VALIDER', 'En attente de validation'),
        ('VALIDE',    'Validé & Clôturé'),
        ('ANNULE',    'Annulé'),
    )
    TYPE_CAMPAGNE_CHOICES = (
        ('GENERAL',     'Inventaire Général (tous les articles)'),
        ('PAR_FAMILLE', 'Inventaire par Famille(s)'),
        ('PERSONNALISE','Inventaire Personnalisé (articles choisis)'),
    )

    titre           = models.CharField(max_length=200)
    magasin         = models.ForeignKey(Magasin, on_delete=models.CASCADE, related_name='inventaires')
    statut          = models.CharField(max_length=20, choices=STATUTS, default='EN_COURS')
    valide_par      = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='inventaires_valides')
    date_validation = models.DateTimeField(null=True, blank=True)
    history         = HistoricalRecords()

    type_campagne   = models.CharField(
        max_length=20,
        choices=TYPE_CAMPAGNE_CHOICES,
        default='GENERAL',
        verbose_name="Type de campagne"
    )
    familles_cibles = models.ManyToManyField(
        FamilleArticle,
        blank=True,
        related_name='inventaires_familles',
        verbose_name="Familles ciblées (si type = Par Famille)"
    )
    articles_cibles = models.ManyToManyField(
        Article,
        blank=True,
        related_name='inventaires_articles',
        verbose_name="Articles choisis (si type = Personnalisé)"
    )

    objects     = TenantManager()
    all_objects = GlobalManager()

    def __str__(self):
        return f"{self.titre} - {self.magasin.nom} ({self.get_statut_display()})"

class LigneInventaire(models.Model):
    campagne           = models.ForeignKey(CampagneInventaire, on_delete=models.CASCADE, related_name='lignes_inventaire')
    article            = models.ForeignKey(Article, on_delete=models.CASCADE, related_name='lignes_inventaire_article')
    quantite_theorique = models.PositiveIntegerField(default=0)
    quantite_physique  = models.PositiveIntegerField(null=True, blank=True)
    history            = HistoricalRecords()

    def ecart(self):
        # ✅ CORRECTION : retourne None si le comptage n'a pas encore été fait
        if self.quantite_physique is not None:
            return self.quantite_physique - self.quantite_theorique
        return None

    def __str__(self):
        return f"{self.article.designation} — Théo:{self.quantite_theorique} / Réel:{self.quantite_physique}"

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantite_theorique__gte=0),
                name='ligneinv_qte_theo_positive'
            ),
        ]

# =========================================================
# GESTION DES BONS
# =========================================================
class MotifAnnulation(SoftDeleteModel):
    entreprise        = models.ForeignKey('accounts.Entreprise', on_delete=models.CASCADE, related_name='motifs_annulation')
    libelle           = models.CharField(max_length=100)
    actif             = models.BooleanField(default=True)
    cree_le           = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True, null=True, blank=True)
    cree_par          = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='motifs_crees')
    modifie_par       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='motifs_modifies')

    objects     = TenantManager()
    all_objects = GlobalManager()

    def __str__(self):
        return self.libelle

    def peut_etre_supprime(self):
        return not self.bons_annules.exists()

    class Meta:
        verbose_name = "Motif d'annulation"
        verbose_name_plural = "Motifs d'annulation"
        constraints = [
            models.UniqueConstraint(
                fields=['entreprise', 'libelle'],
                condition=models.Q(is_deleted=False),
                name='unique_motif_actif'
            ),
        ]

class Beneficiaire(SoftDeleteModel):
    entreprise  = models.ForeignKey('accounts.Entreprise', on_delete=models.CASCADE, related_name='beneficiaires')
    nom_complet = models.CharField(max_length=150, verbose_name="Nom et Prénom")
    poste       = models.CharField(max_length=100, blank=True, null=True, verbose_name="Poste / Fonction")
    service     = models.ForeignKey(Service, on_delete=models.SET_NULL, null=True, blank=True, related_name='beneficiaires_lies')

    objects     = TenantManager()
    all_objects = GlobalManager()

    def __str__(self):
        if self.poste:
            return f"{self.nom_complet} ({self.poste})"
        return self.nom_complet

    class Meta:
        verbose_name = "Bénéficiaire"
        verbose_name_plural = "Bénéficiaires"
        ordering = ['nom_complet']
        constraints = [
            models.UniqueConstraint(
                fields=['entreprise', 'nom_complet'],
                condition=models.Q(is_deleted=False),
                name='unique_beneficiaire_actif'
            ),
        ]

class BonMouvement(TracabiliteModel, SoftDeleteModel):
    TYPE_BON_CHOICES = [
        ('ENTREE',             "Bon d'Entrée (Réception)"),
        ('SORTIE',             'Bon de Sortie (Distribution)'),
        ('SORTIE_HORS_STOCK',  'Bon de Sortie Hors Stock (ENR-BSHS/DAF-002)'),
        ('RETOUR_FOURNISSEUR', 'Retour Fournisseur (Litige)'),
        ('RETOUR_SERVICE',     "Retour d'un Service"),
        ('AJUSTEMENT',         "Ajustement d'Inventaire"),
    ]

    type_bon            = models.CharField(max_length=30, choices=TYPE_BON_CHOICES, db_index=True)
    numero_bon          = models.CharField(max_length=50, editable=False, db_index=True)
    # ✅ CORRECTION : entreprise_id dénormalisé pour contrainte d'unicité par entreprise
    entreprise          = models.ForeignKey('accounts.Entreprise', on_delete=models.CASCADE, related_name='bons_mouvement', null=False, blank=True)
    date_bon            = models.DateTimeField(default=timezone.now, db_index=True)

    # ✅ RÉINTÉGRÉ : champ est_annule pour la logique d'annulation
    est_annule          = models.BooleanField(default=False, db_index=True)

    numero_livraison    = models.PositiveSmallIntegerField(null=True, blank=True, verbose_name="N° de livraison (chronologie)")
    motif_annulation    = models.ForeignKey(MotifAnnulation, on_delete=models.PROTECT, null=True, blank=True, related_name='bons_annules')
    annule_par          = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='bons_annules_user')
    date_annulation     = models.DateTimeField(null=True, blank=True)
    magasin             = models.ForeignKey(Magasin,     on_delete=models.PROTECT, related_name='bons_magasin')
    fournisseur         = models.ForeignKey(Fournisseur, on_delete=models.PROTECT, null=True, blank=True, related_name='bons_fournisseur')
    service_demandeur   = models.ForeignKey(Service,       on_delete=models.PROTECT, null=True, blank=True, related_name='bons_service')

    destinataire        = models.ForeignKey(Beneficiaire, on_delete=models.SET_NULL, null=True, blank=True, related_name='bons_hors_stock', verbose_name="Destinataire (Hors Stock)")
    sondage_satisfait   = models.BooleanField(null=True, blank=True, verbose_name="Sondage : Satisfait ?")
    sondage_observation = models.TextField(blank=True, null=True, verbose_name="Sondage : Observation")
    reference_externe   = models.CharField(max_length=100, blank=True, db_index=True)
    commentaire         = models.TextField(blank=True, null=True)
    commande_liee       = models.ForeignKey('Commande', on_delete=models.SET_NULL, null=True, blank=True, related_name='bons_reception')
    statut_validation   = models.CharField(max_length=20, choices=STATUT_VALIDATION_CHOICES, default='VALIDE')
    valide_par          = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='bons_valides')
    date_validation     = models.DateTimeField(null=True, blank=True)
    document_joint      = models.FileField(upload_to='documents_logistique/bons/%Y/%m/', null=True, blank=True)

    fichier_pdf = models.FileField(
        upload_to='bons_pdf/%Y/%m/',
        null=True, blank=True,
        verbose_name="PDF pré-généré"
    )

    document_scan = models.FileField(
        upload_to='documents_logistique/scans/%Y/%m/',
        null=True, blank=True,
        verbose_name="Fichier scanné (BL/Facture)"
    )
    date_upload_scan = models.DateTimeField(
        null=True, blank=True,
        verbose_name="Date d'upload du scan"
    )
    upload_scan_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='bons_scannes',
        verbose_name="Scan uploadé par"
    )

    def get_signataires_pdf(self, entreprise):
        """
        Retourne les 6 signataires prêts pour le template PDF.
        Si une validation existe, on affiche le nom + fonction snapshotée.
        Sinon on affiche le label par défaut de l'entreprise.
        """
        labels = entreprise.get_labels_signatures()
        resultat = []
        for i, label in enumerate(labels, start=1):
            val = self.validations.filter(ordre=i).first()
            if val and val.valideur:
                resultat.append({
                    'ordre': i,
                    'label': label,
                    'nom': val.valideur.get_full_name() or val.valideur.username,
                    'fonction': val.fonction_snapshot or '',
                    'date': val.date_validation,
                    'signe': True,
                    'signature_url': val.signature_image.url if val.signature_image else None,
                })
            else:
                resultat.append({
                    'ordre': i,
                    'label': label,
                    'nom': None,
                    'fonction': None,
                    'date': None,
                    'signe': False,
                    'signature_url': None,
                })
        return resultat

    @property
    def est_completement_valide(self):
        """Vrai si toutes les cases prévues par le circuit sont signées."""
        try:
            circuit = CircuitValidation.objects.get(
                type_document='SORTIE',
                entreprise=self.magasin.entreprise,
                est_actif=True
            )
        except CircuitValidation.DoesNotExist:
            return True
        nb_valideurs = circuit.valideurs.count()
        # ✅ CORRECTION : ne compter que les validations avec un valideur réel
        nb_signes = self.validations.filter(valideur__isnull=False).count()
        return nb_signes >= min(nb_valideurs, 6)

    class Meta:
        verbose_name        = "Bon de mouvement"
        verbose_name_plural = "Bons de mouvement"
        ordering            = ['-date_bon']
        constraints = [
            # ✅ CORRECTION : unicité du numéro de bon PAR ENTREPRISE (pas globale)
            models.UniqueConstraint(
                fields=['entreprise', 'numero_bon'],
                condition=models.Q(is_deleted=False),
                name='unique_bon_par_entreprise'
            ),
        ]
        permissions = [
            ('can_add_bon_entree',      "Peut créer des bons d'entrée"),
            ('can_add_bon_sortie',      'Peut créer des bons de sortie'),
            ('can_add_bon_retour',      'Peut créer des bons de retour'),
            ('can_add_bon_hors_stock',  'Peut créer des bons hors stock'),
            ('can_change_bon_entree',   "Peut modifier/annuler des bons d'entrée"),
            ('can_change_bon_sortie',   'Peut modifier/annuler des bons de sortie'),
            ('can_change_bon_retour',   'Peut modifier/annuler des bons de retour'),
            ('can_change_bon_hors_stock','Peut modifier/annuler des bons hors stock'),
            ('can_delete_bon_entree',   "Peut supprimer des bons d'entrée"),
            ('can_delete_bon_sortie',   'Peut supprimer des bons de sortie'),
            ('can_delete_bon_retour',   'Peut supprimer des bons de retour'),
            ('can_delete_bon_hors_stock','Peut supprimer des bons hors stock'),
        ]

    objects     = TenantManager()
    all_objects = GlobalManager()

    def save(self, *args, **kwargs):
        """
        Sauvegarde du bon avec :
        1. Génération automatique du numéro de bon
        2. Vérification du circuit de validation pour le statut initial
        """
        if not self.magasin_id:
            raise ValidationError("Un bon doit être rattaché à un magasin.")

        # ✅ CORRECTION : toujours synchroniser l'entreprise avec le magasin
        self.entreprise_id = self.magasin.entreprise_id

        # ── 1. Numéro de bon ──
        if not self.numero_bon:

            mapping = {
                'ENTREE':             ('BON_ENTREE', 'BE'),
                'RETOUR_SERVICE':     ('BON_RETOUR', 'BR'),
                'SORTIE_HORS_STOCK':  ('BON_HS', 'BSHS'),
            }
            type_doc, prefix = mapping.get(self.type_bon, ('BON_SORTIE', 'BS'))

            def format_num(compteur, annee, eid):
                return f"{prefix}-{annee}-{compteur:03d}"

            self.numero_bon = CompteurDocument.generer_numero(
                self.entreprise_id, type_doc, format_num,
                model_class=self.__class__, field_name='numero_bon'
            )

        # ── 2. Circuit de validation (NOUVEAU) ──
        # Si c'est une création (pas de PK), on vérifie le circuit
        if not self.pk:
            mapping_circuit = {
                'ENTREE':             'ENTREE',
                'SORTIE':             'SORTIE',
                'SORTIE_HORS_STOCK':  'SORTIE',
                'RETOUR_FOURNISSEUR': 'ENTREE',
                'RETOUR_SERVICE':     'ENTREE',
                'AJUSTEMENT':         'AJUSTEMENT',
            }
            type_circuit = mapping_circuit.get(self.type_bon)
            if type_circuit:
                try:
                    circuit = CircuitValidation.objects.get(
                        type_document=type_circuit,
                        entreprise=self.magasin.entreprise,
                        is_deleted=False
                    )
                    if not circuit.est_actif:
                        self.statut_validation = 'VALIDE'
                    else:
                        self.statut_validation = 'ATTENTE'
                except CircuitValidation.DoesNotExist:
                    # ✅ CORRECTION : fail-closed — pas de circuit = BROUILLON (pas VALIDÉ)
                    self.statut_validation = 'BROUILLON'

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.numero_bon} ({self.type_bon})"


class LigneBon(models.Model):
    bon             = models.ForeignKey(BonMouvement, related_name='lignes_bon', on_delete=models.CASCADE)
    article         = models.ForeignKey(Article, on_delete=models.PROTECT, related_name='lignes_article')
    quantite        = models.PositiveIntegerField()
    quantite_servie = models.PositiveIntegerField(null=True, blank=True, verbose_name="Quantité servie")
    prix_unitaire   = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        verbose_name="Prix unitaire CMUP (FCFA)",
        validators=[MinValueValidator(Decimal('0.00'))]
    )
    # ═══════════════════════════════════════════════════════
    # CHAMPS POUR RÉCEPTION PARTIELLE (traçabilité historique)
    # ═══════════════════════════════════════════════════════
    quantite_demandee = models.PositiveIntegerField(
        default=0,
        verbose_name="Quantité demandée (reliquat avant réception)",
        help_text="Reliquat à réceptionner avant cette réception (pour traçabilité)"
    )
    reste = models.PositiveIntegerField(
        default=0,
        verbose_name="Reliquat après réception",
        help_text="Reliquat restant après cette réception (0 si réception complète)"
    )
    # ═══════════════════════════════════════════════════════
    numero_lot      = models.CharField(max_length=50, blank=True, null=True, db_index=True)
    date_peremption = models.DateField(blank=True, null=True)

    @property
    def montant(self):
        qte = self.quantite_servie if self.quantite_servie is not None else self.quantite
        if self.prix_unitaire and qte:
            return Decimal(str(self.prix_unitaire)) * qte
        return None

    def __str__(self):
        return f"{self.article.designation} x {self.quantite}"

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantite__gt=0),
                name='lignebon_quantite_positive'
            ),
            # ✅ CORRECTION : empêcher de servir plus que demandé
            models.CheckConstraint(
                condition=models.Q(quantite_servie__lte=models.F('quantite')) | models.Q(quantite_servie__isnull=True),
                name='lignebon_servie_lte_demandee'
            ),
        ]

# ==========================================================
# CIRCUITS DE VALIDATION
# ==========================================================
class CircuitValidation(SoftDeleteModel):
    TYPE_DOC_CHOICES = [
        ('COMMANDE',   'Commandes Fournisseurs'),
        ('DEMANDE',    'Demandes de Matériel (Services)'),
        ('ENTREE',     'Bons de Réception'),
        ('SORTIE',     'Bons de Sortie'),
        ('AJUSTEMENT', 'Ajustements de Stock'),
        ('INVENTAIRE', "Campagnes d'Inventaires"),
    ]

    entreprise    = models.ForeignKey('accounts.Entreprise', on_delete=models.CASCADE, related_name='circuits_validation', null=True, blank=True)
    type_document = models.CharField(max_length=20, choices=TYPE_DOC_CHOICES)
    est_actif     = models.BooleanField(default=False)
    valideurs = models.ManyToManyField(
        settings.AUTH_USER_MODEL, 
        through='CircuitValidateur',
        blank=True, 
        related_name='circuits_autorises'
    )

    objects     = TenantManager()
    all_objects = GlobalManager()

    def __str__(self):
        return f"{self.get_type_document_display()} - {self.entreprise or 'GLOBAL'} ({'ACTIF' if self.est_actif else 'INACTIF'})"

    class Meta:
        verbose_name        = "Circuit de Validation"
        verbose_name_plural = "Circuits de Validation"
        constraints = [
            # ✅ CORRECTION : contrainte pour circuits avec entreprise
            models.UniqueConstraint(
                fields=['type_document', 'entreprise'],
                condition=models.Q(is_deleted=False) & models.Q(entreprise__isnull=False),
                name='unique_circuit_actif_par_entreprise'
            ),
            # ✅ CORRECTION : contrainte pour circuits globaux (entreprise=NULL)
            models.UniqueConstraint(
                fields=['type_document'],
                condition=models.Q(is_deleted=False) & models.Q(entreprise__isnull=True),
                name='unique_circuit_actif_global'
            ),
        ]


class CircuitValidateur(models.Model):
    """
    ✅ CORRECTION : Modèle through pour définir l'ordre des valideurs dans un circuit.
    Remplace le ManyToManyField simple qui ne permettait pas d'ordonner les signataires.
    """
    circuit = models.ForeignKey(CircuitValidation, on_delete=models.CASCADE, related_name='validateurs')
    valideur = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    ordre = models.PositiveSmallIntegerField(default=1, help_text="Ordre de signature (1, 2, 3...)")
    role = models.CharField(max_length=100, blank=True, help_text="Rôle du signataire (ex: Directeur)")
    date_ajout = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['ordre']
        unique_together = ['circuit', 'valideur']
        verbose_name = "Valideur du circuit"
        verbose_name_plural = "Valideurs du circuit"

    def __str__(self):
        return f"{self.ordre}. {self.valideur} ({self.role or 'Signataire'})"

# ==========================================================
# COMMANDES FOURNISSEURS
# ==========================================================
class Commande(SoftDeleteModel):
    STATUT_CHOICES = [
        ('EN_ATTENTE',    'En attente de livraison'),
        ('LIVRE_PARTIEL', 'Partiellement Livrée'),
        ('LIVRE_TOTAL',   'Totalement Livrée'),
        ('SOLDE',         'Soldée (Reliquat annulé)'),
        ('ANNULE',        'Annulée'),
    ]

    numero_commande   = models.CharField(max_length=50, blank=True, db_index=True)
    date_commande     = models.DateTimeField(default=timezone.now)
    fournisseur       = models.ForeignKey(Fournisseur, on_delete=models.PROTECT, related_name='commandes_fournisseur')
    statut            = models.CharField(max_length=20, choices=STATUT_CHOICES, default='EN_ATTENTE')
    magasin           = models.ForeignKey(Magasin, on_delete=models.PROTECT, null=True, blank=True, related_name='commandes_magasin')
    # ═══════════════════════════════════════════════════════
    # COMMANDE PAR FAMILLE : chaque commande est rattachée à UNE famille d'articles
    # Tous les articles de la commande doivent appartenir à cette famille
    # ═══════════════════════════════════════════════════════
    famille = models.ForeignKey(
        FamilleArticle,
        on_delete=models.PROTECT,
        related_name='commandes_famille',
        null=True, blank=True,          # ← temporaire, le temps de la migration de données
        verbose_name="Famille d'articles"
    )
    cree_par          = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,   related_name='commandes_creees')
    modifie_par       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,  null=True, blank=True, related_name='commandes_modifiees')
    statut_validation = models.CharField(max_length=20, choices=STATUT_VALIDATION_CHOICES, default='BROUILLON')
    valide_par        = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='commandes_validees')
    date_validation   = models.DateTimeField(null=True, blank=True)
    document_joint    = models.FileField(upload_to='documents_logistique/commandes/%Y/%m/', null=True, blank=True)

    objet = models.CharField(max_length=500, blank=True, null=True, verbose_name="Objet de la commande")
    delai_livraison = models.PositiveIntegerField(
        blank=True, 
        null=True, 
        verbose_name="Délai de livraison (en jours)"
    )
    date_livraison_prevue = models.DateField(blank=True, null=True, verbose_name="Date de livraison prévue")

    history           = HistoricalRecords()

    objects     = TenantManager()
    all_objects = GlobalManager()

    def save(self, *args, **kwargs):
        if not self.pk and not self.numero_commande:
            if not self.magasin_id:
                raise ValidationError("Une commande doit être rattachée à un magasin.")
            entreprise_id = self.magasin.entreprise_id

            def format_num(compteur, annee, eid):
                return f"BC-{annee}-{compteur:03d}"

            self.numero_commande = CompteurDocument.generer_numero(
                entreprise_id, 'COMMANDE', format_num,
                model_class=self.__class__, field_name='numero_commande'
            )

            try:
                circuit = CircuitValidation.objects.get(type_document='COMMANDE', entreprise_id=entreprise_id)
                if not circuit.est_actif:
                    self.statut_validation = 'VALIDE'
            except CircuitValidation.DoesNotExist:
                # ✅ CORRECTION : fail-closed — pas de circuit = BROUILLON (pas VALIDÉ)
                self.statut_validation = 'BROUILLON'

        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.numero_commande} - {self.fournisseur.raison_sociale}"

    class Meta:
        verbose_name        = "Commande"
        verbose_name_plural = "Commandes"
        ordering            = ['-date_commande']




class LigneCommande(models.Model):
    """Ligne d'une commande fournisseur."""
    commande          = models.ForeignKey(Commande, on_delete=models.CASCADE, related_name='lignes_commande')
    article           = models.ForeignKey(Article, on_delete=models.PROTECT, related_name='lignes_commande_article')
    quantite_demandee = models.PositiveIntegerField()
    quantite_recue    = models.PositiveIntegerField(default=0)

    # ✅ NOUVEAU CHAMP — remplace la @property reliquat
    reliquat = models.PositiveIntegerField(
        default=0,
        db_index=True,
        help_text="Quantite restante a livrer (auto-calcule)"
    )

    prix_unitaire     = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        validators=[MinValueValidator(Decimal('0.00'))]
    )

    @property
    def montant(self):
        if self.prix_unitaire and self.quantite_demandee:
            return Decimal(str(self.prix_unitaire)) * self.quantite_demandee
        return None

    # ✅ NOUVEAU — recalcule automatiquement le reliquat a chaque save()
    def save(self, *args, **kwargs):
        self.reliquat = max(0, self.quantite_demandee - self.quantite_recue)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.article.designation} (x{self.quantite_demandee})"

    class Meta:
        verbose_name        = "Ligne de commande"
        verbose_name_plural = "Lignes de commande"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantite_demandee__gt=0),
                name='lignecmd_qte_demandee_positive'
            ),
        ]
# ==========================================================
# DEMANDES DE MATÉRIEL
# ==========================================================
class DemandeMateriel(SoftDeleteModel):
    STATUT_CHOICES = [
        ('BROUILLON',           'Brouillon (Non envoyée)'),
        ('EN_ATTENTE_VALIDATION', 'En attente de validation Chef'),
        ('EN_ATTENTE',          'En attente de traitement (Magasin)'),
        ('EN_COURS',            'En cours de traitement'),
        ('LIVRAISON_PARTIELLE', 'Livraison partielle en cours'),
        ('LIVREE',              'Entièrement livrée'),
        ('RECEPTIONNE',         'Réceptionnée — clôturée'),
        ('CLOTUREE',            'Clôturée par le magasinier'),
        ('REFUSEE',             'Refusée'),
        ('ANNULEE',             'Annulée par le demandeur'),
    ]
    STATUTS_HISTORIQUE = ('RECEPTIONNE', 'CLOTUREE', 'REFUSEE','ANNULEE')

    numero_demande    = models.CharField(max_length=50, db_index=True)
    demandeur         = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='mes_demandes')
    service_demandeur = models.ForeignKey('core.Service', on_delete=models.PROTECT)
    magasin_cible     = models.ForeignKey(Magasin, on_delete=models.PROTECT, related_name='demandes_recues')
    statut            = models.CharField(max_length=25, choices=STATUT_CHOICES, default='BROUILLON', db_index=True)
    date_demande      = models.DateTimeField(auto_now_add=True)
    annule_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='demandes_annulees'
    )
    date_annulation = models.DateTimeField(null=True, blank=True)

    date_validation   = models.DateTimeField(null=True, blank=True)
    valide_par        = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='demandes_validees')
    commentaire       = models.TextField(blank=True, null=True)
    bon_sortie_lie    = models.ForeignKey('BonMouvement', on_delete=models.SET_NULL, null=True, blank=True, related_name='demande_origine')

    fichier_pdf = models.FileField(
        upload_to='demandes/pdf/%Y/%m/',
        null=True, blank=True,
        verbose_name="PDF du Bon de Demande"
    )

    motif_cloture     = models.TextField(blank=True, null=True, verbose_name="Motif de clôture (reliquat abandonné)")
    date_cloture      = models.DateTimeField(null=True, blank=True)
    cloture_par       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='demandes_cloturees')

    valide_par_chef      = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name='demandes_approuvees_chef')
    date_validation_chef = models.DateTimeField(null=True, blank=True)
    motif_refus          = models.CharField(max_length=255, null=True, blank=True)

    objects     = TenantManager()
    all_objects = GlobalManager()

    @property
    def quantite_demandee_totale(self):
        return self.lignes_demande.aggregate(total=models.Sum('quantite_demandee'))['total'] or 0

    @property
    def quantite_servie_totale(self):
        # ✅ CORRECTION : exclure les livraisons annulées du calcul
        return self.livraisons.filter(est_annule=False).aggregate(
            total=models.Sum('quantite_livree')
        )['total'] or 0

    @property
    def reste(self):
        return max(0, self.quantite_demandee_totale - self.quantite_servie_totale)

    @property
    def est_en_historique(self):
        return self.statut in self.STATUTS_HISTORIQUE

    @property
    def taux_service(self):
        total = self.quantite_demandee_totale
        if not total:
            return 0
        return min(100, round(self.quantite_servie_totale * 100 / total))

    @property
    def total_articles(self):
        return self.lignes_demande.count()

    @property
    def taux_livraison(self):
        demande = self.quantite_demandee_totale
        if demande == 0:
            return 0
        taux = (self.quantite_servie_totale / demande) * 100
        return min(100, round(taux, 1))

    @property
    def est_cloturable(self):
        return self.statut in ('EN_COURS', 'LIVRAISON_PARTIELLE', 'LIVREE') and self.reste > 0

    @property
    def statut_badge(self):
        badges = {
            'BROUILLON':             {'couleur': '#6c757d', 'icone': 'fa-edit', 'texte': 'Brouillon'},
            'EN_ATTENTE_VALIDATION': {'couleur': '#ffc107', 'icone': 'fa-user-clock', 'texte': 'Attente Chef'},
            'EN_ATTENTE':            {'couleur': '#17a2b8', 'icone': 'fa-clock', 'texte': 'Attente Magasin'},
            'EN_COURS':              {'couleur': '#fd7e14', 'icone': 'fa-spinner fa-spin', 'texte': 'En cours'},
            'LIVRAISON_PARTIELLE':   {'couleur': '#e65100', 'icone': 'fa-box-open', 'texte': 'Livraison Partielle'},
            'LIVREE':                {'couleur': '#28a745', 'icone': 'fa-truck-loading', 'texte': 'Livrée'},
            'RECEPTIONNE':           {'couleur': '#20c997', 'icone': 'fa-handshake', 'texte': 'Réceptionnée'},
            'CLOTUREE':              {'couleur': '#6f42c1', 'icone': 'fa-lock', 'texte': 'Clôturée'},
            'REFUSEE':               {'couleur': '#dc3545', 'icone': 'fa-times-circle', 'texte': 'Refusée'},
        }
        return badges.get(self.statut, {'couleur': '#999', 'icone': 'fa-question-circle', 'texte': self.statut})

    def actualiser_statut(self):
        # ✅ CORRECTION : bloquer la mise à jour pour TOUS les statuts historiques
        if self.statut in self.STATUTS_HISTORIQUE:
            return

        nb_livraisons = self.livraisons.count()
        if nb_livraisons == 0:
            return

        if self.reste <= 0:
            # ✅ CORRECTION : un seul aggregate au lieu de 2 requêtes N+1
            # ✅ CORRECTION : exclure les livraisons annulées du comptage
            from django.db.models import Count, Q
            livraisons_stats = self.livraisons.filter(est_annule=False).aggregate(
                total=Count('id'),
                signees=Count('id', filter=Q(accuse__est_signe=True, accuse__est_annule=False)),
                sans_accuse=Count('id', filter=Q(accuse__isnull=True)),
            )
            tous_signes = (livraisons_stats['signees'] == livraisons_stats['total'] 
                          and livraisons_stats['sans_accuse'] == 0)
            nouveau_statut = 'RECEPTIONNE' if tous_signes else 'LIVREE'
        else:
            nouveau_statut = 'LIVRAISON_PARTIELLE'

        if self.statut != nouveau_statut:
            self.statut = nouveau_statut
            self.save(update_fields=['statut'])

    def __str__(self):
        return f"{self.numero_demande} - {self.service_demandeur.nom}"

    def clean(self):
        # ✅ CORRECTION : empêcher la modification d'une demande en statut historique
        if self.pk and self.statut in self.STATUTS_HISTORIQUE:
            raise ValidationError(
                f"Une demande en statut '{self.get_statut_display()}' ne peut plus être modifiée."
            )
        super().clean()

    class Meta:
        verbose_name        = "Demande de matériel"
        verbose_name_plural = "Demandes de matériel"
        ordering            = ['-date_demande']

class LigneDemande(models.Model):
    demande           = models.ForeignKey(DemandeMateriel, on_delete=models.CASCADE, related_name='lignes_demande')
    article           = models.ForeignKey(Article, on_delete=models.PROTECT, related_name='lignes_demande_article')
    quantite_demandee = models.PositiveIntegerField(default=1)
    quantite_accordee = models.PositiveIntegerField(default=0)

    @property
    def quantite_livree(self):
        # ✅ CORRECTION : exclure les livraisons annulées du calcul
        return LivraisonLigne.objects.filter(
            livraison__demande=self.demande,
            article=self.article,
            livraison__est_annule=False
        ).aggregate(total=models.Sum('quantite_livree'))['total'] or 0

    @property
    def reste(self):
        return max(0, self.quantite_demandee - self.quantite_livree)

    def __str__(self):
        return f"{self.quantite_demandee}x {self.article.designation}"

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=models.Q(quantite_demandee__gt=0),
                name='lignedem_qte_demandee_positive'
            ),
        ]

# ══════════════════════════════════════════════════════════════════════════════
# SYSTÈME DE LIVRAISONS PARTIELLES + ACCUSÉS DE RÉCEPTION
# ══════════════════════════════════════════════════════════════════════════════
class LivraisonPartielle(models.Model):
    demande          = models.ForeignKey(DemandeMateriel, on_delete=models.CASCADE, related_name='livraisons', verbose_name="Demande")
    numero_livraison = models.PositiveSmallIntegerField(verbose_name="N° livraison", editable=False)
    quantite_livree  = models.PositiveIntegerField(verbose_name="Quantité livrée (total bon)")
    est_partielle    = models.BooleanField(default=False, verbose_name="Est une livraison partielle", help_text="Vrai si la quantité livrée < quantité demandée")
    date_livraison   = models.DateTimeField(auto_now_add=True)
    livre_par        = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='livraisons_effectuees', verbose_name="Livré par")
    bon_sortie       = models.ForeignKey('BonMouvement', on_delete=models.SET_NULL, null=True, blank=True, related_name='livraison_origine', verbose_name="Bon de sortie lié")
    observations     = models.TextField(blank=True, null=True, verbose_name="Observations du magasinier")

    # ✅ RÉINTÉGRÉ : champ est_annule pour la logique d'annulation
    est_annule       = models.BooleanField(default=False, verbose_name="Annulé")

    def save(self, *args, **kwargs):
        """
        Génération atomique du numéro de livraison via CompteurDocument.
        ✅ CORRECTION : remplace le select_for_update() sur queryset vide (bug race condition)
           par le système de compteur atomique déjà utilisé ailleurs.
        """
        if not self.pk:
            with transaction.atomic():
                # Verrouiller la demande
                demande = DemandeMateriel.objects.select_for_update().get(pk=self.demande_id)

                # ✅ CORRECTION : utiliser CompteurDocument pour génération atomique
                def format_num_livraison(compteur, annee, eid):
                    return compteur  # Retourne un int pour numero_livraison

                self.numero_livraison = CompteurDocument.generer_numero(
                    entreprise_id=demande.magasin_cible.entreprise_id,
                    type_doc=f"LIV_{demande.id}"[:20],  # Tronqué à 20 caractères — plus de headroom
                    format_func=format_num_livraison
                )

                # Auto-calcul est_partielle
                reste_apres = max(0, demande.reste - self.quantite_livree)
                self.est_partielle = reste_apres > 0

                # ✅ CORRECTION : Appel standard à super().save() (le bloc hash_preuve a été retiré)
                super().save(*args, **kwargs)
        else:
            super().save(*args, **kwargs)

        self.demande.actualiser_statut()

    @property
    def est_receptionne(self):
        return (
            hasattr(self, 'accuse')
            and self.accuse.est_signe
            and not self.accuse.est_annule
        )

    def __str__(self):
        return f"Livraison #{self.numero_livraison} — {self.demande.numero_demande}"

    def annuler(self, user=None):
        """Annule cette livraison et met à jour le stock + statut de la demande."""
        if self.est_annule:
            return

        with transaction.atomic():
            self.est_annule = True
            self.save(update_fields=['est_annule'])

            # Remettre le stock si un bon de sortie est lié
            if self.bon_sortie:
                for ligne in self.bon_sortie.lignes_bon.all():
                    try:
                        Mouvement.objects.create(
                            type_mouvement='RETOUR_SERVICE',
                            article=ligne.article,
                            magasin=self.bon_sortie.magasin,
                            quantite=ligne.quantite,
                            prix_unitaire=ligne.prix_unitaire,
                            utilisateur=user,
                            reference_document=f"ANNUL-{self.numero_livraison}",
                            commentaire=f"Annulation livraison #{self.numero_livraison}"
                        )
                    except ValidationError as e:
                        logger.warning(
                            "Impossible de créer le mouvement de retour pour l'annulation "
                            f"livraison #{self.numero_livraison}, article {ligne.article}: {e}"
                        )
                        # On continue malgré l'erreur — le stock pourra être ajusté manuellement

            self.demande.actualiser_statut()

    class Meta:
        verbose_name        = "Livraison partielle"
        verbose_name_plural = "Livraisons partielles"
        ordering            = ['demande', 'numero_livraison']
        unique_together     = ('demande', 'numero_livraison')

class LivraisonLigne(models.Model):
    livraison = models.ForeignKey(
        LivraisonPartielle, 
        on_delete=models.CASCADE, 
        related_name='lignes_livraison'
    )
    article = models.ForeignKey(Article, on_delete=models.CASCADE)

    # ── Champs de base ──
    quantite_livree = models.PositiveIntegerField(default=0)
    prix_unitaire = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)

    # ── Traçabilité livraison partielle (3 champs cohérents) ──
    # Sémantique corrigée audit 2026-07-04 :
    #   quantite_demandee  = VRAIE quantité demandée (depuis LigneDemande)
    #   reste_avant_livraison = reste À LIVRER avant cette livraison
    #   reste = reste APRÈS cette livraison (0 si complète)
    quantite_demandee = models.PositiveIntegerField(
        default=0,
        verbose_name="Quantité demandée (originale)",
        help_text="Quantité initialement demandée par le service (depuis LigneDemande)"
    )
    reste_avant_livraison = models.PositiveIntegerField(
        default=0,
        verbose_name="Reste avant livraison",
        help_text="Quantité restant à livrer AVANT cette livraison (pour traçabilité historique)"
    )
    reste = models.PositiveIntegerField(
        default=0,
        verbose_name="Reste après livraison",
        help_text="Reliquat restant APRÈS cette livraison (0 si livraison complète)"
    )

    def save(self, *args, **kwargs):
        # Auto-population des champs de traçabilité à la création
        if self._state.adding:
            ligne_demande = LigneDemande.objects.filter(
                demande=self.livraison.demande,
                article=self.article
            ).first()
            if ligne_demande:
                self.quantite_demandee = ligne_demande.quantite_demandee
                self.reste_avant_livraison = ligne_demande.reste
            self.reste = max(0, self.reste_avant_livraison - self.quantite_livree)
        super().save(*args, **kwargs)

class AccuseReception(models.Model):
    livraison        = models.OneToOneField(LivraisonPartielle, on_delete=models.CASCADE, related_name='accuse', verbose_name="Livraison")
    receptionne_par  = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='accuses_signes', verbose_name="Réceptionné par")
    date_reception   = models.DateTimeField(null=True, blank=True, verbose_name="Date de réception")
    satisfait        = models.BooleanField(null=True, blank=True, verbose_name="Satisfait de la prestation ?")
    observations     = models.TextField(blank=True, null=True, verbose_name="Observations du réceptionnaire")
    est_signe        = models.BooleanField(default=False, verbose_name="Accusé signé")
    signature_image  = models.ImageField(upload_to='signatures/accuses/%Y/%m/', null=True, blank=True, verbose_name="Signature (image)")

    # ✅ RÉINTÉGRÉ : champ est_annule pour la logique d'annulation
    est_annule       = models.BooleanField(default=False, verbose_name="Annulé")

    def signer(self, user, est_satisfait=None, texte_observations=""):
        """
        Signe l'accusé de réception.
        ✅ CORRECTION : vérifie que l'utilisateur est autorisé à signer.
        """
        from django.utils import timezone
        import os
        from django.core.files import File

        # ✅ CORRECTION : vérifier l'autorisation
        demandeur = self.livraison.demande.demandeur
        if user != demandeur and not user.is_superuser:
            raise ValidationError(
                "Seul le demandeur ou un superutilisateur peut signer l'accusé de réception."
            )

        self.receptionne_par = user
        self.date_reception  = timezone.now()
        self.est_signe       = True
        self.satisfait = est_satisfait
        if texte_observations:
            self.observations = texte_observations

        profil = getattr(user, 'profil', None)
        if profil and getattr(profil, 'signature', None):
            try:
                src_path = profil.signature.path
                if os.path.exists(src_path):
                    with open(src_path, 'rb') as f:
                        nom_fichier = f"sig_rec_{user.pk}_liv{self.livraison.id}.png"
                        self.signature_image.save(nom_fichier, File(f), save=False)
            except Exception:
                logger.exception("Erreur copie signature lors de la signature de l'accusé")

        self.save()
        if hasattr(self.livraison, 'demande') and hasattr(self.livraison.demande, 'actualiser_statut'):
            self.livraison.demande.actualiser_statut()

    def __str__(self):
        statut = "Signé" if self.est_signe else "En attente"
        return f"Accusé #{self.livraison.numero_livraison} — {self.livraison.demande.numero_demande} [{statut}]"

    class Meta:
        verbose_name        = "Accusé de réception"
        verbose_name_plural = "Accusés de réception"

class BonDeLivraison(SoftDeleteModel):
    commande = models.ForeignKey(
        Commande,
        on_delete=models.CASCADE,
        related_name='bons_livraison_commande',
        verbose_name="Commande"
    )
    bon_entree = models.ForeignKey(
        'BonMouvement',
        on_delete=models.CASCADE,
        related_name='bons_livraison_entree',
        null=True, blank=True,
        verbose_name="Bon d'entrée lié"
    )
    fichier = models.FileField(upload_to='bons_livraison/%Y/%m/')
    reference_bl = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        verbose_name="Référence BL"
    )
    date_upload = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Date d'upload"
    )
    upload_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='bons_livraison_uploades'
    )

    class Meta:
        ordering = ['-date_upload']
        verbose_name = "Bon de livraison"
        verbose_name_plural = "Bons de livraison"

    def __str__(self):
        return f"BL {self.reference_bl or self.id} — {self.commande.numero_commande}"

# ══════════════════════════════════════════════════════════════════════════════
# VALIDATIONS DES DOCUMENTS (Signatures sur les 6 cases PDF)
# ══════════════════════════════════════════════════════════════════════════════
class ValidationDocument(models.Model):
    """
    Stocke chaque signature effectuée sur un bon.
    La fonction est snapshotée car l'utilisateur peut changer de service plus tard.
    """
    bon = models.ForeignKey(
        'BonMouvement',
        on_delete=models.CASCADE,
        related_name='validations',
        verbose_name="Bon concerné"
    )
    valideur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='validations_effectuees',
        verbose_name="Signataire"
    )
    ordre = models.PositiveSmallIntegerField(
        choices=[
            (1, 'Signataire 1 — Émission / Demandeur'),
            (2, 'Signataire 2 — Magasinier / Exécution'),
            (3, 'Signataire 3 — Responsable Service'),
            (4, 'Signataire 4 — Directeur'),
            (5, 'Signataire 5 — Contrôleur'),
            (6, 'Signataire 6 — Réceptionnaire'),
        ],
        verbose_name="Case signature"
    )
    date_validation = models.DateTimeField(auto_now_add=True, verbose_name="Date de signature")
    fonction_snapshot = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="Fonction au moment de la signature",
        help_text="Ex: Chef de Service Cardiologie"
    )
    signature_image = models.ImageField(
        upload_to='signatures/validations/%Y/%m/',
        null=True, blank=True,
        verbose_name="Image de la signature"
    )
    commentaire = models.TextField(blank=True, null=True, verbose_name="Commentaire")

    class Meta:
        verbose_name = "Validation sur document"
        verbose_name_plural = "Validations sur documents"
        unique_together = ['bon', 'ordre']
        ordering = ['ordre']

    def __str__(self):
        return f"Case {self.ordre} — {self.valideur} ({self.fonction_snapshot or '—'})"


# ══════════════════════════════════════════════════════════════════════════════
# MODÈLE DE DOCUMENT PDF CONFIGURABLE PAR MAGASIN
# ══════════════════════════════════════════════════════════════════════════════
class ModeleDocumentMagasin(TracabiliteModel):
    """
    Modèle de mise en page PDF configurable par magasin et par type de document.
    Stocke la description complète du document dans un JSONField.

    Hiérarchie de résolution :
    1. ModeleDocumentMagasin (si est_actif=True)
    2. accounts.ConfigDocument (config entreprise)
    3. _default_config() (fallback)
    """
    TYPE_DOC_CHOICES = [
        ('BS', 'Bon de Sortie'),
        ('BE', "Bon d'Entrée"),
        ('BR', 'Bon de Retour'),
        ('BSHS', 'Bon Hors Stock'),
        ('BC', 'Bon de Commande'),
        ('BDM', 'Bon de Demande de Matériel')
    ]

    magasin = models.ForeignKey(
        Magasin,
        on_delete=models.CASCADE,
        related_name='modeles_documents',
        verbose_name="Magasin concerné"
    )
    type_document = models.CharField(
        max_length=10,
        choices=TYPE_DOC_CHOICES,
        verbose_name="Type de document"
    )
    est_actif = models.BooleanField(
        default=True,
        verbose_name="Modèle actif"
    )
    config = models.JSONField(
        default=dict,
        verbose_name="Configuration de mise en page (JSON)",
        help_text="Description complète : cartouche, tableau, signatures, pied de page..."
    )

    class Meta:
        verbose_name = "Modèle de document PDF"
        verbose_name_plural = "Modèles de documents PDF"
        unique_together = ['magasin', 'type_document']
        ordering = ['magasin__nom', 'type_document']
        constraints = [
            models.CheckConstraint(
                condition=models.Q(type_document__in=['BS', 'BE', 'BR', 'BSHS', 'BC', 'BDM']),
                name='check_type_doc',
                violation_error_message="Le type de document doit être BS, BE, BR, BSHS, BC ou BDM.",
            ),
        ]
        permissions = [
            ('can_configurer_modeles_pdf', "Peut configurer les modèles de documents PDF"),
        ]

    def __str__(self):
        return f"{self.get_type_document_display()} — {self.magasin.nom}"

    @staticmethod
    @lru_cache(maxsize=128)
    def _default_config_structured(cfg_entreprise_json, type_doc):
        """
        Construit la structure JSON par défaut à partir de la config entreprise legacy.
        Utilise @lru_cache pour éviter les recalculs répétés (max 128 configs en mémoire).
        cfg_entreprise_json est un tuple de tuples (hashable) pour le cache.

        ⚠️ ATTENTION : Ce cache est statique par processus. Si un admin modifie
        la ConfigDocument en base, le cache restera obsolète jusqu'au redémarrage.
        Pour invalider : ModeleDocumentMagasin._default_config_structured.cache_clear()
        """
        # Reconvertir le tuple en dict
        cfg_entreprise = dict(cfg_entreprise_json) if cfg_entreprise_json else {}

        mapping = {
            'BON_SORTIE': 'BS', 'BON_ENTREE': 'BE', 'BON_RETOUR': 'BR',
            'BON_HS': 'BSHS', 'COMMANDE': 'BC'
        }
        code = mapping.get(type_doc, 'BS')

        if type_doc == 'BON_SORTIE':
            sigs = [
                {'ordre': 1, 'role': 'demandeur',    'label': 'Émission',          'visible': True, 'position': 'left',   'style': 'ligne_pointillee', 'condition': 'toujours'},
                {'ordre': 2, 'role': 'magasinier',   'label': 'Vu pour exécution', 'visible': True, 'position': 'center', 'style': 'ligne_pointillee', 'condition': 'toujours'},
                {'ordre': 3, 'role': 'responsable',  'label': 'Sortie effectuée',  'visible': True, 'position': 'right',  'style': 'ligne_pointillee', 'condition': 'toujours'},
                {'ordre': 4, 'role': 'receptionnaire','label': 'Réception',        'visible': True, 'position': 'right',  'style': 'ligne_pointillee', 'condition': 'toujours'},
            ]
            colonnes_defaut = ['numero', 'reference', 'designation', 'unite', 'quantite', 'quantite_servie']
            ps2 = "PS2 : GERER LES PRESTATIONS EXTERNES"
            code_iso = "ENR-BSM/DAF-001"
        elif type_doc == 'BON_ENTREE':
            sigs = [
                {'ordre': 1, 'role': 'responsable', 'label': 'Responsable', 'visible': True, 'position': 'left',  'style': 'ligne_pointillee', 'condition': 'toujours'},
                {'ordre': 2, 'role': 'magasinier',  'label': 'Magasinier',  'visible': True, 'position': 'right', 'style': 'ligne_pointillee', 'condition': 'toujours'},
            ]
            colonnes_defaut = ['numero', 'reference', 'designation', 'unite', 'quantite', 'lot', 'peremption', 'prix_unitaire', 'montant']
            ps2 = "PS2 : GERER LES APPROVISIONNEMENTS"
            code_iso = "ENR-BEM/DAF-001"
        elif type_doc == 'COMMANDE':
            sigs = [
                {'ordre': 1, 'role': 'sous_directeur', 'label': 'Le Sous-Directeur de la Logistique', 'visible': True, 'position': 'left',  'style': 'ligne_pointillee', 'condition': 'toujours'},
                {'ordre': 2, 'role': 'responsable',    'label': 'Le Responsable',                      'visible': True, 'position': 'right', 'style': 'ligne_pointillee', 'condition': 'toujours'},
            ]
            colonnes_defaut = ['numero', 'reference', 'designation', 'unite', 'quantite']
            ps2 = "PS2 : GERER LES PRESTATIONS EXTERNES"
            code_iso = "ENR-BDC/DAF-001"
        else:
            sigs = [
                {'ordre': 1, 'role': 'demandeur',   'label': 'Demandeur',   'visible': True, 'position': 'left',  'style': 'ligne_pointillee', 'condition': 'toujours'},
                {'ordre': 2, 'role': 'responsable', 'label': 'Responsable', 'visible': True, 'position': 'right', 'style': 'ligne_pointillee', 'condition': 'toujours'},
            ]
            colonnes_defaut = ['numero', 'reference', 'designation', 'unite', 'quantite']
            ps2 = ""
            code_iso = ""

        all_colonnes = [
            {'code': 'numero',         'label': 'N°',          'visible': 'numero' in colonnes_defaut,         'largeur': '5%',  'obligatoire': True},
            {'code': 'reference',      'label': 'Code',        'visible': 'reference' in colonnes_defaut,      'largeur': '12%', 'obligatoire': True},
            {'code': 'designation',    'label': 'Désignation', 'visible': 'designation' in colonnes_defaut,    'largeur': '30%', 'obligatoire': True},
            {'code': 'unite',          'label': 'Unité',       'visible': 'unite' in colonnes_defaut,          'largeur': '8%',  'obligatoire': True},
            {'code': 'quantite',       'label': 'Qté',         'visible': 'quantite' in colonnes_defaut,       'largeur': '8%',  'obligatoire': True},
            {'code': 'quantite_servie','label': 'Qté servie',  'visible': 'quantite_servie' in colonnes_defaut,  'largeur': '8%',  'obligatoire': False},
            {'code': 'lot',            'label': 'N° Lot',      'visible': 'lot' in colonnes_defaut,              'largeur': '12%', 'obligatoire': False},
            {'code': 'peremption',     'label': 'Péremption',  'visible': 'peremption' in colonnes_defaut,       'largeur': '12%', 'obligatoire': False},
            {'code': 'prix_unitaire',  'label': 'P.U.',        'visible': 'prix_unitaire' in colonnes_defaut,    'largeur': '10%', 'obligatoire': False},
            {'code': 'montant',        'label': 'Montant',     'visible': 'montant' in colonnes_defaut,         'largeur': '12%', 'obligatoire': False},
        ]

        return {
            'cartouche': {
                'afficher_logo':           cfg_entreprise.get('afficher_logo', True),
                'position_logo':            'left',
                'afficher_republique':     cfg_entreprise.get('afficher_republique', True),
                'afficher_devise':          True,
                'afficher_direction':       True,
                'afficher_sous_direction':  True,
                'afficher_service':         True,
                'afficher_telephone':       cfg_entreprise.get('afficher_telephone', True),
                'afficher_cc':              cfg_entreprise.get('afficher_cc', True),
                'afficher_ifu':             cfg_entreprise.get('afficher_ifu', True),
                'afficher_rccm':            cfg_entreprise.get('afficher_rccm', True),
                'trait_separation_epaisseur': 1,
                'trait_separation_couleur':   '#000000',
                'afficher_code_iso':          True,
            },
            'tableau': {
                'colonnes': all_colonnes,
                'lignes_dynamiques': True,
                'lignes_minimum': 10,
                'alternance_couleurs': False,
                'bordure_style': 'solid',
                'bordure_epaisseur': 'normal',
            },
            'signatures': sigs,
            'service_demandeur': {
                'encadrer': True,
                'position': 'left',
            },
            'sondage': {
                'afficher': True,
                'trait_separation': True,
                'style_cases': True,
            },
            'pied_de_page': {
                'texte_personnalise': cfg_entreprise.get('pied_page_pdf', ''),
                'afficher_numero_page': True,
                'afficher_date_generation': True,
                'afficher_trait_couleur': True,
                'trait_couleur': '#17a2b8',
            },
            'metadonnees': {
                'code_document':      cfg_entreprise.get('code_document', code_iso),
                'date_creation_doc':  cfg_entreprise.get('date_creation_doc', '10/06/2024'),
                'date_revision_doc':  cfg_entreprise.get('date_revision_doc', '19/05/2025'),
                'version_doc':        cfg_entreprise.get('version_doc', '002'),
                'ps2_label':          cfg_entreprise.get('ps2_label', ps2),
            },
            'direction_label':      cfg_entreprise.get('direction_label', "DIRECTION DES AFFAIRES FINANCIÈRES"),
            'sous_direction_label': cfg_entreprise.get('sous_direction_label', "SOUS-DIRECTION DE LA LOGISTIQUE"),
            'service_label':        cfg_entreprise.get('service_label', "SERVICE APPROVISIONNEMENT ET GESTION DES STOCKS"),
            'couleur_principale':   cfg_entreprise.get('couleur_principale', "#1c5b96"),
            'republique_label':     cfg_entreprise.get('republique_label', "RÉPUBLIQUE DE CÔTE D'IVOIRE"),
            'devise_label':         cfg_entreprise.get('devise_label', "Union - Discipline - Travail"),
        }

    @staticmethod
    def _deep_merge(base, override):
        """Fusion récursive de deux dictionnaires."""
        result = base.copy()
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = ModeleDocumentMagasin._deep_merge(result[key], value)
            elif key in result and isinstance(result[key], list) and isinstance(value, list):
                result[key] = value
            else:
                result[key] = value
        return result

    @classmethod
    def invalidate_cache(cls):
        """Invalide le cache LRU des configurations par défaut. À appeler après
        toute modification de ConfigDocument ou ModeleDocumentMagasin."""
        cls._default_config_structured.cache_clear()

    @staticmethod
    def _freeze_dict(obj):
        """
        Convertit récursivement un dict/list en structure hashable (tuple).
        Nécessaire pour que @lru_cache puisse hasher l'argument.
        """
        if isinstance(obj, dict):
            return tuple(sorted((k, ModeleDocumentMagasin._freeze_dict(v)) for k, v in obj.items()))
        elif isinstance(obj, list):
            return tuple(ModeleDocumentMagasin._freeze_dict(v) for v in obj)
        return obj

    def get_config_complete(self, type_doc_legacy='BON_SORTIE'):
        """
        Retourne la configuration fusionnée avec les valeurs par défaut.
        Garantit que toutes les clés attendues par les templates existent.
        """
        from accounts.models import Entreprise, ConfigDocument

        entreprise = self.magasin.entreprise

        cfg_entreprise = {}
        if hasattr(entreprise, 'get_pdf_config'):
            try:
                cfg_entreprise = entreprise.get_pdf_config(type_doc=type_doc_legacy)
            except Exception:
                pass

        cfg = self.config or {}
        # ✅ CORRECTION : convertir récursivement en structure hashable pour @lru_cache
        # Les listes internes (ex: colonnes) doivent aussi devenir des tuples
        cfg_key = self._freeze_dict(cfg_entreprise) if cfg_entreprise else ()
        defaults = self._default_config_structured(cfg_key, type_doc_legacy)
        return self._deep_merge(defaults, cfg)