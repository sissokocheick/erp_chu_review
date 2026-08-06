import logging
from dataclasses import dataclass
from typing import List, Dict, Any, Optional

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.http import HttpResponse
from django.template.loader import render_to_string
from weasyprint import HTML

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
# CONFIGURATION PDF
# ═════════════════════════════════════════════════════════════════════════════

def get_pdf_config(magasin, type_doc_code, request):
    """
    Récupère la configuration PDF pour un magasin et un type de document.
    Résolution : ModeleDocumentMagasin > Défaut.
    Retourne (pdf_config_dict, logo_url).
    
    La configuration retournée a la structure suivante :
    {
        'cartouche': { afficher_logo, afficher_republique, afficher_devise, ... },
        'metadonnees': { code_document, date_creation_doc, ... },
        'sondage': { afficher, trait_separation, ... },
        'signatures': [...],
        'couleur_principale': str,
        'pied_de_page': { texte_personnalise: str },
        'texte_institutionnel': str,
    }
    """
    from stock.models import ModeleDocumentMagasin

    # Mapping type_doc_code (BS, BE, ...) → type_doc_legacy (BON_SORTIE, BON_ENTREE, ...)
    TYPE_DOC_MAP = {
        'BS': 'BON_SORTIE',
        'BE': 'BON_ENTREE',
        'BR': 'BON_RETOUR',
        'BSHS': 'BON_HS',
        'BC': 'COMMANDE',
        'BDM': 'DEMANDE_MATERIEL',
        'AJUSTEMENT': 'AJUSTEMENT',
        'ETAT_STOCK': 'ETAT_STOCK',
        'HISTORIQUE': 'HISTORIQUE',
        'INVENTAIRE': 'INVENTAIRE',
        'RAPPORT': 'RAPPORT',
    }
    type_doc_legacy = TYPE_DOC_MAP.get(type_doc_code, 'BON_SORTIE')

    # Valeurs par défaut (structure complète)
    pdf_config = {
        'cartouche': {
            'afficher_logo': True,
            'position_logo': 'left',
            'afficher_republique': True,
            'afficher_devise': True,
            'afficher_direction': True,
            'afficher_sous_direction': True,
            'afficher_service': True,
            'afficher_telephone': True,
            'afficher_cc': False,
            'afficher_ifu': False,
            'afficher_rccm': False,
            'trait_separation_epaisseur': 1,
            'trait_separation_couleur': '#000000',
            'afficher_code_iso': True,
        },
        'metadonnees': {
            'code_document': type_doc_code,
            'date_creation_doc': '',
            'date_revision_doc': '',
            'version_doc': '1.0',
            'ps2_label': '',
        },
        'sondage': {
            'afficher': True,
            'trait_separation': True,
            'style_cases': True,
        },
        'signatures': [],
        'service_demandeur': {
            'encadrer': True,
            'position': 'left',
        },
        'pied_de_page': {
            'texte_personnalise': '',
            'afficher_numero_page': True,
            'afficher_date_generation': True,
            'afficher_trait_couleur': True,
            'trait_couleur': '#17a2b8',
        },
        'direction_label': "DIRECTION DES AFFAIRES FINANCIÈRES",
        'sous_direction_label': "SOUS-DIRECTION DE LA LOGISTIQUE",
        'service_label': "SERVICE APPROVISIONNEMENT ET GESTION DES STOCKS",
        'couleur_principale': '#1c5b96',
        'texte_institutionnel': "Direction des Affaires Financières / Sous-Direction de la Logistique",
        'republique_label': "RÉPUBLIQUE DE CÔTE D'IVOIRE",
        'devise_label': "Union - Discipline - Travail",
    }

    logo_url = None

    # Récupérer le modèle de document actif pour ce magasin + type
    modele = None
    if magasin:
        modele = ModeleDocumentMagasin.objects.filter(
            magasin=magasin,
            type_document=type_doc_code,
            est_actif=True
        ).first()

    if modele and modele.config:
        config = modele.config
        # Fusionner la config du modèle avec les valeurs par défaut
        pdf_config = ModeleDocumentMagasin._deep_merge(pdf_config, config)
        
        # S'assurer que les métadonnées de base sont présentes
        if 'metadonnees' not in pdf_config:
            pdf_config['metadonnees'] = {}
        pdf_config['metadonnees']['code_document'] = config.get('code_document', pdf_config['metadonnees'].get('code_document', type_doc_code))
        pdf_config['metadonnees']['date_creation_doc'] = config.get('date_creation_doc', pdf_config['metadonnees'].get('date_creation_doc', ''))
        pdf_config['metadonnees']['date_revision_doc'] = config.get('date_revision_doc', pdf_config['metadonnees'].get('date_revision_doc', ''))
        pdf_config['metadonnees']['version_doc'] = config.get('version_doc', pdf_config['metadonnees'].get('version_doc', '1.0'))
        pdf_config['metadonnees']['ps2_label'] = config.get('ps2_label', pdf_config['metadonnees'].get('ps2_label', ''))
        
        # Gérer le logo
        if config.get('logo'):
            try:
                logo_url = _make_absolute_url(request, config['logo'])
            except Exception:
                pass

    # Fallback logo magasin
    if not logo_url and magasin and getattr(magasin, 'logo', None):
        try:
            logo_url = _make_absolute_url(request, magasin.logo.url)
        except Exception:
            pass

    # Fallback logo statique
    if not logo_url:
        logo_url = request.build_absolute_uri(settings.STATIC_URL + 'img/logo.png')

    # Pied de page fallback sur magasin
    if 'pied_de_page' not in pdf_config:
        pdf_config['pied_de_page'] = {}
    if not pdf_config['pied_de_page'].get('texte_personnalise') and magasin:
        pdf_config['pied_de_page']['texte_personnalise'] = getattr(magasin, 'pied_de_page', '') or ''

    # Texte institutionnel fallback
    if not pdf_config.get('texte_institutionnel'):
        pdf_config['texte_institutionnel'] = (
            "Direction des Affaires Financières / Sous-Direction de la Logistique"
        )

    return pdf_config, logo_url


def _make_absolute_url(request, url):
    """Construit une URL absolue à partir d'une URL relative ou absolue."""
    if not url:
        return None
    if str(url).startswith('http'):
        return str(url)
    return request.build_absolute_uri(str(url))


# ═════════════════════════════════════════════════════════════════════════════
# RENDU PDF
# ═════════════════════════════════════════════════════════════════════════════

def render_pdf_response(request, template, context, filename, inline=True):
    """
    Rend un template HTML en PDF et retourne une HttpResponse.
    """
    html_string = render_to_string(template, context, request=request)
    base_url = request.build_absolute_uri('/')

    try:
        pdf_bytes = HTML(string=html_string, base_url=base_url).write_pdf()
    except Exception as e:
        logger.exception("[PDF] Erreur génération %s : %s", template, e)
        return HttpResponse("Erreur lors de la génération du PDF.", status=500)

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    disposition = 'inline' if inline else 'attachment'
    response['Content-Disposition'] = f'{disposition}; filename="{filename}"'
    return response


def render_pdf_to_bytes(request, template, context):
    """Génère un PDF et retourne les bytes (pour sauvegarde en cache)."""
    html_string = render_to_string(template, context, request=request)
    base_url = request.build_absolute_uri('/')
    return HTML(string=html_string, base_url=base_url).write_pdf()


# ═════════════════════════════════════════════════════════════════════════════
# PAGINATION DES LIGNES (multi-pages)
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class PaginationResult:
    pages: List[List[Dict]]
    est_multi_page: bool


def paginate_lignes(lignes_data: List[Dict], pdf_config: Dict, lignes_par_page: int = 18) -> PaginationResult:
    """
    Découpe les lignes en pages pour les documents multi-pages.
    """
    if not lignes_data:
        return PaginationResult(pages=[[]], est_multi_page=False)

    if len(lignes_data) <= lignes_par_page:
        return PaginationResult(pages=[lignes_data], est_multi_page=False)

    pages = []
    for i in range(0, len(lignes_data), lignes_par_page):
        pages.append(lignes_data[i:i + lignes_par_page])

    return PaginationResult(pages=pages, est_multi_page=len(pages) > 1)


# ═════════════════════════════════════════════════════════════════════════════
# SIGNATURES
# ═════════════════════════════════════════════════════════════════════════════

def build_signature_cases(bon, pdf_config, request):
    """
    Construit les cases de signature pour un bon de mouvement.
    Retourne une liste de dicts avec les infos de chaque signataire.
    Utilise la configuration 'signatures' du pdf_config si disponible.
    """
    cases = []
    
    # Vérifier si les signatures sont activées (nouvelle structure ou ancienne)
    afficher = True
    if 'sondage' in pdf_config:
        # Nouvelle structure : pas de flag global, on utilise les signatures de la config
        signatures_config = pdf_config.get('signatures', [])
        if not signatures_config:
            # Si aucune signature configurée, on utilise les signatures par défaut
            pass
    else:
        # Ancienne structure (rétrocompatibilité)
        afficher = pdf_config.get('afficher_signatures', True)
        if not afficher:
            return cases
    
    # Magasinier / Créateur
    if bon.cree_par:
        profil = getattr(bon.cree_par, 'profil', None)
        fonction = profil.fonction.nom if profil and profil.fonction else ''
        signature_path = _get_signature_url(request, bon.cree_par)
        cases.append({
            'label': 'Magasinier',
            'sous_label': 'Service Logistique',
            'user_name': bon.cree_par.get_full_name() or bon.cree_par.username,
            'fonction': fonction,
            'date': bon.date_creation,
            'signature_path': signature_path,
            'has_signature': bool(signature_path),
            'position': 'left',
            'style': 'ligne_pointillee',
        })

    # Validateur
    if bon.valide_par:
        profil = getattr(bon.valide_par, 'profil', None)
        fonction = profil.fonction.nom if profil and profil.fonction else ''
        signature_path = _get_signature_url(request, bon.valide_par)
        cases.append({
            'label': 'Vu pour exécution',
            'sous_label': 'Responsable',
            'user_name': bon.valide_par.get_full_name() or bon.valide_par.username,
            'fonction': fonction,
            'date': bon.date_validation,
            'signature_path': signature_path,
            'has_signature': bool(signature_path),
            'position': 'right',
            'style': 'ligne_pointillee',
        })

    return cases


def build_signatures_config(pdf_config, request):
    """
    Construit la configuration des signatures génériques (pour documents sans bon).
    Utilise la configuration 'signatures' du pdf_config si disponible.
    """
    configs = []
    
    # Vérifier si les signatures sont activées (nouvelle structure ou ancienne)
    if 'sondage' in pdf_config:
        # Nouvelle structure : utiliser les signatures de la config
        signatures_config = pdf_config.get('signatures', [])
        if signatures_config:
            for sig in signatures_config:
                if sig.get('visible', True):
                    configs.append({
                        'label': sig.get('label', 'Signataire'),
                        'role': sig.get('role', ''),
                        'user_name': '',
                        'sous_label': '',
                        'date': None,
                        'signature_path': None,
                        'has_signature': False,
                        'position': sig.get('position', 'left'),
                        'style': sig.get('style', 'ligne_pointillee'),
                    })
            if configs:
                return configs
    
    # Ancienne structure (rétrocompatibilité) ou fallback
    if not pdf_config.get('afficher_signatures', True):
        return configs

    configs.append({
        'label': 'Magasinier',
        'role': 'Service Logistique',
        'user_name': '',
        'sous_label': '',
        'date': None,
        'signature_path': None,
        'has_signature': False,
        'position': 'left',
        'style': 'ligne_pointillee',
    })
    configs.append({
        'label': 'Responsable',
        'role': 'Direction',
        'user_name': '',
        'sous_label': '',
        'date': None,
        'signature_path': None,
        'has_signature': False,
        'position': 'right',
        'style': 'ligne_pointillee',
    })
    return configs


def _get_signature_url(request, user):
    """Retourne l'URL absolue de la signature d'un utilisateur."""
    if not user:
        return None
    profil = getattr(user, 'profil', None)
    if not profil:
        return None
    signature = getattr(profil, 'signature', None)
    if not signature:
        return None
    try:
        return _make_absolute_url(request, signature.url)
    except Exception:
        return None


# ═════════════════════════════════════════════════════════════════════════════
# CACHE PDF (helpers pour stockage dans FileField)
# ═════════════════════════════════════════════════════════════════════════════

def servir_pdf_cache(bon, filename):
    """
    Lit un PDF depuis le stockage Django et retourne HttpResponse.
    Retourne None si le cache est absent ou invalide.
    """
    if not getattr(bon, 'fichier_pdf', None) or not bon.fichier_pdf.name:
        return None
    try:
        if default_storage.exists(bon.fichier_pdf.name):
            with default_storage.open(bon.fichier_pdf.name, 'rb') as f:
                pdf_bytes = f.read()
            response = HttpResponse(pdf_bytes, content_type='application/pdf')
            response['Content-Disposition'] = f'inline; filename="{filename}"'
            return response
    except Exception as e:
        logger.warning("[PDF] Cache inaccessible : %s", e)
    return None


def sauver_pdf_cache(bon, filename, pdf_bytes):
    """
    Sauvegarde les bytes PDF dans le FileField du bon.
    Supprime l'ancien fichier s'il existe pour éviter les conflits.
    """
    try:
        if bon.fichier_pdf and bon.fichier_pdf.name and default_storage.exists(bon.fichier_pdf.name):
            default_storage.delete(bon.fichier_pdf.name)
        bon.fichier_pdf.save(filename, ContentFile(pdf_bytes), save=True)
    except Exception as e:
        logger.warning("[PDF] Sauvegarde cache échouée : %s", e)
