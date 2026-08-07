from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.db.models import Sum, Count, Avg, Q, F, Case, When, IntegerField, Value, DecimalField
from django.db.models.functions import TruncDay, TruncWeek, TruncMonth, TruncYear
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.template.loader import render_to_string
from django.urls import reverse
from weasyprint import HTML

import csv
import json
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from accounts.permissions import verifier_permission
from ..models import (
    Mouvement, StockItem, Service, DemandeMateriel, LigneDemande,
    AccuseReception, Magasin, Article, BonMouvement, Commande, LivraisonPartielle)
from stock.services.isolation_service import get_magasins_autorises
from ..decorators import magasin_requis, catch_errors
# from ..services import StockService, PDFService  # SUPPRIMÉ : non utilisés dans ce fichier
from .catalogue import paginer

logger = logging.getLogger(__name__)


def parse_date_range(date_range, default_days=365):
    if date_range:
        try:
            parts = date_range.split(' - ')
            if len(parts) == 2:
                start = datetime.strptime(parts[0], '%d/%m/%Y').date()
                end = datetime.strptime(parts[1], '%d/%m/%Y').date()
                if start > end:
                    start, end = end, start
                return start, end
        except Exception:
            pass
    end = timezone.now().date()
    start = end - timedelta(days=default_days)
    return start, end


MOIS_MAP = {
    'janvier': 1, 'février': 2, 'mars': 3, 'avril': 4, 'mai': 5, 'juin': 6,
    'juillet': 7, 'août': 8, 'septembre': 9, 'octobre': 10, 'novembre': 11, 'décembre': 12,
    'jan': 1, 'janv': 1, 'fév': 2, 'fev': 2, 'févr': 2, 'mar': 3, 'avr': 4,
    'juin': 6, 'jui': 6, 'juil': 7, 'juill': 7, 'aoû': 8, 'aou': 8, 'aout': 8,
    'sep': 9, 'sept': 9, 'oct': 10, 'nov': 11, 'déc': 12, 'dec': 12, 'déce': 12,
}


def _get_magasin_filtre(request):
    """Helper : retourne le magasin_actif_id de la session si présent."""
    return request.session.get('magasin_actif_id')


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_rapports')
@magasin_requis
@catch_errors(redirect_url='page_rapports')
def page_rapports(request):
    services = Service.objects.exclude(nom="DESTRUCTION / PÉREMPTIONS").order_by('nom')

    magasin_actif_id = _get_magasin_filtre(request)
    magasin_actif = None
    if magasin_actif_id:
        magasin_actif = Magasin.objects.filter(id=magasin_actif_id).first()

    return render(request, 'stock/rapports.html', {
        'services': services,
        'magasin_actif': magasin_actif,
    })


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_rapports')
@magasin_requis
@catch_errors(redirect_url='page_rapports')
def export_stock_excel(request):
    """Export CSV de l'état du stock — FILTRÉ par magasin actif."""
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="Etat_du_Stock.csv"'
    response.write('\ufeff'.encode('utf8'))
    writer = csv.writer(response, delimiter=';')

    writer.writerow([
        'Référence', 'Désignation', 'Famille', 'Magasin',
        'Quantité Disponible', 'Seuil Minimum', 'Seuil Critique',
        'Seuil Maximum', 'Valeur CMUP (FCFA)', 'Valeur Totale (FCFA)', 'Statut',
    ])

    stocks = StockItem.objects.select_related(
        'article__famille', 'magasin'
    ).all()

    magasin_id = _get_magasin_filtre(request)
    if magasin_id:
        stocks = stocks.filter(magasin_id=magasin_id)

    for s in stocks:
        qte = s.quantite_physique
        art = s.article
        if art.seuil_critique is not None and qte <= art.seuil_critique:
            statut = "CRITIQUE"
        elif qte <= art.seuil_minimum:
            statut = "ALERTE"
        elif art.seuil_maximum and art.seuil_maximum > 0 and qte >= art.seuil_maximum:
            statut = "SURSTOCK"
        else:
            statut = "OK"

        valeur_totale = round(qte * Decimal(str(s.valeur_cmup)), 2) if s.valeur_cmup else Decimal('0.00')

        writer.writerow([
            art.reference if art.reference else "-",
            art.designation,
            art.famille.intitule,
            s.magasin.nom,
            qte,
            art.seuil_minimum,
            art.seuil_critique,
            art.seuil_maximum if art.seuil_maximum else "-",
            Decimal(str(s.valeur_cmup)) if s.valeur_cmup else Decimal('0.00'),
            valeur_totale,
            statut,
        ])
    return response


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_rapports')
@magasin_requis
@catch_errors(redirect_url='page_rapports')
def export_commandes_excel(request):
    """Export CSV des commandes — FILTRÉ par magasin actif."""
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="Historique_Commandes.csv"'
    response.write('\ufeff'.encode('utf8'))
    writer = csv.writer(response, delimiter=';')

    writer.writerow([
        'N° Commande', 'Date Création', 'Fournisseur',
        'Statut Logistique', 'Statut Validation', 'Magasin', 'Créé par'
    ])
    commandes = Commande.objects.select_related(
        'fournisseur', 'cree_par', 'magasin'
    ).all().order_by('-date_commande')

    magasin_id = _get_magasin_filtre(request)
    if magasin_id:
        commandes = commandes.filter(magasin_id=magasin_id)

    for c in commandes:
        date_c = timezone.localtime(c.date_commande).strftime('%d/%m/%Y %H:%M') if c.date_commande else ""
        writer.writerow([
            c.numero_commande, date_c, c.fournisseur.raison_sociale,
            c.get_statut_display(), c.get_statut_validation_display(),
            c.magasin.nom if c.magasin else "—",
            c.cree_par.username
        ])
    return response


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_rapports')
@magasin_requis
@catch_errors(redirect_url='page_rapports')
def export_mouvements_excel(request):
    """Export CSV de l'historique complet des mouvements — FILTRÉ par magasin actif."""
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="Historique_Mouvements.csv"'
    response.write('\ufeff'.encode('utf8'))
    writer = csv.writer(response, delimiter=';')

    writer.writerow([
        'Date Mouvement', 'Type', 'N° Bon', 'Article', 'Référence', 'Quantité', 'Unité',
        'Service Demandeur', 'Magasin', 'Opérateur', 'Motif'
    ])

    mouvements = Mouvement.objects.select_related(
        'article', 'magasin', 'utilisateur', 'service_demandeur', 'fournisseur'
    ).all().order_by('-date_mouvement')

    magasin_id = _get_magasin_filtre(request)
    if magasin_id:
        mouvements = mouvements.filter(magasin_id=magasin_id)

    for m in mouvements:
        date_m = timezone.localtime(m.date_mouvement).strftime('%d/%m/%Y %H:%M') if m.date_mouvement else ""
        writer.writerow([
            date_m,
            m.get_type_mouvement_display(),
            m.reference_document or "—",
            m.article.designation if m.article else "—",
            m.article.reference if m.article else "—",
            m.quantite,
            m.article.unite_distribution if m.article else "—",
            m.service_demandeur.nom if m.service_demandeur else "—",
            m.magasin.nom if m.magasin else "—",
            m.utilisateur.get_full_name() if m.utilisateur else "—",
            getattr(m, 'commentaire', '') or '—',
        ])
    return response


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_rapports')
@magasin_requis
@catch_errors(redirect_url='page_rapports')
def export_articles_excel(request):
    """Export CSV du catalogue articles complet — PAS de filtre magasin (catalogue global)."""
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="Catalogue_Articles.csv"'
    response.write('\ufeff'.encode('utf8'))
    writer = csv.writer(response, delimiter=';')

    writer.writerow([
        'Référence', 'Désignation', 'Famille', 'Unité Distribution', 'Unité Achat',
        'Seuil Minimum', 'Seuil Critique', 'Seuil Maximum', 'Prix de Référence (FCFA)', 'Actif'
    ])

    articles = Article.objects.select_related('famille').all().order_by('designation')

    for a in articles:
        unite_achat = getattr(a, 'unite_achat', None) or a.unite_distribution or "—"
        prix_ref = Decimal(str(a.prix_reference)) if a.prix_reference else Decimal('0.00')

        writer.writerow([
            a.reference or "—",
            a.designation,
            a.famille.intitule if a.famille else "—",
            a.unite_distribution or "—",
            unite_achat,
            a.seuil_minimum or 0,
            a.seuil_critique or 0,
            a.seuil_maximum if a.seuil_maximum else "—",
            prix_ref,
            "Oui" if getattr(a, 'actif', True) else "Non",
        ])
    return response


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_stats_demandes')
@magasin_requis
@catch_errors(redirect_url='page_rapports')
def stats_demandes(request):
    """Statistiques des demandes — FILTRÉ par magasin actif."""
    date_range = request.GET.get('date_range', '')
    service_id = request.GET.get('service', '')
    periode = request.GET.get('periode', 'mois')

    date_debut, date_fin = parse_date_range(date_range, default_days=365)

    qs_demandes = DemandeMateriel.objects.filter(
        date_demande__date__gte=date_debut,
        date_demande__date__lte=date_fin
    ).exclude(statut__in=['BROUILLON', 'ANNULEE'])

    qs_lignes = LigneDemande.objects.filter(
        demande__date_demande__date__gte=date_debut,
        demande__date_demande__date__lte=date_fin
    ).exclude(demande__statut__in=['BROUILLON', 'ANNULEE'])

    magasin_id = _get_magasin_filtre(request)
    if magasin_id:
        qs_demandes = qs_demandes.filter(magasin_cible_id=magasin_id)
        qs_lignes = qs_lignes.filter(demande__magasin_cible_id=magasin_id)

    if service_id:
        qs_demandes = qs_demandes.filter(service_demandeur_id=service_id)
        qs_lignes = qs_lignes.filter(demande__service_demandeur_id=service_id)

    top_services = qs_demandes.values('service_demandeur__nom').annotate(
        nb=Count('id', distinct=True),
        total_qte=Sum('lignes_demande__quantite_demandee')
    ).order_by('-total_qte')[:10]

    top_articles = qs_lignes.values(
        'article__designation', 'article__unite_distribution'
    ).annotate(
        total_demandee=Sum('quantite_demandee')
    ).order_by('-total_demandee')[:10]

    articles_par_service = qs_lignes.values(
        'demande__service_demandeur__nom', 'article__designation'
    ).annotate(
        total_demandee=Sum('quantite_demandee')
    ).order_by('demande__service_demandeur__nom', '-total_demandee')[:50]

    trunc_field = {
        'jour': TruncDay('date_demande'),
        'semaine': TruncWeek('date_demande'),
        'mois': TruncMonth('date_demande'),
        'annee': TruncYear('date_demande'),
    }.get(periode, TruncMonth('date_demande'))

    evolution = qs_demandes.annotate(
        periode=trunc_field
    ).values('periode').annotate(
        nb_demandes=Count('id')
    ).order_by('periode')

    total_demandes = qs_demandes.count()
    traitees = qs_demandes.filter(
        statut__in=['LIVREE', 'RECEPTIONNE', 'CLOTUREE']
    ).count()
    taux_traitement = round((traitees / total_demandes) * 100, 1) if total_demandes else 0

    if periode == 'mois':
        chart_evolution_labels = json.dumps([e['periode'].strftime('%m/%Y') for e in evolution])
    elif periode == 'jour':
        chart_evolution_labels = json.dumps([e['periode'].strftime('%d/%m/%Y') for e in evolution])
    elif periode == 'semaine':
        chart_evolution_labels = json.dumps([e['periode'].strftime('%d/%m/%Y') for e in evolution])
    elif periode == 'annee':
        chart_evolution_labels = json.dumps([e['periode'].strftime('%Y') for e in evolution])
    else:
        chart_evolution_labels = json.dumps([e['periode'].strftime('%d/%m/%Y') for e in evolution])
    chart_evolution_data = json.dumps([e['nb_demandes'] for e in evolution])

    magasin_actif_id = _get_magasin_filtre(request)
    magasin_actif = None
    if magasin_actif_id:
        magasin_actif = Magasin.objects.filter(id=magasin_actif_id).first()

    context = {
        'date_range': date_range,
        'periode': periode,
        'service_id': service_id,
        'services': Service.objects.all().order_by('nom'),
        'total_demandes': total_demandes,
        'taux_traitement': taux_traitement,
        'top_services': top_services,
        'top_articles': top_articles,
        'articles_par_service': articles_par_service,
        'chart_evolution_labels': chart_evolution_labels,
        'chart_evolution_data': chart_evolution_data,
        'magasin_actif': magasin_actif,
    }
    return render(request, 'stock/stats_demandes.html', context)


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_stats_sondages')
@magasin_requis
@catch_errors(redirect_url='page_rapports')
def stats_sondages(request):
    """Statistiques des sondages — FILTRÉ par magasin actif."""
    date_range = request.GET.get('date_range', '')
    service_id = request.GET.get('service', '')

    date_debut, date_fin = parse_date_range(date_range, default_days=365)

    qs_signes = AccuseReception.objects.filter(
        est_signe=True,
        date_reception__date__gte=date_debut,
        date_reception__date__lte=date_fin,
    ).select_related(
        'livraison__demande__service_demandeur', 'receptionne_par'
    )

    magasin_id = _get_magasin_filtre(request)
    if magasin_id:
        qs_signes = qs_signes.filter(livraison__demande__magasin_cible_id=magasin_id)

    if service_id and service_id.isdigit():
        qs_signes = qs_signes.filter(
            livraison__demande__service_demandeur_id=int(service_id)
        )

    total_reponses = qs_signes.count()
    satisfaits = qs_signes.filter(satisfait=True).count()
    insatisfaits = qs_signes.filter(satisfait=False).count()
    neutres = qs_signes.filter(satisfait__isnull=True).count()
    taux_satisfaction = round((satisfaits / total_reponses) * 100, 1) if total_reponses else 0

    note_moyenne = (
        (satisfaits * 4.5 + neutres * 3 + insatisfaits * 1.5) / total_reponses
    ) if total_reponses else 0
    note_moyenne = round(note_moyenne, 1)

    qs_tous_accuses = AccuseReception.objects.filter(
        livraison__date_livraison__date__gte=date_debut,
        livraison__date_livraison__date__lte=date_fin
    )
    if service_id and service_id.isdigit():
        qs_tous_accuses = qs_tous_accuses.filter(
            livraison__demande__service_demandeur_id=int(service_id)
        )
    if magasin_id:
        qs_tous_accuses = qs_tous_accuses.filter(livraison__demande__magasin_cible_id=magasin_id)

    total_accuses_crees = qs_tous_accuses.count()
    taux_reponse = round((total_reponses / total_accuses_crees) * 100, 1) if total_accuses_crees else 0

    delai_total_sec = 0
    nb_delais = 0
    for acc in qs_signes.select_related('livraison').iterator():
        if acc.date_reception and acc.livraison and acc.livraison.date_livraison:
            delta = acc.date_reception - acc.livraison.date_livraison
            if delta.total_seconds() >= 0:
                delai_total_sec += delta.total_seconds()
                nb_delais += 1
    delai_moyen_heures = round((delai_total_sec / nb_delais) / 3600, 1) if nb_delais else 0

    satisfaction_par_service = qs_signes.annotate(
        nom_service=F('livraison__demande__service_demandeur__nom')
    ).values('nom_service').annotate(
        nb_reponses=Count('id'),
        satisfaits=Count('id', filter=Q(satisfait=True)),
        insatisfaits=Count('id', filter=Q(satisfait=False)),
        neutres=Count('id', filter=Q(satisfait__isnull=True)),
        moyenne=Avg(
            Case(
                When(satisfait=True, then=Value(4.5)),
                When(satisfait=False, then=Value(1.5)),
                default=Value(3.0),
                output_field=DecimalField(max_digits=3, decimal_places=1)
            )
        )
    ).order_by('-nb_reponses')

    top_service = satisfaction_par_service.first() if satisfaction_par_service else None
    flop_service = satisfaction_par_service.last() if satisfaction_par_service else None

    par_mois = qs_signes.annotate(
        mois=TruncMonth('date_reception')
    ).values('mois').annotate(
        note_moy=Avg(
            Case(
                When(satisfait=True, then=Value(4.5)),
                When(satisfait=False, then=Value(1.5)),
                default=Value(3.0),
                output_field=DecimalField(max_digits=3, decimal_places=1)
            )
        ),
        total=Count('id')
    ).order_by('mois')
    chart_notes_labels = json.dumps([m['mois'].strftime('%b %Y') for m in par_mois])
    chart_notes_data = json.dumps([float(m['note_moy']) for m in par_mois])

    repartition_labels = json.dumps(['Satisfaits', 'Neutres', 'Insatisfaits'])
    repartition_data = json.dumps([satisfaits, neutres, insatisfaits])

    derniers_commentaires = qs_signes.exclude(observations='').order_by('-date_reception')[:10]
    reponses_recentes = qs_signes.select_related(
        'livraison__demande', 'livraison__livre_par'
    ).order_by('-date_reception')[:15]

    magasin_actif_id = _get_magasin_filtre(request)
    magasin_actif = None
    if magasin_actif_id:
        magasin_actif = Magasin.objects.filter(id=magasin_actif_id).first()

    context = {
        'date_range': date_range,
        'service_id': service_id,
        'services': Service.objects.all().order_by('nom'),
        'total_reponses': total_reponses,
        'total_accuses_crees': total_accuses_crees,
        'taux_reponse': taux_reponse,
        'note_moyenne': note_moyenne,
        'taux_satisfaction': taux_satisfaction,
        'delai_moyen_heures': delai_moyen_heures,
        'satisfaction_par_service': satisfaction_par_service,
        'top_service': top_service,
        'flop_service': flop_service,
        'derniers_commentaires': derniers_commentaires,
        'reponses_recentes': reponses_recentes,
        'chart_notes_labels': chart_notes_labels,
        'chart_notes_data': chart_notes_data,
        'chart_repartition_labels': repartition_labels,
        'chart_repartition_data': repartition_data,
        'magasin_actif': magasin_actif,
    }
    return render(request, 'stock/stats_sondages.html', context)


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_rapports')
@magasin_requis
@catch_errors(redirect_url='page_rapports')
def api_details_stats(request):
    try:
        detail_type = request.GET.get('type')
        identifier = request.GET.get('id', '')
        page = max(1, int(request.GET.get('page', 1)))
        per_page = 20
        offset = (page - 1) * per_page

        date_range = request.GET.get('date_range', '')
        service_id = request.GET.get('service', '')
        periode = request.GET.get('periode', 'mois')
        date_debut, date_fin = parse_date_range(date_range, default_days=365)

        magasin_id = _get_magasin_filtre(request)

        data = []
        total = 0

        if detail_type in ['demandes_global', 'demandes_service', 'taux_traitement',
                           'services_actifs', 'articles_global', 'articles_par_service', 'evolution']:

            qs = DemandeMateriel.objects.filter(
                date_demande__date__gte=date_debut,
                date_demande__date__lte=date_fin
            ).exclude(statut__in=['BROUILLON', 'ANNULEE'])

            if magasin_id:
                qs = qs.filter(magasin_cible_id=magasin_id)

            if service_id and service_id.isdigit():
                qs = qs.filter(service_demandeur_id=int(service_id))

            if detail_type == 'demandes_global':
                total = qs.count()
                items = qs.select_related('service_demandeur', 'demandeur').order_by('-date_demande')[offset:offset+per_page]
                data = [{
                    'numero_demande': d.numero_demande,
                    'demande_id': d.id,
                    'date': d.date_demande.strftime('%d/%m/%Y') if d.date_demande else '—',
                    'service': d.service_demandeur.nom if d.service_demandeur else '—',
                    'demandeur': (d.demandeur.get_full_name() or d.demandeur.username) if d.demandeur else '—',
                    'statut': d.get_statut_display(),
                    'quantite_totale': d.quantite_demandee_totale or 0
                } for d in items]

            elif detail_type == 'demandes_service' and identifier:
                q2 = qs.filter(service_demandeur__nom=identifier)
                total = q2.count()
                items = q2.select_related('demandeur').order_by('-date_demande')[offset:offset+per_page]
                data = [{
                    'numero_demande': d.numero_demande,
                    'demande_id': d.id,
                    'date': d.date_demande.strftime('%d/%m/%Y') if d.date_demande else '—',
                    'demandeur': (d.demandeur.get_full_name() or d.demandeur.username) if d.demandeur else '—',
                    'statut': d.get_statut_display(),
                    'quantite': d.quantite_demandee_totale or 0
                } for d in items]

            elif detail_type == 'taux_traitement':
                total = qs.count()
                items = qs.order_by('-date_demande')[offset:offset+per_page]
                data = [{
                    'numero_demande': d.numero_demande,
                    'demande_id': d.id,
                    'date': d.date_demande.strftime('%d/%m/%Y') if d.date_demande else '—',
                    'service': d.service_demandeur.nom if d.service_demandeur else '—',
                    'statut': d.get_statut_display(),
                    'traitee': 'Oui' if d.statut in ['LIVREE', 'RECEPTIONNE', 'CLOTUREE'] else 'Non'
                } for d in items]

            elif detail_type == 'services_actifs':
                svc = qs.values('service_demandeur__nom').annotate(
                    total_qte=Sum('lignes_demande__quantite_demandee'),
                    nb=Count('id', distinct=True)
                ).order_by('-total_qte')
                total = svc.count()
                items = list(svc[offset:offset+per_page])
                data = [{
                    'service': s['service_demandeur__nom'] or '—',
                    'quantite_totale': s['total_qte'] or 0,
                    'nb_demandes': s['nb']
                } for s in items]

            elif detail_type == 'articles_global':
                ql = LigneDemande.objects.filter(demande__in=qs).values(
                    'article__designation', 'article__unite_distribution'
                ).annotate(
                    total=Sum('quantite_demandee')
                ).order_by('-total')
                total = ql.count()
                items = list(ql[offset:offset+per_page])
                data = [{
                    'article': i['article__designation'],
                    'unite': i['article__unite_distribution'] or '—',
                    'quantite_demandee': i['total']
                } for i in items]

            elif detail_type == 'articles_par_service' and identifier:
                parts = identifier.split('||')
                if len(parts) == 2:
                    q2 = LigneDemande.objects.filter(
                        demande__in=qs,
                        demande__service_demandeur__nom=parts[0],
                        article__designation=parts[1]
                    ).select_related('demande')
                    total = q2.count()
                    items = q2.order_by('-demande__date_demande')[offset:offset+per_page]
                    data = [{
                        'numero_demande': l.demande.numero_demande,
                        'demande_id': l.demande.id,
                        'date': l.demande.date_demande.strftime('%d/%m/%Y') if l.demande.date_demande else '—',
                        'quantite': l.quantite_demandee,
                        'statut': l.demande.get_statut_display()
                    } for l in items]

            elif detail_type == 'evolution' and identifier:
                q2 = qs.none()
                try:
                    if periode == 'jour':
                        d = datetime.strptime(identifier, '%d/%m/%Y').date()
                        q2 = qs.filter(date_demande__date=d)
                    elif periode == 'semaine':
                        d = datetime.strptime(identifier, '%d/%m/%Y').date()
                        q2 = qs.filter(date_demande__week=d.isocalendar()[1], date_demande__year=d.year)
                    elif periode == 'mois':
                        if '/' in identifier:
                            p = identifier.split('/')
                            if len(p) == 2:
                                q2 = qs.filter(date_demande__year=int(p[1]), date_demande__month=int(p[0]))
                        else:
                            c = identifier.lower().replace('.', '').strip().split()
                            if len(c) == 2 and MOIS_MAP.get(c[0]):
                                q2 = qs.filter(date_demande__year=int(c[1]), date_demande__month=MOIS_MAP[c[0]])
                    elif periode == 'annee':
                        q2 = qs.filter(date_demande__year=int(identifier))
                except Exception as ex:
                    logger.warning("[stats] evolution parse error: %s", ex)

                total = q2.count()
                items = q2.order_by('-date_demande')[offset:offset+per_page]
                data = [{
                    'numero_demande': d.numero_demande,
                    'demande_id': d.id,
                    'date': d.date_demande.strftime('%d/%m/%Y') if d.date_demande else '—',
                    'service': d.service_demandeur.nom if d.service_demandeur else '—',
                    'statut': d.get_statut_display()
                } for d in items]

        return JsonResponse({
            'data': data,
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': (total + per_page - 1) // per_page if total else 1
        })

    except Exception as e:
        logger.exception("[api_details_stats] %s", e)
        return JsonResponse({
            'error': 'Erreur interne du serveur.', 'data': [], 'total': 0,
            'page': 1, 'per_page': 20, 'total_pages': 1
        }, status=500)


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_rapports')
@magasin_requis
@catch_errors(redirect_url='page_rapports')
def api_details_sondages(request):
    try:
        page = max(1, int(request.GET.get('page', 1)))
        per_page = 20
        offset = (page - 1) * per_page

        date_range = request.GET.get('date_range', '')
        service_id = request.GET.get('service', '')
        service_nom = request.GET.get('service_nom', '')
        satisfaction = request.GET.get('satisfaction', '')
        date_debut, date_fin = parse_date_range(date_range, default_days=365)

        qs = AccuseReception.objects.filter(
            est_signe=True,
            date_reception__date__gte=date_debut,
            date_reception__date__lte=date_fin,
        ).select_related(
            'livraison__demande__service_demandeur',
            'livraison__livre_par',
            'receptionne_par__profil',
            'livraison__demande__demandeur'
        )

        magasin_id = _get_magasin_filtre(request)
        if magasin_id:
            qs = qs.filter(livraison__demande__magasin_cible_id=magasin_id)

        if service_id and service_id.isdigit():
            qs = qs.filter(livraison__demande__service_demandeur_id=int(service_id))
        if service_nom:
            qs = qs.filter(livraison__demande__service_demandeur__nom=service_nom)

        if satisfaction == 'satisfait':
            qs = qs.filter(satisfait=True)
        elif satisfaction == 'insatisfait':
            qs = qs.filter(satisfait=False)
        elif satisfaction == 'neutre':
            qs = qs.filter(satisfait__isnull=True)

        total = qs.count()
        items = qs.order_by('-date_reception')[offset:offset+per_page]

        data = []
        for acc in items:
            liv = acc.livraison
            dem = liv.demande if liv else None
            note = 4.5 if acc.satisfait is True else (1.5 if acc.satisfait is False else 3.0)
            data.append({
                'id': acc.id,
                'date_reception': acc.date_reception.strftime('%d/%m/%Y %H:%M') if acc.date_reception else '—',
                'service': dem.service_demandeur.nom if dem and dem.service_demandeur else '—',
                'numero_demande': dem.numero_demande if dem else '—',
                'demande_id': dem.id if dem else None,
                'livre_par': liv.livre_par.get_full_name() if liv and liv.livre_par else '—',
                'receptionne_par': acc.receptionne_par.get_full_name() if acc.receptionne_par else '—',
                'satisfait': 'Satisfait' if acc.satisfait is True else ('Insatisfait' if acc.satisfait is False else 'Neutre'),
                'note': note,
                'observations': acc.observations or '',
                'quantite_livree': liv.quantite_livree if liv else 0,
            })

        return JsonResponse({
            'data': data,
            'total': total,
            'page': page,
            'per_page': per_page,
            'total_pages': (total + per_page - 1) // per_page if total else 1
        })

    except Exception as e:
        logger.exception("[api_details_sondages] %s", e)
        return JsonResponse({
            'error': 'Erreur interne du serveur.', 'data': [], 'total': 0,
            'page': 1, 'per_page': 20, 'total_pages': 1
        }, status=500)


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_rapports')
@magasin_requis
@catch_errors(redirect_url='page_rapports')
def api_detail_demande(request, demande_id):
    try:
        demande = get_object_or_404(
            DemandeMateriel.objects.select_related(
                'service_demandeur', 'demandeur', 'magasin_cible',
                'valide_par', 'valide_par_chef', 'cloture_par', 'bon_sortie_lie'
            ),
            id=demande_id)

        magasin_id = _get_magasin_filtre(request)
        if magasin_id and demande.magasin_cible_id != int(magasin_id):
            return JsonResponse({'error': 'Cette demande n\'appartient pas au magasin sélectionné.'}, status=403)

        profil = getattr(request.user, 'profil', None)
        est_magasinier = request.user.has_perm('accounts.menu_guichet')
        est_demandeur = (demande.demandeur == request.user)
        est_du_service = (profil and profil.service == demande.service_demandeur)
        if not (est_magasinier or est_demandeur or est_du_service or request.user.is_staff):
            return JsonResponse({'error': 'Accès refusé'}, status=403)

        livraisons_data = []
        for liv in demande.livraisons.select_related('bon_sortie').prefetch_related('accuse').all():
            accuse = getattr(liv, 'accuse', None)
            livraisons_data.append({
                'numero': liv.numero_livraison,
                'quantite': liv.quantite_livree,
                'date': liv.date_livraison.strftime('%d/%m/%Y %H:%M') if liv.date_livraison else None,
                'est_signe': accuse.est_signe if accuse else False,
                'signe_par': accuse.receptionne_par.get_full_name() if accuse and accuse.receptionne_par else None,
            })

        data = {
            'id': demande.id,
            'numero_demande': demande.numero_demande,
            'statut': demande.statut,
            'statut_display': demande.get_statut_display(),
            'date_demande': demande.date_demande.strftime('%d/%m/%Y %H:%M') if demande.date_demande else None,
            'service': demande.service_demandeur.nom if demande.service_demandeur else '—',
            'demandeur': demande.demandeur.get_full_name() or demande.demandeur.username,
            'magasin': demande.magasin_cible.nom if demande.magasin_cible else '—',
            'commentaire': demande.commentaire or '',
            'quantite_demandee_totale': demande.quantite_demandee_totale,
            'quantite_servie_totale': demande.quantite_servie_totale,
            'reste': demande.reste,
            'taux_service': demande.taux_service,
            'bon_sortie': demande.bon_sortie_lie.numero_bon if demande.bon_sortie_lie else None,
            'bon_sortie_id': demande.bon_sortie_lie.id if demande.bon_sortie_lie else None,
            'valide_par': demande.valide_par.get_full_name() if demande.valide_par else None,
            'date_validation': demande.date_validation.strftime('%d/%m/%Y %H:%M') if demande.date_validation else None,
            'lignes': [{
                'article': l.article.designation,
                'quantite_demandee': l.quantite_demandee,
                'quantite_livree': l.quantite_livree,
                'reste': l.reste,
            } for l in demande.lignes_demande.select_related('article').all()],
            'livraisons': livraisons_data,
        }
        return JsonResponse(data)

    except Exception as e:
        logger.exception("[api_detail_demande] Crash : %s", e)
        return JsonResponse({'error': 'Erreur interne du serveur.'}, status=500)


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_rapports')
@magasin_requis
@catch_errors(redirect_url='page_rapports')
def export_sondages_csv(request):
    """Export CSV des sondages — FILTRÉ par magasin actif."""
    date_range = request.GET.get('date_range', '')
    service_id = request.GET.get('service', '')

    date_debut, date_fin = parse_date_range(date_range, default_days=365)

    qs = AccuseReception.objects.filter(
        est_signe=True,
        date_reception__date__gte=date_debut,
        date_reception__date__lte=date_fin,
    ).select_related(
        'livraison__demande__service_demandeur',
        'livraison__livre_par',
        'receptionne_par'
    ).order_by('-date_reception')

    magasin_id = _get_magasin_filtre(request)
    if magasin_id:
        qs = qs.filter(livraison__demande__magasin_cible_id=magasin_id)

    if service_id and service_id.isdigit():
        qs = qs.filter(livraison__demande__service_demandeur_id=int(service_id))

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="Sondages_Satisfaction.csv"'
    response.write('\ufeff'.encode('utf8'))

    writer = csv.writer(response, delimiter=';', quoting=csv.QUOTE_MINIMAL)
    writer.writerow([
        'Date réception', 'Service', 'N° Demande', 'Demandeur',
        'Livré par', 'Avis', 'Note', 'Commentaire', 'Qté livrée', 'Magasin'
    ])

    for acc in qs:
        liv = acc.livraison
        dem = liv.demande if liv else None

        if acc.satisfait is True:
            avis = 'Satisfait'
            note = '4.5'
        elif acc.satisfait is False:
            avis = 'Insatisfait'
            note = '1.5'
        else:
            avis = 'Neutre'
            note = '3.0'

        writer.writerow([
            acc.date_reception.strftime('%d/%m/%Y %H:%M') if acc.date_reception else '',
            dem.service_demandeur.nom if dem and dem.service_demandeur else '',
            dem.numero_demande if dem else '',
            acc.receptionne_par.get_full_name() if acc.receptionne_par else '',
            liv.livre_par.get_full_name() if liv and liv.livre_par else '',
            avis,
            note,
            (acc.observations or '').replace(';', ','),
            liv.quantite_livree if liv else 0,
            dem.magasin_cible.nom if dem and dem.magasin_cible else '',
        ])

    return response


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_stats_satisfaction')
@magasin_requis
@catch_errors(redirect_url='page_rapports')
def stats_satisfaction_services(request):
    """Statistiques de satisfaction par service — FILTRÉ par magasin actif."""
    date_range = request.GET.get('date_range', '')
    service_id = request.GET.get('service', '')

    date_debut, date_fin = parse_date_range(date_range, default_days=365)

    services = Service.objects.all().order_by('nom')

    qs_demandes = DemandeMateriel.objects.filter(
        date_demande__date__gte=date_debut,
        date_demande__date__lte=date_fin
    ).exclude(statut__in=['BROUILLON', 'ANNULEE'])

    magasin_id = _get_magasin_filtre(request)
    if magasin_id:
        qs_demandes = qs_demandes.filter(magasin_cible_id=magasin_id)

    if service_id and service_id.isdigit():
        qs_demandes = qs_demandes.filter(service_demandeur_id=int(service_id))
        services = services.filter(id=int(service_id))

    stats_services = []
    g_total_demandes = g_total_livraisons = g_total_accuses = 0
    g_sat = g_insat = g_neut = 0

    for service in services:
        demandes_svc = qs_demandes.filter(service_demandeur=service)
        total_demandes = demandes_svc.count()

        livraisons = LivraisonPartielle.objects.filter(demande__in=demandes_svc)
        total_livraisons = livraisons.count()

        accuses = AccuseReception.objects.filter(
            livraison__in=livraisons,
            est_signe=True,
            date_reception__date__gte=date_debut,
            date_reception__date__lte=date_fin)
        total_accuses = accuses.count()

        sat = accuses.filter(satisfait=True).count()
        insat = accuses.filter(satisfait=False).count()
        neut = accuses.filter(satisfait__isnull=True).count()

        taux_sat = round((sat / total_accuses) * 100, 1) if total_accuses else 0
        taux_rep = round((total_accuses / total_livraisons) * 100, 1) if total_livraisons else 0
        note_moy = ((sat * 4.5) + (neut * 3) + (insat * 1.5)) / total_accuses if total_accuses else 0

        stats_services.append({
            'service': service,
            'total_demandes': total_demandes,
            'total_livraisons': total_livraisons,
            'total_accuses': total_accuses,
            'satisfaits': sat,
            'insatisfaits': insat,
            'neutres': neut,
            'taux_satisfaction': taux_sat,
            'taux_reponse': taux_rep,
            'note_moyenne': round(note_moy, 1),
        })

        g_total_demandes += total_demandes
        g_total_livraisons += total_livraisons
        g_total_accuses += total_accuses
        g_sat += sat
        g_insat += insat
        g_neut += neut

    g_taux_sat = round((g_sat / g_total_accuses) * 100, 1) if g_total_accuses else 0
    g_taux_rep = round((g_total_accuses / g_total_livraisons) * 100, 1) if g_total_livraisons else 0
    g_note = ((g_sat * 4.5) + (g_neut * 3) + (g_insat * 1.5)) / g_total_accuses if g_total_accuses else 0

    svc_avec_data = [s for s in stats_services if s['total_accuses'] > 0]
    labels = [s['service'].nom for s in svc_avec_data]
    data_sat = [s['taux_satisfaction'] for s in svc_avec_data]
    data_rep = [s['taux_reponse'] for s in svc_avec_data]
    data_notes = [s['note_moyenne'] for s in svc_avec_data]

    magasin_actif_id = _get_magasin_filtre(request)
    magasin_actif = None
    if magasin_actif_id:
        magasin_actif = Magasin.objects.filter(id=magasin_actif_id).first()

    context = {
        'date_range': date_range,
        'service_id': service_id,
        'services': Service.objects.all().order_by('nom'),
        'stats_services': stats_services,
        'global': {
            'total_demandes': g_total_demandes,
            'total_livraisons': g_total_livraisons,
            'total_accuses': g_total_accuses,
            'satisfaits': g_sat,
            'insatisfaits': g_insat,
            'neutres': g_neut,
            'taux_satisfaction': g_taux_sat,
            'taux_reponse': g_taux_rep,
            'note_moyenne': round(g_note, 1),
        },
        'chart_labels': json.dumps(labels),
        'chart_sat': json.dumps(data_sat),
        'chart_rep': json.dumps(data_rep),
        'chart_notes': json.dumps(data_notes),
        'chart_repartition_labels': json.dumps(['Satisfaits', 'Neutres', 'Insatisfaits']),
        'chart_repartition_data': json.dumps([g_sat, g_neut, g_insat]),
        'magasin_actif': magasin_actif,
    }
    return render(request, 'stock/stats_satisfaction_services.html', context)