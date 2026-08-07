"""
Service d'isolation par magasin - Centralisation des règles d'accès

Ce module garantit que tous les accès aux données sont filtrés selon les permissions
de l'utilisateur. Il doit être utilisé exclusivement dans toutes les vues du module stock.

Architecture :
- Utilisateur superuser → accès à TOUS les magasins
- Utilisateur standard → accès uniquement aux magasins autorisés dans son profil
- Utilisateur sans profil → accès AUCUN magasin (sécurité par défaut)
"""

import logging
from django.db.models import QuerySet
from ..models import Magasin

logger = logging.getLogger(__name__)


def get_magasins_autorises(request) -> QuerySet:
    """
    Retourne les magasins autorisés pour l'utilisateur courant.
    
    Règles métier :
    1. Superuser : accès à tous les magasins (Magasin.objects.all())
    2. Utilisateur avec profil : accès aux magasins liés via ManyToMany
    3. Utilisateur sans profil : accès vide (Magasin.objects.none())
    
    Args:
        request: Requête HTTP Django contenant l'utilisateur
        
    Returns:
        QuerySet[Magasin]: Ensemble des magasins autorisés (jamais None)
        
    Raises:
        Aucun exception levée - retourne toujours un QuerySet valide
        
    Exemple:
        >>> magasins = get_magasins_autorises(request)
        >>> articles = Article.objects.filter(magasin__in=magasins)
    """
    user = request.user
    
    # Cas 1 : Superuser a accès à tout
    if user.is_superuser:
        return Magasin.objects.all()
    
    # Cas 2 & 3 : Utilisateur standard
    try:
        profil = user.profil
        magasins = profil.magasins_autorises.all()
        
        # Logging pour audit (optionnel, niveau DEBUG)
        logger.debug(
            "Utilisateur %s (%s) autorisé sur %d magasins",
            user.username,
            user.id,
            magasins.count()
        )
        
        return magasins
    except Exception as e:
        # Cas 3 : Profil inexistant ou erreur → accès refusé par sécurité
        logger.warning(
            "Utilisateur %s (%s) sans profil valide - accès magasins refusé: %s",
            user.username,
            user.id,
            str(e)
        )
        return Magasin.objects.none()


def verifier_acces_magasin(request, magasin_id: int) -> bool:
    """
    Vérifie si l'utilisateur a accès à un magasin spécifique.
    
    Args:
        request: Requête HTTP Django
        magasin_id: ID du magasin à vérifier
        
    Returns:
        bool: True si l'utilisateur a accès, False sinon
        
    Exemple:
        >>> if not verifier_acces_magasin(request, magasin_id):
        ...     raise PermissionDenied("Accès refusé au magasin")
    """
    magasins_autorises = get_magasins_autorises(request)
    return magasins_autorises.filter(id=magasin_id).exists()


def filtrer_par_magasins(queryset: QuerySet, request, field_name: str = 'magasin') -> QuerySet:
    """
    Filtre un QuerySet pour ne retourner que les objets des magasins autorisés.
    
    Args:
        queryset: QuerySet à filtrer (doit avoir une relation vers Magasin)
        request: Requête HTTP Django
        field_name: Nom du champ de relation vers Magasin (défaut: 'magasin')
                   Pour les relations imbriquées, utiliser la notation Django :
                   ex: 'ligne_bon__magasin'
        
    Returns:
        QuerySet filtré
        
    Raises:
        ValueError: Si le field_name n'est pas valide pour le modèle
        
    Exemple:
        >>> bons = BonMouvement.objects.all()
        >>> bons_auto = filtrer_par_magasins(bons, request, field_name='magasin')
    """
    magasins = get_magasins_autorises(request)
    
    # Si aucun magasin autorisé, retourne un queryset vide du même type
    if not magasins.exists():
        return queryset.none()
    
    filtre_kwargs = {f'{field_name}__in': magasins}
    return queryset.filter(**filtre_kwargs)
