# -*- coding: utf-8 -*-
"""Catalogue : registre, fiche detail, modification, QR, scan, rebuts, pertes."""
import logging
import base64
from io import BytesIO

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.urls import reverse
from decimal import Decimal

import qrcode

from stock.models import Article
from accounts.permissions import verifier_permission
from core.models import Service

from ..models import (
    Immobilisation, TypeEquipement, CategoriePatrimoine,
    Batiment, Bureau, Marque, MouvementPatrimoine,
)
from .common import patrimoine_required

logger = logging.getLogger(__name__)


@login_required(login_url='/auth/login/')

@patrimoine_required

@verifier_permission('accounts.menu_pat_registre')

def registre(request):

    qs = Immobilisation.objects.select_related(

        'type_equipement__categorie', 'bureau__etage__batiment',

        'service_affectation', 'marque', 'modele',

    ).exclude(statut='EN_ATTENTE').order_by('-date_creation')


    q = request.GET.get('q', '').strip()

    if '/scan/' in q:

        q = q.rstrip('/').split('/')[-1]

        
    categorie_id = request.GET.get('categorie', '')

    type_id      = request.GET.get('type', '')

    statut       = request.GET.get('statut', '')

    service_id   = request.GET.get('service', '')

    batiment_id  = request.GET.get('batiment', '')

    action       = request.GET.get('action', '')


    if q:

        qs = qs.filter(

            Q(code_patrimoine__icontains=q) | Q(numero_serie__icontains=q) |

            Q(nom_affichage__icontains=q)   | Q(marque__nom__icontains=q) |

            Q(modele__nom__icontains=q)     | Q(specs_techniques__icontains=q)

        ).distinct()

    if categorie_id: qs = qs.filter(type_equipement__categorie_id=categorie_id)

    if type_id:      qs = qs.filter(type_equipement_id=type_id)

    if statut:       qs = qs.filter(statut=statut)

    if service_id:   qs = qs.filter(service_affectation_id=service_id)

    if batiment_id:  qs = qs.filter(bureau__etage__batiment_id=batiment_id)

    if action:       qs = qs.filter(action_requise=action)


    stats = {

        'total':       qs.count(),

        'actifs':      qs.filter(statut='ACTIF').count(),

        'en_panne':    qs.filter(statut='EN_PANNE').count(),

        'en_attente':  Immobilisation.objects.filter(statut='EN_ATTENTE').count(),

        'val_totale':  qs.aggregate(t=Sum('valeur_acquisition'))['t'] or 0,

    }


    per_page = request.GET.get('per_page', '20')

    if per_page == 'all':
        limite = max(1, qs.count())
    else:
        try:
            limite = max(1, min(int(per_page), 500))
        except (TypeError, ValueError):
            limite = 20

    page     = Paginator(qs, limite).get_page(request.GET.get('page'))


    context = {

        'immos': page, 'today': timezone.now().date(), 'stats': stats,

        'categories': CategoriePatrimoine.objects.filter(est_active=True),

        'types': TypeEquipement.objects.filter(est_actif=True).select_related('categorie'),

        'batiments': Batiment.objects.all().order_by('code'),

        'q': q, 'categorie_id': categorie_id, 'type_id': type_id, 'statut': statut,

        'service_id': service_id, 'batiment_id': batiment_id, 'action': action, 'per_page': per_page,

        'statut_choices': Immobilisation.STATUT_CHOICES, 'action_choices': Immobilisation.ACTION_CHOICES,

    }

    return render(request, 'patrimoine/registre.html', context)


@login_required(login_url='/auth/login/')

@patrimoine_required

def fiche_detail(request, pk):

    immo = get_object_or_404(

        Immobilisation.objects.select_related(

            'type_equipement__categorie', 'bureau__etage__batiment', 'service_affectation', 'marque', 'modele',

            'fournisseur', 'bon_sortie_origine', 'article_stock', 'contrat_maintenance__prestataire',

        ).prefetch_related('mouvements', 'interventions'), pk=pk

    )

    return render(request, 'patrimoine/fiche_detail.html', {

        'immo': immo, 'mouvements': immo.mouvements.order_by('-date_mouvement')[:10],

        'interventions': immo.interventions.order_by('-date_signalement')[:10],

        'specs_schema': immo.type_equipement.specs_schema if immo.type_equipement else [],

        'specs': immo.specs_techniques,

    })


@login_required(login_url='/auth/login/')

@patrimoine_required

@verifier_permission('accounts.menu_pat_registre')

def modifier_immo(request, pk):

    immo  = get_object_or_404(Immobilisation, pk=pk)

    if request.method == 'POST':

        try:

            immo.code_patrimoine        = request.POST.get('code_patrimoine') or immo.code_patrimoine

            immo.numero_serie           = request.POST.get('numero_serie', immo.numero_serie)

            immo.nom_affichage          = request.POST.get('nom_affichage', immo.nom_affichage)

            immo.type_equipement_id     = request.POST.get('type_equipement', immo.type_equipement_id)

            immo.marque_id              = request.POST.get('marque') or None

            immo.modele_id              = request.POST.get('modele') or None

            immo.bureau_id              = request.POST.get('bureau') or None

            immo.service_affectation_id = request.POST.get('service') or None

            immo.emplacement_exact      = request.POST.get('emplacement_exact', '')

            immo.garantie_expiration    = request.POST.get('garantie_expiration') or None

            # Liste blanche : le select HTML limite l'UI, pas un POST forgé.
            statut_poste = request.POST.get('statut')
            if statut_poste in [c[0] for c in Immobilisation.STATUT_CHOICES]:
                immo.statut = statut_poste

            action_postee = request.POST.get('action_requise')
            if action_postee and action_postee in [c[0] for c in Immobilisation.ACTION_CHOICES]:
                immo.action_requise = action_postee

            immo.notes                  = request.POST.get('notes', '')


            if request.POST.get('valeur_acquisition'):

                immo.valeur_acquisition = Decimal(request.POST.get('valeur_acquisition'))


            if immo.type_equipement_id:

                te = TypeEquipement.objects.get(pk=immo.type_equipement_id)

                specs = dict(immo.specs_techniques)

                for champ in te.specs_schema:

                    key = champ['key']

                    val = request.POST.get(f'spec_{key}', '')

                    if val: specs[key] = val

                immo.specs_techniques = specs


            immo.modifie_par = request.user

            immo.save()

            messages.success(request, "✅ Bien mis à jour.")

            return redirect('patrimoine_detail', pk=immo.pk)

        except Exception as e:

            messages.error(request, f"❌ Erreur : {e}")


    return render(request, 'patrimoine/modifier_immo.html', {

        'immo': immo, 

        'types': TypeEquipement.objects.filter(est_actif=True).select_related('categorie'),

        'marques': Marque.objects.all().order_by('nom'), 

        'bureaux': Bureau.objects.select_related('etage__batiment').all(),

        'services': Service.objects.all().order_by('nom'),

        'batiments': Batiment.objects.all().order_by('nom'),

    })


@login_required(login_url='/auth/login/')

@patrimoine_required

@verifier_permission('accounts.menu_pat_registre')

def etiquette_qr(request, pk):

    immo = get_object_or_404(Immobilisation, pk=pk)

    donnees_qr = request.build_absolute_uri(reverse('patrimoine_scan', args=[immo.code_patrimoine]))

    qr = qrcode.QRCode(version=1, box_size=10, border=1)

    qr.add_data(donnees_qr)

    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")

    buffer = BytesIO()

    img.save(buffer, format="PNG")

    return render(request, 'patrimoine/etiquette_qr.html', {'immo': immo, 'qr_code': base64.b64encode(buffer.getvalue()).decode("utf-8")})


@login_required(login_url='/auth/login/')

@patrimoine_required

@verifier_permission('accounts.menu_pat_registre')

def quick_edit(request, pk):

    if request.method != 'POST': return JsonResponse({'error': 'POST only'}, status=405)

    # Bouton « Forcer le statut (Admin) » : réservé au superuser
    if not request.user.is_superuser:
        return JsonResponse({'error': 'Réservé au superutilisateur'}, status=403)

    immo = get_object_or_404(Immobilisation, pk=pk)

    champ = request.POST.get('champ')

    val = request.POST.get('valeur')

    if champ not in {'statut', 'action_requise'}: return JsonResponse({'error': 'Champ non autorisé'}, status=400)

    # Listes blanches : un POST forgé ne doit pas écrire un statut arbitraire
    # (les filtres/badges/rapports reposent sur STATUT_CHOICES).
    if champ == 'statut' and val not in [c[0] for c in Immobilisation.STATUT_CHOICES]:
        return JsonResponse({'error': 'Statut non autorisé'}, status=400)
    if champ == 'action_requise' and val not in [c[0] for c in Immobilisation.ACTION_CHOICES]:
        return JsonResponse({'error': 'Action non autorisée'}, status=400)

    setattr(immo, champ, val)

    immo.modifie_par = request.user

    immo.save(update_fields=[champ, 'modifie_par', 'date_modification'])

    # Traçabilité : un statut REFORME/DISPARU/CEDE forcé doit apparaître
    # dans les registres rebuts/pertes (mouvement équivalent à la
    # réconciliation d'inventaire).
    STATUT_VERS_MOUVEMENT = {
        'REFORME': 'REFORME',
        'DISPARU': 'PERTE',
        'CEDE': 'CESSION',
    }
    type_mvt = STATUT_VERS_MOUVEMENT.get(val) if champ == 'statut' else None
    if type_mvt and not immo.mouvements.filter(type_mouvement=type_mvt).exists():
        MouvementPatrimoine.objects.create(
            immobilisation=immo,
            type_mouvement=type_mvt,
            date_mouvement=timezone.now().date(),
            motif=f"Forçage manuel du statut par {request.user.get_full_name() or request.user.username}",
            effectue_par=request.user,
        )

    return JsonResponse({'success': True, 'valeur': val, 'modifie_par': request.user.get_full_name() or request.user.username})


@login_required(login_url='/auth/login/')
def scan_mobile(request, code):

    immo = get_object_or_404(Immobilisation, code_patrimoine=code)

    return render(request, 'patrimoine/scan_mobile.html', {'immo': immo})


@login_required(login_url='/auth/login/')

@patrimoine_required

@verifier_permission('accounts.menu_pat_rebuts')

def registre_rebuts(request):

    rebuts = Immobilisation.objects.filter(statut='REFORME').select_related(

        'type_equipement', 'service_affectation', 'bureau'

    ).order_by('-id')

    
    for r in rebuts:

        mvt_reforme = r.mouvements.filter(type_mouvement='REFORME').order_by('-date_mouvement').first()

        r.details_tracabilite = mvt_reforme


    return render(request, 'patrimoine/registre_rebuts.html', {'rebuts': rebuts})


@login_required(login_url='/auth/login/')

@patrimoine_required

@verifier_permission('accounts.menu_pat_pertes')

def registre_pertes(request):

    pertes = Immobilisation.objects.filter(statut='DISPARU').select_related(

        'type_equipement', 'service_affectation'

    ).order_by('-id')

    
    for p in pertes:

        mvt_perte = p.mouvements.filter(type_mouvement='PERTE').order_by('-date_mouvement').first()

        p.details_tracabilite = mvt_perte


    return render(request, 'patrimoine/registre_pertes.html', {'pertes': pertes})
