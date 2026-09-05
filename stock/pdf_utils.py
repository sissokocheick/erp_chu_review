import logging
from dataclasses import dataclass
from types import SimpleNamespace
from typing import List, Dict, Any, Optional

from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.http import HttpResponse
from django.template.loader import render_to_string
try:
    from weasyprint import HTML
except (ImportError, OSError):
    HTML = None

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas as reportlab_canvas
    from reportlab.lib.utils import simpleSplit
except ImportError:  # pragma: no cover - dépendance déclarée dans requirements
    A4 = None
    reportlab_canvas = None
    simpleSplit = None

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
# CONFIGURATION PDF
# ═════════════════════════════════════════════════════════════════════════════

# Métadonnées documentaires par défaut (l'ancien modèle ConfigDocument a été
# supprimé ; la personnalisation se fait désormais via ModeleDocumentMagasin).
_META_DOCUMENTS_DEFAUT = {
    'BS':   {'code_document': 'ENR-BSM/DAF-001',  'date_creation_doc': '10/06/2024', 'date_revision_doc': '19/05/2025', 'version_doc': '002', 'ps2_label': 'PS2 : GERER LES PRESTATIONS EXTERNES'},
    'BE':   {'code_document': 'ENR-BEM/DAF-001',  'date_creation_doc': '10/06/2024', 'date_revision_doc': '19/05/2025', 'version_doc': '001', 'ps2_label': 'PS2 : GERER LES APPROVISIONNEMENTS'},
    'BR':   {'code_document': 'ENR-BRM/DAF-001',  'date_creation_doc': '10/06/2024', 'date_revision_doc': '19/05/2025', 'version_doc': '001', 'ps2_label': 'PS2 : GERER LE STOCK'},
    'BSHS': {'code_document': 'ENR-BHSM/DAF-001', 'date_creation_doc': '10/06/2024', 'date_revision_doc': '19/05/2025', 'version_doc': '001', 'ps2_label': 'PS2 : GERER LES PRESTATIONS EXTERNES'},
    'BC':   {'code_document': 'ENR-BCM/DAF-001',  'date_creation_doc': '10/06/2024', 'date_revision_doc': '19/05/2025', 'version_doc': '001', 'ps2_label': 'PS2 : GERER LES APPROVISIONNEMENTS'},
    'BDM':  {'code_document': 'ENR-BDM/DAF-001',  'date_creation_doc': '10/06/2024', 'date_revision_doc': '19/05/2025', 'version_doc': '001', 'ps2_label': 'PS2 : GERER LES APPROVISIONNEMENTS'},
    'AJUSTEMENT': {'code_document': 'ENR-AJM/DAF-001', 'date_creation_doc': '10/06/2024', 'date_revision_doc': '19/05/2025', 'version_doc': '001', 'ps2_label': 'PS2 : GERER LE STOCK'},
    'ETAT_STOCK': {'code_document': 'ENR-ESM/DAF-001', 'date_creation_doc': '10/06/2024', 'date_revision_doc': '19/05/2025', 'version_doc': '001', 'ps2_label': 'PS2 : GERER LE STOCK'},
    'HISTORIQUE': {'code_document': 'ENR-HIM/DAF-001', 'date_creation_doc': '10/06/2024', 'date_revision_doc': '19/05/2025', 'version_doc': '001', 'ps2_label': 'PS2 : GERER LE STOCK'},
    'INVENTAIRE': {'code_document': 'ENR-IVM/DAF-001', 'date_creation_doc': '10/06/2024', 'date_revision_doc': '19/05/2025', 'version_doc': '001', 'ps2_label': 'PS2 : GERER LE STOCK'},
    'RAPPORT':    {'code_document': 'ENR-RPM/DAF-001', 'date_creation_doc': '10/06/2024', 'date_revision_doc': '19/05/2025', 'version_doc': '001', 'ps2_label': 'PS2 : GERER LE STOCK'},
}


def _config_document_flat(type_doc_code, magasin=None):
    """Retourne la config « plate » d'un type de document (ex-ConfigDocument).

    Les métadonnées (code ISO, version…) personnalisées vivent désormais dans
    ModeleDocumentMagasin : on les reprend si un modèle actif existe pour ce
    type ET ce magasin. Sinon on ne fournit que les drapeaux d'affichage et on
    laisse ModeleDocumentMagasin._default_config_structured appliquer ses
    codes ISO par type.

    ⚠️ Sans filtre magasin, le premier modèle actif du type (quel que soit son
    magasin) contaminerait la configuration par défaut de tous les autres
    magasins. Le filtre est donc obligatoire dès qu'un magasin est connu.
    """
    base = {
        'afficher_logo': True,
        'afficher_cachet': True,
        'afficher_signatures': True,
        'afficher_cc': True,
        'afficher_ifu': True,
        'afficher_rccm': True,
        'afficher_telephone': True,
        'pied_page_pdf': '',
    }
    try:
        from stock.models import ModeleDocumentMagasin
        qs = ModeleDocumentMagasin.objects.filter(
            type_document=type_doc_code, est_actif=True)
        if magasin is not None:
            qs = qs.filter(magasin=magasin)
        modele = qs.first()
        if modele and modele.config:
            cfg = modele.config or {}
            metas = cfg.get('metadonnees')
            if isinstance(metas, dict):
                base.update(metas)
    except Exception:
        pass
    return base


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
            ModeleDocumentMagasin._freeze_dict(
                _config_document_flat(type_doc_code, magasin)),
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
        try:
            from core.models import ConfigurationHopital
            hopital_config = ConfigurationHopital.get_instance()
            if hopital_config.logo:
                logo_url = _make_absolute_url(request, hopital_config.logo.url)
        except Exception as e:
            logger.warning("[PDF] Erreur lecture logo global hopital: %s", e)

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

    from core.models import ConfigurationHopital
    hopital = ConfigurationHopital.objects.first()

    if hopital:
        pdf_config['couleur_principale'] = hopital.couleur_principale or '#1c5b96'
    else:
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

    # Parametres unifies globaux
    pdf_config['afficher_logo'] = getattr(hopital, 'afficher_logo', True) if hopital else True
    pdf_config['afficher_cachet'] = getattr(hopital, 'afficher_cachet', True) if hopital else True
    pdf_config['afficher_cc'] = getattr(hopital, 'afficher_cc', True) if hopital else True
    pdf_config['afficher_ifu'] = getattr(hopital, 'afficher_ifu', True) if hopital else True
    pdf_config['afficher_rccm'] = getattr(hopital, 'afficher_rccm', True) if hopital else True
    pdf_config['afficher_telephone'] = getattr(hopital, 'afficher_telephone', True) if hopital else True
    pdf_config['afficher_republique'] = getattr(hopital, 'afficher_republique', True) if hopital else True
    pdf_config['afficher_devise'] = getattr(hopital, 'afficher_devise', True) if hopital else True
    pdf_config['afficher_direction'] = getattr(hopital, 'afficher_direction', True) if hopital else True
    pdf_config['afficher_sous_direction'] = getattr(hopital, 'afficher_sous_direction', True) if hopital else True
    pdf_config['afficher_service'] = getattr(hopital, 'afficher_service', True) if hopital else True
    pdf_config['direction_label'] = getattr(hopital, 'direction_label', '') if hopital else ''
    pdf_config['sous_direction_label'] = getattr(hopital, 'sous_direction_label', '') if hopital else ''
    pdf_config['service_label'] = getattr(hopital, 'service_label', '') if hopital else ''
    
    # La signature reste parametrable par bon/document
    pdf_config['afficher_signatures'] = pdf_config.get('afficher_signatures', True)

    # Pied de page unifie globalement
    pdf_config['pied_de_page'] = {
        'texte_personnalise': getattr(hopital, 'pied_page_pdf', _pied_de_page_par_defaut()) if hopital else _pied_de_page_par_defaut(),
        'afficher_numero_page': True,
        'afficher_date_generation': True,
        'afficher_trait_couleur': True,
        'trait_couleur': pdf_config.get('couleur_principale', '#17a2b8'),
    }

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

def _texte_html(html_string):
    """Extrait un texte lisible du HTML pour le moteur PDF de secours."""
    from html import unescape
    import re

    texte = re.sub(
        r'<(script|style)[^>]*>.*?</\\1>',
        ' ',
        html_string,
        flags=re.S | re.I,
    )
    texte = re.sub(r'<[^>]+>', ' ', texte)
    texte = unescape(texte)
    return [ligne.strip() for ligne in texte.splitlines() if ligne.strip()]


def _lignes_fallback(context, html_string):
    """Construit des lignes PDF stables à partir du contexte métier.

    Le fallback ne cherche pas à reproduire la mise en page WeasyPrint ; il
    garantit un PDF lisible et exploitable lorsque les bibliothèques GTK de
    WeasyPrint ne sont pas disponibles (notamment sur Windows).
    """
    pages = context.get('pages') if isinstance(context, dict) else None
    if pages:
        resultat = []
        for numero, page in enumerate(pages, start=1):
            lignes_page = [f"Page {numero}"]
            lignes = page.get('lignes') or []
            for ligne in lignes:
                if isinstance(ligne, dict):
                    ref = ligne.get('reference') or ligne.get('article__reference') or ''
                    designation = ligne.get('designation') or ''
                    article = ligne.get('article')
                    if not designation and article is not None:
                        designation = getattr(article, 'designation', '')
                    qte = (ligne.get('quantite') or ligne.get('quantite_recue')
                           or ligne.get('quantite_demandee') or '')
                    lignes_page.append(f"{ref}  {designation}  {qte}".strip())
            if page.get('est_derniere_page'):
                lignes_page.extend(['DEMANDEUR', 'SIGNATURES'])
            resultat.append({
                'lignes': lignes_page,
                'hauteur_ligne': page.get('hauteur_ligne'),
            })
        return resultat

    lignes = _texte_html(html_string)
    return [{'lignes': lignes or ['Document PDF sans données'], 'hauteur_ligne': None}]


def _pdf_fallback(context, html_string):
    """Génère un PDF minimal avec ReportLab si WeasyPrint est indisponible."""
    if reportlab_canvas is None or A4 is None:
        raise RuntimeError(
            "Aucun moteur PDF disponible : installez WeasyPrint ou ReportLab."
        )

    from io import BytesIO

    buffer = BytesIO()
    pdf = reportlab_canvas.Canvas(buffer, pagesize=A4)
    largeur, hauteur = A4
    pages = _lignes_fallback(context, html_string)
    total_pages = len(pages)
    mm_to_pt = 72.0 / 25.4

    for page_num, page_data in enumerate(pages, start=1):
        page_lignes = page_data.get('lignes') or []
        hauteur_ligne = page_data.get('hauteur_ligne')
        try:
            hauteur_ligne_pt = float(hauteur_ligne) * mm_to_pt
        except (TypeError, ValueError):
            hauteur_ligne_pt = 14.0
        hauteur_ligne_pt = max(14.0, hauteur_ligne_pt)

        # Réserver la zone d'en-tête et du bloc de signatures comme le rendu
        # HTML. Cela permet au fallback de conserver l'étirement des lignes
        # calculé par ajouter_hauteurs_lignes et d'éviter un tableau tassé en
        # haut de page.
        reserve_pt = 0.0
        if hauteur_ligne is not None:
            if page_num == 1:
                reserve_pt = 72.0 / 25.4 * 72.0
            else:
                reserve_pt = 13.0 / 25.4 * 72.0
        y = hauteur - 36.0 - reserve_pt

        title = page_lignes[0] if page_lignes and page_lignes[0].startswith('Page ') else None
        if title:
            pdf.setFont('Helvetica-Bold', 9)
            pdf.drawString(36, min(hauteur - 24, y + 20), title)
            lignes_a_rendre = page_lignes[1:]
        else:
            lignes_a_rendre = page_lignes

        for texte in lignes_a_rendre:
            morceaux = (simpleSplit(str(texte), 'Helvetica', 9, largeur - 72)
                        if simpleSplit else [str(texte)])
            morceaux = morceaux or ['']
            pdf.setFont('Helvetica', 9)
            for index, morceau in enumerate(morceaux):
                # Une désignation longue peut occuper plusieurs lignes, sans
                # modifier la hauteur réservée à la ligne du tableau.
                pdf.drawString(36, y - (index * 10), morceau[:180])
            y -= max(hauteur_ligne_pt, len(morceaux) * 10)

        pdf.setFont('Helvetica', 8)
        pdf.drawRightString(largeur - 36, 20, f"{page_num} / {total_pages}")
        pdf.showPage()

    pdf.save()
    return buffer.getvalue()


def _marquer_template(response, template):
    """Conserve l'information de template pour les tests et outils Django."""
    response.templates = [SimpleNamespace(name=template)]
    return response

def _weasyprint_disponible():
    """Vérifie si WeasyPrint est correctement installé et importable."""
    return HTML is not None


def render_pdf_response(request, template, context, filename, inline=True):
    """
    Rend un template HTML en PDF et retourne une HttpResponse.
    Si WeasyPrint n'est pas disponible, retourne le HTML brut avec
    un message d'avertissement (fallback gracieux).
    """
    html_string = render_to_string(template, context, request=request)
    base_url = request.build_absolute_uri('/')

    if not _weasyprint_disponible():
        logger.warning(
            "[PDF] WeasyPrint indisponible — génération ReportLab de secours pour %s", template)
        pdf_bytes = _pdf_fallback(context, html_string)
        response = HttpResponse(pdf_bytes, content_type='application/pdf')
        disposition = 'inline' if inline else 'attachment'
        response['Content-Disposition'] = f'{disposition}; filename="{filename}"'
        response['X-PDF-Engine'] = 'reportlab-fallback'
        return _marquer_template(response, template)

    try:
        pdf_bytes = HTML(string=html_string, base_url=base_url).write_pdf()
    except Exception as e:
        logger.exception("[PDF] Erreur génération %s : %s", template, e)
        return HttpResponse(
            f"<html><body><h2>Erreur de génération PDF</h2>"
            f"<p>Template : {template}</p>"
            f"<p>Erreur : {e}</p></body></html>",
            content_type='text/html; charset=utf-8',
            status=500,
        )

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    disposition = 'inline' if inline else 'attachment'
    response['Content-Disposition'] = f'{disposition}; filename="{filename}"'
    return _marquer_template(response, template)


def render_pdf_to_bytes(request, template, context):
    """Génère un PDF et retourne les bytes (pour sauvegarde en cache).
    Retourne None si WeasyPrint n'est pas disponible."""
    html_string = render_to_string(template, context, request=request)
    base_url = request.build_absolute_uri('/')
    if not _weasyprint_disponible():
        logger.warning(
            "[PDF] WeasyPrint indisponible — génération ReportLab de secours (%s)", template)
        return _pdf_fallback(context, html_string)
    return HTML(string=html_string, base_url=base_url).write_pdf()


# ═════════════════════════════════════════════════════════════════════════════
# PAGINATION DES LIGNES (multi-pages)
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class PaginationResult:
    pages: List[List[Dict]]
    est_multi_page: bool


def paginate_lignes(lignes_data: List[Dict], pdf_config: Dict, lignes_par_page: int = 18, type_doc: str = '') -> PaginationResult:
    """
    Découpe les lignes en pages pour les documents multi-pages.

    La pagination est consciente des hauteurs : une page unique doit contenir
    l'entête complète + les lignes + le bloc-bas (sondage + signatures) dans la
    hauteur utile. Si ça ne rentre pas, le document passe en multi-pages avec
    une dernière page qui porte le bloc-bas.
    """
    if not lignes_data:
        return PaginationResult(pages=[[]], est_multi_page=False)

    n = len(lignes_data)
    # Hauteur réelle minimale d'une ligne (le contenu ne se compresse pas en dessous).
    entete_p1 = ENTETE_P1_MM.get(type_doc or '', ENTETE_P1_MM['default']) + THEAD_MM
    bloc = hauteur_bloc_bas_mm(pdf_config)

    # Capacité d'une page unique : entête complète + bloc-bas + lignes.
    mono_cap = max(1, int((HAUTEUR_UTILE_MM - entete_p1 - bloc) / HAUTEUR_LIGNE_REAL_MIN_MM))
    if n <= mono_cap:
        return PaginationResult(pages=[lignes_data], est_multi_page=False)

    # Multi-pages : la première page (entête, sans bloc) et les pages
    # intermédiaires peuvent porter plus de lignes que la dernière (bloc-bas).
    cap_p1 = max(1, int((HAUTEUR_UTILE_MM - entete_p1) / HAUTEUR_LIGNE_REAL_MIN_MM))
    cap_mid = max(1, int((HAUTEUR_UTILE_MM - ENTETE_PAGE_SUIVANTE_MM) / HAUTEUR_LIGNE_REAL_MIN_MM))
    cap_last = max(1, int((HAUTEUR_UTILE_MM - ENTETE_PAGE_SUIVANTE_MM - bloc) / HAUTEUR_LIGNE_REAL_MIN_MM))

    pages = []
    remaining = n
    # Première page : entête complète, sans bloc-bas (qui va en dernière page).
    # On laisse au moins 1 ligne à la dernière page pour qu'elle porte le bloc-bas.
    take = min(cap_p1, max(1, remaining - 1))
    pages.append(lignes_data[:take])
    remaining -= take
    # Pages intermédiaires : on en remplit le plus possible (cap_mid) tout en
    # laissant au moins 1 ligne à la dernière page (qui porte le bloc-bas).
    while remaining > cap_last:
        take = min(cap_mid, remaining - 1)
        pages.append(lignes_data[len(lignes_data) - remaining:len(lignes_data) - remaining + take])
        remaining -= take
    # Dernière page (avec bloc-bas : sondage + signatures).
    if remaining > 0:
        pages.append(lignes_data[len(lignes_data) - remaining:])

    return PaginationResult(pages=pages, est_multi_page=len(pages) > 1)


# ── Hauteurs de ligne pour remplir la page ──────────────────────────────────
# WeasyPrint n'étire pas un tableau : seule une hauteur explicite sur les <tr>
# permet d'étaler les lignes pour que le contenu atteigne le bas de la page.
# Les réserves d'entête sont volontairement conservatives (légèrement au-dessus
# de la réalité mesurée) : on préfère un petit espace résiduel en bas de page à
# un débordement sur la page suivante, qui casserait la pagination manuelle.

HAUTEUR_UTILE_MM = 279.0  # A4 297mm - 6mm haut - 12mm bas

# Entête de la page 1 (sans le thead, ajouté ensuite) en mm, par type de document.
ENTETE_P1_MM = {
    'default': 63.0,
    'SORTIE': 63.0,
    'ENTREE': 61.0,
    'RETOUR_SERVICE': 63.0,
    'RETOUR_FOURNISSEUR': 63.0,
    'TRANSFERT': 73.0,
    'DEMANDE': 68.0,
    'COMMANDE': 81.0,
    'SORTIE_HORS_STOCK': 64.0,
}

THEAD_MM = 11.0            # hauteur du thead (répété sur chaque page)
ENTETE_PAGE_SUIVANTE_MM = 13.0   # thead seul + marge de sécurité
BLOC_BAS_SANS_SONDAGE_MM = 58.0  # signatures (2 lignes × 26mm) + marge
BLOC_BAS_AVEC_SONDAGE_MM = 80.0  # sondage (~20mm) + signatures (2×26mm) + marge

HAUTEUR_LIGNE_MIN_MM = 8.0
HAUTEUR_LIGNE_MAX_MM = 18.0
# Hauteur réelle minimale d'une ligne avec du contenu réel (désignations sur
# une ou deux lignes, lots, etc.) — mesurée sur des PDF générés (~11.4mm).
# Sert au calcul de capacité des pages (la pagination ne doit jamais promettre
# plus de lignes que ce qui rentre réellement avec l'entête + le bloc-bas).
HAUTEUR_LIGNE_REAL_MIN_MM = 11.5


def hauteur_bloc_bas_mm(pdf_config) -> float:
    """Hauteur estimée du bloc-bas (sondage + signatures) selon la configuration.

    pdf_config est un dict : le sondage s'y trouve sous pdf_config['sondage']['afficher'].
    """
    sondage = (pdf_config or {}).get('sondage', {}).get('afficher', False)
    return BLOC_BAS_AVEC_SONDAGE_MM if sondage else BLOC_BAS_SANS_SONDAGE_MM


def ajouter_hauteurs_lignes(pages, pdf_config, type_doc='', bloc_bas=True):
    """Attache à chaque page une `hauteur_ligne` (mm) pour que le tableau
    remplisse la page jusqu'en bas (étirement des lignes par WeasyPrint).

    pages : liste de dicts {lignes, est_derniere_page, ...} (mutée en place).
    """
    nb_pages = len(pages)
    entete_p1 = ENTETE_P1_MM.get(type_doc or '', ENTETE_P1_MM['default']) + THEAD_MM
    bloc = hauteur_bloc_bas_mm(pdf_config) if bloc_bas else 0.0

    for i, page in enumerate(pages):
        n = len(page.get('lignes') or [])
        if n == 0:
            page['hauteur_ligne'] = '0.00'
            continue
        if nb_pages == 1:
            # Page unique : entête complète + tableau + bloc-bas (sondage + signatures).
            reserve = entete_p1 + bloc
        elif i == 0:
            reserve = entete_p1
        elif i == nb_pages - 1:
            reserve = ENTETE_PAGE_SUIVANTE_MM + bloc
        else:
            reserve = ENTETE_PAGE_SUIVANTE_MM
        hauteur = (HAUTEUR_UTILE_MM - reserve) / n
        # Chaîne avec point décimal : la locale française (virgule) invaliderait le CSS.
        page['hauteur_ligne'] = f"{min(max(hauteur, HAUTEUR_LIGNE_MIN_MM), HAUTEUR_LIGNE_MAX_MM):.2f}"
    return pages


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
    
    if role == 'demandeur':
        return demandeur or (cree_par if hasattr(doc, 'service_demandeur') else None)
    if role == 'magasinier':
        return cree_par
    if role in ('responsable', 'sous_directeur', 'chef_service'):
        # Si valide_par existe, on l'utilise (c'est le validateur)
        # Sinon, fallback sur le responsable du magasin (info affichee meme sans validation)
        if valide_par:
            return valide_par
        magasin = getattr(doc, 'magasin', None)
        if magasin:
            return getattr(magasin, 'responsable', None)
        return None
    if role == 'receptionnaire':
        # currently no reception tracking on BonMouvement, so we leave it empty for manual signing
        return getattr(doc, 'receptionnaire', None)
        
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
        fonction = sig.get('role', '').replace('_', ' ').capitalize()
        date = None
        signature_path = None
        if user is not None:
            user_name = user.get_full_name() or user.username
            profil = getattr(user, 'profil', None)
            if profil is not None and getattr(profil, 'fonction', None):
                fonction = profil.fonction
            elif fonction:
                # Format internal codes like 'sous_directeur' to 'Sous-directeur'
                fonction = fonction.replace('_', ' ').capitalize()
            # Pour le role responsable : utiliser le titre_responsable du magasin
            # (surtout si c'est le fallback magasin et non le validateur)
            if role in ('responsable', 'sous_directeur', 'chef_service') and bon is not None:
                magasin = getattr(bon, 'magasin', None)
                titre_resp = getattr(magasin, 'titre_responsable', None) if magasin else None
                if titre_resp:
                    fonction = titre_resp
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
    if not pdf_bytes:
        logger.debug("[PDF] Sauvegarde cache ignorée (pdf_bytes est None) pour %s", filename)
        return
    try:
        if bon.fichier_pdf and bon.fichier_pdf.name and default_storage.exists(bon.fichier_pdf.name):
            default_storage.delete(bon.fichier_pdf.name)
        bon.fichier_pdf.save(filename, ContentFile(pdf_bytes), save=True)
    except Exception as e:
        logger.warning("[PDF] Sauvegarde cache échouée : %s", e)

