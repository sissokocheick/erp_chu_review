# -*- coding: utf-8 -*-
"""SAS & Immatriculation."""
import logging
import json

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.db import transaction, IntegrityError
from django.utils import timezone
from decimal import Decimal

from accounts.permissions import verifier_permission
from core.models import Service

from ..models import (
    Immobilisation, TypeEquipement, CategoriePatrimoine,
    MouvementPatrimoine, Marque, Modele,
    Batiment, Etage, Bureau,
)
from .common import patrimoine_required

logger = logging.getLogger(__name__)


@login_required(login_url='/auth/login/')

@patrimoine_required

@verifier_permission('accounts.menu_pat_sas')

def sas(request):

    qs = Immobilisation.objects.filter(statut='EN_ATTENTE').order_by('-date_creation')

    return render(request, 'patrimoine/sas.html', {'immos': Paginator(qs, 25).get_page(request.GET.get('page')), 'nb_sas': qs.count()})


@login_required(login_url='/auth/login/')

@patrimoine_required

@verifier_permission('accounts.menu_pat_sas')

def valider_sas(request, pk):

    immo  = get_object_or_404(Immobilisation, pk=pk, statut='EN_ATTENTE')

    types = TypeEquipement.objects.filter(est_actif=True).select_related('categorie')


    if request.method == 'POST':

        try:

            te = TypeEquipement.objects.select_related('categorie').get(pk=request.POST.get('type_equipement'))

            immo.numero_serie         = request.POST.get('numero_serie') or ''

            immo.nom_affichage        = request.POST.get('nom_affichage') or ''

            immo.type_equipement_id   = te.pk

            immo.marque_id            = request.POST.get('marque') or None

            immo.modele_id            = request.POST.get('modele') or None

            immo.bureau_id            = request.POST.get('bureau') or None

            immo.service_affectation_id = request.POST.get('service') or None

            immo.emplacement_exact    = request.POST.get('emplacement_exact') or ''

            immo.date_mise_en_service = request.POST.get('date_mise_en_service') or None

            immo.garantie_expiration  = request.POST.get('garantie_expiration') or None

            immo.action_requise       = request.POST.get('action_requise', 'RAS')

            immo.notes                = request.POST.get('notes', '')


            if request.POST.get('valeur_acquisition'):

                immo.valeur_acquisition = Decimal(request.POST.get('valeur_acquisition'))

                immo.prix_depuis_stock  = False


            if request.POST.get('duree_amortissement_ans'):

                immo.duree_amortissement_ans = int(request.POST.get('duree_amortissement_ans'))


            specs = {}

            for champ in te.specs_schema:

                key = champ['key']

                val = request.POST.get(f'spec_{key}', '')

                if val: specs[key] = val

            immo.specs_techniques = specs


            immo.statut = 'ACTIF'

            immo.modifie_par = request.user


            annee = timezone.now().strftime('%y') 

            cat_code = te.categorie.code[:3].upper() 

            prefix = f"{annee}-{cat_code}-"


            # Garde : les FK brutes du POST peuvent lever IntegrityError de
            # contrainte (FK invalide), pas seulement une collision de code —
            # une boucle « while True » sans borne bloquerait le worker.
            for tentatives in range(1, 11):

                dernier_immo = Immobilisation.objects.filter(code_patrimoine__startswith=prefix).order_by('-code_patrimoine').first()

                nouveau_num = (int(dernier_immo.code_patrimoine.split('-')[-1]) + 1) if dernier_immo and dernier_immo.code_patrimoine else 1

                immo.code_patrimoine = f"{prefix}{nouveau_num:05d}"

                try:

                    with transaction.atomic():

                        immo.save()

                        MouvementPatrimoine.objects.create(

                            immobilisation=immo, type_mouvement='AFFECTATION', bureau_arrivee=immo.bureau,

                            service_arrivee=immo.service_affectation, date_mouvement=timezone.now().date(),

                            motif="Immatriculation initiale", effectue_par=request.user,

                        )

                    break

                except IntegrityError as e:
                    # Collision de code → régénérer et retenter. Une FK
                    # invalide échoue de façon déterministe : abandonner
                    # plutôt que de boucler à l'infini.
                    if 'code_patrimoine' not in str(e) and tentatives >= 3:
                        raise
                    continue
            else:
                raise ValueError(
                    "Impossible de générer un code patrimoine unique "
                    f"après {tentatives} tentatives (préfixe {prefix}).")


            messages.success(request, f"✅ Bien immatriculé sous le code {immo.code_patrimoine}.")

            return redirect('patrimoine_detail', pk=immo.pk)

        except Exception as e:

            messages.error(request, f"❌ Erreur : {e}")

            # Réinitialiser les attributs FK « sales » avant le rendu :
            # l'accès immo.bureau dans le template relèverait ValueError
            # (valeur brute invalide) -> 500 au lieu d'un simple message.
            try:
                immo.refresh_from_db()
            except Exception as e:
                logger.warning("[valider_sas] refresh_from_db immo %s échoué : %s", getattr(immo, 'pk', '?'), e)


    return render(request, 'patrimoine/valider_sas.html', {

        'immo': immo, 'types': types, 'marques': Marque.objects.all().order_by('nom'),

        'bureaux': Bureau.objects.select_related('etage__batiment').all().order_by('etage__batiment__code','etage__nom','nom'),

        'services': Service.objects.all().order_by('nom'), 'action_choices': Immobilisation.ACTION_CHOICES,

        'batiments': Batiment.objects.all().order_by('nom'),

    })


@login_required(login_url='/auth/login/')

@patrimoine_required

@verifier_permission('accounts.menu_pat_sas')

@require_POST

def eclater_bien_sas(request):

    immo_id = request.POST.get('immo_id')

    noms_composants = request.POST.getlist('noms_composants[]')

    # Validation robuste + borne haute : éviter le crash sur une valeur non
    # numérique et la création de milliers de clones en un seul POST.
    try:
        nombre = len(noms_composants) if noms_composants else int(request.POST.get('nombre', 2))
    except (TypeError, ValueError):
        return JsonResponse({'success': False, 'error': "Nombre invalide."})
    if nombre < 2:
        return JsonResponse({'success': False, 'error': "Le nombre doit être au moins 2."})
    if nombre > 15:
        return JsonResponse({'success': False, 'error': "Le nombre maximum de composants est 15."})

    immo = get_object_or_404(Immobilisation, id=immo_id, statut='EN_ATTENTE')

    try:

        with transaction.atomic():

            nouvelle_valeur = (immo.valeur_acquisition or 0) / Decimal(nombre)

            nom_base = immo.nom_affichage or "Matériel"

            immo.nom_affichage = f"{nom_base} — {noms_composants[0]}" if noms_composants else f"{nom_base} (Partie 1)"

            immo.valeur_acquisition = nouvelle_valeur

            immo.save()

            for i in range(1, nombre):

                nom_clone = f"{nom_base} — {noms_composants[i]}" if noms_composants else f"{nom_base} (Partie {i+1})"

                Immobilisation.objects.create(

                    type_equipement=immo.type_equipement, article_stock=immo.article_stock, nom_affichage=nom_clone,

                    service_affectation=immo.service_affectation, bureau=immo.bureau, bon_sortie_origine=immo.bon_sortie_origine,

                    valeur_acquisition=nouvelle_valeur, statut='EN_ATTENTE', cree_par=request.user

                )

        return JsonResponse({'success': True})

    except Exception as e:

        return JsonResponse({'success': False, 'error': str(e)})


@login_required(login_url='/auth/login/')

@patrimoine_required

@verifier_permission('accounts.menu_pat_sas')

def creer_immatriculation_directe(request):

    # Créer une immobilisation est une écriture : POST uniquement (un lien
    # GET préchargé par le navigateur créait des biens fantômes dans le SAS).
    if request.method != 'POST':
        return redirect('patrimoine_sas')

    nouvelle_immo = Immobilisation.objects.create(nom_affichage="Nouveau Matériel (Saisie Directe)", statut='EN_ATTENTE', valeur_acquisition=0, cree_par=request.user)

    return redirect('patrimoine_valider_sas', pk=nouvelle_immo.id)
