# -*- coding: utf-8 -*-
"""Vues de gestion des salles de conférence."""
import json
from datetime import timedelta

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Q, Count
from django.core.paginator import Paginator

from ..models import SalleConference, ReservationSalle, Batiment, Etage, Bureau
from ..views.common import patrimoine_required


@login_required
@patrimoine_required
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
    
    # Disponibilité en temps réel
    now = timezone.now()
    for salle in salles:
        salle.reservation_en_cours = ReservationSalle.objects.filter(
            salle=salle,
            statut='CONFIRMEE',
            date_debut__lte=now,
            date_fin__gte=now
        ).first()
        salle.nb_reservations_today = ReservationSalle.objects.filter(
            salle=salle,
            statut__in=['EN_ATTENTE', 'CONFIRMEE'],
            date_debut__date=now.date()
        ).count()
    
    stats = {
        'total': SalleConference.objects.count(),
        'disponibles': SalleConference.objects.filter(statut='DISPONIBLE').count(),
        'reservations_today': ReservationSalle.objects.filter(
            statut__in=['EN_ATTENTE', 'CONFIRMEE'],
            date_debut__date=now.date()
        ).count(),
        'en_attente': ReservationSalle.objects.filter(statut='EN_ATTENTE').count(),
    }
    
    paginator = Paginator(salles, 20)
    page = request.GET.get('page')
    salles = paginator.get_page(page)
    
    return render(request, 'patrimoine/salles/liste.html', {
        'salles': salles,
        'stats': stats,
        'statut_filter': statut,
        'capacite_min': capacite_min,
        'equipement_filter': equipement,
        'q': q,
    })


@login_required
@patrimoine_required
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
    
    # Réservation en cours
    reservation_en_cours = ReservationSalle.objects.filter(
        salle=salle,
        statut='CONFIRMEE',
        date_debut__lte=now,
        date_fin__gte=now
    ).first()
    
    # Statistiques
    mois_actuel = now.month
    annee_actuelle = now.year
    nb_reservations_mois = ReservationSalle.objects.filter(
        salle=salle,
        date_debut__month=mois_actuel,
        date_debut__year=annee_actuelle,
        statut__in=['CONFIRMEE', 'TERMINEE']
    ).count()
    
    taux_occupation = 0
    if nb_reservations_mois > 0:
        # Calcul approximatif : nb réservations × durée moyenne / (heures ouvrables × jours)
        nb_heures_reservees = ReservationSalle.objects.filter(
            salle=salle,
            date_debut__month=mois_actuel,
            date_debut__year=annee_actuelle,
            statut__in=['CONFIRMEE', 'TERMINEE']
        ).aggregate(
            total=Count('id')
        )['total'] or 0
        taux_occupation = min(100, round(nb_heures_reservees / 20 * 100))  # 20 créneaux/jour max
    
    return render(request, 'patrimoine/salles/detail.html', {
        'salle': salle,
        'reservations_avenir': reservations_avenir,
        'reservation_en_cours': reservation_en_cours,
        'nb_reservations_mois': nb_reservations_mois,
        'taux_occupation': taux_occupation,
    })


@login_required
@patrimoine_required
def creer_salle(request):
    """Créer une nouvelle salle de conférence."""
    if request.method == 'POST':
        try:
            salle = SalleConference(
                nom=request.POST.get('nom', '').strip(),
                code=request.POST.get('code', '').strip(),
                capacite=int(request.POST.get('capacite', 10) or 10),
                superficie_m2=int(request.POST['superficie_m2']) if request.POST.get('superficie_m2') else None,
                description=request.POST.get('description', ''),
                videoconf='videoconf' in request.POST,
                ecran_projecteur='ecran_projecteur' in request.POST,
                tableau_blanc='tableau_blanc' in request.POST,
                wifi='wifi' in request.POST,
                climatisation='climatisation' in request.POST,
                sonorisation='sonorisation' in request.POST,
                micro='micro' in request.POST,
                statut=request.POST.get('statut', 'DISPONIBLE'),
                notes=request.POST.get('notes', ''),
                cree_par=request.user,
                modifie_par=request.user,
            )
            
            # Localisation
            batiment_id = request.POST.get('batiment')
            if batiment_id:
                salle.batiment_id = int(batiment_id)
            etage_id = request.POST.get('etage')
            if etage_id:
                salle.etage_id = int(etage_id)
            bureau_id = request.POST.get('bureau')
            if bureau_id:
                salle.bureau_id = int(bureau_id)
            
            # Service
            service_id = request.POST.get('service_gestionnaire')
            if service_id:
                salle.service_gestionnaire_id = int(service_id)
            
            salle.save()
            messages.success(request, f'✅ Salle {salle.nom} créée avec succès.')
            return redirect('patrimoine_salle_detail', pk=salle.pk)
            
        except Exception as e:
            messages.error(request, f'❌ Erreur : {e}')
    
    batiments = Batiment.objects.all().order_by('nom')
    return render(request, 'patrimoine/salles/formulaire.html', {
        'salle': None,
        'batiments': batiments,
    })


@login_required
@patrimoine_required
def modifier_salle(request, pk):
    """Modifier une salle existante."""
    salle = get_object_or_404(SalleConference, pk=pk)
    
    if request.method == 'POST':
        try:
            salle.nom = request.POST.get('nom', salle.nom)
            salle.code = request.POST.get('code', salle.code)
            salle.capacite = int(request.POST.get('capacite', salle.capacite) or 10)
            salle.superficie_m2 = int(request.POST['superficie_m2']) if request.POST.get('superficie_m2') else None
            salle.description = request.POST.get('description', '')
            salle.videoconf = 'videoconf' in request.POST
            salle.ecran_projecteur = 'ecran_projecteur' in request.POST
            salle.tableau_blanc = 'tableau_blanc' in request.POST
            salle.wifi = 'wifi' in request.POST
            salle.climatisation = 'climatisation' in request.POST
            salle.sonorisation = 'sonorisation' in request.POST
            salle.micro = 'micro' in request.POST
            salle.statut = request.POST.get('statut', salle.statut)
            salle.notes = request.POST.get('notes', '')
            salle.modifie_par = request.user
            
            batiment_id = request.POST.get('batiment')
            salle.batiment_id = int(batiment_id) if batiment_id else None
            etage_id = request.POST.get('etage')
            salle.etage_id = int(etage_id) if etage_id else None
            bureau_id = request.POST.get('bureau')
            salle.bureau_id = int(bureau_id) if bureau_id else None
            service_id = request.POST.get('service_gestionnaire')
            salle.service_gestionnaire_id = int(service_id) if service_id else None
            
            salle.save()
            messages.success(request, f'✅ Salle {salle.nom} mise à jour.')
            return redirect('patrimoine_salle_detail', pk=salle.pk)
            
        except Exception as e:
            messages.error(request, f'❌ Erreur : {e}')
    
    batiments = Batiment.objects.all().order_by('nom')
    return render(request, 'patrimoine/salles/formulaire.html', {
        'salle': salle,
        'batiments': batiments,
    })


@login_required
@patrimoine_required
def supprimer_salle(request, pk):
    """Supprimer une salle."""
    salle = get_object_or_404(SalleConference, pk=pk)
    if request.method == 'POST':
        nom = salle.nom
        salle.delete()
        messages.success(request, f'🗑️ Salle {nom} supprimée.')
        return redirect('patrimoine_salles')
    return redirect('patrimoine_salle_detail', pk=pk)


# ─── Réservations ─────────────────────────────────────────

@login_required
@patrimoine_required
def calendrier_reservations(request):
    """Vue calendrier des réservations de toutes les salles."""
    now = timezone.now()
    
    # Période affichée (semaine courante par défaut)
    today = now.date()
    start_week = today - timedelta(days=today.weekday())  # Lundi
    end_week = start_week + timedelta(days=6)  # Dimanche
    
    # Filtre par semaine
    week_offset = int(request.GET.get('week', 0))
    start_week += timedelta(weeks=week_offset)
    end_week += timedelta(weeks=week_offset)
    
    salles = SalleConference.objects.filter(statut='DISPONIBLE').order_by('nom')
    
    # Réservations de la semaine
    reservations = ReservationSalle.objects.filter(
        statut__in=['EN_ATTENTE', 'CONFIRMEE'],
        date_debut__date__gte=start_week,
        date_fin__date__lte=end_week
    ).select_related('salle', 'demandeur', 'service_demandeur')
    
    # Organisation par salle et jour
    calendrier = {}
    for salle in salles:
        calendrier[salle.pk] = {
            'salle': salle,
            'jours': {}
        }
        for i in range(7):
            jour = start_week + timedelta(days=i)
            calendrier[salle.pk]['jours'][jour] = reservations.filter(
                salle=salle,
                date_debut__date__lte=jour,
                date_fin__date__gte=jour
            )
    
    # Index du jour today dans la semaine
    today_index = -1
    dates_journee = []
    for i in range(7):
        d = start_week + timedelta(days=i)
        dates_journee.append(d)
        if d == today:
            today_index = i

    # Stats
    all_reservations_week = ReservationSalle.objects.filter(
        date_debut__date__gte=start_week,
        date_fin__date__lte=end_week
    )
    total_reservations = all_reservations_week.count()
    nb_confirmees = all_reservations_week.filter(statut='CONFIRMEE').count()
    nb_en_attente = all_reservations_week.filter(statut='EN_ATTENTE').count()

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


@login_required
@patrimoine_required
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


@login_required
@patrimoine_required
def creer_reservation(request):
    """Créer une réservation de salle."""
    salle_preselect = request.GET.get('salle', '')
    
    if request.method == 'POST':
        try:
            salle = get_object_or_404(SalleConference, pk=request.POST.get('salle'))
            
            reservation = ReservationSalle(
                salle=salle,
                demandeur=request.user,
                objet=request.POST.get('objet', '').strip(),
                description=request.POST.get('description', ''),
                nb_participants=int(request.POST.get('nb_participants', 1) or 1),
                date_debut=request.POST.get('date_debut'),
                date_fin=request.POST.get('date_fin'),
                recurrente='recurrente' in request.POST,
                frequence=request.POST.get('frequence', ''),
                besoin_videoconf='besoin_videoconf' in request.POST,
                besoin_video='besoin_video' in request.POST,
                besoin_son='besoin_son' in request.POST,
                notes_equipement=request.POST.get('notes_equipement', ''),
                cree_par=request.user,
                modifie_par=request.user,
            )
            
            service_id = request.POST.get('service_demandeur')
            if service_id:
                reservation.service_demandeur_id = int(service_id)
            
            reservation.save()
            
            # Vérifier les conflits
            conflits = reservation.conflits
            if conflits.exists():
                messages.warning(request, f'⚠️ Attention : {conflits.count()} réservation(s) en conflit détectée(s) !')
            
            messages.success(request, f'✅ Réservation créée : {reservation.objet} le {reservation.date_debut.strftime("%d/%m/%Y %H:%M")}')
            return redirect('patrimoine_reservations')
            
        except Exception as e:
            messages.error(request, f'❌ Erreur : {e}')
    
    salles = SalleConference.objects.filter(statut='DISPONIBLE').order_by('nom')
    return render(request, 'patrimoine/salles/formulaire_reservation.html', {
        'salles': salles,
        'salle_preselect': salle_preselect,
    })


@login_required
@patrimoine_required
def detail_reservation(request, pk):
    """Détail d'une réservation."""
    reservation = get_object_or_404(
        ReservationSalle.objects.select_related('salle', 'demandeur', 'service_demandeur', 'valide_par'),
        pk=pk
    )
    return render(request, 'patrimoine/salles/detail_reservation.html', {
        'reservation': reservation,
    })


@login_required
@patrimoine_required
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


@login_required
@patrimoine_required
def annuler_reservation(request, pk):
    """Annuler une réservation."""
    reservation = get_object_or_404(ReservationSalle, pk=pk)
    
    if request.method == 'POST':
        reservation.statut = 'ANNULEE'
        reservation.save()
        messages.warning(request, f'🚫 Réservation annulée : {reservation.objet}')
    
    return redirect('patrimoine_reservations')


# ─── AJAX ─────────────────────────────────────────────────

@login_required
def ajax_disponibilite_salle(request):
    """Vérifie la disponibilité d'une salle pour une plage horaire."""
    salle_id = request.GET.get('salle_id')
    debut = request.GET.get('debut')
    fin = request.GET.get('fin')
    
    if not all([salle_id, debut, fin]):
        return JsonResponse({'disponible': False, 'error': 'Paramètres manquants'})
    
    from django.utils.dateparse import parse_datetime
    debut_dt = parse_datetime(debut)
    fin_dt = parse_datetime(fin)
    
    if not debut_dt or not fin_dt:
        return JsonResponse({'disponible': False, 'error': 'Format de date invalide'})
    
    conflits = ReservationSalle.objects.filter(
        salle_id=salle_id,
        statut__in=['EN_ATTENTE', 'CONFIRMEE'],
        date_debut__lt=fin_dt,
        date_fin__gt=debut_dt
    ).count()
    
    return JsonResponse({
        'disponible': conflits == 0,
        'conflits': conflits,
    })


@login_required
def ajax_reservations_salle(request):
    """Retourne les réservations d'une salle pour le calendrier (FullCalendar)."""
    salle_id = request.GET.get('salle_id')
    start = request.GET.get('start')
    end = request.GET.get('end')
    
    qs = ReservationSalle.objects.filter(statut__in=['EN_ATTENTE', 'CONFIRMEE'])
    if salle_id:
        qs = qs.filter(salle_id=salle_id)
    if start:
        qs = qs.filter(date_fin__gte=start)
    if end:
        qs = qs.filter(date_debut__lte=end)
    
    events = []
    for r in qs.select_related('salle', 'demandeur'):
        events.append({
            'id': r.pk,
            'title': f'{r.salle.nom} — {r.objet}',
            'start': r.date_debut.isoformat(),
            'end': r.date_fin.isoformat(),
            'color': '#28a745' if r.statut == 'CONFIRMEE' else '#ffc107',
            'url': f'/patrimoine/salles/reservations/{r.pk}/',
            'extendedProps': {
                'salle': r.salle.nom,
                'demandeur': r.demandeur.get_full_name() if r.demandeur else '',
                'nb_participants': r.nb_participants,
                'statut': r.statut,
            }
        })
    
    return JsonResponse(events, safe=False)


@login_required
def ajax_etages_salle(request):
    """Retourne les étages d'un bâtiment pour le formulaire salle."""
    batiment_id = request.GET.get('batiment_id')
    if not batiment_id:
        return JsonResponse({'etages': []})
    
    etages = Etage.objects.filter(batiment_id=batiment_id).order_by('ordre', 'nom').values('id', 'nom')
    return JsonResponse({'etages': list(etages)})


@login_required
def ajax_bureaux_salle(request):
    """Retourne les bureaux d'un étage pour le formulaire salle."""
    etage_id = request.GET.get('etage_id')
    if not etage_id:
        return JsonResponse({'bureaux': []})
    
    bureaux = Bureau.objects.filter(etage_id=etage_id).order_by('nom').values('id', 'nom')
    return JsonResponse({'bureaux': list(bureaux)})
