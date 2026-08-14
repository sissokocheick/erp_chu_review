# Déploiement Ansible — NexusERP sur Ubuntu

Provisionne un serveur Ubuntu (22.04 / 24.04) de bout en bout :

1. paquets système (venv, pip, client PostgreSQL, nginx, curl, rsync) ;
2. utilisateur système dédié + dossier d'application ;
3. copie du code — **git** (si `repo_url` défini) ou **rsync** du checkout
   local du contrôleur (cas par défaut) ;
4. `.env` de production (template, mode 0600) ;
5. venv + `pip install` + `migrate` + `collectstatic` + `check --deploy` ;
6. service **systemd** (gunicorn, redémarrage auto, healthcheck `/health/`) ;
7. **nginx** reverse proxy avec TLS (auto-signé pour test ou certs existants) ;
8. **cron de sauvegarde PostgreSQL** quotidienne (02h00, rétention graduée) ;
9. vérification finale `GET /health/` → 200.

## Usage

```bash
# 1. Préparer l'inventaire et les variables
cp inventory.example inventory
cp host_vars/example.yml host_vars/prod-01.yml     # adapter + secrets

# 2. (recommandé) chiffrer les secrets
ansible-vault encrypt host_vars/prod-01.yml

# 3. Déployer
ansible-playbook -i inventory playbook.yml         # + --ask-vault-pass si vault
```

## Variables principales (`group_vars/all.yml`, surchargeables par hôte)

| Variable | Rôle |
|---|---|
| `app_user` / `app_dir` / `app_port` | utilisateur, dossier, port interne (gunicorn) |
| `server_name` | nom de domaine public (nginx) |
| `repo_url` (optionnel) | dépôt git du code — sinon rsync depuis `local_checkout` |
| `django_debug` / `secret_key` / `allowed_hosts` | configuration Django |
| `db_*` | connexion PostgreSQL |
| `smtp_*` / `twilio_*` | canaux de notification (optionnels) |
| `tls_self_signed` / `tls_cert` / `tls_key` | TLS (auto-signé ou existant) |

## TLS automatique (Let's Encrypt)

Avec `tls_letsencrypt: true` (et `tls_email` renseigné), le playbook installe
certbot et obtient le certificat au premier déploiement :

```yaml
# host_vars/<hote>.yml
tls_letsencrypt: true
tls_email: admin@chu.example
```

Prérequis : le domaine `server_name` doit pointer (DNS) vers le serveur et le
port 80 doit être ouvert — certbot valide via nginx. Le renouvellement est
automatique (timer `certbot.timer` installé avec le paquet).

## Après le déploiement

- Superutilisateur : `python manage.py createsuperuser` sur le serveur
  (via `sudo -u nexuserp /opt/erp_chu_review/venv/bin/python manage.py createsuperuser`).
- Journal : `journalctl -u nexuserp -f` · Statut : `systemctl status nexuserp`.

## Redéploiement du code seul

```bash
# rsync (défaut) : relancer le playbook entier (idempotent)
ansible-playbook -i inventory playbook.yml
```

> Nécessite la collection `ansible.posix` (synchronize) sur le contrôleur :
> `ansible-galaxy collection install ansible.posix`
