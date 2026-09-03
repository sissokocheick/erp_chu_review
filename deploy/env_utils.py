# -*- coding: utf-8 -*-
"""
Utilitaire de déploiement NexusERP — empêche les CRLF dans .env.

⚠️ SÉCURITÉ : aucun identifiant n'est stocké dans ce fichier.
Les credentials proviennent de variables d'environnement locales :

    NEXUSERP_PROD_HOST     (défaut : 192.168.0.29)
    NEXUSERP_PROD_USER     (défaut : chuangre)
    NEXUSERP_PROD_PASSWORD (obligatoire — jamais de défaut)
    NEXUSERP_SUDO_PASSWORD (défaut : NEXUSERP_PROD_PASSWORD)
    NEXUSERP_PROD_ENV      (défaut : /opt/erp_chu_review/.env)

Usage :
    from deploy.env_utils import write_env_remote, ssh_connect

    ssh = ssh_connect()   # lève RuntimeError si NEXUSERP_PROD_PASSWORD est absent
    write_env_remote(ssh, {...})
"""
import os
import time

import paramiko

PROD_ENV = os.environ.get('NEXUSERP_PROD_ENV', '/opt/erp_chu_review/.env')


def _credential(nom_var, defaut=''):
    """Lit une credential depuis l'environnement. Jamais de secret dans le code."""
    valeur = os.environ.get(nom_var, defaut)
    if not valeur:
        raise RuntimeError(
            f"Variable d'environnement {nom_var} manquante — "
            f"les identifiants de production ne sont plus stockés dans le code. "
            f"Définissez-la avant d'utiliser ce module."
        )
    return valeur


def ssh_connect(host=None, user=None, password=None):
    """Connecte en SSH au serveur de prod (identifiants via l'environnement)."""
    host = host or os.environ.get('NEXUSERP_PROD_HOST', '192.168.0.29')
    user = user or os.environ.get('NEXUSERP_PROD_USER', 'chuangre')
    password = password or os.environ.get('NEXUSERP_PROD_PASSWORD', '')
    if not password:
        raise RuntimeError("NEXUSERP_PROD_PASSWORD manquant — connexion refusée.")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, username=user, password=password, timeout=15)
    return ssh


def _build_env_content(vars_dict):
    """Construit le contenu du .env avec des LF (pas CRLF)."""
    lines = []
    for key, value in vars_dict.items():
        lines.append(f'{key}={value}')
    # Join with \n explicitly (Unix LF)
    return '\n'.join(lines) + '\n'


def write_env_local(filepath, vars_dict):
    """Écrit un fichier .env local avec des LF garantis (pas de CRLF Windows)."""
    content = _build_env_content(vars_dict)
    # newline='' empêche Python d'ajouter \r sur Windows
    with open(filepath, 'w', newline='\n', encoding='utf-8') as f:
        f.write(content)
    return filepath


def write_env_remote(ssh, vars_dict, sudo_password=None):
    """Écrit le .env sur le serveur distant (via SFTP binaire + sudo cp).

    Garantit des line endings Unix (LF) quelle que soit la plateforme locale.
    """
    sudo_password = sudo_password or os.environ.get(
        'NEXUSERP_SUDO_PASSWORD',
        os.environ.get('NEXUSERP_PROD_PASSWORD', ''))

    content = _build_env_content(vars_dict)
    content_bytes = content.encode('utf-8')

    # 1) Upload via SFTP en mode binaire
    sftp = ssh.open_sftp()
    remote_tmp = '/tmp/nexuserp_env_upload'
    with sftp.open(remote_tmp, 'wb') as f:
        f.write(content_bytes)
    sftp.close()

    # 2) Vérifier qu'il n'y a pas de \r
    stdin, stdout, stderr = ssh.exec_command(
        f'file {remote_tmp} && grep -cP "\\\\r" {remote_tmp} && echo "CRLF_FOUND" || echo "LF_OK"'
    )
    check = stdout.read().decode('utf-8', errors='replace')
    if 'CRLF_FOUND' in check:
        print("  WARNING: CRLF detected, fixing...")
        _sudo_cmd(ssh, f'sed -i "s/\\\\r$//" {remote_tmp}', sudo_password)

    # 3) Copier avec sudo
    _sudo_cmd(ssh,
              f'cp {remote_tmp} {PROD_ENV} && '
              f'chown nexuserp:nexuserp {PROD_ENV} && '
              f'chmod 640 {PROD_ENV} && '
              f'echo ENV_OK',
              sudo_password)
    print(f"  .env written: {len(vars_dict)} vars, LF guaranteed")


def fix_crlf_remote(ssh, sudo_password=None):
    """Supprime les \r du .env existant sur le serveur (réparation d'urgence)."""
    sudo_password = sudo_password or os.environ.get(
        'NEXUSERP_SUDO_PASSWORD',
        os.environ.get('NEXUSERP_PROD_PASSWORD', ''))
    _sudo_cmd(ssh, f'sed -i "s/\\\\r$//" {PROD_ENV}', sudo_password)
    _sudo_cmd(ssh, f'chown nexuserp:nexuserp {PROD_ENV}', sudo_password)
    print("  CRLF fixed in remote .env")


def restart_service(ssh, sudo_password=None):
    """Redémarre le service nexuserp."""
    sudo_password = sudo_password or os.environ.get(
        'NEXUSERP_SUDO_PASSWORD',
        os.environ.get('NEXUSERP_PROD_PASSWORD', ''))
    _sudo_cmd(ssh, 'systemctl restart nexuserp', sudo_password)
    time.sleep(5)
    # Health check
    stdin, stdout, stderr = ssh.exec_command('curl -s --max-time 5 http://127.0.0.1:8000/health/')
    health = stdout.read().decode('utf-8', errors='replace').strip()
    print(f"  Health: {health}")
    return health


def _sudo_cmd(ssh, cmd, password):
    """Exécute une commande sudo via PTY (mot de passe via stdin, jamais en argv)."""
    chan = ssh.get_transport().open_session()
    chan.get_pty()
    chan.exec_command('sudo -S -p "" bash -c ' + _quote(cmd))
    time.sleep(1)
    chan.sendall(f'{password}\n'.encode())
    time.sleep(3)
    out = chan.recv(65536).decode('utf-8', errors='replace')
    chan.close()
    return out


def _quote(cmd):
    """Quote une commande pour bash -c (guillemets doubles échappés)."""
    return "'" + cmd.replace("'", "'\\''") + "'"
