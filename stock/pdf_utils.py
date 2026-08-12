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
    
    Hiérarchie de résolution :
    1. ModeleDocumentMagasin (configuration spécifique au magasin)
    2. ConfigDocument (configuration globale par type de document)
    3. Valeurs par défaut
    
    Args:
        magasin: Instance du modèle Magasin
        type_doc_code: Code du type de document (BS, BE, BR, BSHS, BDM, BC)
        request: Requête HTTP Django
        
    Returns:
        tuple: (pdf_config_dict, logo_url)
            - pdf_config_dict: Dictionnaire avec tous les paramètres PDF
            - logo_url: URL absolue du logo à utiliser
    """
    from stock.models import ModeleDocumentMagasin
    from accounts.models import ConfigDocument

    # ═══════════════════════════════════════════════════════════════════════
    # Cartographie code court -> type legacy attendu par get_config_complete
    # ═══════════════════════════════════════════════════════════════════════
    CODE_TO_LEGACY = {
        'BS': 'BON_SORTIE',
        'BE': 'BON_ENTREE',
        'BR': 'BON_RETOUR',
        'BSHS': 'BON_HS',
        'BC': 'COMMANDE',
        'BDM': 'DEMANDE',
    }
    type_doc_legacy = CODE_TO_LEGACY.get(type_doc_code, type_doc_code)

    logo_url = None

    # ═══════════════════════════════════════════════════════════════════════
    # ÉTAPE 1 : Configuration riche par défaut + config magasin
    # (structure cartouche / tableau / signatures / sondage / metadonnees)
    # ═══════════════════════════════════════════════════════════════════════
    modele = None
    if magasin:
        modele = ModeleDocumentMagasin.objects.filter(
            magasin=magasin,
            type_document=type_doc_code,
            est_actif=True
        ).first()

    if modele:
        pdf_config = modele.get_config_complete(type_doc_legacy)
    else:
        # Pas de modèle magasin : défauts riches calculés à partir de ConfigDocument
        pdf_config = ModeleDocumentMagasin._default_config_structured(
            ModeleDocumentMagasin._freeze_dict(_config_document_flat(type_doc_code)),
            type_doc_legacy,
        )

    # ═══════════════════════════════════════════════════════════════════════
    # ÉTAPE 2 : Logo (config magasin -> magasin -> statique)
    # ═══════════════════════════════════════════════════════════════════════
    if modele and modele.config and modele.config.get('logo'):
        try:
            logo_url = _make_absolute_url(request, modele.config['logo'])
        except Exception as e:
            logger.warning("[PDF] Erreur lecture logo config magasin: %s", e)

    if not logo_url and magasin and getattr(magasin, 'logo', None):
        try:
            logo_url = _make_absolute_url(request, magasin.logo.url)
        except Exception as e:
            logger.warning("[PDF] Erreur lecture logo magasin: %s", e)

    if not logo_url:
        logo_url = _static_logo_data_uri()
    if not logo_url:
        try:
            logo_url = request.build_absolute_uri('/static/img/logo.jpg')
        except Exception:
            logo_url = None

    # ═══════════════════════════════════════════════════════════════════════
    # ÉTAPE 3 : Alias « plats » pour compatibilité avec les templates
    # qui accèdent encore pdf_config.couleur_principale, pdf_config.ps2_label…
    # ═══════════════════════════════════════════════════════════════════════
    metadonnees = pdf_config.get('metadonnees') or {}
    pied = pdf_config.get('pied_de_page') or {}
    if isinstance(pied, dict):
        pied_texte = pied.get('texte_personnalise') or ''
    else:
        pied_texte = pied or ''

    pdf_config['couleur_principale'] = pdf_config.get('couleur_principale') or '#1c5b96'
    pdf_config['code_document'] = metadonnees.get('code_document') or type_doc_code
    pdf_config['date_creation_doc'] = metadonnees.get('date_creation_doc') or ''
    pdf_config['date_revision_doc'] = metadonnees.get('date_revision_doc') or ''
    pdf_config['version_doc'] = metadonnees.get('version_doc') or '1.0'
    pdf_config['ps2_label'] = metadonnees.get('ps2_label') or ''
    pdf_config['texte_institutionnel'] = (
        pdf_config.get('texte_institutionnel')
        or (pied_texte or '')
        or "Direction des Affaires Financières / Sous-Direction de la Logistique"
    )

    # Alias plats pour compatibilité (accès pdf_config.afficher_*)
    cartouche = pdf_config.get('cartouche') or {}
    pdf_config['afficher_logo'] = cartouche.get('afficher_logo', True)
    pdf_config['afficher_cc'] = cartouche.get('afficher_cc', True)
    pdf_config['afficher_ifu'] = cartouche.get('afficher_ifu', True)
    pdf_config['afficher_rccm'] = cartouche.get('afficher_rccm', True)
    pdf_config['afficher_telephone'] = cartouche.get('afficher_telephone', True)
    pdf_config['afficher_signatures'] = pdf_config.get('afficher_signatures', True)
    config_globale = ConfigDocument.objects.filter(type_doc=type_doc_code).first()
    pdf_config['afficher_cachet'] = (
        pdf_config.get('afficher_cachet')
        if pdf_config.get('afficher_cachet') is not None
        else (config_globale.afficher_cachet if config_globale else False)
    )

    # Pied de page : s'assurer qu'il s'agit d'un dict (texte + options d'affichage)
    if not isinstance(pdf_config.get('pied_de_page'), dict):
        pdf_config['pied_de_page'] = {
            'texte_personnalise': pied_texte,
            'afficher_numero_page': True,
            'afficher_date_generation': True,
            'afficher_trait_couleur': True,
            'trait_couleur': '#17a2b8',
        }

    # Fallback pied de page : ConfigurationHopital (identité CHU) -> magasin -> défaut
    if not pdf_config['pied_de_page'].get('texte_personnalise'):
        pdf_config['pied_de_page']['texte_personnalise'] = _pied_de_page_par_defaut()

    pdf_config['logo_url'] = logo_url

    return pdf_config, logo_url


def _pied_de_page_par_defaut():
    """Compose le pied de page officiel du CHU à partir de ConfigurationHopital."""
    try:
        from core.models import ConfigurationHopital
        cfg = ConfigurationHopital.get_instance()
    except Exception:
        cfg = None

    if cfg:
        adresse = (cfg.adresse or '').strip()
        telephone = (cfg.telephone or '').strip()
        cc = (cfg.cc or '').strip()
        email = (cfg.email_contact or '').strip()
        identite = (cfg.nom or 'ANGRE BESSIKOI').strip()
        direction = (cfg.direction_label or 'Direction des Affaires Financières').strip()
        sous_direction = (cfg.sous_direction_label or 'Sous-Direction de la Logistique').strip()

        infos = []
        if adresse:
            infos.append(f"Adresse : {adresse}")
        if telephone:
            infos.append(f"Tél : {telephone}")
        if cc:
            infos.append(f"CC N° : {cc}")
        if email:
            infos.append(email)

        ligne1 = identite + (f" * {' * '.join(infos)}" if infos else '')
        ligne2 = f"{direction} * {sous_direction}"
        # Séparateurs \\A : sauts de ligne CSS dans le pied de page (white-space: pre-line)
        return f"{ligne1} \\A {ligne2} \\A Postes : 110 et 200"

    return "Direction des Affaires Financières / Sous-Direction de la Logistique"


def _config_document_flat(type_doc_code):
    """Renvoie les valeurs ConfigDocument (globales) pour un type de document."""
    from accounts.models import ConfigDocument
    config = ConfigDocument.objects.filter(type_doc=type_doc_code).first()
    if not config:
        return {}
    return {
        'afficher_logo': config.afficher_logo,
        'afficher_cachet': config.afficher_cachet,
        'afficher_cc': config.afficher_cc,
        'afficher_ifu': config.afficher_ifu,
        'afficher_rccm': config.afficher_rccm,
        'afficher_telephone': config.afficher_telephone,
        'afficher_signatures': config.afficher_signatures,
        'code_document': config.code_document or '',
        'date_creation_doc': config.date_creation_doc or '',
        'date_revision_doc': config.date_revision_doc or '',
        'version_doc': config.version_doc or '',
        'ps2_label': config.ps2_label or '',
    }


def _make_absolute_url(request, url):
    """Construit une URL absolue à partir d'une URL relative ou absolue."""
    if not url:
        return None
    if str(url).startswith('http'):
        return str(url)
    return request.build_absolute_uri(str(url))


def _static_logo_data_uri():
    """
    Retourne le logo statique par défaut (stock/static/img/logo.jpg)
    encodé en data URI base64 — toujours embarquable par WeasyPrint,
    sans dépendre d'un serveur statique joignable.
    """
    import base64
    import mimetypes
    import os
    try:
        from django.contrib.staticfiles import finders
        logo_path = finders.find('img/logo.jpg')
        if not logo_path or not os.path.isfile(logo_path):
            return None
        mime = mimetypes.guess_type(logo_path)[0] or 'image/jpeg'
        with open(logo_path, 'rb') as f:
            data = base64.b64encode(f.read()).decode('ascii')
        return f"data:{mime};base64,{data}"
    except Exception as e:
        logger.warning("[PDF] Logo statique non encodable : %s", e)
        return None


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

# Rôles de signataires connus et utilisateur associé sur un document.
def _role_utilisateur(doc, role):
    """Retourne l'utilisateur associé à un rôle de signature pour un document.
    Supporte BonMouvement (cree_par) et DemandeMateriel (demandeur).
    """
    cree_par = getattr(doc, 'cree_par', None)
    demandeur = getattr(doc, 'demandeur', None)
    valide_par = getattr(doc, 'valide_par', None)
    if role in ('demandeur', 'magasinier'):
        return cree_par or demandeur
    if role in ('responsable', 'sous_directeur', 'chef_service', 'receptionnaire'):
        return valide_par or cree_par or demandeur
    # economat / communication : aucune signature individuelle (cachet du service)
    return None


def _build_cases_depuis_config(pdf_config, bon=None, request=None):
    """
    Construit les cases de signature à partir de la configuration du document
    (pdf_config['signatures'] : labels, visibilité, position, rôle).
    Les noms/dates sont renseignés depuis le document (si fourni).
    """
    cases = []
    if not pdf_config.get('afficher_signatures', True):
        return cases
    signatures = pdf_config.get('signatures') or []
    for sig in signatures:
        if not sig.get('visible', True):
            continue
        role = sig.get('role', '')
        user = _role_utilisateur(bon, role) if bon is not None else None
        user_name = ''
        fonction = sig.get('role', '')
        date = None
        signature_path = None
        if user is not None:
            user_name = user.get_full_name() or user.username
            profil = getattr(user, 'profil', None)
            if profil is not None and getattr(profil, 'fonction', None):
                fonction = profil.fonction
            valide_par = getattr(bon, 'valide_par', None)
            date = (getattr(bon, 'date_validation', None)
                    if user == valide_par
                    else getattr(bon, 'date_creation', None) or getattr(bon, 'date_demande', None))
            signature_path = _get_signature_url(request, user) if request is not None else None
        cases.append({
            'label': sig.get('label', ''),
            'sous_label': sig.get('role', ''),
            'role': role,
            'user_name': user_name,
            'fonction': fonction if user is not None else '',
            'date': date,
            'has_signature': user is not None and signature_path is not None,
            'signature_path': signature_path,
            'position': sig.get('position', 'left'),
            'style': sig.get('style', 'ligne_pointillee'),
            'default_text': '',
        })
    return cases


def build_signature_cases(bon, pdf_config, request):
    """
    Construit les cases de signature pour un bon de mouvement,
    à partir de la configuration du document (labels configurables).
    """
    return _build_cases_depuis_config(pdf_config, bon=bon, request=request)


def build_signatures_config(pdf_config, request):
    """
    Construit la configuration des signatures génériques (pour documents sans bon),
    à partir de la configuration du document.
    """
    return _build_cases_depuis_config(pdf_config, bon=None, request=request)


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
