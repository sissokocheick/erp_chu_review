from django import forms
from django.contrib.auth.models import User, Group
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from accounts.models import Fonction, Profil, Specialite
from core.models import Service
from stock.models import Magasin


# ==========================================================
# UTILISATEUR
# ==========================================================
class UtilisateurForm(forms.ModelForm):
    """
    Formulaire de création/modification d'utilisateur.
    """
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        required=False,
        label="Mot de passe"
    )
    password_confirm = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        required=False,
        label="Confirmer le mot de passe"
    )
    groups = forms.ModelMultipleChoiceField(
        queryset=Group.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Groupes / Rôles"
    )
    service = forms.ModelChoiceField(
        queryset=Service.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Service"
    )
    specialite = forms.ModelChoiceField(
        queryset=Specialite.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Spécialité"
    )
    fonction = forms.ModelChoiceField(
        queryset=Fonction.objects.all(),
        required=False,
        widget=forms.Select(attrs={'class': 'form-control'}),
        label="Fonction / Titre"
    )
    contact = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control'}),
        label="Téléphone"
    )
    est_chef_service = forms.BooleanField(
        required=False,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label="Chef de service"
    )
    magasins_autorises = forms.ModelMultipleChoiceField(
        queryset=Magasin.objects.all(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Magasins autorisés"
    )

    class Meta:
        model = User
        fields = ['username', 'first_name', 'last_name', 'email', 'is_active', 'is_staff', 'is_superuser']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
        }

    def clean_username(self):
        """
        Le username est saisi tel quel (en minuscules, sans espaces).
        """
        username = self.cleaned_data.get('username', '').strip().lower().replace(' ', '')
        if not username:
            raise ValidationError("Le nom d'utilisateur est obligatoire.")
        if len(username) < 3:
            raise ValidationError("Le login doit contenir au moins 3 caractères.")
        return username

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        password_confirm = cleaned_data.get('password_confirm')

        if password or password_confirm:
            if password != password_confirm:
                raise ValidationError("Les mots de passe ne correspondent pas.")
            if len(password) < 8:
                raise ValidationError("Le mot de passe doit contenir au moins 8 caractères.")

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get('password'):
            user.set_password(self.cleaned_data['password'])
        if commit:
            user.save()
            self.save_m2m()
        return user


# ==========================================================
# PROFIL
# ==========================================================
class ProfilForm(forms.ModelForm):
    """Formulaire de modification du profil."""
    class Meta:
        model = Profil
        fields = ['service', 'specialite', 'fonction', 'contact', 'photo', 'est_chef_service']
        widgets = {
            'service': forms.Select(attrs={'class': 'form-control'}),
            'specialite': forms.Select(attrs={'class': 'form-control'}),
            'fonction': forms.Select(attrs={'class': 'form-control'}),
            'contact': forms.TextInput(attrs={'class': 'form-control'}),
            'photo': forms.FileInput(attrs={'class': 'form-control'}),
            'est_chef_service': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


# ==========================================================
# FONCTION
# ==========================================================
class FonctionForm(forms.ModelForm):
    """Formulaire de création/modification de fonction."""
    class Meta:
        model = Fonction
        fields = ['nom', 'description']
        widgets = {
            'nom': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def clean_nom(self):
        nom = self.cleaned_data.get('nom', '').strip().title()
        if not nom:
            raise ValidationError("Le nom de la fonction est obligatoire.")
        # CORRECTION : vérifier doublon (models.py n'a pas encore unique=True partout)
        qs = Fonction.objects.filter(nom__iexact=nom)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("Cette fonction existe déjà.")
        return nom


# ==========================================================
# SPÉCIALITÉ
# ==========================================================
class SpecialiteForm(forms.ModelForm):
    """Formulaire de création/modification de spécialité."""
    class Meta:
        model = Specialite
        fields = ['nom', 'description']
        widgets = {
            'nom': forms.TextInput(attrs={'class': 'form-control'}),
            'description': forms.Textarea(attrs={'class': 'form-control', 'rows': 3}),
        }

    def clean_nom(self):
        nom = self.cleaned_data.get('nom', '').strip().title()
        if not nom:
            raise ValidationError("Le nom de la spécialité est obligatoire.")
        qs = Specialite.objects.filter(nom__iexact=nom)
        if self.instance and self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise ValidationError("Cette spécialité existe déjà.")
        return nom


# ==========================================================
# CHANGEMENT DE MOT DE PASSE
# ==========================================================
class ChangerMotDePasseForm(forms.Form):
    """Formulaire de changement de mot de passe."""
    ancien_mdp = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        label="Ancien mot de passe"
    )
    nouveau_mdp = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        label="Nouveau mot de passe",
        min_length=8
    )
    confirmation = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control'}),
        label="Confirmer le nouveau mot de passe"
    )

    def __init__(self, user, *args, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)

    def clean_ancien_mdp(self):
        ancien = self.cleaned_data.get('ancien_mdp')
        if not self.user.check_password(ancien):
            raise ValidationError("L'ancien mot de passe est incorrect.")
        return ancien

    def clean(self):
        cleaned_data = super().clean()
        nouveau = cleaned_data.get('nouveau_mdp')
        confirmation = cleaned_data.get('confirmation')
        if nouveau and confirmation and nouveau != confirmation:
            raise ValidationError("Les nouveaux mots de passe ne correspondent pas.")
        return cleaned_data

    def save(self):
        self.user.set_password(self.cleaned_data['nouveau_mdp'])
        self.user.save()
        return self.user
