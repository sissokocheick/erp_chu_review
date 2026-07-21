from django import forms
from .models import Immobilisation, Marque, Modele, Batiment, Bureau
from core.models import Service

class ImmobilisationForm(forms.ModelForm):
    class Meta:
        model = Immobilisation
        fields = [
            'code_patrimoine', 'numero_serie', 
            'marque', 'modele',
            'service_affectation', # 👈 Le Service est ajouté ici !
            'bureau', 'emplacement_exact', 
            'statut'
        ]
        widgets = {
            'code_patrimoine': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: CHU-INFO-2026-001'}),
            'numero_serie': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'S/N écrit sur la machine'}),
            'marque': forms.Select(attrs={'class': 'form-control'}),
            'modele': forms.Select(attrs={'class': 'form-control'}),
            'service_affectation': forms.Select(attrs={'class': 'form-control'}), # 👈 Liste déroulante des services
            'bureau': forms.Select(attrs={'class': 'form-control'}),
            'emplacement_exact': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex: Sur le bureau à gauche'}),
            'statut': forms.Select(attrs={'class': 'form-control'}),
        }
        labels = {
            'service_affectation': 'Service d\'affectation',
            'bureau': 'Bâtiment / Bureau',
            'emplacement_exact': 'Emplacement précis',
        }