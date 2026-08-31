# -*- coding: utf-8 -*-
"""Vues pour les salles de conférence."""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Q, Sum, Count
from django.core.paginator import Paginator
from django.http import JsonResponse
from datetime import timedelta, datetime
from collections import defaultdict

from core.models import Service
from ..models import (
    SalleConference, ReservationSalle, DemandeSalle, Batiment, Etage, Bureau
)
from ..views.common import patrimoine_required
from functools import wraps


def verifier_permission_salle(perm):
    """Decorator: vérifie une permission salle spécifique."""
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapper(request, *args, **kwargs):
            if not (request.user.is_superuser or request.user.has_perm(perm)):
                messages.error(request, "Accès non autorisé.")
                return redirect('/')
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


@verifier_permission_salle("accounts.menu_pat_salles")
def liste_salles(request):
    """Liste des salles de conférence avec disponibilité."""
    salles = SalleConference.objects.select_related('batiment', 'etage', 'service_gestionnaire')

    # Filtres
    statut = request.GET.get('statut', '')
    capacite_min = request.GET.get('capacite_min', '')
    equipement = request.GET.get('equipement', '')
    q = request.GET.get('q', '')

    if statut:
        salles = salles.filter(statut=statut)
    if capacite_min:
        salles = salles.filter(capacite__gte=int(capacite_min))
    if equipement == 'videoconf':
        salles = salles.filter(videoconf=True)
    elif equipement == 'ecran':
        salles = salles.filter(ecran_projecteur=True)
    elif equipement == 'wifi':
        salles = salles.filter(wifi=True)
    elif equipement == 'clim':
        salles = salles.filter(climatisation=True)
    if q:
        salles = salles.filter(Q(nom__icontains=q) | Q(code__icontains=q))

    # ── N+1 fix: une seule requête pour toutes les réservations aujourd'hui ──
    now = timezone.now()
    salle_ids = list(salles.values_list('id', flat=True))

    # Réservation en cours (CONFIRMEE, date_debut <= now <= date_fin)
    reservations_en_cours = {}
    reservations_today_count = {}
    if salle_ids:
        reservations_en_cours_qs = ReservationSalle.objects.filter(
            salle_id__in=salle_ids,
            statut='CONFIRMEE',
            date_debut__lte=now,
            date_fin__gte=now
        ).select_related('demandeur')
        for r in reservations_en_cours_qs:
            reservations_en_cours[r.salle_id] = r

        # Nombre de réservations aujourd'hui
        count_rows = (
            ReservationSalle.objects.filter(
                salle_id__in=salle_ids,
                statut__in=['EN_ATTENTE', 'CONFIRMEE'],
                date_debut__date=now.date()
            )
            .values('salle_id')
            .annotate(nb=Count('id'))
        )
        for row in count_rows:
            reservations_today_count[row['salle_id']] = row['nb']

    for salle in salles:
        salle.reservation_en_cours = reservations_en_cours.get(salle.id)
        salle.nb_reservations_today = reservations_today_count.get(salle.id, 0)

    stats = {
        'total': SalleConference.objects.count(),
        'disponibles': SalleConference.objects.filter(statut='DISPONIBLE').count(),
        'reservations_today': ReservationSalle.objects.filter(
            statut__in=['EN_ATTENTE', 'CONFIRMEE'],
            date_debut__date=now.date()
        ).count(),
    }

    return render(request, 'patrimoine/salles/liste.html', {
        'salles': salles,
        'stats': stats,
        'statut_filter': statut,
        'equipement_filter': equipement,
        'q': q,
    })


@verifier_permission_salle("accounts.menu_pat_salles")
def detail_salle(request, pk):
    """Détail d'une salle avec réservations à venir."""
    salle = get_object_or_404(
        SalleConference.objects.select_related('batiment', 'etage', 'bureau', 'service_gestionnaire'),
        pk=pk
    )

    now = timezone.now()

    # Réservations à venir (prochains 30 jours)
    reservations_avenir = ReservationSalle.objects.filter(
        salle=salle,
        statut__in=['EN_ATTENTE', 'CONFIRMEE'],
        date_fin__gte=now
    ).select_related('demandeur', 'service_demandeur').order_by('date_debut')[:20]

    reservation_en_cours = ReservationSalle.objects.filter(
        salle=salle, statut='CONFIRMEE',
        date_debut__lte=now, date_fin__gte=now
    ).select_related('demandeur').first()

    nb_reservations_mois = ReservationSalle.objects.filter(
        salle=salle,
        statut__in=['EN_ATTENTE', 'CONFIRMEE'],
        date_debut__date__gte=now.date().replace(day=1),
        date_debut__date__lte=now.date()
    ).count()

    # Calcul approximatif des heures réservées (en mémoire, 1 requête)
    reservations_mois = ReservationSalle.objects.filter(
        salle=salle, statut='CONFIRMEE',
        date_debut__date__gte=now.date().replace(day=1),
        date_debut__date__lte=now.date()
    )
    total_minutes = 0
    for r in reservations_mois:
        delta = r.date_fin - r.date_debut
        total_minutes += int(delta.total_seconds() / 60)
    nb_heures_reservees = {'total': total_minutes}

    occupation_mois = round(total_minutes / (30 * 8 * 60) * 100, 1) if total_minutes else 0

    return render(request, 'patrimoine/salles/detail.html', {
        'salle': salle,
        'reservations_avenir': reservations_avenir,
        'reservation_en_cours': reservation_en_cours,
        'nb_reservations_mois': nb_reservations_mois,
        'nb_heures_reservees': nb_heures_reservees.get('total') or 0,
        'occupation_mois': occupation_mois,
    })


@verifier_permission_salle("accounts.menu_pat_salles")
def creer_salle(request):
    """Créer une salle de conférence."""
    if request.method == 'POST':
        try:
            salle = SalleConference.objects.create(
                nom=request.POST.get('nom'),
                code=request.POST.get('code'),
                capacite=int(request.POST.get('capacite', 10)),
                description=request.POST.get('description', ''),
                videoconf='videoconf' in request.POST,
                ecran_projecteur='ecran' in request.POST,
                wifi='wifi' in request.POST,
                climatisation='clim' in request.POST,
                sonorisation='son' in request.POST,
                statut=request.POST.get('statut', 'DISPONIBLE'),
                service_gestionnaire_id=request.POST.get('service_gestionnaire') or None,
                batiment_id=request.POST.get('batiment') or None,
                etage_id=request.POST.get('etage') or None,
                bureau_id=request.POST.get('bureau') or None,
                cree_par=request.user,
                modifie_par=request.user,
            )
            messages.success(request, f'✅ Salle {salle.nom} créée avec succès.')
            return redirect('patrimoine_salle_detail', pk=salle.pk)
        except Exception as e:
            messages.error(request, f'❌ Erreur : {e}')

    from core.models import Service
    batiments = Batiment.objects.all().order_by('nom')
    services = Service.objects.all().order_by('nom')
    return render(request, 'patrimoine/salles/formulaire.html', {
        'salle': None,
        'batiments': batiments,
        'services': services,
    })


@verifier_permission_salle("accounts.menu_pat_salles")
def modifier_salle(request, pk):
    """Modifier une salle de conférence."""
    salle = get_object_or_404(SalleConference, pk=pk)

    if request.method == 'POST':
        try:
            salle.nom = request.POST.get('nom', salle.nom)
            salle.code = request.POST.get('code', salle.code)
            salle.capacite = int(request.POST.get('capacite', salle.capacite))
            salle.description = request.POST.get('description', salle.description)
            salle.videoconf = 'videoconf' in request.POST
            salle.ecran_projecteur = 'ecran' in request.POST
            salle.wifi = 'wifi' in request.POST
            salle.climatisation = 'clim' in request.POST
            salle.sonorisation = 'son' in request.POST
            salle.statut = request.POST.get('statut', salle.statut)
            salle.service_gestionnaire_id = request.POST.get('service_gestionnaire') or None
            salle.batiment_id = request.POST.get('batiment') or None
            salle.etage_id = request.POST.get('etage') or None
            salle.bureau_id = request.POST.get('bureau') or None
            salle.modifie_par = request.user
            salle.save()
            messages.success(request, f'✅ Salle {salle.nom} mise à jour.')
            return redirect('patrimoine_salle_detail', pk=salle.pk)
        except Exception as e:
            messages.error(request, f'❌ Erreur : {e}')

    from core.models import Service
    batiments = Batiment.objects.all().order_by('nom')
    services = Service.objects.all().order_by('nom')
    return render(request, 'patrimoine/salles/formulaire.html', {
        'salle': salle,
        'batiments': batiments,
        'services': services,
    })


@verifier_permission_salle("accounts.menu_pat_salles")
def calendrier_salles(request):
    """Calendrier hebdomadaire des réservations."""
    today = timezone.now().date()
    week_offset = int(request.GET.get('week', 0))
    start_week = today + timedelta(weeks=week_offset) - timedelta(days=today.weekday())
    end_week = start_week + timedelta(days=6)

    salles = SalleConference.objects.filter(statut='DISPONIBLE').order_by('nom')

    # ── N+1 fix: charger TOUTES les réservations de la semaine en une requête ──
    reservations_list = list(ReservationSalle.objects.filter(
        statut__in=['EN_ATTENTE', 'CONFIRMEE'],
        date_debut__date__gte=start_week,
        date_fin__date__lte=end_week
    ).select_related('salle', 'demandeur', 'service_demandeur'))

    # Organiser en mémoire par salle_id → jour
    cal_map = defaultdict(lambda: defaultdict(list))
    for r in reservations_list:
        # Calculer quels jours cette réservation couvre
        r_start = max(r.date_debut.date(), start_week)
        r_end = min(r.date_fin.date(), end_week)
        d = r_start
        while d <= r_end:
            cal_map[r.salle_id][d].append(r)
            d += timedelta(days=1)

    calendrier = {}
    for salle in salles:
        calendrier[salle.pk] = {
            'salle': salle,
            'jours': {}
        }
        for i in range(7):
            jour = start_week + timedelta(days=i)
            calendrier[salle.pk]['jours'][jour] = cal_map[salle.pk].get(jour, [])

    # Index du jour today dans la semaine
    today_index = -1
    dates_journee = []
    for i in range(7):
        d = start_week + timedelta(days=i)
        dates_journee.append(d)
        if d == today:
            today_index = i

    total_reservations = len(reservations_list)
    nb_confirmees = sum(1 for r in reservations_list if r.statut == 'CONFIRMEE')
    nb_en_attente = sum(1 for r in reservations_list if r.statut == 'EN_ATTENTE')

    return render(request, 'patrimoine/salles/calendrier.html', {
        'calendrier': calendrier,
        'salles': salles,
        'start_week': start_week,
        'end_week': end_week,
        'week_offset': week_offset,
        'jours_semaine': ['Lundi', 'Mardi', 'Mercredi', 'Jeudi', 'Vendredi', 'Samedi', 'Dimanche'],
        'today_index': today_index,
        'dates_journee': dates_journee,
        'total_reservations': total_reservations,
        'nb_confirmees': nb_confirmees,
        'nb_en_attente': nb_en_attente,
    })


@verifier_permission_salle("accounts.menu_pat_salles")
def liste_reservations(request):
    """Liste des réservations avec filtres."""
    reservations = ReservationSalle.objects.select_related('salle', 'demandeur', 'service_demandeur')

    # Filtres
    statut = request.GET.get('statut', '')
    salle_id = request.GET.get('salle', '')
    date_debut = request.GET.get('date_debut', '')
    date_fin = request.GET.get('date_fin', '')

    if statut:
        reservations = reservations.filter(statut=statut)
    if salle_id:
        reservations = reservations.filter(salle_id=salle_id)
    if date_debut:
        reservations = reservations.filter(date_debut__date__gte=date_debut)
    if date_fin:
        reservations = reservations.filter(date_fin__date__lte=date_fin)

    paginator = Paginator(reservations, 20)
    page = request.GET.get('page')
    reservations = paginator.get_page(page)

    salles = SalleConference.objects.filter(statut='DISPONIBLE').order_by('nom')

    return render(request, 'patrimoine/salles/reservations.html', {
        'reservations': reservations,
        'salles': salles,
        'statut_filter': statut,
        'salle_filter': salle_id,
    })


@verifier_permission_salle("accounts.menu_pat_salles")
def creer_reservation(request):
    """Créer une réservation de salle."""
    salle_preselect = request.GET.get('salle', '')

    if request.method == 'POST':
        try:
            salle = get_object_or_404(SalleConference, pk=request.POST.get('salle'))
            date_debut = datetime.strptime(request.POST.get('date_debut'), '%Y-%m-%dT%H:%M')
            date_fin = datetime.strptime(request.POST.get('date_fin'), '%Y-%m-%dT%H:%M')

            # Vérifier les conflits
            conflits = ReservationSalle.objects.filter(
                salle=salle,
                statut__in=['EN_ATTENTE', 'CONFIRMEE'],
                date_debut__lt=date_fin,
                date_fin__gt=date_debut
            )
            if conflits.exists():
                messages.warning(request, f'⚠️ Attention : {conflits.count()} réservation(s) en conflit détectée(s) !')

            service_id = request.POST.get('service_demandeur') or None
            reservation = ReservationSalle.objects.create(
                salle=salle,
                demandeur=request.user,
                service_demandeur_id=service_id,
                objet=request.POST.get('objet'),
                description=request.POST.get('description', ''),
                nb_participants=int(request.POST.get('nb_participants', 1)),
                date_debut=date_debut,
                date_fin=date_fin,
                statut='EN_ATTENTE',
                besoin_videoconf='videoconf' in request.POST,
                besoin_video='video' in request.POST,
                besoin_son='son' in request.POST,
                notes_equipement=request.POST.get('notes_equipement', ''),
                cree_par=request.user,
                modifie_par=request.user,
            )
            messages.success(request, f'✅ Réservation créée : {reservation.objet} le {reservation.date_debut.strftime("%d/%m/%Y %H:%M")}')
            return redirect('patrimoine_reservations')

        except Exception as e:
            messages.error(request, f'❌ Erreur : {e}')

    from core.models import Service
    salles = SalleConference.objects.filter(statut='DISPONIBLE').order_by('nom')
    services = Service.objects.all().order_by('nom')
    return render(request, 'patrimoine/salles/formulaire_reservation.html', {
        'salles': salles,
        'services': services,
        'salle_preselect': salle_preselect,
    })


@verifier_permission_salle("accounts.menu_pat_salles")
def detail_reservation(request, pk):
    """Détail d'une réservation."""
    reservation = get_object_or_404(
        ReservationSalle.objects.select_related('salle', 'demandeur', 'service_demandeur', 'valide_par'),
        pk=pk
    )
    return render(request, 'patrimoine/salles/detail_reservation.html', {
        'reservation': reservation,
    })


@verifier_permission_salle("accounts.menu_pat_salles")
def valider_reservation(request, pk):
    """Valider ou refuser une réservation."""
    reservation = get_object_or_404(ReservationSalle, pk=pk)
    
    if request.method == 'POST':
        action = request.POST.get('action', '')
        if action == 'valider':
            reservation.statut = 'CONFIRMEE'
            reservation.valide_par = request.user
            reservation.date_validation = timezone.now()
            reservation.save()
            messages.success(request, f'✅ Réservation confirmée : {reservation.objet}')
        elif action == 'refuser':
            reservation.statut = 'ANNULEE'
            reservation.motif_refus = request.POST.get('motif_refus', '')
            reservation.valide_par = request.user
            reservation.date_validation = timezone.now()
            reservation.save()
            messages.warning(request, f'🚫 Réservation refusée : {reservation.objet}')
    
    return redirect('patrimoine_reservation_detail', pk=pk)


@verifier_permission_salle("accounts.menu_pat_salles")
def annuler_reservation(request, pk):
    """Annuler une réservation."""
    reservation = get_object_or_404(ReservationSalle, pk=pk)
    
    if request.method in ('POST', 'GET'):
        reservation.statut = 'ANNULEE'
        reservation.save()
        messages.warning(request, f'🚫 Réservation annulée : {reservation.objet}')
    
    return redirect('patrimoine_reservations')


@verifier_permission_salle("accounts.menu_pat_salles")
def supprimer_reservation(request, pk):
    """Supprimer une réservation."""
    reservation = get_object_or_404(ReservationSalle, pk=pk)
    reservation.delete()
    messages.warning(request, '🗑️ Réservation supprimée.')
    return redirect('patrimoine_reservations')


# ── AJAX endpoints ──

@login_required
def ajax_etages(request):
    """Retourne les étages d'un bâtiment (JSON)."""
    batiment_id = request.GET.get('batiment_id')
    if not batiment_id:
        return JsonResponse({'etages': []})
    etages = Etage.objects.filter(batiment_id=batiment_id).order_by('nom')
    return JsonResponse({
        'etages': [{'id': e.id, 'nom': e.nom} for e in etages]
    })


@login_required
def ajax_bureaux(request):
    """Retourne les bureaux d'un étage (JSON)."""
    etage_id = request.GET.get('etage_id')
    if not etage_id:
        return JsonResponse({'bureaux': []})
    bureaux = Bureau.objects.filter(etage_id=etage_id).order_by('nom')
    return JsonResponse({
        'bureaux': [{'id': b.id, 'nom': b.nom} for b in bureaux]
    })


# ── Aliases pour compatibilité URLs / __init__.py ──

calendrier_reservations = calendrier_salles


@verifier_permission_salle("accounts.menu_pat_salles")
def supprimer_salle(request, pk):
    """Supprimer une salle de conférence."""
    salle = get_object_or_404(SalleConference, pk=pk)
    salle.delete()
    messages.warning(request, '🗑️ Salle supprimée.')
    return redirect('patrimoine_salles')


@login_required
def ajax_disponibilite_salle(request):
    """Vérifie la disponibilité d'une salle sur une période (JSON)."""
    salle_id = request.GET.get('salle_id')
    date_debut = request.GET.get('date_debut')
    date_fin = request.GET.get('date_fin')

    if not all([salle_id, date_debut, date_fin]):
        return JsonResponse({'disponible': False, 'erreur': 'Paramètres manquants'})

    conflits = ReservationSalle.objects.filter(
        salle_id=salle_id,
        statut__in=['EN_ATTENTE', 'CONFIRMEE'],
        date_debut__lt=date_fin,
        date_fin__gt=date_debut
    ).count()

    return JsonResponse({'disponible': conflits == 0, 'conflits': conflits})


@login_required
def ajax_reservations_salle(request):
    """Retourne les réservations d'une salle pour FullCalendar (JSON)."""
    salle_id = request.GET.get('salle_id')
    start = request.GET.get('start')
    end = request.GET.get('end')

    qs = ReservationSalle.objects.filter(
        statut__in=['EN_ATTENTE', 'CONFIRMEE']
    ).select_related('salle', 'demandeur')

    if salle_id:
        qs = qs.filter(salle_id=salle_id)
    if start:
        qs = qs.filter(date_debut__gte=start)
    if end:
        qs = qs.filter(date_fin__lte=end)

    events = []
    for r in qs:
        events.append({
            'id': r.id,
            'title': r.objet,
            'start': r.date_debut.isoformat(),
            'end': r.date_fin.isoformat(),
            'color': '#059669' if r.statut == 'CONFIRMEE' else '#f59e0b',
            'extendedProps': {
                'salle': r.salle.nom,
                'demandeur': r.demandeur.get_full_name() if r.demandeur else '',
                'statut': r.statut,
            }
        })

    return JsonResponse(events, safe=False)


# Aliases pour compatibilité URLs
ajax_etages_salle = ajax_etages
ajax_bureaux_salle = ajax_bureaux
