# -*- coding: utf-8 -*-
"""Vues pour les demandes de véhicules et salles par les utilisateurs."""
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db import transaction
from django.db.models import Q, Count
from django.core.paginator import Paginator

from core.models import Service
from ..models import (
    DemandeVehicule, DemandeSalle, Vehicule, SalleConference, ReservationSalle
)
from ..views.common import patrimoine_required


# ═══════════════════════════════════════════════════════════
# DEMANDES DE VÉHICULES
# ═══════════════════════════════════════════════════════════

@login_required
def mes_demandes_vehicule(request):
    """Mes demandes de véhicule."""
    demandes = DemandeVehicule.objects.filter(demandeur=request.user).select_related(
        'vehicule', 'chauffeur', 'service_demandeur'
    )
    statut = request.GET.get('statut', '')
    if statut:
        demandes = demandes.filter(statut=statut)

    stats = {
        'total': demandes.count(),
        'en_attente': demandes.filter(statut='EN_ATTENTE').count(),
        'validees': demandes.filter(statut='VALIDEE').count(),
    }

    paginator = Paginator(demandes, 15)
    page = request.GET.get('page')
    demandes = paginator.get_page(page)

    services = Service.objects.all().order_by('nom')
    return render(request, 'patrimoine/vehicules/mes_demandes.html', {
        'demandes': demandes,
        'stats': stats,
        'statut_filter': statut,
        'services': services,
    })


@login_required
def creer_demande_vehicule(request):
    """Créer une demande de véhicule."""
    if request.method == 'POST':
        try:
            demande = DemandeVehicule(
                demandeur=request.user,
                objet=request.POST.get('objet', '').strip(),
                destination=request.POST.get('destination', '').strip(),
                date_depart=request.POST.get('date_depart'),
                date_retour_prevue=request.POST.get('date_retour_prevue'),
                nb_passagers=int(request.POST.get('nb_passagers', 1) or 1),
                urgency=request.POST.get('urgency', 'NORMALE'),
                motif=request.POST.get('motif', ''),
                cree_par=request.user,
                modifie_par=request.user,
            )
            service_id = request.POST.get('service_demandeur')
            if service_id:
                demande.service_demandeur_id = int(service_id)
            demande.save()
            messages.success(request, '✅ Demande de véhicule envoyée avec succès.')
            return redirect('patrimoine_mes_demandes_vehicule')
        except Exception as e:
            messages.error(request, f'❌ Erreur : {e}')

    services = Service.objects.all().order_by('nom')
    return render(request, 'patrimoine/vehicules/creer_demande.html', {
        'services': services,
    })


@login_required
def detail_demande_vehicule(request, pk):
    """Détail d'une demande de véhicule."""
    demande = get_object_or_404(
        DemandeVehicule.objects.select_related('vehicule', 'chauffeur', 'demandeur', 'valide_par', 'service_demandeur'),
        pk=pk
    )
    # Seul le demandeur ou un validateur peut voir
    if not (request.user == demande.demandeur or request.user.is_superuser or request.user.has_perm('accounts.menu_pat_tickets')):
        messages.error(request, "⛔ Accès non autorisé.")
        return redirect('patrimoine_mes_demandes_vehicule')

    return render(request, 'patrimoine/vehicules/detail_demande.html', {
        'demande': demande,
    })


@login_required
def annuler_demande_vehicule(request, pk):
    """Annuler une demande de véhicule."""
    demande = get_object_or_404(DemandeVehicule, pk=pk, demandeur=request.user)
    if demande.statut == 'EN_ATTENTE':
        demande.statut = 'ANNULEE'
        demande.save(update_fields=['statut'])
        messages.warning(request, '🚫 Demande annulée.')
    else:
        messages.error(request, '❌ Impossible d\'annuler cette demande.')
    return redirect('patrimoine_mes_demandes_vehicule')


@login_required
@patrimoine_required
def demandes_vehicule_a_valider(request):
    """Liste des demandes de véhicule en attente de validation (validateurs)."""
    if not (request.user.is_superuser or request.user.is_staff
            or request.user.has_perm('accounts.menu_pat_vehicules_valider')):
        messages.error(request, "⛔ Accès non autorisé.")
        return redirect('patrimoine_vehicules')
    demandes = DemandeVehicule.objects.filter(
        statut='EN_ATTENTE'
    ).select_related('demandeur', 'service_demandeur')

    paginator = Paginator(demandes, 15)
    page = request.GET.get('page')
    demandes = paginator.get_page(page)

    return render(request, 'patrimoine/vehicules/demandes_a_valider.html', {
        'demandes': demandes,
    })


@login_required
@patrimoine_required
def valider_demande_vehicule(request, pk):
    """Valider ou refuser une demande de véhicule."""
    if not (request.user.is_superuser or request.user.is_staff
            or request.user.has_perm('accounts.menu_pat_vehicules_valider')):
        messages.error(request, "⛔ Accès non autorisé — permission de validation requise.")
        return redirect('patrimoine_vehicules')
    demande = get_object_or_404(DemandeVehicule, pk=pk)

    if request.method == 'POST':
        action = request.POST.get('action', '')

        if action == 'valider':
            vehicule_id = request.POST.get('vehicule')
            chauffeur_id = request.POST.get('chauffeur')
            
            if not vehicule_id:
                messages.error(request, '❌ Veuillez sélectionner un véhicule.')
                return redirect('patrimoine_valider_demande_vehicule', pk=pk)
            
            demande.vehicule_id = int(vehicule_id)
            if chauffeur_id:
                try:
                    from django.contrib.auth.models import User
                    demande.chauffeur_id = int(chauffeur_id)
                except (ValueError, User.DoesNotExist):
                    pass
            demande.statut = 'VALIDEE'
            demande.valide_par = request.user
            demande.date_validation = timezone.now()
            demande.commentaire_valider = request.POST.get('commentaire', '')
            demande.km_depart = int(request.POST['km_depart']) if request.POST.get('km_depart') else None
            demande.save()
            messages.success(request, f'✅ Demande validée — Véhicule {demande.vehicule.immatriculation} affecté.')
            return redirect('patrimoine_detail_demande_vehicule', pk=pk)

        elif action == 'refuser':
            demande.statut = 'REFUSEE'
            demande.valide_par = request.user
            demande.date_validation = timezone.now()
            demande.motif_refus = request.POST.get('motif_refus', '')
            demande.save()
            messages.warning(request, '🚫 Demande refusée.')
            return redirect('patrimoine_detail_demande_vehicule', pk=pk)

        elif action == 'retour':
            demande.statut = 'TERMINEE'
            demande.km_retour = int(request.POST['km_retour']) if request.POST.get('km_retour') else None
            demande.observation_retour = request.POST.get('observation_retour', '')
            demande.modifie_par = request.user
            demande.save()
            messages.success(request, '✅ Véhicule rendu — Mission terminée.')
            return redirect('patrimoine_detail_demande_vehicule', pk=pk)

    # GET : Afficher le formulaire de validation avec véhicules disponibles
    vehicules_dispo = Vehicule.objects.filter(statut='DISPONIBLE').select_related('marque', 'modele')
    return render(request, 'patrimoine/vehicules/valider_demande.html', {
        'demande': demande,
        'vehicules_dispo': vehicules_dispo,
    })


# ═══════════════════════════════════════════════════════════
# DEMANDES DE SALLES (simplifiées)
# ═══════════════════════════════════════════════════════════

@login_required
def mes_demandes_salle(request):
    """Mes demandes de salle."""
    demandes = DemandeSalle.objects.filter(demandeur=request.user).select_related(
        'salle_preferee', 'salle_attribuee', 'valide_par'
    )
    statut = request.GET.get('statut', '')
    if statut:
        demandes = demandes.filter(statut=statut)

    stats = {
        'total': demandes.count(),
        'en_attente': demandes.filter(statut='EN_ATTENTE').count(),
        'validees': demandes.filter(statut='VALIDEE').count(),
    }

    paginator = Paginator(demandes, 15)
    page = request.GET.get('page')
    demandes = paginator.get_page(page)

    salles = SalleConference.objects.filter(statut='DISPONIBLE').order_by('nom')
    services = Service.objects.all().order_by('nom')
    return render(request, 'patrimoine/salles/mes_demandes.html', {
        'demandes': demandes,
        'stats': stats,
        'statut_filter': statut,
        'salles': salles,
        'services': services,
    })


@login_required
def creer_demande_salle(request):
    """Créer une demande de salle."""
    if request.method == 'POST':
        try:
            demande = DemandeSalle(
                demandeur=request.user,
                objet=request.POST.get('objet', '').strip(),
                description=request.POST.get('description', ''),
                date_debut=request.POST.get('date_debut'),
                date_fin=request.POST.get('date_fin'),
                nb_participants=int(request.POST.get('nb_participants', 1) or 1),
                besoin_videoconf='besoin_videoconf' in request.POST,
                besoin_video='besoin_video' in request.POST,
                besoin_son='besoin_son' in request.POST,
                notes_equipement=request.POST.get('notes_equipement', ''),
                cree_par=request.user,
                modifie_par=request.user,
            )
            service_id = request.POST.get('service_demandeur')
            if service_id:
                demande.service_demandeur_id = int(service_id)
            salle_id = request.POST.get('salle_preferee')
            if salle_id:
                demande.salle_preferee_id = int(salle_id)
            demande.save()
            messages.success(request, '✅ Demande de salle envoyée avec succès.')
            return redirect('patrimoine_mes_demandes_salle')
        except Exception as e:
            messages.error(request, f'❌ Erreur : {e}')

    salles = SalleConference.objects.filter(statut='DISPONIBLE').order_by('nom')
    services = Service.objects.all().order_by('nom')
    return render(request, 'patrimoine/salles/creer_demande.html', {
        'salles': salles,
        'services': services,
    })


@login_required
def detail_demande_salle(request, pk):
    """Détail d'une demande de salle."""
    demande = get_object_or_404(
        DemandeSalle.objects.select_related('salle_preferee', 'salle_attribuee', 'demandeur', 'valide_par'),
        pk=pk
    )
    if not (request.user == demande.demandeur or request.user.is_superuser or request.user.has_perm('accounts.menu_pat_tickets')):
        messages.error(request, "⛔ Accès non autorisé.")
        return redirect('patrimoine_mes_demandes_salle')

    return render(request, 'patrimoine/salles/detail_demande.html', {
        'demande': demande,
    })


@login_required
def annuler_demande_salle(request, pk):
    """Annuler une demande de salle."""
    demande = get_object_or_404(DemandeSalle, pk=pk, demandeur=request.user)
    if demande.statut == 'EN_ATTENTE':
        demande.statut = 'ANNULEE'
        demande.save(update_fields=['statut'])
        messages.warning(request, '🚫 Demande annulée.')
    else:
        messages.error(request, '❌ Impossible d\'annuler cette demande.')
    return redirect('patrimoine_mes_demandes_salle')


@login_required
@patrimoine_required
def demandes_salle_a_valider(request):
    """Liste des demandes de salle en attente de validation."""
    if not (request.user.is_superuser or request.user.is_staff
            or request.user.has_perm('accounts.menu_pat_salles_valider')):
        messages.error(request, "⛔ Accès non autorisé.")
        return redirect('patrimoine_salles')
    demandes = DemandeSalle.objects.filter(
        statut='EN_ATTENTE'
    ).select_related('demandeur', 'service_demandeur', 'salle_preferee')

    paginator = Paginator(demandes, 15)
    page = request.GET.get('page')
    demandes = paginator.get_page(page)

    return render(request, 'patrimoine/salles/demandes_a_valider.html', {
        'demandes': demandes,
    })


@login_required
@patrimoine_required
def valider_demande_salle(request, pk):
    """Valider ou refuser une demande de salle → crée une réservation."""
    if not (request.user.is_superuser or request.user.is_staff
            or request.user.has_perm('accounts.menu_pat_salles_valider')):
        messages.error(request, "⛔ Accès non autorisé — permission de validation requise.")
        return redirect('patrimoine_salles')
    demande = get_object_or_404(DemandeSalle, pk=pk)

    if request.method == 'POST':
        action = request.POST.get('action', '')

        if action == 'valider':
            salle_id = request.POST.get('salle')
            if not salle_id:
                messages.error(request, '❌ Veuillez sélectionner une salle.')
                return redirect('patrimoine_valider_demande_salle', pk=pk)

            salle = get_object_or_404(SalleConference, pk=salle_id)

            # Transaction atomique : la demande ET la réservation sont créées
            # ensemble, ou rien n'est modifié. Un conflit sur la période bloque
            # la validation (pas de double réservation).
            with transaction.atomic():
                conflit = ReservationSalle.objects.filter(
                    salle=salle,
                    statut__in=['EN_ATTENTE', 'CONFIRMEE'],
                    date_debut__lt=demande.date_fin,
                    date_fin__gt=demande.date_debut,
                ).exists()
                if conflit:
                    messages.error(
                        request,
                        f'⛔ {salle.nom} est déjà réservée sur cette période. '
                        f'Choisissez une autre salle.')
                    return redirect('patrimoine_valider_demande_salle', pk=pk)

                demande.salle_attribuee = salle
                demande.statut = 'VALIDEE'
                demande.valide_par = request.user
                demande.date_validation = timezone.now()
                demande.save()

                # Créer automatiquement la réservation
                ReservationSalle.objects.create(
                    salle=salle,
                    demandeur=demande.demandeur,
                    service_demandeur=demande.service_demandeur,
                    objet=demande.objet,
                    description=demande.description,
                    nb_participants=demande.nb_participants,
                    date_debut=demande.date_debut,
                    date_fin=demande.date_fin,
                    statut='CONFIRMEE',
                    valide_par=request.user,
                    date_validation=timezone.now(),
                    cree_par=request.user,
                    modifie_par=request.user,
                    besoin_videoconf=demande.besoin_videoconf,
                    besoin_video=demande.besoin_video,
                    besoin_son=demande.besoin_son,
                    notes_equipement=demande.notes_equipement,
                )
            messages.success(request, f'✅ Demande validée — Salle {salle.nom} réservée automatiquement.')
            return redirect('patrimoine_detail_demande_salle', pk=pk)

        elif action == 'refuser':
            demande.statut = 'REFUSEE'
            demande.valide_par = request.user
            demande.date_validation = timezone.now()
            demande.motif_refus = request.POST.get('motif_refus', '')
            demande.save()
            messages.warning(request, '🚫 Demande refusée.')
            return redirect('patrimoine_detail_demande_salle', pk=pk)

    # GET : Afficher le formulaire de validation avec salles disponibles
    from django.utils.dateparse import parse_datetime
    # Salles non occupées sur la période demandée
    salles_libres = SalleConference.objects.filter(statut='DISPONIBLE').exclude(
        reservations__statut='CONFIRMEE',
        reservations__date_debut__lt=demande.date_fin,
        reservations__date_fin__gt=demande.date_debut
    ).select_related('batiment').distinct()

    return render(request, 'patrimoine/salles/valider_demande.html', {
        'demande': demande,
        'salles_libres': salles_libres,
    })
