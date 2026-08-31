# -*- coding: utf-8 -*-
import paramiko, sys, io, time, os, tempfile
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('192.168.0.29', username='chuangre', password='Chu@angre2026')

# Write .env WITH export prefix so bash can source it
env_content = """export DJANGO_DEBUG=False
export DJANGO_SECRET_KEY=8KWj8QB8VcDHFbWddy-6RrMemVPyGHthFZZtfJe1Ew0SQLC9KwnPndgfGlv5zYlwVY4
export DJANGO_ALLOWED_HOSTS=192.168.0.29,127.0.0.1,localhost
export CSRF_TRUSTED_ORIGINS=http://192.168.0.29
export TRUSTED_INTERNAL=1
export DB_NAME=chu_angre_db
export DB_USER=postgres
export DB_PASSWORD=postgres
export DB_HOST=localhost
export DB_PORT=5432
"""

local_env = os.path.join(tempfile.gettempdir(), 'restore_env2')
with open(local_env, 'w', newline='\n') as f:
    f.write(env_content)

sftp = ssh.open_sftp()
sftp.put(local_env, '/tmp/restore2.env')
sftp.close()

cmd = 'echo "Chu@angre2026" | sudo -S cp /tmp/restore2.env /opt/erp_chu_review/.env && echo "Chu@angre2026" | sudo -S chown nexuserp:nexuserp /opt/erp_chu_review/.env && echo "Chu@angre2026" | sudo -S chmod 640 /opt/erp_chu_review/.env && echo ENV_OK'
_, stdout, stderr = ssh.exec_command(cmd)
print('ENV:', stdout.read().decode().strip())

# Now run migrate
script = '''#!/bin/bash
set -a
source /opt/erp_chu_review/.env
set +a
source /opt/erp_chu_review/venv/bin/activate
cd /opt/erp_chu_review
echo "SECRET_KEY set: ${DJANGO_SECRET_KEY:+YES}"
echo "DB_PASSWORD set: ${DB_PASSWORD:+YES}"
python manage.py migrate --noinput 2>&1 | tail -5
python manage.py init_roles 2>&1 | tail -12
'''
sftp = ssh.open_sftp()
with sftp.open('/tmp/run_migrate2.sh', 'w') as f:
    f.write(script)
sftp.close()

_, stdout, stderr = ssh.exec_command('chmod +x /tmp/run_migrate2.sh && /tmp/run_migrate2.sh')
print(stdout.read().decode())

# Restart
_, stdout, stderr = ssh.exec_command('echo "Chu@angre2026" | sudo -S systemctl restart nexuserp')
stdout.read()
time.sleep(4)

_, stdout, stderr = ssh.exec_command('curl -s http://127.0.0.1:8000/health/')
print('Health:', stdout.read().decode())
ssh.close()
