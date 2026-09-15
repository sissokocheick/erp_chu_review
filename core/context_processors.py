# -*- coding: utf-8 -*-
from core.models import ConfigurationHopital

def contexte_hopital(request):
    try:
        config = ConfigurationHopital.get_instance()
        return {
            'config_hopital': config,
            'etablissement_nom': config.nom or 'CHU - Centre Hospitalier',
            'etablissement_logo': config.logo if config.logo else None,
            'devise_monetaire': getattr(config, 'devise_monetaire', 'FCFA') or 'FCFA',
            'seuil_alerte_peremption_jours': getattr(config, 'seuil_alerte_peremption_jours', 30) or 30,
        }
    except Exception:
        return {
            'config_hopital': None,
            'etablissement_nom': 'CHU - Centre Hospitalier',
            'etablissement_logo': None,
            'devise_monetaire': 'FCFA',
            'seuil_alerte_peremption_jours': 30,
        }
