# accounts/signals.py — DÉSACTIVÉ (logs gérés directement dans les vues)
"""
⚠️ Les signaux de connexion/déconnexion ont été désactivés car les vues
   custom_login, custom_logout et log_audit gèrent déjà le journal de sécurité.
   L'activation des deux sources créait des DOUBLONS dans AuditConnexion.
"""
