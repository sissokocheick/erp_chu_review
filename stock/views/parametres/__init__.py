"""
Package views/parametres — réexporte toutes les vues pour compatibilité urls.py.
Remplace l'ancien fichier monolithique stock/views/parametres.py
"""
from .logistique import parametres_logistique
from .administratif import parametres_administratifs
from .magasin import parametres_magasin
from .suppression import supprimer_parametre
from .notifications import parametres_notifications

__all__ = [
    'parametres_logistique',
    'parametres_administratifs',
    'parametres_magasin',
    'supprimer_parametre',
    'parametres_notifications',
]
