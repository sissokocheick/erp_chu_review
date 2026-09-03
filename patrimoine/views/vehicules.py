# -*- coding: utf-8 -*-
"""Vues de gestion des véhicules du patrimoine."""
import json
from decimal import Decimal

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.db.models import Sum, Count, Q
from django.core.paginator import Paginator

from ..models import Vehicule, InterventionVehicule, MissionVehicule, Marque, Modele
from core.models import Service
from ..views.common import patrimoine_required


def verifier_permission_vehicule(perm):
    """Decorator: vérifie une permission véhicules spécifique."""
    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapper(request, *args, **kwargs):
            if not (request.user.is_superuser or request.user.has_perm(perm)):
                messages.error(request, "\u26d4 Acc\u00e8s non autoris\u00e9.")
                return redirect('/')
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator


from functools import wraps


@verifier_permission_vehicule('accounts.menu_pat_vehicules')
def liste_vehicules(request):
    """Liste des véhicules avec filtres et statistiques."""
    vehicules = Vehicule.objects.select_related('marque', 'modele', 'service_affectation', 'conducteur_titulaire')
    
    # Filtres
    statut = request.GET.get('statut', '')
    type_v = request.GET.get('type', '')
    service = request.GET.get('service', '')
    q = request.GET.get('q', '')
    
    if statut:
        vehicules = vehicules.filter(statut=statut)
    if type_v:
        vehicules = vehicules.filter(type_vehicule=type_v)
    if service:
        vehicules = vehicules.filter(service_affectation_id=service)
    if q:
        vehicules = vehicules.filter(
            Q(immatriculation__icontains=q) |
            Q(marque__nom__icontains=q) |
            Q(modele__nom__icontains=q)
        )
    
    # Statistiques
    stats = {
        'total': Vehicule.objects.count(),
        'disponibles': Vehicule.objects.filter(statut='DISPONIBLE').count(),
        'en_service': Vehicule.objects.filter(statut='EN_SERVICE').count(),
        'en_maintenance': Vehicule.objects.filter(statut='EN_MAINTENANCE').count(),
        'hors_service': Vehicule.objects.filter(statut='HORS_SERVICE').count(),
        'assurance_expiree': Vehicule.objects.filter(assurance_fin__lt=timezone.now().date()).count(),
        'ct_proche': Vehicule.objects.filter(ct_prochaine_date__lte=timezone.now().date() + timezone.timedelta(days=30)).count(),
    }
    
    paginator = Paginator(vehicules, 20)
    page = request.GET.get('page')
    vehicules = paginator.get_page(page)
    
    return render(request, 'patrimoine/vehicules/liste.html', {
        'vehicules': vehicules,
        'stats': stats,
        'statut_filter': statut,
        'type_filter': type_v,
        'service_filter': service,
        'q': q,
    })


@verifier_permission_vehicule("accounts.menu_pat_vehicules")
def detail_vehicule(request, pk):
    """Détail d'un véhicule avec historique."""
    vehicule = get_object_or_404(
        Vehicule.objects.select_related(
            'marque', 'modele', 'service_affectation', 'conducteur_titulaire'
        ).prefetch_related(
            'interventions_vehicule__immobilisation__type_equipement',
            'missions__service_demandeur',
        ),
        pk=pk
    )
    interventions = vehicule.interventions_vehicule.all()[:10]
    missions = vehicule.missions.all()[:10]
    
    cout_total = vehicule.interventions_vehicule.aggregate(total=Sum('cout'))['total'] or Decimal('0.00')
    
    return render(request, 'patrimoine/vehicules/detail.html', {
        'vehicule': vehicule,
        'interventions': interventions,
        'missions': missions,
        'cout_total': cout_total,
    })


@verifier_permission_vehicule("accounts.menu_pat_vehicules")
def creer_vehicule(request):
    """Créer un nouveau véhicule."""
    if request.method == 'POST':
        try:
            vehicule = Vehicule(
                immatriculation=request.POST.get('immatriculation', '').strip(),
                type_vehicule=request.POST.get('type_vehicule', 'BERLINE'),
                couleur=request.POST.get('couleur', ''),
                numero_chassis=request.POST.get('numero_chassis', ''),
                kilometrage=int(request.POST.get('kilometrage', 0) or 0),
                carburant=request.POST.get('carburant', 'DIESEL'),
                puissance_cv=int(request.POST['puissance_cv']) if request.POST.get('puissance_cv') else None,
                date_premiere_circulation=request.POST.get('date_premiere_circulation') or None,
                date_acquisition=request.POST.get('date_acquisition') or None,
                valeur_acquisition=Decimal(request.POST.get('valeur_acquisition', '0') or '0'),
                assurance_compagnie=request.POST.get('assurance_compagnie', ''),
                assurance_numero=request.POST.get('assurance_numero', ''),
                assurance_debut=request.POST.get('assurance_debut') or None,
                assurance_fin=request.POST.get('assurance_fin') or None,
                assurance_premium=Decimal(request.POST.get('assurance_premium', '0') or '0'),
                ct_dernier_date=request.POST.get('ct_dernier_date') or None,
                ct_prochaine_date=request.POST.get('ct_prochaine_date') or None,
                garage=request.POST.get('garage', ''),
                statut=request.POST.get('statut', 'DISPONIBLE'),
                notes=request.POST.get('notes', ''),
                cree_par=request.user,
                modifie_par=request.user,
            )
            
            # Marque / Modèle
            marque_id = request.POST.get('marque')
            modele_id = request.POST.get('modele')
            if marque_id:
                vehicule.marque_id = int(marque_id)
            if modele_id:
                vehicule.modele_id = int(modele_id)
            
            # Service
            service_id = request.POST.get('service_affectation')
            if service_id:
                vehicule.service_affectation_id = int(service_id)
            
            # Conducteur
            conducteur_id = request.POST.get('conducteur_titulaire')
            if conducteur_id:
                vehicule.conducteur_titulaire_id = int(conducteur_id)
            
            vehicule.save()
            messages.success(request, f'✅ Véhicule {vehicule.immatriculation} créé avec succès.')
            return redirect('patrimoine_vehicule_detail', pk=vehicule.pk)
            
        except Exception as e:
            messages.error(request, f'❌ Erreur : {e}')
    
    from django.contrib.auth.models import User
    marques = Marque.objects.all().order_by('nom')
    services = Service.objects.all().order_by('nom')
    conducteurs = User.objects.filter(is_active=True).order_by('first_name')
    return render(request, 'patrimoine/vehicules/formulaire.html', {
        'vehicule': None,
        'marques': marques,
        'services': services,
        'conducteurs': conducteurs,
        'type_vehicule_choices': Vehicule.TYPE_VEHICULE_CHOICES,
    })


@verifier_permission_vehicule("accounts.menu_pat_vehicules")
def modifier_vehicule(request, pk):
    """Modifier un véhicule existant."""
    vehicule = get_object_or_404(Vehicule, pk=pk)
    
    if request.method == 'POST':
        try:
            vehicule.immatriculation = request.POST.get('immatriculation', vehicule.immatriculation)
            vehicule.type_vehicule = request.POST.get('type_vehicule', vehicule.type_vehicule)
            vehicule.couleur = request.POST.get('couleur', '')
            vehicule.numero_chassis = request.POST.get('numero_chassis', '')
            vehicule.kilometrage = int(request.POST.get('kilometrage', 0) or 0)
            vehicule.carburant = request.POST.get('carburant', 'DIESEL')
            vehicule.puissance_cv = int(request.POST['puissance_cv']) if request.POST.get('puissance_cv') else None
            vehicule.date_premiere_circulation = request.POST.get('date_premiere_circulation') or None
            vehicule.date_acquisition = request.POST.get('date_acquisition') or None
            vehicule.valeur_acquisition = Decimal(request.POST.get('valeur_acquisition', '0') or '0')
            vehicule.assurance_compagnie = request.POST.get('assurance_compagnie', '')
            vehicule.assurance_numero = request.POST.get('assurance_numero', '')
            vehicule.assurance_debut = request.POST.get('assurance_debut') or None
            vehicule.assurance_fin = request.POST.get('assurance_fin') or None
            vehicule.assurance_premium = Decimal(request.POST.get('assurance_premium', '0') or '0')
            vehicule.ct_dernier_date = request.POST.get('ct_dernier_date') or None
            vehicule.ct_prochaine_date = request.POST.get('ct_prochaine_date') or None
            vehicule.garage = request.POST.get('garage', '')
            vehicule.statut = request.POST.get('statut', vehicule.statut)
            vehicule.notes = request.POST.get('notes', '')
            vehicule.modifie_par = request.user
            
            marque_id = request.POST.get('marque')
            vehicule.marque_id = int(marque_id) if marque_id else None
            modele_id = request.POST.get('modele')
            vehicule.modele_id = int(modele_id) if modele_id else None
            service_id = request.POST.get('service_affectation')
            vehicule.service_affectation_id = int(service_id) if service_id else None
            conducteur_id = request.POST.get('conducteur_titulaire')
            vehicule.conducteur_titulaire_id = int(conducteur_id) if conducteur_id else None
            
            vehicule.save()
            messages.success(request, f'✅ Véhicule {vehicule.immatriculation} mis à jour.')
            return redirect('patrimoine_vehicule_detail', pk=vehicule.pk)
            
        except Exception as e:
            messages.error(request, f'❌ Erreur : {e}')
    
    from django.contrib.auth.models import User
    marques = Marque.objects.all().order_by('nom')
    services = Service.objects.all().order_by('nom')
    conducteurs = User.objects.filter(is_active=True).order_by('first_name')
    return render(request, 'patrimoine/vehicules/formulaire.html', {
        'vehicule': vehicule,
        'marques': marques,
        'services': services,
        'conducteurs': conducteurs,
        'type_vehicule_choices': Vehicule.TYPE_VEHICULE_CHOICES,
    })


@verifier_permission_vehicule("accounts.menu_pat_vehicules")
def supprimer_vehicule(request, pk):
    """Supprimer un véhicule."""
    vehicule = get_object_or_404(Vehicule, pk=pk)
    if request.method == 'POST':
        imm = vehicule.immatriculation
        vehicule.delete()
        messages.success(request, f'🗑️ Véhicule {imm} supprimé.')
        return redirect('patrimoine_vehicules')
    return redirect('patrimoine_vehicule_detail', pk=pk)


# ─── Interventions véhicule ───────────────────────────────

@verifier_permission_vehicule("accounts.menu_pat_vehicules")
def liste_interventions_vehicule(request, vehicule_pk):
    """Liste des interventions pour un véhicule."""
    vehicule = get_object_or_404(Vehicule, pk=vehicule_pk)
    interventions = vehicule.interventions_vehicule.all()
    
    statut = request.GET.get('statut', '')
    if statut:
        interventions = interventions.filter(statut=statut)
    
    return render(request, 'patrimoine/vehicules/interventions.html', {
        'vehicule': vehicule,
        'interventions': interventions,
        'statut_filter': statut,
    })


@verifier_permission_vehicule("accounts.menu_pat_vehicules")
def creer_intervention_vehicule(request, vehicule_pk):
    """Créer une intervention pour un véhicule."""
    vehicule = get_object_or_404(Vehicule, pk=vehicule_pk)
    
    if request.method == 'POST':
        try:
            intervention = InterventionVehicule(
                vehicule=vehicule,
                type_intervention=request.POST.get('type_intervention', 'ENTRETIEN'),
                statut=request.POST.get('statut', 'PLANIFIEE'),
                date_prevue=request.POST.get('date_prevue') or None,
                date_realisation=request.POST.get('date_realisation') or None,
                garage_prestataire=request.POST.get('garage_prestataire', ''),
                description=request.POST.get('description', ''),
                cout=Decimal(request.POST.get('cout', '0') or '0'),
                kilometrage=int(request.POST['kilometrage']) if request.POST.get('kilometrage') else None,
                kilometre_prochaine_vidange=int(request.POST['kilometre_prochaine_vidange']) if request.POST.get('kilometre_prochaine_vidange') else None,
                cree_par=request.user,
                modifie_par=request.user,
            )
            intervention.save()
            
            # Mettre à jour le kilométrage si fourni
            if intervention.kilometrage and intervention.kilometrage > vehicule.kilometrage:
                vehicule.kilometrage = intervention.kilometrage
                vehicule.save(update_fields=['kilometrage'])
            
            messages.success(request, f'✅ Intervention créée pour {vehicule.immatriculation}.')
            return redirect('patrimoine_vehicule_interventions', vehicule_pk=vehicule.pk)
            
        except Exception as e:
            messages.error(request, f'❌ Erreur : {e}')
    
    return render(request, 'patrimoine/vehicules/formulaire_intervention.html', {
        'vehicule': vehicule,
    })


# ─── Missions véhicule ────────────────────────────────────

@verifier_permission_vehicule("accounts.menu_pat_vehicules")
def liste_missions_vehicule(request, vehicule_pk):
    """Liste des missions pour un véhicule."""
    vehicule = get_object_or_404(Vehicule, pk=vehicule_pk)
    missions = vehicule.missions.all()
    
    statut = request.GET.get('statut', '')
    if statut:
        missions = missions.filter(statut=statut)
    
    return render(request, 'patrimoine/vehicules/missions.html', {
        'vehicule': vehicule,
        'missions': missions,
        'statut_filter': statut,
    })


@verifier_permission_vehicule("accounts.menu_pat_vehicules")
def creer_mission_vehicule(request, vehicule_pk):
    """Créer une mission pour un véhicule."""
    vehicule = get_object_or_404(Vehicule, pk=vehicule_pk)
    
    if request.method == 'POST':
        try:
            mission = MissionVehicule(
                vehicule=vehicule,
                chauffeur_id=int(request.POST['chauffeur']) if request.POST.get('chauffeur') else None,
                objet=request.POST.get('objet', ''),
                destination=request.POST.get('destination', ''),
                date_depart=request.POST.get('date_depart'),
                date_retour=request.POST.get('date_retour') or None,
                km_depart=int(request.POST['km_depart']) if request.POST.get('km_depart') else None,
                km_retour=int(request.POST['km_retour']) if request.POST.get('km_retour') else None,
                statut=request.POST.get('statut', 'EN_COURS'),
                demandeur_id=int(request.POST['demandeur']) if request.POST.get('demandeur') else None,
                observation=request.POST.get('observation', ''),
                cree_par=request.user,
                modifie_par=request.user,
            )
            service_id = request.POST.get('service_demandeur')
            if service_id:
                mission.service_demandeur_id = int(service_id)
            mission.save()
            
            # Mettre à jour le kilométrage
            if mission.km_retour and mission.km_retour > vehicule.kilometrage:
                vehicule.kilometrage = mission.km_retour
                vehicule.save(update_fields=['kilometrage'])
            
            messages.success(request, f'✅ Mission enregistrée pour {vehicule.immatriculation}.')
            return redirect('patrimoine_vehicule_missions', vehicule_pk=vehicule.pk)
            
        except Exception as e:
            messages.error(request, f'❌ Erreur : {e}')
    
    return render(request, 'patrimoine/vehicules/formulaire_mission.html', {
        'vehicule': vehicule,
    })


# ─── AJAX ─────────────────────────────────────────────────

@login_required
@patrimoine_required
def ajax_modeles_vehicule(request):
    """Retourne les modèles d'une marque (pour le formulaire véhicule)."""
    marque_id = request.GET.get('marque_id')
    if not marque_id:
        return JsonResponse({'modeles': []})
    
    modeles = Modele.objects.filter(marque_id=marque_id).order_by('nom').values('id', 'nom')
    return JsonResponse({'modeles': list(modeles)})
