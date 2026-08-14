from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from datetime import datetime, timedelta
import logging

from accounts.permissions import verifier_permission
from stock.pdf_utils import (
    get_pdf_config, render_pdf_response, render_pdf_to_bytes,
    paginate_lignes, build_signature_cases, build_signatures_config,
    servir_pdf_cache, sauver_pdf_cache,
)

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════════════════════
# MAPPING : type_bon (modèle) → type_document (ModeleDocumentMagasin)
# ═════════════════════════════════════════════════════════════════════════════
BON_TYPE_TO_DOC_CODE = {
    'ENTREE': 'BE',
    'SORTIE': 'BS',
    'RETOUR_SERVICE': 'BR',
    'RETOUR_FOURNISSEUR': 'BR',
    'SORTIE_HORS_STOCK': 'BSHS',
    'TRANSFERT': 'BS',
}


# ═════════════════════════════════════════════════════════════════════════════
# BON DE MOUVEMENT MULTI-TYPES (BE, BS, BR)
# ═════════════════════════════════════════════════════════════════════════════

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_sorties')
def imprimer_bon_multi_lignes(request, bon_id):
    """Génère le PDF d'un bon de mouvement (Entrée, Sortie, Retour)."""
    from stock.models import BonMouvement

    bon = get_object_or_404(
        BonMouvement.objects.prefetch_related('lignes_bon__article').select_related('magasin', 'magasin_destination', 'fournisseur', 'service_demandeur'),
        id=bon_id
    )

    type_doc_code = BON_TYPE_TO_DOC_CODE.get(bon.type_bon, 'BS')
    pdf_config, logo_url = get_pdf_config(bon.magasin, type_doc_code, request)

    # ── Cache : servir si déjà généré ──
    cache = servir_pdf_cache(bon, f"{bon.type_bon}_{bon.numero_bon}.pdf")
    if cache:
        return cache

    lignes_data = []
    for idx, ligne in enumerate(bon.lignes_bon.all(), start=1):
        article = ligne.article
        lignes_data.append({
            'idx': idx,
            'reference': getattr(article, 'reference', ''),
            'designation': getattr(article, 'designation', ''),
            'unite': getattr(article, 'unite_distribution', None) or getattr(article, 'unite', 'U') or 'U',
            'quantite': ligne.quantite,
            'quantite_servie': getattr(ligne, 'quantite_servie', None),
            'quantite_demandee': getattr(ligne, 'quantite_demandee', None),
            'quantite_recue': ligne.quantite,
            'reste': getattr(ligne, 'reste', None),
            'numero_lot': getattr(ligne, 'numero_lot', None),
            'date_peremption': getattr(ligne, 'date_peremption', None),
        })
    a_lots = any(l['numero_lot'] for l in lignes_data)

    pagination = paginate_lignes(lignes_data, pdf_config, lignes_par_page=18)
    pages = [{'lignes': page} for page in pagination.pages]

    service = bon.service_demandeur
    sondage_data = None
    if bon.sondage_satisfait is not None:
        sondage_data = {
            'satisfaction': 'satisfait' if bon.sondage_satisfait else 'insatisfait',
            'observations': bon.sondage_observation or '',
        }

    context = {
        'bon': bon,
        'magasin': bon.magasin,
        'lignes_data': lignes_data,
        'lignes_pages': pagination.pages,
        'pages': pages,
        'est_multi_page': pagination.est_multi_page,
        'est_reception_partielle': False,
        'est_livraison_partielle': False,
        'est_cloture': False,
        'numero_livraison': bon.numero_livraison,
        'commande': bon.commande_liee,
        'demande': bon.demande_origine,
        'service': service,
        'service_code': getattr(service, 'code', '') if service else '',
        'service_poste': getattr(service, 'poste', '') if service else '',
        'sondage_data': sondage_data,
        'pdf_config': pdf_config,
        'logo_url': logo_url,
        'signature_cases': build_signature_cases(bon, pdf_config, request),
        'a_lots': a_lots,
    }

    template_map = {
        'ENTREE': 'stock/pdf/bon_entree.html',
        'SORTIE': 'stock/pdf/bon_sortie.html',
        'RETOUR_SERVICE': 'stock/pdf/bon_retour.html',
        'RETOUR_FOURNISSEUR': 'stock/pdf/bon_retour.html',
        'TRANSFERT': 'stock/pdf/bon_transfert.html',
    }
    template = template_map.get(bon.type_bon, 'stock/pdf/bon_sortie.html')
    filename = f"{bon.type_bon}_{bon.numero_bon}.pdf"

    response = render_pdf_response(request, template, context, filename)
    if response.status_code == 200:
        try:
            pdf_bytes = render_pdf_to_bytes(request, template, context)
            sauver_pdf_cache(bon, filename, pdf_bytes)
        except Exception as e:
            logger.warning("[PDF] Cache échoué pour %s : %s", bon.numero_bon, e)
    return response


# ═════════════════════════════════════════════════════════════════════════════
# BON D'ENTRÉE (alias pour compatibilité)
# ═════════════════════════════════════════════════════════════════════════════

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_entrees')
def bon_entree_pdf(request, bon_id):
    """Alias : génère le PDF d'un bon d'entrée."""
    return imprimer_bon_multi_lignes(request, bon_id)


# ═════════════════════════════════════════════════════════════════════════════
# COMMANDE
# ═════════════════════════════════════════════════════════════════════════════

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_commandes')
def imprimer_commande(request, commande_id):
    """Génère le PDF d'une commande."""
    from stock.models import Commande

    commande = get_object_or_404(
        Commande.objects.prefetch_related('lignes_commande__article').select_related('fournisseur', 'magasin'),
        id=commande_id
    )
    pdf_config, logo_url = get_pdf_config(commande.magasin, 'BC', request)

    lignes_data = []
    for ligne in commande.lignes_commande.all():
        lignes_data.append({
            'article': ligne.article,
            'quantite_demandee': ligne.quantite_demandee,
            'quantite_recue': ligne.quantite_recue,
            'prix_unitaire': ligne.prix_unitaire,
            'unite': getattr(ligne.article, 'unite', 'U'),
        })

    pagination = paginate_lignes(lignes_data, pdf_config, lignes_par_page=18)

    context = {
        'commande': commande,
        'magasin': commande.magasin,
        'lignes_pages': pagination.pages,
        'est_multi_page': pagination.est_multi_page,
        'pdf_config': pdf_config,
        'logo_url': logo_url,
        'signature_cases': build_signatures_config(pdf_config, request),
    }
    return render_pdf_response(request, 'stock/pdf/bon_commande.html', context, f"CMD_{commande.numero_commande}.pdf")


# ═════════════════════════════════════════════════════════════════════════════
# BON DE DEMANDE
# ═════════════════════════════════════════════════════════════════════════════

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_demandes')
def imprimer_bon_demande(request, demande_id):
    """Génère le PDF d'un bon de demande."""
    from stock.models import DemandeMateriel

    demande = get_object_or_404(
        DemandeMateriel.objects.prefetch_related('lignes_demande__article').select_related('magasin_cible', 'service_demandeur'),
        id=demande_id
    )
    pdf_config, logo_url = get_pdf_config(demande.magasin_cible, 'BDM', request)

    lignes_data = []
    for ligne in demande.lignes_demande.all():
        lignes_data.append({
            'article': ligne.article,
            'quantite': ligne.quantite_demandee,
            'unite': getattr(ligne.article, 'unite', 'U'),
        })

    pagination = paginate_lignes(lignes_data, pdf_config, lignes_par_page=18)

    context = {
        'demande': demande,
        'magasin': demande.magasin_cible,
        'lignes_pages': pagination.pages,
        'est_multi_page': pagination.est_multi_page,
        'pdf_config': pdf_config,
        'logo_url': logo_url,
        'signature_cases': build_signatures_config(pdf_config, request),
    }
    return render_pdf_response(request, 'stock/pdf/bon_demande.html', context, f"BD_{demande.numero_demande}.pdf")


# ═════════════════════════════════════════════════════════════════════════════
# AJUSTEMENT
# ═════════════════════════════════════════════════════════════════════════════

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_ajustements')
def imprimer_ajustement(request, ajustement_id):
    """Génère le PDF d'un ajustement de stock."""
    from stock.models import Ajustement

    ajustement = get_object_or_404(
        Ajustement.objects.select_related('magasin', 'article'),
        id=ajustement_id
    )
    pdf_config, logo_url = get_pdf_config(ajustement.magasin, 'AJUSTEMENT', request)

    lignes_data = [{
        'article': ajustement.article,
        'stock_theorique': ajustement.quantite,
        'stock_reel': ajustement.quantite,
        'ecart': 0,
        'unite': getattr(ajustement.article, 'unite_distribution', 'U'),
    }]

    pagination = paginate_lignes(lignes_data, pdf_config, lignes_par_page=18)

    context = {
        'ajustement': ajustement,
        'magasin': ajustement.magasin,
        'lignes_pages': pagination.pages,
        'est_multi_page': pagination.est_multi_page,
        'pdf_config': pdf_config,
        'logo_url': logo_url,
        'signature_cases': build_signatures_config(pdf_config, request),
    }
    return render_pdf_response(request, 'stock/pdf/ajustement.html', context, f"AJ_{ajustement.numero_ajustement or ajustement.id}.pdf")


# ═════════════════════════════════════════════════════════════════════════════
# ÉTAT DU STOCK
# ═════════════════════════════════════════════════════════════════════════════

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_stock')
def imprimer_etat_stock(request):
    """Génère le PDF de l'état du stock."""
    from stock.models import Magasin, StockItem

    magasin_id = request.session.get('magasin_actif_id')
    magasin = get_object_or_404(Magasin, id=magasin_id) if magasin_id else None
    pdf_config, logo_url = get_pdf_config(magasin, 'ETAT_STOCK', request)

    stocks = StockItem.objects.select_related('article__famille', 'magasin').filter(
        magasin=magasin
    ).order_by('article__designation')
    stocks_data = [
        {'stock': s, 'quantite_physique': s.quantite_physique}
        for s in stocks
    ]

    context = {
        'stocks_data': stocks_data,
        'magasin': magasin,
        'pdf_config': pdf_config,
        'logo_url': logo_url,
        'date_generation': timezone.now(),
        'utilisateur': request.user,
        'signature_cases': build_signatures_config(pdf_config, request),
    }
    return render_pdf_response(request, 'stock/pdf/etat_stock.html', context, "Etat_Stock.pdf")


# ═════════════════════════════════════════════════════════════════════════════
# HISTORIQUE ARTICLE
# ═════════════════════════════════════════════════════════════════════════════

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_stock')
def imprimer_historique_article(request, article_id):
    """Génère le PDF de l'historique d'un article."""
    from stock.models import Article, Mouvement, Magasin

    article = get_object_or_404(Article, id=article_id)
    magasin_id = request.session.get('magasin_actif_id')
    magasin = get_object_or_404(Magasin, id=magasin_id) if magasin_id else None
    pdf_config, logo_url = get_pdf_config(magasin, 'HISTORIQUE', request)

    mouvements = Mouvement.objects.filter(
        article=article,
        magasin=magasin
    ).order_by('-date_mouvement')[:50]

    context = {
        'article': article,
        'mouvements': mouvements,
        'magasin': magasin,
        'pdf_config': pdf_config,
        'logo_url': logo_url,
        'utilisateur': request.user,
        'signature_cases': build_signatures_config(pdf_config, request),
    }
    return render_pdf_response(request, 'stock/pdf/historique_article.html', context, f"Hist_{article.reference}.pdf")


# ═════════════════════════════════════════════════════════════════════════════
# FICHE DE COMPTAGE INVENTAIRE
# ═════════════════════════════════════════════════════════════════════════════

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_inventaires')
def imprimer_fiche_comptage(request, campagne_id):
    """Génère la fiche de comptage d'une campagne d'inventaire."""
    from stock.models import CampagneInventaire

    campagne = get_object_or_404(
        CampagneInventaire.objects.prefetch_related('lignes_inventaire__article').select_related('magasin'),
        id=campagne_id
    )
    pdf_config, logo_url = get_pdf_config(campagne.magasin, 'INVENTAIRE', request)

    lignes_data = []
    for ligne in campagne.lignes_inventaire.all():
        lignes_data.append({
            'article': ligne.article,
            'stock_theorique': ligne.quantite_theorique,
            'unite': getattr(ligne.article, 'unite_distribution', 'U'),
        })

    pagination = paginate_lignes(lignes_data, pdf_config, lignes_par_page=20)

    context = {
        'campagne': campagne,
        'lignes_pages': pagination.pages,
        'est_multi_page': pagination.est_multi_page,
        'pdf_config': pdf_config,
        'logo_url': logo_url,
        'signature_cases': build_signatures_config(pdf_config, request),
    }
    return render_pdf_response(request, 'stock/pdf/fiche_comptage.html', context, f"FC_{campagne.id}.pdf")


# ═════════════════════════════════════════════════════════════════════════════
# RÉSULTAT INVENTAIRE
# ═════════════════════════════════════════════════════════════════════════════

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_inventaires')
def imprimer_resultat_inventaire(request, campagne_id):
    """Génère le PDF du résultat d'une campagne d'inventaire."""
    from stock.models import CampagneInventaire

    campagne = get_object_or_404(
        CampagneInventaire.objects.prefetch_related('lignes_inventaire__article').select_related('magasin'),
        id=campagne_id
    )
    pdf_config, logo_url = get_pdf_config(campagne.magasin, 'INVENTAIRE', request)

    lignes_data = []
    for ligne in campagne.lignes_inventaire.all():
        lignes_data.append({
            'article': ligne.article,
            'stock_theorique': ligne.quantite_theorique,
            'stock_reel': ligne.quantite_physique or 0,
            'ecart': ligne.ecart() or 0,
            'unite': getattr(ligne.article, 'unite_distribution', 'U'),
        })

    pagination = paginate_lignes(lignes_data, pdf_config, lignes_par_page=18)

    context = {
        'campagne': campagne,
        'lignes_pages': pagination.pages,
        'est_multi_page': pagination.est_multi_page,
        'pdf_config': pdf_config,
        'logo_url': logo_url,
        'signature_cases': build_signatures_config(pdf_config, request),
    }
    return render_pdf_response(request, 'stock/pdf/resultat_inventaire.html', context, f"RI_{campagne.id}.pdf")


# ═════════════════════════════════════════════════════════════════════════════
# RAPPORT CONSOMMATION
# ═════════════════════════════════════════════════════════════════════════════

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_rapports')
def rapport_consommation_pdf(request):
    """Génère le PDF du rapport de consommation."""
    from stock.models import Mouvement, Magasin

    magasin_id = request.session.get('magasin_actif_id')
    magasin = get_object_or_404(Magasin, id=magasin_id) if magasin_id else None
    pdf_config, logo_url = get_pdf_config(magasin, 'RAPPORT', request)

    date_debut = request.GET.get('date_debut')
    date_fin = request.GET.get('date_fin')
    if date_debut:
        date_debut = datetime.strptime(date_debut, '%Y-%m-%d').date()
    else:
        date_debut = timezone.now().date() - timedelta(days=30)
    if date_fin:
        date_fin = datetime.strptime(date_fin, '%Y-%m-%d').date()
    else:
        date_fin = timezone.now().date()

    mouvements = Mouvement.objects.filter(
        type_mouvement='SORTIE',
        date_mouvement__date__range=(date_debut, date_fin)
    ).select_related('article', 'magasin')

    if magasin:
        mouvements = mouvements.filter(magasin=magasin)

    consommation = {}
    for m in mouvements:
        ref = m.article.reference or m.article.designation
        if ref not in consommation:
            consommation[ref] = {
                'article': m.article,
                'total_sortie': 0,
                'unite': getattr(m.article, 'unite', 'U'),
            }
        consommation[ref]['total_sortie'] += abs(m.quantite)

    context = {
        'consommation': sorted(consommation.values(), key=lambda x: x['total_sortie'], reverse=True),
        'date_debut': date_debut,
        'date_fin': date_fin,
        'magasin': magasin,
        'pdf_config': pdf_config,
        'logo_url': logo_url,
        'signature_cases': build_signatures_config(pdf_config, request),
    }
    return render_pdf_response(request, 'stock/pdf/rapport_consommation.html', context, "Rapport_Consommation.pdf")


# ═════════════════════════════════════════════════════════════════════════════
# BON HORS STOCK
# ═════════════════════════════════════════════════════════════════════════════

@login_required(login_url='/auth/login/')
def imprimer_bon_hors_stock(request, bon_id):
    """Génère le PDF d'un bon de sortie hors stock."""
    from django.contrib import messages
    from stock.models import BonMouvement

    # ── Vérification permission (menu_hors_stock OU menu_sorties) ──
    if not request.user.has_perm('accounts.menu_hors_stock') and not request.user.has_perm('accounts.menu_sorties'):
        messages.error(
            request,
            "Accès refusé : Permission 'menu_hors_stock' ou 'menu_sorties' requise. "
            "Contactez l'administrateur pour l'ajouter à votre rôle."
        )
        return redirect('liste_bons_hors_stock')

    bon = get_object_or_404(
        BonMouvement.objects.prefetch_related('lignes_bon__article').select_related('magasin', 'service_demandeur'),
        id=bon_id, type_bon='SORTIE_HORS_STOCK'
    )
    pdf_config, logo_url = get_pdf_config(bon.magasin, 'BSHS', request)

    # Construire lignes_data pour le template
    lignes_data = []
    for ligne in bon.lignes_bon.all():
        lignes_data.append({
            'reference': getattr(ligne.article, 'reference', ''),
            'designation': ligne.article.designation,
            'unite': getattr(ligne.article, 'unite', 'U'),
            'quantite': ligne.quantite,
        })

    # Signatures pilotées par la configuration du document (labels/visibilité)
    signature_cases = build_signatures_config(pdf_config, request)

    # Service destination
    service = bon.service_demandeur
    service_poste = getattr(service, 'poste', '') if service else ''
    service_code = getattr(service, 'code', '') if service else ''

    context = {
        'bon': bon,
        'lignes_data': lignes_data,
        'pdf_config': pdf_config,
        'logo_url': logo_url,
        'signature_cases': signature_cases,
        'service': service,
        'service_poste': service_poste,
        'service_code': service_code,
        'fournisseur': None,
    }
    return render_pdf_response(request, 'stock/pdf/bon_hors_stock.html', context, f"BS_HS_{bon.numero_bon}.pdf")
