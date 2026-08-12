"""
Package views/parametres — réexporte toutes les vues pour compatibilité urls.py.
Remplace l'ancien fichier monolithique stock/views/parametres.py
"""
from .logistique import parametres_logistique
from .administratif import parametres_administratifs
from .circuits import page_circuits_validation
from .motifs import parametres_motifs
from .magasin import parametres_magasin
from .audit import journal_audit_securite
from .suppression import supprimer_parametre
from .notifications import parametres_notifications

__all__ = [
    'parametres_logistique',
    'parametres_administratifs',
    'page_circuits_validation',
    'parametres_motifs',
    'parametres_magasin',
    'journal_audit_securite',
    'supprimer_parametre',
    'parametres_notifications',
]
