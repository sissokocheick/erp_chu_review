from django import forms
from django.contrib.auth.models import User
from .models import (
    Mouvement, Article, Fournisseur, FamilleArticle,
    Ajustement, Magasin, BonMouvement, Beneficiaire, MotifAnnulation,
    FamilleParametre,
)
from core.models import Service
from accounts.models import Specialite, Fonction


def _limiter_choix_article(field, queryset, limite=200):
    """Limite uniquement les options HTML sans tronquer la validation ORM.

    ``ModelChoiceField`` doit conserver un queryset non découpé : sa validation
    appelle ``queryset.get(pk=...)`` et Django refuse un queryset déjà slicé.
    """
    field.queryset = queryset
    choix = [('', field.empty_label or '---------')]
    choix.extend((article.pk, str(article)) for article in queryset[:limite])
    field.widget.choices = choix


# ==========================================================
# MOUVEMENTS
# ==========================================================

class SortieStockForm(forms.ModelForm):
    class Meta:
        model  = Mouvement
        fields = [
            'article', 'magasin', 'quantite',
            'numero_lot', 'date_peremption',
            'service_demandeur', 'reference_document'
        ]
        widgets = {
            'article':           forms.Select(attrs={'class': 'form-control'}),
            'magasin':           forms.Select(attrs={'class': 'form-control'}),
            'quantite':          forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'numero_lot':        forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: LOT-2026-001 (facultatif)'
            }),
            'date_peremption':   forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'service_demandeur': forms.Select(attrs={'class': 'form-control'}),
            'reference_document':forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Ordonnance n° 1234'}),
        }
        labels = {
            'numero_lot': 'N° de lot',
            'date_peremption': 'Date de péremption',
        }

    def __init__(self, *args, **kwargs):
        self.utilisateur = kwargs.pop('utilisateur', None)
        super().__init__(*args, **kwargs)
        _limiter_choix_article(
            self.fields['article'],
            Article.objects.filter(
                stocks__quantite_physique__gt=0
            ).distinct(),
        )
        self.fields['magasin'].queryset = Magasin.objects.all()
        self.fields['service_demandeur'].queryset = Service.objects.all()
        self.fields['service_demandeur'].label = "Service Demandeur"

    def clean(self):
        cleaned_data = super().clean()
        article = cleaned_data.get('article')
        numero_lot = cleaned_data.get('numero_lot')
        date_peremption = cleaned_data.get('date_peremption')

        if article and article.requiert_lot_peremption:
            if not numero_lot:
                self.add_error('numero_lot', "Cet article nécessite un numéro de lot.")
            if not date_peremption:
                self.add_error('date_peremption', "Cet article nécessite une date de péremption.")

        return cleaned_data

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.type_mouvement = 'SORTIE'
        if self.utilisateur:
            instance.utilisateur = self.utilisateur
        if commit:
            instance.save()
        return instance


class EntreeStockForm(forms.ModelForm):
    class Meta:
        model  = Mouvement
        fields = [
            'article', 'magasin', 'quantite', 'fournisseur',
            'prix_unitaire',
            'numero_lot', 'date_peremption',
            'reference_document', 'commentaire',
        ]
        widgets = {
            'article':           forms.Select(attrs={'class': 'form-control'}),
            'magasin':           forms.Select(attrs={'class': 'form-control'}),
            'quantite':          forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'fournisseur':       forms.Select(attrs={'class': 'form-control'}),
            'prix_unitaire':     forms.NumberInput(attrs={
                'class': 'form-control', 'min': '0', 'step': '0.01',
                'placeholder': 'Prix unitaire (FCFA) — sert au calcul CMUP'
            }),
            'numero_lot':        forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: LOT-2026-001 (facultatif)'
            }),
            'date_peremption':   forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'reference_document':forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: N° Bon de Livraison ou Facture'
            }),
            'commentaire':       forms.Textarea(attrs={
                'class': 'form-control', 'rows': 2,
                'placeholder': 'Notes de réception...'
            }),
        }
        labels = {
            'prix_unitaire':   'Prix unitaire (FCFA)',
            'numero_lot':      'N° de lot',
            'date_peremption': 'Date de péremption',
        }

    def __init__(self, *args, **kwargs):
        self.utilisateur = kwargs.pop('utilisateur', None)
        super().__init__(*args, **kwargs)
        _limiter_choix_article(
            self.fields['article'],
            Article.objects.filter(is_deleted=False).order_by('designation'),
        )
        self.fields['magasin'].queryset = Magasin.objects.all()
        self.fields['fournisseur'].queryset = Fournisseur.objects.all()

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.type_mouvement = 'ENTREE'
        if self.utilisateur:
            instance.utilisateur = self.utilisateur
        if commit:
            instance.save()
        return instance


# ==========================================================
# CATALOGUE
# ==========================================================

class ArticleForm(forms.ModelForm):
    class Meta:
        model  = Article
        fields = [
            'designation',
            'famille',
            'unite_distribution',
            'seuil_minimum',
            'seuil_critique',
            'seuil_maximum',
            'prix_reference',
            'gere_lots_peremption',
            'est_immobilisable',
        ]
        widgets = {
            'designation':        forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: Paracetamol 500mg, Seringue 5ml...'
            }),
            'famille':            forms.Select(attrs={'class': 'form-control'}),
            'unite_distribution': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: Pot, Paquet de 100, Rouleau, Paire'
            }),
            'seuil_minimum':      forms.NumberInput(attrs={
                'class': 'form-control', 'min': '0',
                'placeholder': 'Qté minimum avant alerte jaune'
            }),
            'seuil_critique':     forms.NumberInput(attrs={
                'class': 'form-control', 'min': '0',
                'placeholder': 'Qté critique — alerte rouge (rupture imminente)'
            }),
            'seuil_maximum':      forms.NumberInput(attrs={
                'class': 'form-control', 'min': '0',
                'placeholder': 'Qté max avant surstock — laisser vide si non utilise'
            }),
            'prix_reference':     forms.NumberInput(attrs={
                'class': 'form-control', 'min': '0', 'step': '0.01',
                'placeholder': 'Prix unitaire de reference (FCFA)'
            }),
            'gere_lots_peremption': forms.CheckboxInput(attrs={'style': 'width: 20px; height: 20px; cursor: pointer;'}),
            'est_immobilisable': forms.CheckboxInput(attrs={'style': 'width: 20px; height: 20px; cursor: pointer;'}),
        }
        labels = {
            'reference':      'Reference interne',
            'seuil_minimum':  'Seuil minimum (alerte jaune)',
            'seuil_critique': 'Seuil critique (alerte rouge)',
            'seuil_maximum':  'Seuil maximum (surstock bleu)',
            'prix_reference': 'Prix de reference (FCFA)',
            'gere_lots_peremption': 'Gere les lots et peremptions',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['famille'].queryset = FamilleArticle.objects.all()

    def clean_designation(self):
        designation = self.cleaned_data.get('designation', '').strip()
        if designation:
            qs = Article.objects.filter(designation__iexact=designation)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError("Un article avec cette designation existe deja.")
        return designation

    def save(self, commit=True):
        instance = super().save(commit=False)
        if commit:
            instance.save()
        return instance
# ==========================================================
# SERVICES / CLIENTS INTERNES
# ==========================================================

class ServiceForm(forms.ModelForm):
    class Meta:
        model  = Service
        fields = ['nom', 'code', 'poste_telephone', 'telecopie']
        widgets = {
            'nom':            forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: SERVICE ECONOMIQUE'
            }),
            'code':           forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: SA01'
            }),
            'poste_telephone':forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: 200'
            }),
            'telecopie':      forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: 27 22 49 64 01'
            }),
        }
        labels = {
            'code':            'Code service (CDC)',
            'poste_telephone': 'Poste téléphonique',
            'telecopie':       'Télécopie / Fax',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def save(self, commit=True):
        instance = super().save(commit=False)
        if commit:
            instance.save()
        return instance


# ==========================================================
# FOURNISSEURS
# ==========================================================

class FournisseurForm(forms.ModelForm):
    class Meta:
        model  = Fournisseur
        fields = ['code', 'raison_sociale', 'contact', 'telephone', 'telecopie']
        widgets = {
            'code':           forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: 401F74'}),
            'raison_sociale': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: SOMAR SERVICES'}),
            'contact':        forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: M. KONÉ ALASSANE'}),
            'telephone':      forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: 01 02 03 04 05'}),
            'telecopie':      forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: 27 22 49 64 01'}),
        }
        labels = {
            'contact': 'Interlocuteur',
            'telecopie': 'Télécopie / Fax',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def save(self, commit=True):
        instance = super().save(commit=False)
        if commit:
            instance.save()
        return instance
# ==========================================================
# FAMILLES D'ARTICLES
# ==========================================================

class FamilleArticleForm(forms.ModelForm):
    class Meta:
        model  = FamilleArticle
        fields = [
            'code', 'intitule',
            'type_famille', 'methode_valorisation',
            'ligne_budgetaire',  # <-- AJOUT ICI
            'est_centralise', 'categorie',
            'gere_lots_peremption',
            'est_immobilisable',
        ]
        widgets = {
            'code': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: 2261MOBMAT, 6190FOUBUR'
            }),
            'intitule': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: MOBILIER ET MATERIEL DE BUREAU'
            }),
            'type_famille': forms.Select(attrs={
                'class': 'form-control select2-tags'
            }),
            'methode_valorisation': forms.Select(attrs={
                'class': 'form-control select2-tags'
            }),
            'categorie': forms.Select(attrs={
                'class': 'form-control select2-tags'
            }),
            'ligne_budgetaire': forms.Select(attrs={
                'class': 'form-control select2-tags'
            }),

            # --- Checkboxes stylisées ---
            'est_centralise': forms.CheckboxInput(attrs={
                'style': 'width: 20px; height: 20px; cursor: pointer;'
            }),
            'gere_lots_peremption': forms.CheckboxInput(attrs={
                'style': 'width: 20px; height: 20px; cursor: pointer;'
            }),
            'est_immobilisable': forms.CheckboxInput(attrs={
                'style': 'width: 20px; height: 20px; cursor: pointer;'
            }),
        }
        labels = {
            'type_famille': 'Type de famille (D/T/C)',
            'methode_valorisation': 'Méthode de valorisation',
            'ligne_budgetaire': 'Ligne budgétaire', # <-- AJOUT ICI
            'est_centralise': 'Famille centralisée',
            'categorie': 'Catégorie',
            'gere_lots_peremption': 'Gère les lots et péremptions',
            'est_immobilisable': 'Est immobilisable (Biens d\'équipement)',
        }

    def __init__(self, *args, **kwargs):
        categories = kwargs.pop('categories', None)
        lignes_budgetaires = kwargs.pop('lignes_budgetaires', None)
        types_famille = kwargs.pop('types_famille', None)
        valorisations = kwargs.pop('valorisations', None)
        super().__init__(*args, **kwargs)

        # En POST aussi, charger les anciennes valeurs pour que Select2 accepte
        # une valeur existante même lorsque la vue ne fournit pas les listes.
        famille_values = FamilleArticle.objects.all()
        if categories is None:
            categories = famille_values.exclude(categorie__isnull=True).exclude(categorie='').values_list('categorie', flat=True).distinct()
        if lignes_budgetaires is None:
            lignes_budgetaires = famille_values.exclude(ligne_budgetaire__isnull=True).exclude(ligne_budgetaire='').values_list('ligne_budgetaire', flat=True).distinct()
        if types_famille is None:
            types_famille = famille_values.exclude(type_famille__isnull=True).exclude(type_famille='').values_list('type_famille', flat=True).distinct()
        if valorisations is None:
            valorisations = famille_values.exclude(methode_valorisation__isnull=True).exclude(methode_valorisation='').values_list('methode_valorisation', flat=True).distinct()

        # Peupler les choix dynamiques : référentiel géré + anciennes valeurs
        managed_types = FamilleParametre.objects.filter(
            type_parametre='TYPE_FAMILLE', actif=True
        ).values_list('valeur', flat=True)
        managed_valos = FamilleParametre.objects.filter(
            type_parametre='VALORISATION', actif=True
        ).values_list('valeur', flat=True)
        managed_categories = FamilleParametre.objects.filter(
            type_parametre='CATEGORIE', actif=True
        ).values_list('valeur', flat=True)
        managed_lignes = FamilleParametre.objects.filter(
            type_parametre='LIGNE_BUDGETAIRE', actif=True
        ).values_list('valeur', flat=True)

        all_types = list(dict.fromkeys(list(types_famille) + list(managed_types)))
        type_choices = [('', '-- Choisir ou taper --')] + [(t, t) for t in all_types]
        self.fields['type_famille'].choices = type_choices
        self.fields['type_famille'].widget.choices = type_choices

        all_valos = list(dict.fromkeys(list(valorisations) + list(managed_valos)))
        valo_choices = [('', '-- Choisir ou taper --')] + [(v, v) for v in all_valos]
        self.fields['methode_valorisation'].choices = valo_choices
        self.fields['methode_valorisation'].widget.choices = valo_choices

        cat_choices = [('', '-- Choisir ou taper --')] + [
            (c, c) for c in list(dict.fromkeys(list(categories) + list(managed_categories)))
        ]
        self.fields['categorie'].choices = cat_choices
        self.fields['categorie'].widget.choices = cat_choices

        lb_choices = [('', '-- Choisir ou taper --')] + [
            (l, l) for l in list(dict.fromkeys(list(lignes_budgetaires) + list(managed_lignes)))
        ]
        self.fields['ligne_budgetaire'].choices = lb_choices
        self.fields['ligne_budgetaire'].widget.choices = lb_choices

    def save(self, commit=True):
        instance = super().save(commit=False)
        if commit:
            instance.save()
        return instance

class FamilleParametreForm(forms.ModelForm):
    class Meta:
        model = FamilleParametre
        fields = ['type_parametre', 'valeur']
        widgets = {
            'type_parametre': forms.HiddenInput(),
            'valeur': forms.TextInput(attrs={
                'class': 'form-control',
                'maxlength': 100,
                'required': True,
                'placeholder': 'Saisir une valeur…',
            }),
        }
        labels = {'valeur': 'Valeur'}

    def clean_valeur(self):
        valeur = ' '.join(self.cleaned_data.get('valeur', '').strip().split())
        if not valeur:
            raise forms.ValidationError('La valeur est obligatoire.')
        return valeur

    def clean(self):
        cleaned = super().clean()
        type_parametre = cleaned.get('type_parametre')
        valeur = cleaned.get('valeur')
        if type_parametre and valeur:
            qs = FamilleParametre.objects.filter(
                type_parametre=type_parametre,
                valeur__iexact=valeur,
            )
            if self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError('Cette valeur existe déjà dans ce référentiel.')
        return cleaned


# ==========================================================
# AJUSTEMENTS
# ==========================================================

class AjustementForm(forms.ModelForm):
    class Meta:
        model  = Ajustement
        fields = ['article', 'magasin', 'motif', 'quantite', 'commentaire']
        widgets = {
            'article':    forms.Select(attrs={'class': 'form-control'}),
            'magasin':    forms.Select(attrs={'class': 'form-control'}),
            'motif':      forms.Select(attrs={'class': 'form-control'}),
            'quantite':   forms.NumberInput(attrs={'class': 'form-control', 'min': '1'}),
            'commentaire':forms.Textarea(attrs={
                'class': 'form-control', 'rows': '2',
                'placeholder': 'Expliquez la raison...'
            }),
        }

    def __init__(self, *args, **kwargs):
        self.utilisateur = kwargs.pop('utilisateur', None)
        super().__init__(*args, **kwargs)
        # ⚠️ Ne JAMAIS tronquer la queryset d'un ModelChoiceField : Django
        # valide via queryset.get(pk=...), impossible sur une queryset
        # déjà découpée ([:200]) → le formulaire devenait invalide pour
        # TOUS les articles. On garde la base complète pour la validation
        # et on borne uniquement le <select> rendu côté navigateur.
        qs_articles = Article.objects.filter(
            is_deleted=False).order_by('designation')
        _limiter_choix_article(self.fields['article'], qs_articles)
        self.fields['magasin'].queryset = Magasin.objects.all()
        for champ in ['magasin', 'commentaire', 'motif']:
            if champ in self.fields:
                self.fields[champ].required = False
                self.fields[champ].widget.attrs.pop('required', None)

    def save(self, commit=True):
        instance = super().save(commit=False)
        if self.utilisateur and not getattr(instance, 'cree_par_id', None):
            instance.cree_par = self.utilisateur
        if commit:
            instance.save()
        return instance


# ==========================================================
# MAGASINS
# ==========================================================

class MagasinForm(forms.ModelForm):
    class Meta:
        model  = Magasin
        fields = ['nom', 'localisation']
        widgets = {
            'nom':         forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: Magasin Central Informatique'
            }),
            'localisation':forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: Bâtiment A, Rez-de-chaussée'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def save(self, commit=True):
        instance = super().save(commit=False)
        if commit:
            instance.save()
        return instance


# ==========================================================
# BON DE SORTIE HORS STOCK
# ==========================================================

class BonHorsStockForm(forms.ModelForm):
    class Meta:
        model = BonMouvement
        fields = ['magasin', 'fournisseur', 'service_demandeur', 'destinataire', 'reference_externe', 'commentaire']
        widgets = {
            'magasin':           forms.Select(attrs={'class': 'form-control'}),
            'fournisseur':       forms.Select(attrs={'class': 'form-control'}),
            'service_demandeur': forms.Select(attrs={'class': 'form-control'}),
            'destinataire':      forms.Select(attrs={'class': 'form-control'}),
            'reference_externe': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: N° Bon de Livraison fournisseur'
            }),
            'commentaire':       forms.Textarea(attrs={
                'class': 'form-control', 'rows': 2,
                'placeholder': 'Notes complémentaires...'
            }),
        }
        labels = {
            'magasin':           'Magasin rattaché',
            'fournisseur':       'Fournisseur',
            'service_demandeur': 'Service destinataire',
            'destinataire':      'Destinataire (Bénéficiaire)',
            'reference_externe': 'N° BL / Référence',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['magasin'].queryset = Magasin.objects.all()
        self.fields['fournisseur'].queryset = Fournisseur.objects.all()
        self.fields['service_demandeur'].queryset = Service.objects.all()
        self.fields['destinataire'].queryset = Beneficiaire.objects.all()

    def save(self, commit=True):
        instance = super().save(commit=False)
        instance.type_bon = 'SORTIE_HORS_STOCK'
        if commit:
            instance.save()
        return instance


# ==========================================================
# SPÉCIALITÉS
# ==========================================================

class SpecialiteForm(forms.ModelForm):
    class Meta:
        model  = Specialite
        fields = ['nom']
        widgets = {
            'nom': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Nom de la spécialité'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def save(self, commit=True):
        instance = super().save(commit=False)
        if commit:
            instance.save()
        return instance


class MagasinParametresForm(forms.ModelForm):
    class Meta:
        model = Magasin
        fields = [
            'titre_responsable', 'responsable', 'pied_de_page'
        ]
        widgets = {
            'titre_responsable': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Pharmacien Chef', 'title': 'Ce texte apparaît dans la case "Vu pour exécution" du PDF'}),
            'responsable': forms.Select(attrs={'class': 'form-control', 'title': 'Utilisateur qui signe numériquement dans la case magasinier'}),
            'pied_de_page': forms.TextInput(attrs={'class': 'form-control', 'title': "Texte du pied de page (laissez vide pour utiliser celui de l'établissement)"}),
        }
        help_texts = {
            'titre_responsable': 'Ex: Sous-Directeur de la Logistique — affiché dans la case "Vu pour exécution" du PDF.',
            'pied_de_page': "Si vide, le pied de page de l'établissement est utilisé automatiquement.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['responsable'].queryset = User.objects.filter(
            is_active=True
        ).order_by('first_name', 'last_name')


# ==========================================================
# BÉNÉFICIAIRES
# ==========================================================

class BeneficiaireForm(forms.ModelForm):
    class Meta:
        model = Beneficiaire
        fields = ['nom_complet', 'poste', 'service']
        widgets = {
            'nom_complet': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: Dr. KONÉ ALASSANE'
            }),
            'poste': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: Chef de Service, Pharmacien...'
            }),
            'service': forms.Select(attrs={'class': 'form-control'}),
        }
        labels = {
            'nom_complet': 'Nom complet',
            'poste': 'Poste / Fonction',
            'service': 'Service rattaché',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['service'].queryset = Service.objects.all()

    def save(self, commit=True):
        instance = super().save(commit=False)
        if commit:
            instance.save()
        return instance


# ==========================================================
# MOTIFS D'ANNULATION
# ==========================================================

class MotifAnnulationForm(forms.ModelForm):
    class Meta:
        model = MotifAnnulation
        fields = ['libelle']
        widgets = {
            'libelle': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: Erreur de saisie, Annulation demandée...'
            }),
        }
        labels = {
            'libelle': 'Libellé du motif',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def save(self, commit=True):
        instance = super().save(commit=False)
        if commit:
            instance.save()
        return instance


# ==========================================================
# FONCTIONS
# ==========================================================

class FonctionForm(forms.ModelForm):
    class Meta:
        model = Fonction
        fields = ['nom', 'description']
        widgets = {
            'nom': forms.TextInput(attrs={
                'class': 'form-control',
                'placeholder': 'Ex: Infirmier(e), Médecin, Technicien...'
            }),
            'description': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 2,
                'placeholder': 'Description optionnelle de la fonction...'
            }),
        }
        labels = {
            'nom': 'Nom de la fonction',
            'description': 'Description',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def save(self, commit=True):
        instance = super().save(commit=False)
        if commit:
            instance.save()
        return instance
