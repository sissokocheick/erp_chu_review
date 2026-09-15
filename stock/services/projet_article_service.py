# -*- coding: utf-8 -*-
"""
Service de gestion et de filtrage des articles liés aux chantiers et projets.
Permet d'identifier les articles ayant fait l'objet d'entrées en stock pour un projet,
ou prévus dans ses proformas / devis fournisseurs.
"""
from typing import Set, Dict, List, Any


def get_articles_ids_pour_projet(projet_id: int, inclure_previsions: bool = True) -> Set[int]:
    """
    Retourne l'ensemble des IDs d'articles associés à un projet :
    1. Articles entrés en stock via un Bon d'Entrée rattaché au projet (hors bons annulés ou rejetés).
    2. Articles figurant dans les besoins / proformas actives du chantier (si inclure_previsions=True).
    """
    if not projet_id:
        return set()

    from stock.models import LigneBon
    from projets.models import ProjetBesoin, ProjetProformaLigne

    # 1. Articles issus des bons d'entrée validés ou en cours pour ce projet
    articles_ids = set(
        LigneBon.objects.filter(
            bon__projet_id=projet_id,
            bon__type_bon='ENTREE',
            bon__is_deleted=False,
            bon__est_annule=False
        ).exclude(
            bon__statut_validation__in=['REJETE', 'ANNULE']
        ).values_list('article_id', flat=True)
    )

    # 2. Articles prévus au devis / proforma ou besoins du chantier
    if inclure_previsions:
        besoins_ids = set(
            ProjetBesoin.objects.filter(
                projet_id=projet_id
            ).values_list('article_id', flat=True)
        )
        proformas_ids = set(
            ProjetProformaLigne.objects.filter(
                proforma__projet_id=projet_id,
                proforma__statut='ACTIF'
            ).values_list('article_id', flat=True)
        )
        articles_ids |= (besoins_ids | proformas_ids)

    return articles_ids


def get_map_articles_projets(projets_qs, inclure_previsions: bool = True) -> Dict[str, List[int]]:
    """
    Construit un dictionnaire optimisé en requêtes groupées :
    { "projet_id": [id_article1, id_article2, ...] } pour tous les projets spécifiés.
    Évite tout problème N+1 sur les interfaces de saisie.
    """
    if not projets_qs:
        return {}

    projets_ids = [p.id for p in projets_qs]
    mapping: Dict[str, Set[int]] = {str(pid): set() for pid in projets_ids}

    from stock.models import LigneBon
    from projets.models import ProjetBesoin, ProjetProformaLigne

    # 1. Bons d'entrée groupés
    lignes = LigneBon.objects.filter(
        bon__projet_id__in=projets_ids,
        bon__type_bon='ENTREE',
        bon__is_deleted=False,
        bon__est_annule=False
    ).exclude(
        bon__statut_validation__in=['REJETE', 'ANNULE']
    ).values_list('bon__projet_id', 'article_id')

    for pid, aid in lignes:
        if str(pid) in mapping:
            mapping[str(pid)].add(aid)

    # 2. Prévisions et proformas groupées
    if inclure_previsions:
        besoins = ProjetBesoin.objects.filter(
            projet_id__in=projets_ids
        ).values_list('projet_id', 'article_id')
        for pid, aid in besoins:
            if str(pid) in mapping:
                mapping[str(pid)].add(aid)

        proformas = ProjetProformaLigne.objects.filter(
            proforma__projet_id__in=projets_ids,
            proforma__statut='ACTIF'
        ).values_list('proforma__projet_id', 'article_id')
        for pid, aid in proformas:
            if str(pid) in mapping:
                mapping[str(pid)].add(aid)

    return {k: sorted(list(v)) for k, v in mapping.items()}


def article_appartient_au_projet(article_id: int, projet_id: int, inclure_previsions: bool = True) -> bool:
    """Vérifie si un article appartient aux matériels d'un projet."""
    if not article_id or not projet_id:
        return False
    return article_id in get_articles_ids_pour_projet(projet_id, inclure_previsions=inclure_previsions)
