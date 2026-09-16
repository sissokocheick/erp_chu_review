import paramiko

def fetch_prod_logs():
    host = '192.168.0.29'
    user = 'chuangre'
    pwd = 'Chu@angre2026'
    
    print("Connecting to production server...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(host, username=user, password=pwd)
        
        commands = [
            "sudo -S cat /opt/erp_chu_review/logs/gunicorn-error.log | tail -n 50",
            "sudo -S systemctl status nexuserp.service --no-pager"
        ]
        
        for cmd in commands:
            print(f"--- Command: {cmd} ---")
            stdin, stdout, stderr = ssh.exec_command(cmd)
            stdin.write(pwd + '\n')
            stdin.flush()
            print(stdout.read().decode('utf-8'))
            err = stderr.read().decode('utf-8')
            if err:
                print(f"STDERR: {err}")
    finally:
        ssh.close()

if __name__ == '__main__':
    fetch_prod_logs()
