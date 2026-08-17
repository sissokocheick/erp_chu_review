# -*- coding: utf-8 -*-
"""
Rapports du module Patrimoine.

Rapport mensuel de la valeur des immobilisations par service : nombre de
biens, valeur d'acquisition, amortissement cumulé et VNC (valeur nette
comptable), avec détail par type d'équipement, évolution des acquisitions,
tri par clic sur les colonnes et exports CSV + PDF (logo / entête configurés).
"""
import csv
import json
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum, Q
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone
from django.urls import reverse

from accounts.permissions import verifier_permission
from core.models import ConfigurationHopital, Service
from stock.views.catalogue import paginer
from .models import Immobilisation

logger = logging.getLogger(__name__)

STATUTS_SORTIS = ('REFORME', 'CEDE', 'DISPARU')


def _parse_date_range(date_range):
    """Plage libre 'JJ/MM/AAAA - JJ/MM/AAAA' → (debut, fin), sinon (None, None)."""
    if not date_range:
        return None, None
    try:
        parts = date_range.split(' - ')
        if len(parts) == 2:
            debut = datetime.strptime(parts[0], '%d/%m/%Y').date()
            fin = datetime.strptime(parts[1], '%d/%m/%Y').date()
            if debut > fin:
                debut, fin = fin, debut
            return debut, fin
    except (ValueError, TypeError):
        pass
    return None, None


def _filtres(request):
    """Lit les filtres de la requête (période, service, sortis) et la période effective."""
    date_range = request.GET.get('date_range', '')
    service_id = request.GET.get('service', '')
    inclure_sortis = request.GET.get('inclure_sortis') == '1'

    try:
        nb_mois = int(request.GET.get('mois', '6'))
        if nb_mois not in (1, 3, 6, 12):
            nb_mois = 6
    except (TypeError, ValueError):
        nb_mois = 6

    date_debut, date_fin = _parse_date_range(date_range)
    if date_debut is None:
        date_fin = timezone.now().date()
        premier = date_fin.replace(day=1)
        for _ in range(nb_mois - 1):
            premier = (premier - timedelta(days=1)).replace(day=1)
        date_debut = premier
        date_range = (f"{date_debut.strftime('%d/%m/%Y')} - "
                      f"{date_fin.strftime('%d/%m/%Y')}")

    qs = Immobilisation.objects.select_related(
        'service_affectation', 'type_equipement')
    # Le parc tel qu'il existe à la fin de la période
    qs = qs.filter(Q(date_acquisition__isnull=True)
                   | Q(date_acquisition__lte=date_fin))
    if not inclure_sortis:
        qs = qs.exclude(statut__in=STATUTS_SORTIS)
    if service_id:
        qs = qs.filter(service_affectation_id=service_id)

    return (qs, date_debut, date_fin, service_id, nb_mois,
            date_range, inclure_sortis)


def _agreger(qs):
    """Agrège par service (nb, valeur_acquisition, vnc, amorti) et par
    service × type d'équipement. La VNC étant une propriété calculée, on
    parcourt les biens en Python."""
    par_service = defaultdict(lambda: {
        'service_demandeur__nom': '', 'nb': 0,
        'valeur_acq': Decimal('0.00'), 'vnc': Decimal('0.00'),
        'amorti': Decimal('0.00'),
    })
    par_svc_type = defaultdict(lambda: {
        'service_demandeur__nom': '', 'type__nom': '',
        'nb': 0, 'valeur_acq': Decimal('0.00'),
        'vnc': Decimal('0.00'),
    })
    for immo in qs.iterator():
        svc_nom = (immo.service_affectation.nom
                   if immo.service_affectation else 'Non affecté')
        type_nom = (immo.type_equipement.nom
                    if immo.type_equipement_id else 'Sans type')

        v_acq = immo.valeur_acquisition or Decimal('0.00')
        vnc = immo.vnc if immo.valeur_acquisition else Decimal('0.00')
        amorti = max(v_acq - vnc, Decimal('0.00'))

        s = par_service[svc_nom]
        s['service_demandeur__nom'] = svc_nom
        s['nb'] += 1
        s['valeur_acq'] += v_acq
        s['vnc'] += vnc
        s['amorti'] += amorti

        d = par_svc_type[(svc_nom, type_nom)]
        d['service_demandeur__nom'] = svc_nom
        d['type__nom'] = type_nom
        d['nb'] += 1
        d['valeur_acq'] += v_acq
        d['vnc'] += vnc

    return list(par_service.values()), list(par_svc_type.values())


def _trier(lignes, tri, ordre, champs, defaut):
    """Tri par clic : whitelist de champs, tri Python (la VNC est calculée)."""
    cle = champs.get(tri)
    if cle is None:
        return sorted(lignes, key=defaut, reverse=True)
    reverse = (ordre == 'desc')
    return sorted(lignes, key=lambda r: r.get(cle) or 0, reverse=reverse)


_CHAMPS_SERVICE = {
    'service': 'service_demandeur__nom',
    'nb': 'nb',
    'valeur': 'valeur_acq',
    'vnc': 'vnc',
    'amorti': 'amorti',
}
_CHAMPS_DETAIL = {
    'service': 'service_demandeur__nom',
    'type': 'type__nom',
    'nb': 'nb',
    'valeur': 'valeur_acq',
    'vnc': 'vnc',
}


def _evolution(qs, date_debut, date_fin):
    """Acquisitions par mois (nb + valeur) sur la période, séries complètes."""
    data = {}
    evo = (qs.filter(date_acquisition__isnull=False,
                     date_acquisition__range=(date_debut, date_fin))
           .values('date_acquisition__year', 'date_acquisition__month')
           .annotate(nb=Count('id'), valeur=Sum('valeur_acquisition')))
    for e in evo:
        cle = (e['date_acquisition__year'], e['date_acquisition__month'])
        data[cle] = e

    labels, nb_serie, val_serie = [], [], []
    courant = date_debut.replace(day=1)
    while courant <= date_fin:
        e = data.get((courant.year, courant.month), {})
        labels.append(courant.strftime('%m/%Y'))
        nb_serie.append(int(e.get('nb') or 0))
        val_serie.append(float(e.get('valeur') or 0))
        annee, mois = courant.year, courant.month
        courant = courant.replace(year=annee + (mois == 12),
                                  month=(mois % 12) + 1)
    return labels, nb_serie, val_serie


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_pat_registre')
def rapport_valeur_services(request):
    """Valeur des immobilisations par service : tableau + détail + évolution."""
    qs, date_debut, date_fin, service_id, nb_mois, date_range, inclure_sortis = \
        _filtres(request)

    par_service, par_svc_type = _agreger(qs)

    total_nb = sum(r['nb'] for r in par_service)
    total_acq = sum(r['valeur_acq'] for r in par_service)
    total_vnc = sum(r['vnc'] for r in par_service)
    total_amorti = sum(r['amorti'] for r in par_service)

    for r in par_service:
        r['part_vnc'] = ((float(r['vnc']) / float(total_vnc) * 100)
                         if total_vnc else 0)

    tri = request.GET.get('tri', '')
    ordre = request.GET.get('ordre', 'asc')
    par_service = _trier(par_service, tri, ordre, _CHAMPS_SERVICE,
                         defaut=lambda r: r['vnc'])
    tri_detail = request.GET.get('dtri', '')
    ordre_detail = request.GET.get('dordre', 'asc')
    par_svc_type = _trier(par_svc_type, tri_detail, ordre_detail,
                          _CHAMPS_DETAIL,
                          defaut=lambda r: (r['service_demandeur__nom'],
                                            r['vnc']))

    # Détail paginé (même convention que le rapport de consommation :
    # detail_per_page 20/50/100/tout + page)
    detail_page, detail_per_page = paginer(
        par_svc_type, request, per_page_key='detail_per_page', default=20)
    detail_total = detail_page.paginator.count

    labels, nb_serie, val_serie = _evolution(qs, date_debut, date_fin)

    context = {
        'par_service': par_service,
        'par_svc_type': par_svc_type,
        'detail_page': detail_page,
        'detail_per_page': detail_per_page,
        'detail_total': detail_total,
        'total_nb': total_nb,
        'total_acq': total_acq,
        'total_vnc': total_vnc,
        'total_amorti': total_amorti,
        'date_debut': date_debut,
        'date_fin': date_fin,
        'date_range': date_range,
        'service_id': service_id,
        'mois': nb_mois,
        'inclure_sortis': inclure_sortis,
        'services': Service.objects.all().order_by('nom'),
        'tri': tri,
        'ordre': ordre,
        'tri_detail': tri_detail,
        'ordre_detail': ordre_detail,
        'chart_labels': json.dumps(labels),
        'chart_nb': json.dumps(nb_serie),
        'chart_valeur': json.dumps(val_serie),
        'chart_services_labels': json.dumps(
            [r['service_demandeur__nom'] for r in par_service][:8]),
        'chart_services_data': json.dumps(
            [float(r['vnc']) for r in par_service][:8]),
        'export_url': reverse('patrimoine_rapport_valeurs_csv'),
        'export_detail_url': reverse('patrimoine_rapport_valeurs_detail_csv'),
        'pdf_url': reverse('patrimoine_rapport_valeurs_pdf'),
    }
    return render(request, 'patrimoine/rapport_valeur_services.html', context)


def _export_csv(request, detail=False):
    qs, date_debut, date_fin, service_id, nb_mois, date_range, inclure_sortis = \
        _filtres(request)
    par_service, par_svc_type = _agreger(qs)

    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="' + (
        'Valeur_Immobilisations_Detail_par_Service.csv'
        if detail else 'Valeur_Immobilisations_par_Service.csv') + '"'
    response.write('\ufeff'.encode('utf8'))
    writer = csv.writer(response, delimiter=';')

    if detail:
        writer.writerow([
            'Service', "Type d'équipement", 'Nb biens',
            "Valeur d'acquisition (FCFA)", 'VNC (FCFA)', 'Période',
        ])
        for r in par_svc_type:
            writer.writerow([
                r['service_demandeur__nom'], r['type__nom'], r['nb'],
                f"{r['valeur_acq']:.2f}".replace('.', ','),
                f"{r['vnc']:.2f}".replace('.', ','),
                f"{date_debut.strftime('%d/%m/%Y')} - "
                f"{date_fin.strftime('%d/%m/%Y')}",
            ])
    else:
        writer.writerow([
            'Service', 'Nb biens', "Valeur d'acquisition (FCFA)",
            'Amortissement cumulé (FCFA)', 'VNC (FCFA)', 'Période',
        ])
        for r in par_service:
            writer.writerow([
                r['service_demandeur__nom'], r['nb'],
                f"{r['valeur_acq']:.2f}".replace('.', ','),
                f"{r['amorti']:.2f}".replace('.', ','),
                f"{r['vnc']:.2f}".replace('.', ','),
                f"{date_debut.strftime('%d/%m/%Y')} - "
                f"{date_fin.strftime('%d/%m/%Y')}",
            ])
    return response


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_pat_registre')
def export_valeur_services_csv(request):
    return _export_csv(request, detail=False)


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_pat_registre')
def export_valeur_services_detail_csv(request):
    return _export_csv(request, detail=True)


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_pat_registre')
def rapport_valeur_services_pdf(request):
    """PDF du rapport de valeur des immobilisations par service."""
    from stock.pdf_utils import get_pdf_config, render_pdf_response

    qs, date_debut, date_fin, service_id, nb_mois, date_range, inclure_sortis = \
        _filtres(request)
    par_service, par_svc_type = _agreger(qs)

    total_nb = sum(r['nb'] for r in par_service)
    total_acq = sum(r['valeur_acq'] for r in par_service)
    total_vnc = sum(r['vnc'] for r in par_service)
    total_amorti = sum(r['amorti'] for r in par_service)

    for r in par_service:
        r['part_vnc'] = ((float(r['vnc']) / float(total_vnc) * 100)
                         if total_vnc else 0)

    par_service = _trier(par_service, request.GET.get('tri', ''),
                         request.GET.get('ordre', 'asc'), _CHAMPS_SERVICE,
                         defaut=lambda r: r['vnc'])
    par_svc_type = _trier(par_svc_type, request.GET.get('dtri', ''),
                          request.GET.get('dordre', 'asc'), _CHAMPS_DETAIL,
                          defaut=lambda r: (r['service_demandeur__nom'],
                                            r['vnc']))

    service = None
    if service_id:
        service = Service.objects.filter(id=service_id).first()

    # Nom de l'établissement pour le cartouche (le patrimoine n'est pas
    # scopé magasin : on utilise l'identité globale du CHU)
    try:
        nom_etablissement = ConfigurationHopital.get_instance().nom
    except Exception:
        nom_etablissement = ''

    pdf_config, logo_url = get_pdf_config(None, 'RAPPORT', request)

    context = {
        'par_service': par_service,
        'par_svc_type': par_svc_type,
        'total_nb': total_nb,
        'total_acq': total_acq,
        'total_vnc': total_vnc,
        'total_amorti': total_amorti,
        'date_debut': date_debut,
        'date_fin': date_fin,
        'service': service,
        'nom_etablissement': nom_etablissement,
        'inclure_sortis': inclure_sortis,
        'pdf_config': pdf_config,
        'logo_url': logo_url,
        'edite_par': request.user,
        'date_impression': timezone.now(),
    }
    return render_pdf_response(
        request, 'patrimoine/pdf/rapport_valeur_services.html',
        context, 'Valeur_Immobilisations_par_Service.pdf')
