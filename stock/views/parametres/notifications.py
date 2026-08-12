# -*- coding: utf-8 -*-
"""Paramètres des notifications : canaux email (SMTP) et SMS (API)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect

from accounts.permissions import verifier_permission
from ...decorators import catch_errors
from core.models import ConfigurationNotification
from core.forms import ConfigurationNotificationForm


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_notifications_config', 'accounts.menu_parametres')
@catch_errors(redirect_url='/')
def parametres_notifications(request):
    """Page de configuration des canaux de notification (email / SMS)."""
    config = ConfigurationNotification.get_instance()

    if request.method == 'POST':
        form = ConfigurationNotificationForm(request.POST, instance=config)
        if form.is_valid():
            form.save()
            messages.success(
                request, "✅ Configuration des notifications enregistrée."
            )
            return redirect('parametres_notifications')
    else:
        form = ConfigurationNotificationForm(instance=config)

    # ── Diagnostic de configuration : signale les canaux activés mais non
    #    livrables (SMTP incomplet, SMS sans clé…) pour éviter les envois muets.
    diagnostic = []
    if config.activer_email:
        manquants = []
        if not config.email_expediteur:
            manquants.append("email expéditeur")
        if not config.smtp_host:
            manquants.append("hôte SMTP")
        if not config.smtp_user or not config.smtp_password:
            manquants.append("identifiants SMTP (utilisateur / mot de passe)")
        if manquants:
            diagnostic.append({
                'niveau': 'danger',
                'titre': "Email activé mais non livrable",
                'detail': "Les emails ne partiront pas : manque "
                          + ", ".join(manquants) + ".",
            })
    if config.activer_sms:
        manquants = []
        if not config.sms_expediteur:
            manquants.append("expéditeur (sender ID)")
        if not config.sms_api_url:
            manquants.append("URL de l'API")
        if not config.sms_api_key:
            manquants.append("clé API")
        if manquants:
            diagnostic.append({
                'niveau': 'danger',
                'titre': "SMS activé mais non livrable",
                'detail': "Les SMS ne partiront pas : manque "
                          + ", ".join(manquants) + ".",
            })
        elif config.sms_provider == 'TWILIO' and config.sms_twilio_template:
            diagnostic.append({
                'niveau': 'warning',
                'titre': "Compte Twilio en mode trial",
                'detail': "Seuls les SMS de notification (modèle prédéfini) partent. "
                          "Les codes de réinitialisation de mot de passe (texte réel) "
                          "nécessitent un compte Twilio payant.",
            })
        if config.sms_mode_test:
            diagnostic.append({
                'niveau': 'info',
                'titre': "Mode test SMS activé",
                'detail': "Aucun SMS réel n'est envoyé : ils sont journalisés dans les logs.",
            })

    return render(request, 'stock/parametres_notifications.html', {
        'form': form,
        'config': config,
        'diagnostic': diagnostic,
    })
