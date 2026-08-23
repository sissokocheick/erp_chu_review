# -*- coding: utf-8 -*-
"""
Formulaires du module core.

ConfigurationHopitalForm : édition de la configuration unique de
l'établissement (mono-tenant).
"""
from django import forms

from core.models import ConfigurationHopital, ConfigurationNotification


class ConfigurationHopitalForm(forms.ModelForm):
    """Formulaire d'édition de la configuration de l'établissement."""

    class Meta:
        model = ConfigurationHopital
        fields = [
            # Identité
            'nom', 'couleur_principale', 'logo', 'cachet',
            # Contact & légal
            'telephone', 'email_contact', 'cc', 'ifu', 'rccm',
            'ville', 'adresse', 'pays',
            # Hiérarchie
            'direction_label', 'sous_direction_label', 'service_label',
            'pied_page_pdf',
            # Numérotation
            'prefixe_bon_sortie', 'prefixe_bon_entree', 'prefixe_bon_retour',
            'prefixe_bon_hors_stock', 'prefixe_commande',
            # Signatures
            
        ]
        widgets = {
            'nom': forms.TextInput(attrs={'class': 'form-control', 'required': True}),
            'couleur_principale': forms.TextInput(attrs={'class': 'form-control', 'type': 'color'}),
            'logo': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'cachet': forms.ClearableFileInput(attrs={'class': 'form-control'}),
            'telephone': forms.TextInput(attrs={'class': 'form-control'}),
            'email_contact': forms.EmailInput(attrs={'class': 'form-control'}),
            'cc': forms.TextInput(attrs={'class': 'form-control'}),
            'ifu': forms.TextInput(attrs={'class': 'form-control'}),
            'rccm': forms.TextInput(attrs={'class': 'form-control'}),
            'ville': forms.TextInput(attrs={'class': 'form-control'}),
            'adresse': forms.Textarea(attrs={'class': 'form-control', 'rows': '2'}),
            'pays': forms.TextInput(attrs={'class': 'form-control'}),
            'direction_label': forms.TextInput(attrs={'class': 'form-control'}),
            'sous_direction_label': forms.TextInput(attrs={'class': 'form-control'}),
            'service_label': forms.TextInput(attrs={'class': 'form-control'}),
            'pied_page_pdf': forms.Textarea(attrs={'class': 'form-control', 'rows': '2'}),
            'prefixe_bon_sortie': forms.TextInput(attrs={'class': 'form-control'}),
            'prefixe_bon_entree': forms.TextInput(attrs={'class': 'form-control'}),
            'prefixe_bon_retour': forms.TextInput(attrs={'class': 'form-control'}),
            'prefixe_bon_hors_stock': forms.TextInput(attrs={'class': 'form-control'}),
            'prefixe_commande': forms.TextInput(attrs={'class': 'form-control'}),
            
        }


class ConfigurationNotificationForm(forms.ModelForm):
    """Formulaire d'édition de la configuration des notifications (email / SMS)."""

    class Meta:
        model = ConfigurationNotification
        fields = [
            # Email
            'activer_email', 'smtp_host', 'smtp_port', 'smtp_user',
            'smtp_password', 'email_expediteur', 'smtp_use_tls',
            # SMS
            'activer_sms', 'sms_provider', 'sms_api_url', 'sms_api_key',
            'sms_expediteur', 'sms_twilio_template',
            'sms_param_numero', 'sms_param_message',
            'sms_mode_test',
        ]
        widgets = {
            # render_value=False : le secret n'est pas renvoyé au navigateur
            # à chaque affichage du formulaire (anti-fuite via HTML/backup).
            'smtp_password': forms.PasswordInput(render_value=False, attrs={'class': 'form-control', 'autocomplete': 'new-password'}),
            'sms_api_key': forms.PasswordInput(render_value=False, attrs={'class': 'form-control', 'autocomplete': 'new-password'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Secrets non renvoyés au navigateur (render_value=False) : un champ
        # laissé vide à la soumission signifie « conserver l'ancien secret ».
        self._anciens_secrets = {
            'smtp_password': getattr(self.instance, 'smtp_password', '') or '',
            'sms_api_key': getattr(self.instance, 'sms_api_key', '') or '',
        }
        self.fields['smtp_password'].required = False
        self.fields['sms_api_key'].required = False
        self.fields['smtp_password'].help_text = "Laisser vide pour conserver le mot de passe actuel."
        self.fields['sms_api_key'].help_text = "Laisser vide pour conserver la clé actuelle."
        for field in self.fields.values():
            if not isinstance(field.widget, forms.PasswordInput):
                css = field.widget.attrs.get('class', '')
                field.widget.attrs['class'] = (css + ' form-control').strip()
            if isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs['class'] = 'form-check-input'
            if isinstance(field.widget, forms.Select):
                field.widget.attrs['class'] = 'form-control'

    def clean_smtp_password(self):
        return self.cleaned_data.get('smtp_password') or self._anciens_secrets['smtp_password']

    def clean_sms_api_key(self):
        return self.cleaned_data.get('sms_api_key') or self._anciens_secrets['sms_api_key']
