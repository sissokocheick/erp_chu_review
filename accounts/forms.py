from django import forms
from django.contrib.auth.models import User, Group
from .models import Profil, Entreprise, Fonction
from django.core.exceptions import ValidationError
from .utils import valider_mot_de_passe
import re


class UtilisateurForm(forms.ModelForm):
    """Gère les champs natifs Django User + le choix du Rôle (Group)."""

    groupe = forms.ModelChoiceField(
        queryset=Group.objects.none(),
        required=False,
        label="Rôle attribué",
        empty_label="--- Aucun rôle ---",
        widget=forms.Select(attrs={'class': 'form-control'})
    )

    # CORRECTION : champ mot de passe pour la création via formulaire
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Laissez vide pour génération auto'}),
        label="Mot de passe (optionnel)"
    )

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: j.dupont'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Jean'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Dupont'}),
            'email': forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Ex: j.dupont@hopital.com'}),
        }

    def __init__(self, *args, **kwargs):
        self.entreprise = kwargs.pop('entreprise', None)
        super().__init__(*args, **kwargs)

        if self.entreprise:
            self.fields['groupe'].queryset = Group.objects.filter(
                roleentreprise__entreprise=self.entreprise
            ).order_by('name')

        if self.instance and self.instance.pk:
            group = self.instance.groups.first()
            if group:
                self.fields['groupe'].initial = group
            # Masquer le champ password en modification
            self.fields['password'].widget = forms.HiddenInput()
            self.fields['password'].required = False

    def clean_username(self):
        username = self.cleaned_data.get('username', '').lower().strip()
        if not username:
            raise forms.ValidationError("Le nom d'utilisateur est obligatoire.")

        if self.entreprise:
            username_complet = f"{username}@{self.entreprise.slug}"
            qs = User.objects.filter(username__iexact=username_complet)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)

            if qs.exists():
                raise forms.ValidationError(
                    f"Ce nom d'utilisateur est déjà utilisé dans l'entreprise « {self.entreprise.nom} »."
                )
            return username_complet  # ← RETOURNE LE USERNAME FORMATÉ
        return username

    def clean_password(self):
        """CORRECTION : valide le mot de passe selon la politique centralisée."""
        password = self.cleaned_data.get('password', '')
        # En création (pas d'instance) et password fourni
        if not self.instance.pk and password:
            erreurs = valider_mot_de_passe(password, contexte='default')
            if erreurs:
                raise forms.ValidationError(
                    "Le mot de passe doit contenir : " + " | ".join(erreurs)
                )
        return password

    # SUPPRESSION de validate_unique() override — laisse Django gérer l'unicité
    # L'unicité du username est déjà vérifiée dans clean_username()


class FonctionForm(forms.ModelForm):
    """Formulaire de création/modification d'une fonction."""
    class Meta:
        model = Fonction
        fields = ['nom', 'description']
        widgets = {
            'nom': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Chef de Service Informatique'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 2, 'placeholder': 'Description optionnelle...'}),
        }

    def __init__(self, *args, **kwargs):
        self.entreprise = kwargs.pop('entreprise', None)
        super().__init__(*args, **kwargs)

    def clean_nom(self):
        nom = self.cleaned_data.get('nom', '').strip()
        if not nom:
            raise forms.ValidationError("Le nom de la fonction est obligatoire.")
        if self.entreprise:
            qs = Fonction.objects.filter(entreprise=self.entreprise, nom__iexact=nom)
            if self.instance and self.instance.pk:
                qs = qs.exclude(pk=self.instance.pk)
            if qs.exists():
                raise forms.ValidationError("Cette fonction existe déjà dans votre entreprise.")
        return nom


class ProfilForm(forms.ModelForm):
    """Gère les champs étendus du profil + fonction."""
    class Meta:
        model = Profil
        fields = ['contact', 'specialite', 'service', 'fonction', 'magasins_autorises', 'photo']
        widgets = {
            'contact': forms.TextInput(attrs={
                'class': 'clean-input-pro',
                'placeholder': 'Ex: 01 02 03 04 05',
                'maxlength': '14'
            }),
            'specialite': forms.Select(attrs={'class': 'clean-input-pro'}),
            'service': forms.Select(attrs={'class': 'clean-input-pro'}),
            'fonction': forms.Select(attrs={'class': 'clean-input-pro'}),
            'magasins_autorises': forms.SelectMultiple(attrs={
                'class': 'clean-input-pro select2-magasins',
                'style': 'width: 100%;'
            }),
            'photo': forms.FileInput(attrs={
                'accept': 'image/png, image/jpeg',
                'style': 'display: none;'
            }),
        }

    def __init__(self, *args, **kwargs):
        entreprise = kwargs.pop('entreprise', None)
        super().__init__(*args, **kwargs)
        if entreprise:
            self.fields['specialite'].queryset = self.fields['specialite'].queryset.filter(entreprise=entreprise)
            self.fields['service'].queryset = self.fields['service'].queryset.filter(entreprise=entreprise)
            self.fields['fonction'].queryset = self.fields['fonction'].queryset.filter(entreprise=entreprise).order_by('nom')
            self.fields['magasins_autorises'].queryset = self.fields['magasins_autorises'].queryset.filter(entreprise=entreprise)

    def clean_contact(self):
        """Validation du numéro de téléphone ivoirien."""
        contact = self.cleaned_data.get('contact', '').strip()
        if not contact:
            return contact
        # Format accepté : 01 XX XX XX XX ou +225 XX XX XX XX
        pattern = r'^(\+225[\s]?)?(01|05|07)[\s]?[0-9]{2}[\s]?[0-9]{2}[\s]?[0-9]{2}[\s]?[0-9]{2}$'
        if not re.match(pattern, contact.replace(' ', '')):
            raise forms.ValidationError(
                "Format invalide. Exemples : 01 02 03 04 05 ou +225 01 02 03 04 05"
            )
        return contact


# ==========================================================
# 🏢 FORMULAIRE CONFIG ENTREPRISE (IDENTITÉ PURE)
# ==========================================================
class EntrepriseConfigForm(forms.ModelForm):
    """Formulaire de configuration entreprise : identité, contact, logo, cachet."""

    class Meta:
        model = Entreprise
        fields = [
            'nom', 'slug', 'email_contact', 'telephone',
            'adresse', 'ville', 'pays',
            'cc', 'ifu', 'rccm',
            'logo', 'cachet', 'couleur_principale',
        ]
        widgets = {
            'nom': forms.TextInput(attrs={'class': 'nx-input', 'readonly': 'readonly'}),
            'slug': forms.TextInput(attrs={'class': 'nx-input', 'readonly': 'readonly'}),
            'email_contact': forms.EmailInput(attrs={'class': 'nx-input'}),
            'telephone': forms.TextInput(attrs={'class': 'nx-input'}),
            'adresse': forms.Textarea(attrs={'class': 'nx-textarea', 'rows': 2}),
            'ville': forms.TextInput(attrs={'class': 'nx-input'}),
            'pays': forms.TextInput(attrs={'class': 'nx-input'}),
            'cc': forms.TextInput(attrs={'class': 'nx-input'}),
            'ifu': forms.TextInput(attrs={'class': 'nx-input'}),
            'rccm': forms.TextInput(attrs={'class': 'nx-input'}),
            'logo': forms.ClearableFileInput(attrs={'class': 'nx-input', 'accept': 'image/png,image/jpeg'}),
            'cachet': forms.ClearableFileInput(attrs={'class': 'nx-input', 'accept': 'image/png,image/jpeg'}),
            'couleur_principale': forms.TextInput(attrs={'class': 'nx-input', 'maxlength': 7, 'id': 'id_couleur_principale'}),
        }

    def clean_couleur_principale(self):
        couleur = self.cleaned_data.get('couleur_principale')
        if couleur and not re.match(r'^#[0-9A-Fa-f]{6}$', couleur):
            raise forms.ValidationError("Format invalide. Exemple : #1c5b96")
        return couleur

    def _validate_image(self, image_field, field_name):
        """Validation commune pour logo et cachet (type MIME + taille)."""
        image = self.cleaned_data.get(image_field)
        if not image:
            return image

        # Vérification taille
        if image.size > 2 * 1024 * 1024:
            raise forms.ValidationError(f"Le {field_name} ne doit pas dépasser 2 Mo.")

        # Vérification extension
        ext = image.name.split('.')[-1].lower()
        if ext not in ['png', 'jpg', 'jpeg']:
            raise forms.ValidationError(f"Format accepté : PNG ou JPG uniquement.")

        # Vérification type MIME réel (si Pillow disponible)
        try:
            from PIL import Image
            img = Image.open(image)
            if img.format not in ['PNG', 'JPEG']:
                raise forms.ValidationError(f"Le fichier {field_name} n'est pas une image valide.")
            image.seek(0)  # Remettre le curseur au début pour la sauvegarde
        except ImportError:
            pass  # Pillow non installé, on se contente de l'extension
        except Exception:
            raise forms.ValidationError(f"Le fichier {field_name} est corrompu ou invalide.")

        return image

    def clean_logo(self):
        return self._validate_image('logo', 'logo')

    def clean_cachet(self):
        return self._validate_image('cachet', 'cachet')
