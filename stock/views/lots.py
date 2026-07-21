from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import JsonResponse

from .catalogue import get_magasins_autorises
from ..models import Article, StockItem


@login_required(login_url='/auth/login/')
def api_lots_disponibles(request, article_id, magasin_id):
    """
    Retourne les lots disponibles (StockItem) pour un article dans un magasin.
    Appel AJAX depuis le formulaire de sortie.
    """
    entreprise = request.entreprise
    magasins_autorises = get_magasins_autorises(request)
    if not magasins_autorises.filter(id=magasin_id).exists():
        return JsonResponse({'error': 'Magasin non autorisé'}, status=403)

    # CORRECTION : vérifier que l'article appartient à l'entreprise
    article = Article.objects.filter(
        id=article_id,
        entreprise=entreprise
    ).first()
    if not article:
        return JsonResponse({'error': 'Article non trouvé ou non autorisé'}, status=403)

    lots = StockItem.objects.filter(
        article_id=article_id,
        magasin_id=magasin_id,
        quantite_physique__gt=0
    ).exclude(
        Q(batch_number__isnull=True) | Q(batch_number='')
    ).order_by('expiry_date').values('batch_number', 'quantite_physique', 'expiry_date', 'valeur_cmup')

    return JsonResponse({
        'lots': list(lots),
        'gere_lots': article.famille.gere_lots_peremption if article.famille else False
    })
