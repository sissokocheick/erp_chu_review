from datetime import datetime, timezone

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods
from django.urls import reverse
from django.views.decorators.http import require_POST

import core.backups as backups_service
from core.health import run_checks
from core.supervision import (
    _taille_lisible,
    taille_base,
    lister_erreurs_logs,
    lister_requetes_lentes,
    lister_sauvegardes,
    taille_base,
    usage_disque,
)


def health_check(request):
    """Endpoint /health/ pour la supervision (LB, systemd HealthCheck, uptime).

    - database : canal critique → 503 si KO.
    - smtp / sms : canaux optionnels (disabled/test/error) → dégradent le
      statut mais ne font jamais tomber le service en 503.
    Anonyme : les détails d'erreur (hôte/port/SQL) restent côté serveur —
    seuls les statuts sont exposés publiquement.
    """
    import logging

    status, checks = run_checks()

    # Journaliser le détail côté serveur, ne PAS l'exposer anonymement
    # (les exceptions DB contiennent hôte, port, base et utilisateur).
    logger = logging.getLogger('core.health')
    for nom, check in checks.items():
        if check.get('status') == 'error' and check.get('detail'):
            logger.error("[health] %s KO : %s", nom, check['detail'])
            check['detail'] = 'unavailable'

    payload = {
        'status': status,
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'checks': checks,
    }
    return JsonResponse(payload, status=200 if checks['database']['status'] == 'ok' else 503)


@login_required(login_url='/auth/login/')
def supervision(request):
    """Tableau de bord de supervision — réservé au superutilisateur.

    Regroupe : l'état de santé (/health/), les sauvegardes PostgreSQL
    récentes et les erreurs de log des dernières heures.
    """
    if not request.user.is_superuser:
        return HttpResponseForbidden("⛔ Accès réservé à l'administrateur.")
    status, checks = run_checks()
    octets_base = taille_base()
    disque = usage_disque()
    pct = disque['pourcentage'] if disque else 0
    disque_statut = 'green' if pct < 70 else ('orange' if pct < 90 else 'red')
    context = {
        'status': status,
        'checks': checks,
        'sauvegardes': lister_sauvegardes(limit=10),
        'erreurs_logs': lister_erreurs_logs(limit=50),
        'taille_base_octets': octets_base,
        'taille_base_lisible': _taille_lisible(octets_base) if octets_base else '—',
        'disque': disque,
        'disque_statut': disque_statut,
        'requetes_lentes': lister_requetes_lentes(limit=20),
    }
    return render(request, 'core/supervision.html', context)


# ═════════════════════════════════════════════════════════════════════════════
# PARAMÈTRES — SAUVEGARDES (réservé au superutilisateur)
# ═════════════════════════════════════════════════════════════════════════════

@login_required(login_url='/auth/login/')
def parametres_sauvegardes(request):
    """Page Paramètres › Sauvegardes : configurer la destination, lancer une
    sauvegarde, télécharger ou supprimer les fichiers .backup locaux.

    La configuration est stockée dans backups/config.json (pas en base) afin
    de rester disponible même si la base de données est indisponible.
    """
    if not request.user.is_superuser:
        return HttpResponseForbidden("⛔ Accès réservé à l'administrateur.")

    if request.method == 'POST':
        # L'upload multipart utilise une clé 'fichier' dans le form
        if 'fichier' in request.FILES:
            return _sauvegardes_upload(request)
        return _sauvegardes_post(request)

    context = {
        'config': backups_service.lire_config(),
        'sauvegardes': backups_service.lister_backups(),
        'derniere_execution': lire_derniere_execution(),
        'etat_backup': backups_service.etat_sauvegardes(),
        'etat_planning': backups_service.etat_planning(),
        'jours_choices': backups_service.JOURS_SEMAINE,
        'taille_base_octets': taille_base(),
    }
    octets = context['taille_base_octets']
    context['taille_base_lisible'] = _taille_lisible(octets) if octets else '—'
    return render(request, 'core/sauvegardes.html', context)


@require_POST
def _sauvegardes_post(request):
    """Actions POST de la page sauvegardes (dispatch sur request.POST['action'])."""
    action = request.POST.get('action', '').strip()
    url = reverse('parametres_sauvegardes')

    if action == 'enregistrer_config':
        ok, msg = backups_service.ecrire_config(request.POST)
        (messages.success if ok else messages.error)(request, msg)
        return redirect(url)

    if action == 'lancer':
        ok, sortie = backups_service.lancer_sauvegarde()
        if ok:
            messages.success(request, "✅ Sauvegarde terminée avec succès.")
        else:
            messages.error(request, "❌ La sauvegarde a échoué — voir le détail ci-dessous.")
        # Le détail complet est ré-affiché sur la page (dernière exécution)
        _ecrire_derniere_execution(sortie, ok)
        return redirect(url)

    if action == 'supprimer':
        ok, msg = backups_service.supprimer_backup(request.POST.get('nom', ''))
        (messages.success if ok else messages.error)(request, msg)
        return redirect(url)

    if action == 'appliquer_planning':
        ok, msg = backups_service.appliquer_planning(request.POST)
        (messages.success if ok else messages.error)(request, msg)
        return redirect(url)

    if action == 'restaurer':
        ok, msg = backups_service.restaurer_backup(
            request.POST.get('nom', ''),
            request.POST.get('confirmation', ''))
        (messages.success if ok else messages.error)(request, msg)
        return redirect(url)

    messages.error(request, "Action inconnue.")
    return redirect(url)


def _sauvegardes_upload(request):
    """Gère l'upload d'un fichier .backup depuis un support externe."""
    fichier = request.FILES.get('fichier')
    ok, msg, nom = backups_service.uploadeer_backup(fichier)
    (messages.success if ok else messages.error)(request, msg)
    return redirect(reverse('parametres_sauvegardes'))


def _fichier_derniere_execution():
    return backups_service._dossier_backups() / 'derniere_execution.txt'


def _ecrire_derniere_execution(sortie, ok):
    try:
        _fichier_derniere_execution().write_text(
            f"{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}|{'OK' if ok else 'ECHEC'}\n{sortie}",
            encoding='utf-8')
    except OSError:
        pass


def lire_derniere_execution():
    try:
        texte = _fichier_derniere_execution().read_text(encoding='utf-8')
    except OSError:
        return None
    premiere, _, reste = texte.partition('\n')
    quand, sep, statut = premiere.partition('|')
    if not sep:
        return None
    return {'date': quand, 'ok': statut == 'OK', 'sortie': reste.strip()}


@login_required(login_url='/auth/login/')
def telecharger_backup(request, nom):
    """Télécharge un fichier .backup local (superutilisateur uniquement)."""
    if not request.user.is_superuser:
        return HttpResponseForbidden("⛔ Accès réservé à l'administrateur.")
    chemin = backups_service.chemin_backup(nom)
    if not chemin:
        messages.error(request, "❌ Sauvegarde introuvable.")
        return redirect('parametres_sauvegardes')
    reponse = FileResponse(chemin.open('rb'), as_attachment=True)
    reponse['Content-Length'] = chemin.stat().st_size
    return reponse
