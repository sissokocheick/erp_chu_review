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
    """
    from stock.models import ModeleDocumentMagasin

    # Valeurs par défaut
    pdf_config = {
        'afficher_logo': True,
        'afficher_cachet': False,
        'afficher_cc': False,
        'afficher_ifu': False,
        'afficher_rccm': False,
        'afficher_telephone': True,
        'afficher_signatures': True,
        'code_document': type_doc_code,
        'date_creation_doc': '',
        'date_revision_doc': '',
        'version_doc': '1.0',
        'ps2_label': '',
        'couleur_principale': '#1c5b96',
        'pied_de_page': '',
        'texte_institutionnel': '',
        'logo_url': None,
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
        pdf_config.update({
            'afficher_logo': config.get('afficher_logo', True),
            'afficher_cachet': config.get('afficher_cachet', False),
            'afficher_cc': config.get('afficher_cc', False),
            'afficher_ifu': config.get('afficher_ifu', False),
            'afficher_rccm': config.get('afficher_rccm', False),
            'afficher_telephone': config.get('afficher_telephone', True),
            'afficher_signatures': config.get('afficher_signatures', True),
            'code_document': config.get('code_document', type_doc_code) or type_doc_code,
            'date_creation_doc': config.get('date_creation_doc', '') or '',
            'date_revision_doc': config.get('date_revision_doc', '') or '',
            'version_doc': config.get('version_doc', '1.0') or '1.0',
            'ps2_label': config.get('ps2_label', '') or '',
            'couleur_principale': config.get('couleur_principale', '#1c5b96') or '#1c5b96',
            'pied_de_page': config.get('pied_de_page', '') or '',
            'texte_institutionnel': config.get('texte_institutionnel', '') or '',
        })
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
    if not pdf_config['pied_de_page'] and magasin:
        pdf_config['pied_de_page'] = getattr(magasin, 'pied_de_page', '') or ''

    # Texte institutionnel fallback
    if not pdf_config['texte_institutionnel']:
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
    """
    cases = []
    afficher = pdf_config.get('afficher_signatures', True)
    if not afficher:
        return cases

    # Magasinier / Créateur
    if bon.cree_par:
        cases.append({
            'label': 'Magasinier',
            'sous_label': 'Service Logistique',
            'user_name': bon.cree_par.get_full_name() or bon.cree_par.username,
            'fonction': '',
            'date': bon.date_creation,
            'signature_path': _get_signature_url(request, bon.cree_par),
            'position': 'left',
            'style': 'ligne_pointillee',
        })

    # Validateur
    if bon.valide_par:
        cases.append({
            'label': 'Vu pour exécution',
            'sous_label': 'Responsable',
            'user_name': bon.valide_par.get_full_name() or bon.valide_par.username,
            'fonction': '',
            'date': bon.date_validation,
            'signature_path': _get_signature_url(request, bon.valide_par),
            'position': 'right',
            'style': 'ligne_pointillee',
        })

    return cases


def build_signatures_config(pdf_config, request):
    """
    Construit la configuration des signatures génériques (pour documents sans bon).
    """
    configs = []
    if not pdf_config.get('afficher_signatures', True):
        return configs

    configs.append({
        'label': 'Magasinier',
        'role': 'Service Logistique',
        'user_name': '',
        'sous_label': '',
        'date': None,
        'signature_path': None,
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
