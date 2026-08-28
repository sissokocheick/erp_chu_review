from django.core.paginator import Paginator

def paginer(qs, request, per_page_key='per_page', default=15, max_all=500, page_key='page'):
    """
    Fonction centralisée pour la pagination.

    Garde-fous : per_page=0 (ZeroDivisionError), négatif (EmptyPage) ou
    énorme (DoS mémoire) étaient acceptés — on borne désormais la valeur.
    """
    per_page = request.GET.get(per_page_key, str(default))
    is_list = isinstance(qs, list)

    if per_page == 'all':
        count = len(qs) if is_list else qs.count()
        limite = min(count, max_all) if count > 0 else 1
    else:
        try:
            limite = int(per_page)
        except (ValueError, TypeError):
            limite = default
        # Borne stricte : au moins 1, au plus max_all
        limite = max(1, min(limite, max_all))

    page = request.GET.get(page_key)
    # Return the original string for 'all' (template checks per_page == 'all'),
    # otherwise return the sanitized int so template dropdown can match
    display = per_page if per_page == 'all' else limite
    return Paginator(qs, limite).get_page(page), display
