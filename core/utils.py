from django.core.paginator import Paginator

def paginer(qs, request, per_page_key='per_page', default=15, max_all=500, page_key='page'):
    """
    Fonction centralisée pour la pagination.
    """
    per_page = request.GET.get(per_page_key, str(default))
    is_list = isinstance(qs, list)
    
    if per_page == 'all':
        count = len(qs) if is_list else qs.count()
        limite = min(count, max_all) if count > 0 else 1
    else:
        try:
            limite = int(per_page)
        except ValueError:
            limite = default
            
    page = request.GET.get(page_key)
    return Paginator(qs, limite).get_page(page), per_page
