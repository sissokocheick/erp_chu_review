# -*- coding: utf-8 -*-
"""
Utilitaire de déploiement NexusERP — empêche les CRLF dans .env.

Usage:
    from deploy.env_utils import write_env_remote, ssh_connect

    ssh = ssh_connect()
    write_env_remote(ssh, {
        'DJANGO_DEBUG': 'False',
        'DB_PASSWORD': 'postgres',
        ...
    })
"""
import paramiko, sys, io, time, os

PROD_HOST = '192.168.0.29'
PROD_USER = 'chuangre'
PROD_PASS = 'Chu@angre2026'
PROD_ENV = '/opt/erp_chu_review/.env'


def ssh_connect(host=PROD_HOST, user=PROD_USER, password=PROD_PASS):
    """Connecte en SSH au serveur de prod."""
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


def write_env_remote(ssh, vars_dict, sudo_password=PROD_PASS):
    """Écrit le .env sur le serveur distant (via SFTP binaire + sudo cp).
    
    Garantit des line endings Unix (LF) quelle que soit la plateforme locale.
    """
    content = _build_env_content(vars_dict)
    # Encode en bytes Latin-1 pour éviter toute conversion CRLF
    content_bytes = content.encode('utf-8')

    # 1) Upload via SFTP en mode binaire
    sftp = ssh.open_sftp()
    remote_tmp = '/tmp/nexuserp_env_upload'
    with sftp.open(remote_tmp, 'wb') as f:
        f.write(content_bytes)
    sftp.close()

    # 2) Vérifier qu'il n'y a pas de \r
    stdin, stdout, stderr = ssh.exec_command(
        f'file {remote_tmp} && grep -cP "\\r" {remote_tmp} && echo "CRLF_FOUND" || echo "LF_OK"'
    )
    check = stdout.read().decode('utf-8', errors='replace')
    if 'CRLF_FOUND' in check:
        print(f"  WARNING: CRLF detected, fixing...")
        # Fallback: strip \r with sed
        _sudo_cmd(ssh, f'sed -i "s/\\r$//" {remote_tmp}', sudo_password)

    # 3) Copier avec sudo
    _sudo_cmd(ssh,
        f'cp {remote_tmp} {PROD_ENV} && '
        f'chown nexuserp:nexuserp {PROD_ENV} && '
        f'chmod 640 {PROD_ENV} && '
        f'echo ENV_OK',
        sudo_password
    )
    print(f"  .env written: {len(vars_dict)} vars, LF guaranteed")


def fix_crlf_remote(ssh, sudo_password=PROD_PASS):
    """Supprime les \\r du .env existant sur le serveur (réparation d'urgence)."""
    _sudo_cmd(ssh, f'sed -i "s/\\r$//" {PROD_ENV}', sudo_password)
    _sudo_cmd(ssh, f'chown nexuserp:nexuserp {PROD_ENV}', sudo_password)
    print("  CRLF fixed in remote .env")


def restart_service(ssh, sudo_password=PROD_PASS):
    """Redémarre le service nexuserp."""
    _sudo_cmd(ssh, 'systemctl restart nexuserp', sudo_password)
    time.sleep(5)
    # Health check
    stdin, stdout, stderr = ssh.exec_command('curl -s --max-time 5 http://127.0.0.1:8000/health/')
    health = stdout.read().decode('utf-8', errors='replace').strip()
    print(f"  Health: {health}")
    return health


def _sudo_cmd(ssh, cmd, password):
    """Exécute une commande sudo via PTY."""
    chan = ssh.get_transport().open_session()
    chan.get_pty()
    chan.exec_command(f'echo "{password}" | sudo -S bash -c "{cmd}" 2>&1')
    time.sleep(2)
    chan.sendall(f'{password}\n'.encode())
    time.sleep(3)
    out = chan.recv(65536).decode('utf-8', errors='replace')
    chan.close()
    return out
