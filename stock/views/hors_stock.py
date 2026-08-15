import os
import logging
from datetime import datetime
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone

from accounts.permissions import verifier_permission
from core.models import ConfigurationHopital
from stock.services.isolation_service import get_magasins_autorises
from ..decorators import magasin_requis, catch_errors
from ..pdf_utils import get_pdf_config, paginate_lignes, ajouter_hauteurs_lignes, build_signature_cases
from ..models import (
    BonMouvement, LigneBon, MotifAnnulation,
    Article, Magasin, Service,
    Fournisseur, Beneficiaire)
from ..services import NumeroGenerator, PDFService, NotificationService
from ..services.bon_service import BonService
from .catalogue import paginer
from .common import _has_perm_bon
from .common_views import render_liste, get_magasin_actif, build_redirect_url

logger = logging.getLogger(__name__)

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_sorties_hors_stock')
@magasin_requis
@catch_errors(redirect_url='liste_bons_hors_stock')
def liste_bons_hors_stock(request):
    """Dispatcher : GET affiche, POST crée."""
    if request.method == 'POST':
        return _creer_bon_hors_stock(request)
    return _afficher_bons_hors_stock(request)

def _afficher_bons_hors_stock(request):
    """Branche GET : filtres, pagination, contexte."""
    magasins_autorises = get_magasins_autorises(request)

    onglet = request.GET.get('onglet', 'actifs')
    bons_base = BonMouvement.objects.filter(
        type_bon='SORTIE_HORS_STOCK', magasin__in=magasins_autorises
    ).select_related(
        'magasin', 'fournisseur', 'service_demandeur', 'destinataire', 'cree_par'
    ).prefetch_related(
        'lignes_bon__article'
    ).order_by('-date_bon')

    # Le magasin sélectionné dans l'en-tête s'applique partout :
    # la liste ne montre que le magasin actif de la session.
    magasin_actif = get_magasin_actif(request)
    if magasin_actif:
        bons_base = bons_base.filter(magasin=magasin_actif)

    if onglet == 'historique':
        qs = bons_base.filter(est_annule=True)
    else:
        qs = bons_base.filter(est_annule=False)

    counts = {
        'actifs': bons_base.filter(est_annule=False).count(),
        'historique': bons_base.filter(est_annule=True).count(),
    }

    # ── FILTRES ──
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(numero_bon__icontains=q) |
            Q(fournisseur__raison_sociale__icontains=q) |
            Q(service_demandeur__nom__icontains=q) |
            Q(destinataire__nom_complet__icontains=q)
        ).distinct()

    date_range = request.GET.get('date_range', '').strip()
    if date_range:
        try:
            parts = date_range.split(' - ')
            if len(parts) == 2:
                d1 = datetime.strptime(parts[0].strip(), '%d/%m/%Y')
                d2 = datetime.strptime(parts[1].strip(), '%d/%m/%Y')
                qs = qs.filter(date_bon__date__gte=d1, date_bon__date__lte=d2)
        except Exception:
            pass

    per_page = request.GET.get('per_page', '15')
    bons, _ = paginer(qs, request, per_page_key='per_page', default=15)

    context = {
        'bons': bons,
        'counts': counts,
        'onglet': onglet,
        'q_bon': q,
        'date_range': date_range,
        'per_page': per_page,
        'magasins': magasins_autorises.order_by('nom'),
        'magasin_actif': magasin_actif,
        'fournisseurs': Fournisseur.objects.filter(est_agree=True),
        'services': Service.objects.all(),
        'articles': Article.objects.all().order_by('designation'),
        'beneficiaires': Beneficiaire.objects.all().order_by('nom_complet'),
        'motifs_annulation': MotifAnnulation.objects.filter(actif=True),
        'peut_creer': _has_perm_bon(request.user, 'add', 'SORTIE_HORS_STOCK'),
        'peut_annuler': _has_perm_bon(request.user, 'change', 'SORTIE_HORS_STOCK'),
    }
    return render(request, 'stock/liste_bons_hors_stock.html', context)

def _creer_bon_hors_stock(request):
    """Branche POST : validation, création via service, redirection."""
    action = request.POST.get('action')
    if action == 'creer_beneficiaire':
        nom = request.POST.get('nom_complet', '').strip()
        poste = request.POST.get('poste', '').strip()
        service_id = request.POST.get('service')
        if nom:
            b = Beneficiaire.objects.create(
                nom_complet=nom, poste=poste,
                service_id=service_id if service_id else None
            )
            if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                return JsonResponse({
                    'success': True,
                    'id': b.id,
                    'nom': b.nom_complet,
                    'poste': b.poste,
                    'service_id': b.service_id
                })
        return JsonResponse({'success': False})

    # ── VALIDATION DES CHAMPS OBLIGATOIRES ──
    magasin_id = request.POST.get('magasin')
    if not magasin_id or not magasin_id.strip().isdigit():
        messages.error(request, "❌ Aucun magasin valide assigné à votre profil.")
        return redirect('liste_bons_hors_stock')

    magasins_autorises = get_magasins_autorises(request)
    if not magasins_autorises.filter(id=int(magasin_id)).exists():
        messages.error(request, "⛔ Vous n'avez pas accès à ce magasin.")
        return redirect('liste_bons_hors_stock')
    magasin = get_object_or_404(Magasin, id=int(magasin_id))

    fournisseur_id = request.POST.get('fournisseur')
    fournisseur = None
    if fournisseur_id and fournisseur_id.strip().isdigit():
        fournisseur = get_object_or_404(Fournisseur, id=int(fournisseur_id))

    service_id = request.POST.get('service_demandeur')
    service_demandeur = None
    if service_id and service_id.strip().isdigit():
        service_demandeur = get_object_or_404(Service, id=int(service_id))

    destinataire_id = request.POST.get('destinataire')
    destinataire = None
    if destinataire_id and destinataire_id.strip().isdigit():
        destinataire = get_object_or_404(Beneficiaire, id=int(destinataire_id))

    ref_externe = request.POST.get('reference_externe', '').strip()
    commentaire = request.POST.get('commentaire', '').strip()
    article_ids = request.POST.getlist('articles[]')
    quantites = request.POST.getlist('quantites[]')

    if not article_ids:
        messages.error(request, "❌ Le bon ne peut pas être vide.")
        return redirect('liste_bons_hors_stock')

    # Validation des articles (mono-tenant)
    articles_valides = set(
        Article.objects.filter(
            id__in=[aid for aid in article_ids if aid and aid.strip().isdigit()]
        ).values_list('id', flat=True)
    )

    # Conversion IDs → objets avec validation stricte
    lignes = []
    for aid, qte_dem in zip(article_ids, quantites):
        if aid and aid.strip().isdigit() and qte_dem and qte_dem.strip().isdigit():
            aid_int = int(aid.strip())
            if aid_int not in articles_valides:
                messages.error(
                    request,
                    "⛔ Un ou plusieurs articles sélectionnés ne sont pas valides."
                )
                return redirect('liste_bons_hors_stock')
            lignes.append({'article_id': aid_int, 'quantite': int(qte_dem.strip())})

    if not lignes:
        messages.error(request, "❌ Aucun article valide sélectionné.")
        return redirect('liste_bons_hors_stock')

    try:
        bon = BonService.creer_bon_hors_stock(
            lignes=lignes,
            utilisateur=request.user,
            magasin=magasin,
            fournisseur=fournisseur,
            service_demandeur=service_demandeur,
            destinataire=destinataire,
            reference_externe=ref_externe,
            commentaire=commentaire)
    except IntegrityError as e:
        logger.exception("[BSHS] IntegrityError création bon : %s", e)
        messages.error(request, "⛔ Erreur lors de la création du bon. Vérifiez la console pour le détail.")
        return redirect('liste_bons_hors_stock')

    messages.success(request, f"✅ Bon {bon.numero_bon} enregistré.")
    return redirect(f"{reverse('liste_bons_hors_stock')}?print_bon={bon.id}")

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_sorties_hors_stock')
@magasin_requis
@catch_errors(redirect_url='liste_bons_hors_stock')
def annuler_bon_hors_stock(request, bon_id):
    if request.method != 'POST':
        return redirect('liste_bons_hors_stock')

    magasins_autorises = get_magasins_autorises(request)
    bon = get_object_or_404(
        BonMouvement, id=bon_id, type_bon='SORTIE_HORS_STOCK',
        magasin__in=magasins_autorises
    )

    motif_id = request.POST.get('motif_id')
    if not motif_id:
        messages.error(request, "❌ Veuillez sélectionner un motif d'annulation.")
        return redirect('liste_bons_hors_stock')

    motif = get_object_or_404(MotifAnnulation, id=motif_id)

    try:
        BonService.annuler_bon_hors_stock(bon, motif, request.user)
    except ValueError as e:
        logger.exception("[BSHS] %s", e)
        messages.error(request, "⛔ Erreur lors de la création du bon. Veuillez réessayer.")
        return redirect('liste_bons_hors_stock')

    messages.success(request, f"✅ Bon {bon.numero_bon} annulé.")
    return redirect('liste_bons_hors_stock')

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_sorties_hors_stock')
@magasin_requis
@catch_errors(redirect_url='liste_bons_hors_stock')
def apercu_bon_hors_stock(request, bon_id):
    bon = get_object_or_404(
        BonMouvement.objects.filter(
            type_bon='SORTIE_HORS_STOCK').prefetch_related(
            'lignes_bon__article__famille'
        ).select_related(
            'magasin', 'fournisseur', 'service_demandeur',
            'cree_par', 'destinataire'
        ),
        id=bon_id
    )

    magasins_autorises = get_magasins_autorises(request)
    if not magasins_autorises.filter(id=bon.magasin_id).exists():
        messages.error(request, "⛔ Accès non autorisé.")
        return redirect('liste_bons_hors_stock')

    service = bon.service_demandeur
    service_poste = getattr(service, 'poste_telephone', '') if service else ''
    service_code = getattr(service, 'code', '') if service else ''

    pdf_config, logo_url = get_pdf_config(bon.magasin, 'BSHS', request)

    lignes_data = []
    for ligne in bon.lignes_bon.select_related('article').all():
        article = ligne.article
        unite = 'U'
        for attr in ('unite_distribution', 'unite_mesure', 'unite'):
            if hasattr(article, attr):
                val = getattr(article, attr)
                if val:
                    unite = val
                    break
        lignes_data.append({
            'reference': getattr(article, 'reference', '') or str(article.id),
            'designation': getattr(article, 'designation', '') or '',
            'unite': unite,
            'quantite': ligne.quantite,
        })

    pagination = paginate_lignes(lignes_data, pdf_config, lignes_par_page=18, type_doc='SORTIE_HORS_STOCK')
    pages = [
        {'lignes': page, 'est_derniere_page': i == len(pagination.pages) - 1}
        for i, page in enumerate(pagination.pages)
    ]
    pages = ajouter_hauteurs_lignes(pages, pdf_config, type_doc='SORTIE_HORS_STOCK')

    context = {
        'is_apercu': True,
        'bon': bon,
        'magasin': bon.magasin,
        'lignes': list(bon.lignes_bon.all()),
        'lignes_data': lignes_data,
        'lignes_pages': pagination.pages,
        'pages': pages,
        'est_multi_page': pagination.est_multi_page,
        'empty_lines': list(range(max(0, 12 - len(lignes_data)))),
        'service': service,
        'service_code': service_code,
        'service_poste': service_poste,
        'logo_url': logo_url,
        'date_impression': timezone.now(),
        'pdf_config': pdf_config,
        'signature_cases': build_signature_cases(bon, pdf_config, request),
    }
    return render(request, 'stock/pdf/bon_hors_stock.html', context)

