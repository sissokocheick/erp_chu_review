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
        ok, sortie = backups_service.lancer_sauvegarde(source='manuel')
        if ok:
            messages.success(request, "✅ Sauvegarde terminée avec succès.")
        else:
            messages.error(request, "❌ La sauvegarde a échoué — voir le détail ci-dessous.")
        _ecrire_derniere_execution(sortie, ok, source='manuel')
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


from django.http import JsonResponse


def analyser_backup_ajax(request):
    """Endpoint AJAX : analyse un backup et retourne le preview en JSON."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST requis'}, status=405)
    if not request.user.is_superuser:
        return JsonResponse({'error': 'Accès interdit'}, status=403)
    nom = request.POST.get('nom', '').strip()
    if not nom:
        return JsonResponse({'error': 'Nom manquant'}, status=400)
    analyse, err = backups_service.analyser_backup(nom)
    if err:
        return JsonResponse({'error': err}, status=400)
    return JsonResponse(analyse)


def tester_connectivite_ajax(request):
    """Endpoint AJAX : teste la connectivité vers le serveur distant de backup."""
    if request.method != 'POST':
        return JsonResponse({'error': 'POST requis'}, status=405)
    if not request.user.is_superuser:
        return JsonResponse({'error': 'Accès interdit'}, status=403)

    config = backups_service.lire_config()
    type_distant = config.get('type_distant', 'aucun')
    host = config.get('host', '')
    user = config.get('user', '')
    password = config.get('password', '')
    remote_dir = config.get('remote_dir', '')

    if type_distant == 'aucun' or not host:
        return JsonResponse({
            'ok': False,
            'statut': 'non_configure',
            'message': 'Aucun serveur distant configuré.',
            'details': []
        })

    import time, socket, subprocess, sys, io
    details = []
    start = time.time()

    # 1. Test ping (résolution DNS + connectivité réseau)
    try:
        ping_out = subprocess.run(
            ['ping', '-n', '2', '-w', '2000', host],
            capture_output=True, text=True, timeout=10,
            encoding='utf-8', errors='replace'
        )
        if ping_out.returncode == 0:
            # Extraire le temps moyen
            for line in ping_out.stdout.split('\n'):
                if 'Moyen' in line or 'Average' in line or 'moyen' in line.lower():
                    details.append({'test': 'Ping', 'ok': True, 'detail': line.strip()})
                    break
            else:
                details.append({'test': 'Ping', 'ok': True, 'detail': f'{host} répond'})
        else:
            details.append({'test': 'Ping', 'ok': False, 'detail': f'{host} ne répond pas au ping'})
    except Exception as e:
        details.append({'test': 'Ping', 'ok': False, 'detail': f'Erreur : {e}'})

    # 2. Test port (SMB = 445, SSH = 22)
    port = 445 if type_distant == 'smb' else 22
    port_name = 'SMB (445)' if type_distant == 'smb' else 'SSH (22)'
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        result = sock.connect_ex((host, port))
        sock.close()
        if result == 0:
            details.append({'test': f'Port {port_name}', 'ok': True, 'detail': f'Port {port} ouvert'})
        else:
            details.append({'test': f'Port {port_name}', 'ok': False, 'detail': f'Port {port} fermé ou filtré'})
    except Exception as e:
        details.append({'test': f'Port {port_name}', 'ok': False, 'detail': f'Erreur : {e}'})

    # 3. Test authentification + accès au dossier
    if type_distant == 'smb':
        try:
            import paramiko
            # Pour SMB, on utilise net use via cmd
            share_path = f'\\\\{host}\\{remote_dir}' if remote_dir else f'\\\\{host}'
            test_cmd = f'net use {share_path} /user:{user} {password} 2>&1'
            r = subprocess.run(
                ['cmd', '/c', test_cmd],
                capture_output=True, text=True, timeout=15,
                encoding='utf-8', errors='replace'
            )
            output = (r.stdout + r.stderr).strip()
            if 'ok' in output.lower() or 'réussie' in output.lower() or r.returncode == 0:
                details.append({'test': 'Authentification SMB', 'ok': True, 'detail': f'Connexion réussie vers {share_path}'})
                # Test listing
                list_cmd = f'dir {share_path} /b 2>&1'
                r2 = subprocess.run(
                    ['cmd', '/c', list_cmd],
                    capture_output=True, text=True, timeout=10,
                    encoding='utf-8', errors='replace'
                )
                files = [l.strip() for l in r2.stdout.strip().split('\n') if l.strip()]
                backups = [f for f in files if f.endswith('.backup')]
                details.append({'test': 'Listage fichiers', 'ok': True, 'detail': f'{len(backups)} backup(s) trouvé(s) sur {len(files)} fichier(s)'})
                # Disconnect
                subprocess.run(['cmd', '/c', f'net use {share_path} /delete 2>nul'], capture_output=True, timeout=5)
            else:
                details.append({'test': 'Authentification SMB', 'ok': False, 'detail': output[:200]})
        except Exception as e:
            details.append({'test': 'Authentification SMB', 'ok': False, 'detail': f'Erreur : {e}'})

    elif type_distant == 'ssh':
        try:
            import paramiko
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(host, username=user, password=password, timeout=10)
            details.append({'test': 'Authentification SSH', 'ok': True, 'detail': f'Connecté en tant que {user}@{host}'})
            # Test listing
            remote_path = remote_dir if remote_dir else '.'
            stdin, stdout, stderr = client.exec_command(f'ls -la {remote_path} 2>&1')
            output = stdout.read().decode('utf-8', errors='replace')
            files = [l.strip().split()[-1] for l in output.strip().split('\n') if '.backup' in l]
            details.append({'test': 'Listage fichiers', 'ok': True, 'detail': f'{len(files)} backup(s) trouvé(s) dans {remote_path}'})
            client.close()
        except ImportError:
            details.append({'test': 'Authentification SSH', 'ok': False, 'detail': 'paramiko non installé'})
        except Exception as e:
            details.append({'test': 'Authentification SSH', 'ok': False, 'detail': f'Erreur : {e}'})

    elapsed = round(time.time() - start, 1)
    all_ok = all(d['ok'] for d in details)

    # Mettre à jour le cache distant si tous les tests passent
    if all_ok:
        from core.backups import _ecrire_cache_distant
        _ecrire_cache_distant('ok', '', None, None, ajax_valide=True)

    return JsonResponse({
        'ok': all_ok,
        'statut': 'ok' if all_ok else 'erreur',
        'message': f'✅ Tous les tests passés ({elapsed}s)' if all_ok else f'❌ {sum(1 for d in details if not d["ok"])} test(s) échoué(s) sur {len(details)}',
        'details': details,
        'elapsed': elapsed,
    })


def _fichier_derniere_execution():
    return backups_service._dossier_backups() / 'derniere_execution.txt'


def _ecrire_derniere_execution(sortie, ok, source='manuel'):
    try:
        _fichier_derniere_execution().write_text(
            f"{datetime.now().strftime('%d/%m/%Y %H:%M:%S')}|{'OK' if ok else 'ECHEC'}|{source}\n{sortie}",
            encoding='utf-8')
    except OSError:
        pass


def lire_derniere_execution():
    try:
        texte = _fichier_derniere_execution().read_text(encoding='utf-8')
    except OSError:
        return None
    premiere, _, reste = texte.partition('\n')
    parts = premiere.split('|')
    if len(parts) < 2:
        return None
    quand = parts[0]
    statut = parts[1]
    # Source dans la ligne header ou dans le corps (SOURCE:xxx)
    source = parts[2] if len(parts) >= 3 else ''
    corps = reste.strip()
    if not source:
        for ligne in corps.split('\n'):
            if ligne.startswith('SOURCE:'):
                source = ligne.split(':', 1)[1].strip()
                break
    # Nettoyer la ligne SOURCE du corps affiché
    if source:
        corps = '\n'.join(l for l in corps.split('\n') if not l.startswith('SOURCE:'))
    return {'date': quand, 'ok': statut == 'OK', 'source': source, 'sortie': corps}


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
