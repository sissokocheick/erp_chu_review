# -*- coding: utf-8 -*-
"""Restore .env and restart production server."""
import paramiko, sys, io, time, os, tempfile
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.0.29', username='chuangre', password='Chu@angre2026')

# Write proper .env locally
env_content = """DJANGO_DEBUG=False
DJANGO_SECRET_KEY=8KWj8QB8VcDHFbWddy-6RrMemVPyGHthFZZtfJe1Ew0SQLC9KwnPndgfGlv5zYlwVY4
DJANGO_ALLOWED_HOSTS=192.168.0.29,127.0.0.1,localhost
CSRF_TRUSTED_ORIGINS=http://192.168.0.29
TRUSTED_INTERNAL=1
DB_NAME=chu_angre_db
DB_USER=postgres
DB_PASSWORD=postgres
DB_HOST=localhost
DB_PORT=5432
"""

local_env = os.path.join(tempfile.gettempdir(), 'restore_env')
with open(local_env, 'w', newline='\n') as f:
    f.write(env_content)

sftp = ssh.open_sftp()
sftp.put(local_env, '/tmp/restore.env')
sftp.close()

# Copy with sudo
cmd = 'echo "Chu@angre2026" | sudo -S cp /tmp/restore.env /opt/erp_chu_review/.env && echo "Chu@angre2026" | sudo -S chown nexuserp:nexuserp /opt/erp_chu_review/.env && echo "Chu@angre2026" | sudo -S chmod 640 /opt/erp_chu_review/.env && echo ENV_OK'
_, stdout, stderr = ssh.exec_command(cmd)
print('ENV:', stdout.read().decode().strip())

# Run migrate + init_roles
cmd2 = 'bash -c "set -a && source /opt/erp_chu_review/.env && set +a && source /opt/erp_chu_review/venv/bin/activate && cd /opt/erp_chu_review && python manage.py migrate --noinput 2>&1 | tail -5 && python manage.py init_roles 2>&1 | tail -12"'
_, stdout, stderr = ssh.exec_command(cmd2)
print(stdout.read().decode())

# Restart
_, stdout, stderr = ssh.exec_command('echo "Chu@angre2026" | sudo -S systemctl restart nexuserp')
stdout.read()
time.sleep(4)

_, stdout, stderr = ssh.exec_command('curl -s http://127.0.0.1:8000/health/')
print('Health:', stdout.read().decode())
ssh.close()
