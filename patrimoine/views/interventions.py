# -*- coding: utf-8 -*-
"""Interventions, tickets, dispatch, portail prestataire."""
import logging
import json

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.http import JsonResponse
from django.utils import timezone

from stock.models import Article, Magasin
from core.models import Service
from accounts.permissions import verifier_permission
from decimal import Decimal

from ..models import (
    Immobilisation, Intervention, ComptePrestataire,
    TechnicienPrestataire, ParametresPatrimoine,
    ContratMaintenance,
    MouvementPatrimoine, TypeEquipement,
)
from stock.models import Fournisseur, DemandeMateriel, LigneDemande
from django.contrib.auth.models import User
from .common import patrimoine_required

logger = logging.getLogger(__name__)


@login_required(login_url='/auth/login/')

@patrimoine_required

@verifier_permission('accounts.menu_pat_tech')

def liste_interventions(request):

    params = ParametresPatrimoine.get_parametres()

    mode_visibilite = params.mode_visibilite_interventions

    qs = Intervention.objects.all()


    if not request.user.is_superuser:

        est_chef = request.user.is_staff

        try:

            profil = request.user.profil

            if mode_visibilite == 'DIRECT':

                if not est_chef:

                    domaines_ids = profil.domaines_intervention.values_list('id', flat=True)

                    qs = qs.filter(immobilisation__type_equipement__categorie_id__in=domaines_ids)

            elif mode_visibilite == 'DISPATCH':

                if not est_chef:

                    qs = qs.filter(intervenant=request.user)

        except AttributeError:

            if not est_chef:

                qs = Intervention.objects.none()


    qs = qs.select_related('immobilisation__type_equipement__categorie', 'immobilisation__service_affectation', 'intervenant', 'contrat').order_by('-date_signalement')

    per_page = request.GET.get('per_page', '15')

    limite = qs.count() or 1 if per_page == 'all' else int(per_page) if per_page.isdigit() else 15


    return render(request, 'patrimoine/interventions.html', {

        'interventions': Paginator(qs, limite).get_page(request.GET.get('page')),

        'mode_visibilite': mode_visibilite,

    })


@login_required(login_url='/auth/login/')

@patrimoine_required

def detail_intervention(request, intervention_id):

    intervention = get_object_or_404(Intervention, id=intervention_id)

    articles_catalogue = Article.objects.all().order_by('designation')

    fournisseurs = Fournisseur.objects.all().order_by('raison_sociale')

    techniciens_externes = TechnicienPrestataire.objects.filter(est_actif=True)


    if request.method == 'POST':

        action = request.POST.get('action')


        if action == 'prendre_en_charge':

            intervention.statut = 'EN_COURS'

            intervention.intervenant = request.user

            if not intervention.date_debut_intervention:

                intervention.date_debut_intervention = timezone.now()

            messages.success(request, "🔧 Vous avez pris en charge cette intervention.")


        elif action == 'demander_pieces':

            params = ParametresPatrimoine.get_parametres()

            if not params.magasin_pieces:

                messages.error(request, "❌ Aucun magasin de pièces configuré.")

                return redirect('detail_intervention', intervention_id=intervention.id)


            article_ids = request.POST.getlist('articles[]')

            quantites = request.POST.getlist('quantites[]')


            if article_ids:

                service_dem = intervention.immobilisation.service_affectation or (request.user.profil.service if hasattr(request.user, 'profil') else None)
                if not service_dem:
                    messages.error(request, "❌ Impossible de créer la demande de pièces : aucun service demandeur déterminé (bien non affecté et profil sans service).")
                    return redirect('detail_intervention', intervention_id=intervention.id)

                numero_demande = f"REQ-MAINT-{intervention.id}-{timezone.now().strftime('%y%m%d%H%M')}"

                nouvelle_demande = DemandeMateriel.objects.create(

                    numero_demande=numero_demande, demandeur=request.user, service_demandeur=service_dem,

                    magasin_cible=params.magasin_pieces, statut='EN_ATTENTE',

                    commentaire=f"Pièces pour l'intervention #{intervention.id}"

                )

                for aid, qte in zip(article_ids, quantites):

                    if aid and qte and int(qte) > 0:

                        LigneDemande.objects.create(demande=nouvelle_demande, article_id=aid, quantite_demandee=int(qte))

                intervention.demandes_pieces.add(nouvelle_demande)

                intervention.statut = 'EN_ATTENTE_PIECES'

                messages.success(request, "📦 Demande envoyée au magasin.")


        elif action == 'receptionner_demande':

            demande_id = request.POST.get('demande_id')

            demande = get_object_or_404(DemandeMateriel, id=demande_id)

            demande.statut = 'LIVREE'

            demande.save()

            demandes_restantes = intervention.demandes_pieces.exclude(statut__in=['ANNULEE', 'REFUSEE', 'LIVREE', 'RECEPTIONNE', 'CLOTUREE'])

            if not demandes_restantes.exists() and intervention.statut == 'EN_ATTENTE_PIECES':

                intervention.statut = 'EN_COURS'

            messages.success(request, "📦 Pièces réceptionnées.")


        elif action == 'deleguer_prestataire':

            prestataire_id = request.POST.get('prestataire')

            tech_id = request.POST.get('technicien_appele')

            sortie = request.POST.get('necessite_sortie') == 'on'


            intervention.prestataire_concerne_id = prestataire_id if prestataire_id else None

            intervention.technicien_appele_id = tech_id if tech_id else None

            intervention.date_appel_prestataire = timezone.now()

            intervention.necessite_sortie_reparation = sortie

            intervention.statut = 'EN_COURS'

            
            if sortie:

                MouvementPatrimoine.objects.create(

                    immobilisation=intervention.immobilisation,

                    type_mouvement='REPARATION',

                    bureau_depart=intervention.immobilisation.bureau,

                    service_depart=intervention.immobilisation.service_affectation,

                    date_mouvement=timezone.now().date(),

                    motif=f"Sortie pour réparation externe (Ticket #{intervention.id})",

                    effectue_par=request.user

                )

                intervention.immobilisation.statut = 'EN_PANNE'

                intervention.immobilisation.save()


            messages.success(request, "🤝 Intervention déléguée au prestataire externe.")


        elif action == 'retour_prestataire':

            intervention.date_retour_reelle = timezone.now()

            intervention.date_fin_intervention = timezone.now()

            intervention.actions_effectuees = request.POST.get('rapport', '')

            
            if 'rapport_scan' in request.FILES:

                intervention.rapport_prestataire_scan = request.FILES['rapport_scan']

            if 'bon_signe' in request.FILES:

                intervention.bon_sortie_signe_scan = request.FILES['bon_signe']

            
            intervention.statut = 'EN_ATTENTE_VALIDATION'

            
            if intervention.necessite_sortie_reparation:

                MouvementPatrimoine.objects.create(

                    immobilisation=intervention.immobilisation,

                    type_mouvement='RETOUR_REPARATION',

                    bureau_arrivee=intervention.immobilisation.bureau,

                    service_arrivee=intervention.immobilisation.service_affectation,

                    date_mouvement=timezone.now().date(),

                    motif=f"Retour de réparation externe (Ticket #{intervention.id})",

                    effectue_par=request.user

                )

            messages.success(request, "✅ Retour enregistré, rapport joint et dossier transmis pour validation.")


        elif action == 'soumettre_devis':

            intervention.frais_hors_contrat = Decimal(request.POST.get('montant_devis', 0))

            intervention.motif_frais_hors_contrat = request.POST.get('motif_devis', '')

            intervention.statut = 'EN_ATTENTE_DEVIS'

            intervention.devis_accepte = None

            messages.success(request, "📝 Devis soumis. En attente de l'accord de l'administration.")


        elif action == 'valider_devis' and request.user.is_superuser:

            intervention.devis_accepte = True

            intervention.statut = 'EN_COURS'

            messages.success(request, "✅ Devis validé ! L'intervention se poursuit.")


        elif action == 'refuser_devis' and request.user.is_superuser:

            intervention.devis_accepte = False

            intervention.statut = 'EN_COURS'

            messages.warning(request, "❌ Devis refusé.")

            
        elif action == 'resoudre':

            demandes_inutiles = intervention.demandes_pieces.exclude(statut__in=['LIVREE', 'RECEPTIONNE', 'CLOTUREE', 'REFUSEE', 'ANNULEE'])

            for d in demandes_inutiles:

                d.statut = 'ANNULEE'

                d.motif_refus = "Annulation automatique (Intervention terminée)"

                d.save()

            intervention.statut = 'EN_ATTENTE_VALIDATION'

            intervention.actions_effectuees = request.POST.get('rapport', intervention.actions_effectuees)

            diagnostic = request.POST.get('diagnostic')

            if diagnostic:

                intervention.diagnostic = diagnostic

            intervention.date_fin_intervention = timezone.now()

            messages.success(request, "✅ Réparation terminée. En attente de validation.")


        elif action == 'valider' and request.user.is_superuser:

            intervention.statut = 'RESOLUE'

            intervention.valide_par = request.user

            intervention.date_validation = timezone.now()

            machine = intervention.immobilisation

            machine.statut = 'ACTIF'

            machine.action_requise = 'RAS'

            machine.save()

            messages.success(request, "🎉 Intervention clôturée !")


        intervention.save()

        return redirect('detail_intervention', intervention_id=intervention.id)


    return render(request, 'patrimoine/detail_intervention.html', {

        'intervention': intervention, 

        'articles_catalogue': articles_catalogue,

        'fournisseurs': fournisseurs,

        'techniciens_externes': techniciens_externes

    })


@login_required(login_url="/auth/login/")

def signaler_panne(request, immo_id):

    equipement = get_object_or_404(Immobilisation, id=immo_id)

    if request.method == 'POST':

        description = request.POST.get('description', '')

        photo = request.FILES.get('photo')

        intervention = Intervention.objects.create(

            immobilisation=equipement, type_intervention='CURATIVE', statut='NOUVELLE',

            description_probleme=description, photo=photo

        )

        return render(request, 'patrimoine/confirmer_signalement_panne.html', {'intervention': intervention})

    return render(request, 'patrimoine/signaler_panne.html', {'equipement': equipement})


@login_required(login_url='/auth/login/')

@patrimoine_required

@verifier_permission('accounts.menu_pat_tech')

def creer_intervention(request, immo_pk):

    immo = get_object_or_404(Immobilisation, pk=immo_pk)

    if request.method == 'POST':

        try:

            est_prest = hasattr(request.user, 'compte_prestataire')

            type_inter = request.POST.get('type_intervention', 'CURATIVE')

            inter = Intervention.objects.create(

                immobilisation=immo, contrat_id=request.POST.get('contrat') or None, type_intervention=type_inter,

                intervenant=request.user, est_prestataire_externe=est_prest, date_signalement=timezone.now(),

                date_debut_intervention=request.POST.get('date_debut') or None, date_fin_intervention=request.POST.get('date_fin') or None,

                description_probleme=request.POST.get('description_probleme', ''), actions_effectuees=request.POST.get('actions_effectuees', ''),

                cout_main_oeuvre=request.POST.get('cout_mo', 0) or 0, cout_pieces=request.POST.get('cout_pieces', 0) or 0,

                cout_deplacement=request.POST.get('cout_deplacement', 0) or 0, statut='EN_ATTENTE_VALIDATION' if est_prest else 'EN_COURS',

                cree_par=request.user,

            )

            if type_inter == 'CURATIVE':

                immo.statut = 'EN_PANNE'

                immo.save()

            messages.success(request, "✅ Problème signalé avec succès.")

            if 'mobile' in request.GET:

                return redirect('patrimoine_scan', code=immo.code_patrimoine)

            return redirect('patrimoine_detail', pk=immo_pk)

        except Exception as e:

            messages.error(request, f"❌ Erreur : {e}")


    contrats = ContratMaintenance.objects.filter(equipements=immo, statut='ACTIF')

    return render(request, 'patrimoine/creer_intervention.html', {'immo': immo, 'contrats': contrats, 'types': Intervention.TYPE_CHOICES})


@login_required(login_url='/auth/login/')

@patrimoine_required

@verifier_permission('accounts.menu_pat_tech')

def valider_intervention(request, pk):

    inter = get_object_or_404(Intervention, pk=pk)

    if request.method == 'POST':

        statut = request.POST.get('statut')

        inter.statut = statut

        inter.valide_par = request.user

        inter.date_validation = timezone.now()

        inter.commentaire_validation = request.POST.get('commentaire', '')

        inter.modifie_par = request.user

        inter.save()

        if statut in ['TERMINEE', 'CLOTUREE', 'VALIDEE', 'RESOLUE']:

            machine = inter.immobilisation

            machine.statut = 'ACTIF'

            machine.action_requise = 'RAS'

            machine.save()

        messages.success(request, "✅ Intervention validée et équipement mis à jour.")

    return redirect('patrimoine_detail', pk=inter.immobilisation_id)


@login_required(login_url='/auth/login/')

@patrimoine_required

@verifier_permission('accounts.menu_pat_tech')

def portail_prestataire(request):

    try:

        compte = request.user.compte_prestataire

    except AttributeError:

        messages.error(request, "⛔ Accès non autorisé — aucun compte prestataire.")

        return redirect('/')

    except Exception as e:

        logger.warning("[portail_prestataire] Erreur accès compte %s : %s", request.user, e)

        messages.error(request, "⛔ Erreur d'accès.")

        return redirect('/')

    if not compte.est_actif:

        messages.error(request, "Votre compte prestataire est désactivé.")

        return redirect('/')

    contrats = compte.contrats_autorises.filter(statut='ACTIF').prefetch_related('equipements')

    interventions_recentes = Intervention.objects.filter(contrat__in=contrats).order_by('-date_signalement')[:20]

    return render(request, 'patrimoine/portail_prestataire.html', {'compte': compte, 'contrats': contrats, 'interventions_recentes': interventions_recentes})


@login_required(login_url='/auth/login/')

def mes_tickets(request):

    qs = Intervention.objects.filter(cree_par=request.user).select_related(

        'immobilisation__type_equipement__categorie',

        'immobilisation__service_affectation',

        'intervenant'

    ).order_by('-date_signalement')


    tab = request.GET.get('tab', 'encours')

    statuts_historique = ['RESOLUE', 'TERMINEE', 'CLOTUREE', 'ANNULE', 'ANNULEE', 'REJETEE', 'FERME', 'FERMEE']

    
    if tab == 'historique':

        qs = qs.filter(statut__in=statuts_historique)

    else:

        qs = qs.exclude(statut__in=statuts_historique)


    per_page = request.GET.get('per_page', '10')

    limite = qs.count() or 1 if per_page == 'all' else int(per_page) if str(per_page).isdigit() else 10

    page = Paginator(qs, limite).get_page(request.GET.get('page'))


    all_qs = Intervention.objects.filter(cree_par=request.user)

    stats = {

        'en_cours': all_qs.exclude(statut__in=statuts_historique).count(),

        'resolus': all_qs.filter(statut__in=statuts_historique).count(),

    }


    return render(request, 'patrimoine/mes_tickets.html', {

        'tickets': page, 'stats': stats, 'per_page': per_page, 'current_tab': tab

    })


@login_required(login_url='/auth/login/')

@patrimoine_required

@verifier_permission('accounts.menu_pat_dispatch')

def dispatch_interventions(request):

    # ── Seuls les chefs de service peuvent dispatcher ──

    if not hasattr(request.user, 'profil') or not request.user.profil.est_chef_service:

        messages.error(request, "⛔ Accès réservé aux chefs de service.")

        return redirect('/')

    
    service_chef = request.user.profil.service

    if not service_chef:

        messages.error(request, "⛔ Aucun service assigné à votre profil.")

        return redirect('/')

        
    params = ParametresPatrimoine.get_parametres()

    mode_actuel = params.mode_visibilite_interventions


    if request.method == 'POST':

        intervention_id = request.POST.get('intervention_id')

        technicien_id = request.POST.get('technicien_id')

        intervention = get_object_or_404(Intervention, id=intervention_id)

        
        # Sécurité : on ne peut dispatcher que les pannes de SON service

        if intervention.immobilisation.service_affectation != service_chef:

            messages.error(request, "⛔ Cette panne ne concerne pas votre service.")

            return redirect('patrimoine_dispatch')

            
        if technicien_id:

            technicien = get_object_or_404(User, id=technicien_id)

            intervention.intervenant = technicien

            intervention.statut = 'PLANIFIEE'

            intervention.modifie_par = request.user

            intervention.save()

            messages.success(request, f"✅ Panne assignée à {technicien.get_full_name() or technicien.username}.")

        return redirect('patrimoine_dispatch')


    if mode_actuel == 'DISPATCH':

        pannes_en_attente = Intervention.objects.filter(

            statut='NOUVELLE', 

            intervenant__isnull=True,

            immobilisation__service_affectation=service_chef

        ).select_related(

            'immobilisation__type_equipement__categorie',

            'immobilisation__service_affectation',

            'cree_par'

        ).order_by('date_signalement')

    else:

        pannes_en_attente = Intervention.objects.none()


    # Techniciens rattachés au même service

    techniciens = User.objects.filter(

        is_active=True,

        profil__service=service_chef

    ).order_by('first_name')


    return render(request, 'patrimoine/dispatch.html', {

        'pannes_en_attente': pannes_en_attente,

        'techniciens': techniciens,

        'mode_actuel': mode_actuel,

        'service_chef': service_chef,

    })


@login_required(login_url='/auth/login/')

@patrimoine_required

@verifier_permission('accounts.menu_pat_tech')

def mes_interventions_tech(request):

    params = ParametresPatrimoine.get_parametres()

    mode_visibilite = params.mode_visibilite_interventions


    mes_pannes = Intervention.objects.filter(intervenant=request.user).select_related(

        'immobilisation__type_equipement__categorie',

        'immobilisation__service_affectation',

        'cree_par'

    )


    a_faire_perso = mes_pannes.filter(statut__in=['NOUVELLE', 'PLANIFIEE']).order_by('-date_signalement')

    en_cours = mes_pannes.filter(statut__in=['EN_COURS', 'EN_ATTENTE_PIECES']).order_by('-date_signalement')

    a_valider = mes_pannes.filter(statut='EN_ATTENTE_VALIDATION').order_by('-date_fin_intervention')

    historique_perso = mes_pannes.filter(statut__in=['RESOLUE', 'CLOTUREE', 'TERMINEE']).order_by('-date_fin_intervention')


    pannes_libres = Intervention.objects.none()

    if mode_visibilite != 'DISPATCH':

        base_libres = Intervention.objects.filter(

            statut='NOUVELLE', intervenant__isnull=True

        ).select_related(

            'immobilisation__type_equipement__categorie',

            'immobilisation__service_affectation',

            'cree_par'

        ).order_by('date_signalement')


        if mode_visibilite == 'GLOBAL':

            pannes_libres = base_libres

        elif mode_visibilite == 'DIRECT' and hasattr(request.user, 'profil'):

            domaines_ids = request.user.profil.domaines_intervention.values_list('id', flat=True)

            pannes_libres = base_libres.filter(immobilisation__type_equipement__categorie_id__in=domaines_ids)


    types_equipements = TypeEquipement.objects.all().order_by('nom')


    return render(request, 'patrimoine/mes_interventions.html', {

        'a_faire_perso': a_faire_perso,

        'pannes_libres': pannes_libres,

        'en_cours': en_cours,

        'a_valider': a_valider,

        'historique_perso': historique_perso,

        'mode_visibilite': mode_visibilite,

        'types_equipements': types_equipements,

    })


@login_required(login_url='/auth/login/')

def suivi_ticket(request, pk):

    intervention = get_object_or_404(Intervention, pk=pk)

    if intervention.cree_par != request.user and not request.user.is_superuser and not request.user.has_perm('accounts.menu_pat_tech'):

        messages.error(request, "⛔ Vous n'êtes pas autorisé à voir ce ticket.")

        return redirect('patrimoine_mes_tickets')

    return render(request, 'patrimoine/suivi_ticket.html', {'intervention': intervention})


@login_required(login_url='/auth/login/')

def declarer_panne_pc(request):

    if request.method == 'POST':

        immo_id = request.POST.get('equipement')

        description = request.POST.get('description', '')

        urgence = request.POST.get('degre_urgence', 'MOYENNE')

        photo = request.FILES.get('photo')

        equipement = get_object_or_404(Immobilisation, id=immo_id)

        
        Intervention.objects.create(

            immobilisation=equipement, type_intervention='CURATIVE', statut='NOUVELLE',

            description_probleme=description, degre_urgence=urgence, photo=photo, cree_par=request.user

        )

        equipement.statut = 'EN_PANNE'

        equipement.save()

        messages.success(request, f"✅ Panne signalée pour {equipement.nom_affichage}.")

        return redirect('patrimoine_mes_tickets')

        
    equipements = Immobilisation.objects.exclude(statut__in=['EN_ATTENTE', 'REFORME']).select_related('service_affectation', 'bureau').order_by('nom_affichage')

    
    try:

        params = ParametresPatrimoine.get_parametres()

        if not request.user.is_superuser and hasattr(request.user, 'profil'):

            profil = request.user.profil

            if params.perimetre_declaration == 'SERVICE' and profil.service:

                equipements = equipements.filter(service_affectation=profil.service)

            elif params.perimetre_declaration == 'BUREAU' and profil.bureau:

                equipements = equipements.filter(bureau=profil.bureau)
    except Exception as e:
        logger.warning("[declarer_panne_pc] Filtre périmètre échoué : %s", e)

    return render(request, 'patrimoine/declarer_panne_pc.html', {'equipements': equipements})


@login_required(login_url='/auth/login/')

@patrimoine_required

@verifier_permission('accounts.menu_pat_tech')

def imprimer_bon_sortie_reparation(request, pk):

    intervention = get_object_or_404(Intervention, pk=pk)

    return render(request, 'patrimoine/bon_sortie_reparation_print.html', {'intervention': intervention})
