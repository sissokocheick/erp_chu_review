# -*- coding: utf-8 -*-
"""Contrats maintenance et echancier."""
import logging

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.utils import timezone

from accounts.permissions import verifier_permission

from stock.models import Fournisseur
from core.models import Service
from ..models import (
    Immobilisation, ContratMaintenance, TypeContrat,
    Intervention, Batiment, TypeEquipement,
)
from .common import patrimoine_required

logger = logging.getLogger(__name__)


@login_required(login_url='/auth/login/')

@patrimoine_required

@verifier_permission('accounts.menu_pat_contrats')

def liste_contrats(request):

    if request.method == 'POST' and 'creer_contrat' in request.POST:

        try:

            ContratMaintenance.objects.create(

                reference=request.POST.get('reference'),

                prestataire_id=request.POST.get('prestataire'),

                type_contrat_id=request.POST.get('type_contrat'),

                date_debut=request.POST.get('date_debut'),

                date_fin=request.POST.get('date_fin'),

                cout_annuel=request.POST.get('cout_annuel', 0),

                description=request.POST.get('description', ''),

                statut='ACTIF',

                cree_par=request.user

            )

            messages.success(request, "✅ Nouveau contrat créé avec succès.")

        except Exception as e:

            messages.error(request, f"❌ Erreur lors de la création : {e}")

        return redirect('patrimoine_contrats')


    qs = ContratMaintenance.objects.select_related('prestataire', 'type_contrat').annotate(nb_equip=Count('equipements')).order_by('date_fin')

    
    return render(request, 'patrimoine/contrats.html', {

        'contrats': qs, 

        'fournisseurs': Fournisseur.objects.all().order_by('raison_sociale'),

        'types_contrat': TypeContrat.objects.all().order_by('nom'),

        'nb_expirant': qs.filter(date_fin__lte=timezone.now().date() + timezone.timedelta(days=30), date_fin__gte=timezone.now().date()).count(),

        'nb_expires': qs.filter(date_fin__lt=timezone.now().date()).count(),

    })


@login_required(login_url='/auth/login/')

@patrimoine_required

@verifier_permission('accounts.menu_pat_contrats')

def detail_contrat(request, pk):

    contrat = get_object_or_404(ContratMaintenance.objects.select_related('prestataire').prefetch_related('equipements', 'interventions'), pk=pk)

    if request.method == 'POST' and 'save_contrat' in request.POST:

        try:

            contrat.reference = request.POST.get('reference', contrat.reference)

            contrat.date_debut = request.POST.get('date_debut', contrat.date_debut)

            contrat.date_fin = request.POST.get('date_fin', contrat.date_fin)

            contrat.cout_annuel = request.POST.get('cout_annuel', contrat.cout_annuel)

            contrat.description = request.POST.get('description', contrat.description)

            contrat.modifie_par = request.user

            contrat.save()

            messages.success(request, "✅ Contrat mis à jour.")

        except Exception as e:

            messages.error(request, f"❌ {e}")

        return redirect('patrimoine_contrat_detail', pk=pk)

    return render(request, 'patrimoine/contrat_detail.html', {'contrat': contrat, 'interventions': contrat.interventions.order_by('-date_signalement')[:20]})


@login_required(login_url='/auth/login/')

@patrimoine_required

@verifier_permission('accounts.menu_pat_contrats')

def assigner_equipements_contrat(request, contrat_id):

    from django.db.models import Q, Count

    contrat = get_object_or_404(ContratMaintenance, id=contrat_id)

    
    equipements_disponibles = Immobilisation.objects.filter(

        Q(contrat_maintenance__isnull=True) | 

        Q(contrat_maintenance__statut='EXPIRE') | 

        Q(contrat_maintenance=contrat)

    ).select_related('type_equipement__categorie', 'service_affectation', 'bureau__etage__batiment')


    batiment_id = request.GET.get('batiment')

    service_id = request.GET.get('service')

    type_id = request.GET.get('type')


    if batiment_id:

        equipements_disponibles = equipements_disponibles.filter(bureau__etage__batiment_id=batiment_id)

    if service_id:

        equipements_disponibles = equipements_disponibles.filter(service_affectation_id=service_id)

    if type_id:

        equipements_disponibles = equipements_disponibles.filter(type_equipement_id=type_id)


    if request.method == 'POST':

        equipements_coches = request.POST.getlist('equipements')

        Immobilisation.objects.filter(contrat_maintenance=contrat).update(contrat_maintenance=None)

        if equipements_coches:
            # Serve-side : ne rattacher que les équipements réellement
            # « disponibles » (sans contrat actif, ou déjà à ce contrat) —
            # un POST forgé/obsolète ne doit pas voler les équipements
            # d'un autre contrat ACTIF.
            ids_valides = list(
                equipements_disponibles.filter(
                    id__in=equipements_coches).values_list('id', flat=True))
            Immobilisation.objects.filter(id__in=ids_valides).update(contrat_maintenance=contrat)

        messages.success(request, "✅ La couverture du contrat a été mise à jour avec succès.")

        return redirect('patrimoine_contrats')


    context = {

        'contrat': contrat,

        'equipements': equipements_disponibles,

        'batiments': Batiment.objects.all().order_by('nom'),

        'services': Service.objects.all().order_by('nom'),

        'types_equipement': TypeEquipement.objects.all().order_by('nom'),

        'batiment_id': batiment_id,

        'service_id': service_id,

        'type_id': type_id,

    }

    return render(request, 'patrimoine/assigner_equipements_contrat.html', context)


@login_required(login_url='/auth/login/')
@patrimoine_required
@verifier_permission('accounts.menu_pat_contrats')
def echeancier_maintenance(request):
    """Prochaine échéance de maintenance préventive par contrat actif.

    L'échéance se calcule depuis la dernière intervention préventive
    réalisée (date de fin) + la fréquence du contrat ; à défaut, depuis
    la date de début du contrat. Les contrats en retard sont remontés
    en tête.
    """
    from datetime import date as date_cls

    aujourdhui = timezone.now().date()

    def plus_mois(date_base, frequence_mois):
        """Ajoute N mois à une date (jour plafonné à 28 pour les fins de mois)."""
        if not frequence_mois or frequence_mois <= 0:
            frequence_mois = 12
        total = date_base.month - 1 + frequence_mois
        annee = date_base.year + total // 12
        mois = total % 12 + 1
        return date_cls(annee, mois, min(date_base.day, 28))

    def statut_echeance(prochaine):
        """Statut OK/PROCHE selon le nombre de jours avant la prochaine échéance."""
        jours = (prochaine - aujourdhui).days
        if jours <= 30:
            return 'PROCHE', jours
        return 'OK', jours

    contrats = ContratMaintenance.objects.filter(
        statut='ACTIF'
    ).select_related('prestataire', 'type_contrat')

    echeances = []
    for contrat in contrats:
        derniere = Intervention.objects.filter(
            contrat=contrat,
            type_intervention='PREVENTIVE',
            date_fin_intervention__isnull=False,
        ).order_by('-date_fin_intervention').first()

        if derniere and derniere.date_fin_intervention:
            base = derniere.date_fin_intervention.date()
        else:
            base = contrat.date_debut

        if derniere and derniere.date_fin_intervention:
            # Une préventive a été réalisée : elle satisfait l'échéance de sa
            # date de fin. La prochaine échéance = date de fin + fréquence.
            # Si cette échéance est déjà passée (préventive trop ancienne),
            # le contrat est en retard.
            prochaine = plus_mois(base, contrat.frequence_mois)
            if prochaine < aujourdhui:
                statut = 'EN_RETARD'
                jours = (aujourdhui - prochaine).days
                echeance_affichee = prochaine
            else:
                statut, jours = statut_echeance(prochaine)
                echeance_affichee = prochaine
        else:
            # Aucune préventive réalisée : les échéances partent de la date de
            # début. La dernière échéance <= aujourd'hui est due.
            echeance_due = None
            echeance = base
            while echeance <= aujourdhui:
                echeance_due = echeance
                echeance = plus_mois(echeance, contrat.frequence_mois)

            if echeance_due is not None and echeance_due < aujourdhui:
                statut = 'EN_RETARD'
                jours = (aujourdhui - echeance_due).days
                echeance_affichee = echeance_due
            else:
                target = echeance_due if echeance_due is not None else echeance
                statut, jours = statut_echeance(target)
                echeance_affichee = target

        nb_equipements = Immobilisation.objects.filter(
            contrat_maintenance=contrat).count()

        echeances.append({
            'contrat': contrat,
            'prochaine_echeance': echeance_affichee,
            'jours_restants': jours,
            'statut': statut,
            'nb_equipements': nb_equipements,
            'derniere_preventive': (derniere.date_fin_intervention
                                    if derniere else None),
        })

    ordre = {'EN_RETARD': 0, 'PROCHE': 1, 'OK': 2}
    echeances.sort(key=lambda e: (ordre.get(e['statut'], 3), e['jours_restants']))

    context = {
        'echeances': echeances,
        'aujourdhui': aujourdhui,
        'nb_retard': sum(1 for e in echeances if e['statut'] == 'EN_RETARD'),
        'nb_proche': sum(1 for e in echeances if e['statut'] == 'PROCHE'),
        'nb_contrats_actifs': len(echeances),
    }
    return render(request, 'patrimoine/echeancier_maintenance.html', context)
