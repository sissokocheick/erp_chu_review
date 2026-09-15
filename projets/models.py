from decimal import Decimal
from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from simple_history.models import HistoricalRecords

class Projet(models.Model):
    STATUT_CHOICES = [
        ('PREPARATION', 'En préparation'),
        ('EN_COURS', 'En cours'),
        ('SUSPENDU', 'Suspendu'),
        ('TERMINE', 'Terminé'),
        ('ANNULE', 'Annulé'),
    ]

    nom = models.CharField(max_length=200, db_index=True)
    description = models.TextField(blank=True, default="")
    
    date_debut = models.DateField(null=True, blank=True)
    date_fin_prevue = models.DateField(null=True, blank=True)
    date_fin_reelle = models.DateField(null=True, blank=True)
    
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='PREPARATION', db_index=True)
    
    chef_de_projet = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='projets_supervises')
    direction_responsable = models.ForeignKey(
        'core.Service',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='projets_direction',
        verbose_name="Direction / Service responsable"
    )
    responsable_direction = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='projets_direction_responsable',
        verbose_name="Responsable / Signataire de la Direction"
    )
    fournisseur = models.ForeignKey(
        'stock.Fournisseur',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='projets',
        verbose_name="Fournisseur / Entreprise en charge"
    )
    meme_fournisseur_livreur = models.BooleanField(
        default=True,
        verbose_name="Même fournisseur pour la livraison du matériel",
        help_text="Si activé, ce fournisseur sera automatiquement sélectionné lors des mouvements d'entrée de stock liés à ce projet."
    )
    budget_alloue = models.DecimalField(max_digits=15, decimal_places=0, null=True, blank=True)
    
    # Traçabilité
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)
    cree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='projets_crees')
    modifie_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='projets_modifies')
    
    is_deleted = models.BooleanField(default=False, db_index=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    history = HistoricalRecords()

    class Meta:
        verbose_name = "Projet"
        verbose_name_plural = "Projets"
        ordering = ['-date_creation']

    def __str__(self):
        return self.nom

class ProjetBesoin(models.Model):
    """
    Définit la Proforma ou le matériel prévu initialement pour un projet.
    """
    projet = models.ForeignKey(Projet, on_delete=models.CASCADE, related_name='besoins')
    article = models.ForeignKey('stock.Article', on_delete=models.CASCADE, related_name='+')
    quantite_prevue = models.PositiveIntegerField(default=1)
    
    date_ajout = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Besoin de Projet"
        verbose_name_plural = "Besoins de Projets"
        unique_together = ('projet', 'article')

    def __str__(self):
        return f"{self.quantite_prevue} x {self.article} (Projet: {self.projet.nom})"


class ProjetProforma(models.Model):
    """
    Représente une Proforma ou un Devis Fournisseur prévisionnel pour un projet.
    """
    STATUT_CHOICES = [
        ('ACTIF', 'Actif'),
        ('ANNULE', 'Annulé'),
    ]

    projet = models.ForeignKey(Projet, on_delete=models.CASCADE, related_name='proformas')
    numero_proforma = models.CharField(max_length=100, db_index=True, verbose_name="Numéro / Réf Proforma")
    date_proforma = models.DateField(default=timezone.now, verbose_name="Date d'enregistrement")
    fournisseur = models.ForeignKey(
        'stock.Fournisseur',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='proformas_projet',
        verbose_name="Fournisseur / Prestataire"
    )
    objet = models.CharField(max_length=255, blank=True, default="", verbose_name="Objet / Remarque")
    fichier_joint = models.FileField(upload_to='projets/proformas/', null=True, blank=True, verbose_name="Fichier scan / Devis")
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='ACTIF', db_index=True)
    
    # Traçabilité
    cree_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    modifie_par = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "Proforma Projet"
        verbose_name_plural = "Proformas Projets"
        ordering = ['-date_proforma', '-date_creation']

    def __str__(self):
        return f"{self.numero_proforma} ({self.projet.nom})"

    @property
    def total_articles(self):
        return sum(l.quantite_prevue for l in self.lignes.all())

    @property
    def total_montant_estime(self):
        return sum(l.montant_estime for l in self.lignes.all())


class ProjetProformaLigne(models.Model):
    """
    Ligne d'article détaillée d'une proforma de projet.
    """
    proforma = models.ForeignKey(ProjetProforma, on_delete=models.CASCADE, related_name='lignes')
    article = models.ForeignKey('stock.Article', on_delete=models.CASCADE, related_name='+')
    quantite_prevue = models.PositiveIntegerField(default=1)
    prix_unitaire_estime = models.DecimalField(max_digits=15, decimal_places=0, null=True, blank=True, default=0)

    class Meta:
        verbose_name = "Ligne de Proforma"
        verbose_name_plural = "Lignes de Proforma"

    def __str__(self):
        return f"{self.quantite_prevue} x {self.article.designation}"

    @property
    def montant_estime(self):
        return (self.prix_unitaire_estime or Decimal('0')) * self.quantite_prevue

