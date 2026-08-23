# core/pdf_pagination.py
"""
Système de pagination PDF pour les bons de mouvement.

Logique améliorée :
  - Page unique (≤ 28 lignes) : page unique, bloc bas en bas
  - Multi-page :
      • Page 1 = 28 lignes max (en-tête complet)
      • Pages intermédiaires = 40 lignes max (juste header tableau)
      • Dernière page = reste des lignes + bloc bas (max 30 lignes)
  - Protection anti-page-vide : la dernière page a toujours ≥ 5 lignes
"""

import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any

logger = logging.getLogger(__name__)

# A4 = 210mm x 297mm
PAGE_HEIGHT_MM = 297.0
PAGE_MARGIN_MM = 10.0
PAGE_CONTENT_HEIGHT_MM = PAGE_HEIGHT_MM - (2 * PAGE_MARGIN_MM)  # 277mm

# ═══════════════════════════════════════════════════════════════════════════
# SEUILS DE LIGNES PAR PAGE (dérivés dynamiquement de HauteurElements)
# ═══════════════════════════════════════════════════════════════════════════

LIGNE_STD_MM = 6.0  # Référence pour le calcul dynamique

# ✅ CORRECTION P0 : constantes dérivées de HauteurElements (pas magiques)
LIGNES_PAGE_1 = 28  # Page 1 avec en-tête complet (fixe, validé empiriquement)
LIGNES_PAGE_INTERM = 40  # Pages intermédiaires (header tableau seul)
LIGNES_MIN_DERNIERE = 5  # Minimum de lignes sur la dernière page

# Capacité dernière page = (hauteur disponible - bloc bas) / ligne std
# h_fixe_inter = cartouche(18) + marge(1.5) + service(13) + marge(1.5) + header(10) = 44mm
# h_bloc_bas = 15 + 1.5 + 1.5 + 22 + 1.5 + 6 = 47.5mm
# espace dispo = 277 - 44 - 47.5 = 185.5mm
# lignes max = 185.5 / 6 = ~30

# Conversion
MM_TO_PT = 2.83465
PT_TO_MM = 1.0 / MM_TO_PT


class HauteurElements:
    """Hauteurs estimées en mm des éléments du document."""

    ENTETE_ETATIQUE_MM = 8.0
    CARTOUCHE_CENTRAL_MM = 18.0
    SERVICE_INFOS_MM = 13.0
    TABLEAU_HEADER_MM = 10.0
    LIGNE_STD_MM = 6.0
    LIGNE_LONGUE_MM = 8.0
    LIGNE_MAX_MM = 10.0
    SONDAGE_MM = 15.0
    TRAIT_MM = 1.5
    SIGNATURES_MM = 22.0
    PIED_DE_PAGE_MM = 6.0
    MARGE_MM = 1.5

    @classmethod
    def hauteur_bloc_bas_mm(cls) -> float:
        return cls.SONDAGE_MM + cls.MARGE_MM + cls.TRAIT_MM + cls.MARGE_MM + cls.SIGNATURES_MM + cls.MARGE_MM + cls.PIED_DE_PAGE_MM

    @classmethod
    def hauteur_fixe_haut_mm(cls, avec_entete: bool = True) -> float:
        h = cls.CARTOUCHE_CENTRAL_MM + cls.MARGE_MM + cls.SERVICE_INFOS_MM + cls.MARGE_MM + cls.TABLEAU_HEADER_MM
        if avec_entete:
            h += cls.ENTETE_ETATIQUE_MM + cls.MARGE_MM
        return h

    @classmethod
    def hauteur_ligne_mm(cls, designation: str) -> float:
        longueur = len(str(designation))
        if longueur > 75:
            return cls.LIGNE_MAX_MM
        elif longueur > 45:
            return cls.LIGNE_LONGUE_MM
        return cls.LIGNE_STD_MM

    @classmethod
    def capacite_derniere_page(cls) -> int:
        """✅ CORRECTION P0 : calcul dynamique de la capacité dernière page."""
        h_fixe = cls.hauteur_fixe_haut_mm(avec_entete=False)  # page intermédiaire
        h_bloc = cls.hauteur_bloc_bas_mm()
        espace = PAGE_CONTENT_HEIGHT_MM - h_fixe - h_bloc
        return int(espace / cls.LIGNE_STD_MM)


@dataclass
class PageContent:
    """Contenu d'une page."""
    numero: int
    lignes: List[Dict[str, Any]] = field(default_factory=list)
    est_derniere_page: bool = False
    espaceur_mm: float = 0.0
    espaceur_lignes: int = 0
    bloc_bas_rentre: bool = True


@dataclass
class PaginationResult:
    """Résultat de la pagination."""
    pages: List[PageContent]
    hauteur_bloc_bas_mm: float
    espaceur_mm: float
    total_lignes: int
    est_multi_page: bool


def _estimer_hauteur_lignes(lignes: List[Dict], debut: int = 0, fin: int = None) -> float:
    """Estime la hauteur totale d'un groupe de lignes en mm."""
    if fin is None:
        fin = len(lignes)
    return sum(HauteurElements.hauteur_ligne_mm(lignes[i].get('designation', '')) for i in range(debut, min(fin, len(lignes))))


def paginer_bon_sortie(lignes: List[Dict[str, Any]], config: Dict[str, Any]) -> PaginationResult:
    """
    Paginne les lignes avec une logique anti-page-vide.
    """
    total = len(lignes)

    avec_sondage = config.get('sondage', {}).get('afficher', False)
    avec_signatures = bool(config.get('signatures', []))
    avec_pied = bool(config.get('pied_de_page', {}).get('texte_personnalise')) or \
                config.get('pied_de_page', {}).get('afficher_numero_page', False) or \
                config.get('pied_de_page', {}).get('afficher_trait_couleur', False)
    avec_entete = config.get('cartouche', {}).get('afficher_republique', True) or \
                  config.get('cartouche', {}).get('afficher_devise', True)

    h_bloc_bas = HauteurElements.hauteur_bloc_bas_mm() if (avec_sondage or avec_signatures or avec_pied) else 0.0
    h_fixe = HauteurElements.hauteur_fixe_haut_mm(avec_entete=avec_entete)
    h_page = PAGE_CONTENT_HEIGHT_MM
    marge = HauteurElements.MARGE_MM

    # ✅ CORRECTION P0 : capacité dynamique
    capacite_derniere = HauteurElements.capacite_derniere_page()

    # CAS A : ≤ 28 lignes → page unique
    if total <= LIGNES_PAGE_1:
        h_lignes = _estimer_hauteur_lignes(lignes)
        h_totale = h_fixe + h_lignes + h_bloc_bas + marge
        espaceur = max(0.0, h_page - h_totale)
        # ✅ CORRECTION P0 : utiliser LIGNE_STD_MM au lieu de 5.0
        espaceur_lignes = int(espaceur / HauteurElements.LIGNE_STD_MM)
        logger.debug(f"[PDF] Page unique ({total} lignes), espaceur={espaceur:.1f}mm")
        return PaginationResult(
            pages=[PageContent(numero=1, lignes=lignes, est_derniere_page=True,
                               espaceur_mm=espaceur, espaceur_lignes=espaceur_lignes,
                               bloc_bas_rentre=True)],
            hauteur_bloc_bas_mm=h_bloc_bas,
            espaceur_mm=espaceur,
            total_lignes=total,
            est_multi_page=False,
        )

    # CAS B : > 28 lignes → multi-page
    pages: List[PageContent] = []

    lignes_p1 = lignes[:LIGNES_PAGE_1]
    pages.append(PageContent(numero=1, lignes=lignes_p1, est_derniere_page=False,
                             bloc_bas_rentre=False))

    reste = lignes[LIGNES_PAGE_1:]

    # ✅ Découpe en pages intermédiaires tant que le reste dépasse la
    # capacité d'une DERNIÈRE page (qui porte le bloc signatures/sondage).
    # NB : l'ancienne condition (`> capacite_derniere + LIGNES_MIN_DERNIERE`)
    # laissait passer 31-35 lignes (débordement du bloc bas) et, pour 36-40,
    # consommait tout dans une page intermédiaire → aucune page finale,
    # signatures perdues.
    while len(reste) > capacite_derniere:
        lignes_inter = reste[:LIGNES_PAGE_INTERM]
        reste = reste[LIGNES_PAGE_INTERM:]
        pages.append(PageContent(numero=len(pages)+1, lignes=lignes_inter,
                                 est_derniere_page=False, bloc_bas_rentre=False))

    # Le découpage peut avoir tout consommé (multiple exact de 40) : reprendre
    # la dernière page intermédiaire et la scinder pour garantir une vraie
    # page finale dans les limites de sa capacité.
    if not reste and pages:
        pool = pages.pop().lignes  # ≤ LIGNES_PAGE_INTERM lignes
        if len(pool) > capacite_derniere:
            k = max(LIGNES_MIN_DERNIERE, len(pool) - LIGNES_PAGE_INTERM)
            pages.append(PageContent(numero=len(pages)+1, lignes=pool[:-k],
                                     est_derniere_page=False, bloc_bas_rentre=False))
            reste = pool[-k:]
        else:
            reste = pool

    # Protection anti-page-vide
    if len(reste) < LIGNES_MIN_DERNIERE and len(pages) >= 1:
        nb_a_voler = LIGNES_MIN_DERNIERE - len(reste)
        derniere_page_source = pages[-1]
        min_requis_source = LIGNES_MIN_DERNIERE if len(pages) == 1 else LIGNES_PAGE_INTERM // 2
        if len(derniere_page_source.lignes) > nb_a_voler + min_requis_source:
            lignes_volees = derniere_page_source.lignes[-nb_a_voler:]
            derniere_page_source.lignes = derniere_page_source.lignes[:-nb_a_voler]
            reste = lignes_volees + reste
            logger.debug(f"[PDF] Vol de {nb_a_voler} lignes pour éviter page vide")
        else:
            # ✅ CORRECTION P0 : fusionner avec l'avant-dernière au lieu de warning
            logger.warning(f"[PDF] Fusion dernière page ({len(reste)} lignes) avec précédente")
            if len(pages) > 1:
                pages[-2].lignes.extend(reste)
                pages.pop()
                reste = []
            # Sinon on garde la page telle quelle (cas pathologique)

    if reste:  # Peut être vide si fusion ci-dessus
        pages.append(PageContent(numero=len(pages)+1, lignes=reste, est_derniere_page=True,
                                 bloc_bas_rentre=True))

    logger.debug(f"[PDF] Multi-page: {len(pages)} pages, dernière={len(reste)} lignes")
    return PaginationResult(
        pages=pages,
        hauteur_bloc_bas_mm=h_bloc_bas,
        espaceur_mm=0.0,
        total_lignes=total,
        est_multi_page=True,
    )


def pt_to_mm(pt: float) -> float:
    return pt * PT_TO_MM


def mm_to_pt(mm: float) -> float:
    return mm * MM_TO_PT
