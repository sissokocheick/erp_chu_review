# -*- coding: utf-8 -*-
"""Inventaire tournant."""
import logging
import json

from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.utils import timezone
from django.db import transaction

from accounts.permissions import verifier_permission

from ..models import (
    Immobilisation, CampagneInventairePatrimoine,
    LigneInventairePatrimoine,
)
from .common import patrimoine_required

logger = logging.getLogger(__name__)


@login_required(login_url='/auth/login/')

@patrimoine_required

@verifier_permission('accounts.menu_pat_inventaire')

def patrimoine_campagnes_inventaire(request):

    campagnes = CampagneInventairePatrimoine.objects.all().select_related('categorie_cible', 'batiment_cible', 'responsable').order_by('-date_debut')

    categories = CategoriePatrimoine.objects.filter(est_active=True).order_by('nom')

    batiments = Batiment.objects.all().order_by('nom')


    if request.method == 'POST':

        action = request.POST.get('action')


        if action == 'save_campagne':

            item_id = request.POST.get('item_id')

            titre = request.POST.get('titre')

            reference = request.POST.get('reference')

            date_debut = request.POST.get('date_debut')

            date_fin_prevue = request.POST.get('date_fin_prevue') or None

            categorie_id = request.POST.get('categorie_cible') or None

            batiment_id = request.POST.get('batiment_cible') or None

            if not titre or not reference or not date_debut:
                messages.error(request, "⛔ Titre, référence et date de début sont obligatoires.")
                return redirect('patrimoine_campagnes_inventaire')


            if item_id:

                CampagneInventairePatrimoine.objects.filter(id=item_id).update(

                    titre=titre, reference=reference, date_debut=date_debut,

                    date_fin_prevue=date_fin_prevue, categorie_cible_id=categorie_id,

                    batiment_cible_id=batiment_id, modifie_par=request.user

                )

                messages.success(request, "Campagne modifiée avec succès.")

            else:

                CampagneInventairePatrimoine.objects.create(

                    titre=titre, reference=reference, date_debut=date_debut,

                    date_fin_prevue=date_fin_prevue, categorie_cible_id=categorie_id,

                    batiment_cible_id=batiment_id, responsable=request.user,

                    cree_par=request.user, statut='BROUILLON'

                )

                messages.success(request, "Nouvelle campagne d'inventaire créée.")


        elif action == 'delete_campagne':

            item_id = request.POST.get('item_id')

            try:

                CampagneInventairePatrimoine.objects.filter(id=item_id).delete()

                messages.success(request, "Campagne supprimée.")

            except ProtectedError:

                messages.error(request, "⛔ Impossible de supprimer cette campagne car des scans ont déjà été effectués.")


        return redirect('patrimoine_campagnes_inventaire')


    context = {'campagnes': campagnes, 'categories': categories, 'batiments': batiments}

    return render(request, 'patrimoine/patrimoine_campagnes_inventaire.html', context)


@login_required(login_url='/auth/login/')

@patrimoine_required

@verifier_permission('accounts.menu_pat_inventaire')

def detail_campagne_inventaire(request, campagne_id):

    campagne = get_object_or_404(CampagneInventairePatrimoine, id=campagne_id)

    
    params = ParametresPatrimoine.objects.first()

    validation_active = params.validation_inventaire_active if params else False

    validateurs = params.validateurs_inventaire.all() if params else []

    peut_valider = request.user in validateurs or request.user.is_superuser

    
    if request.method == 'POST':

        action = request.POST.get('action')

        
        if action == 'generer_lignes' and campagne.statut == 'BROUILLON':

            with transaction.atomic():

                campagne.lignes.all().delete()

                biens = Immobilisation.objects.filter(statut__in=['ACTIF', 'EN_PANNE'])

                if campagne.categorie_cible:

                    biens = biens.filter(type_equipement__categorie=campagne.categorie_cible)

                if campagne.batiment_cible:

                    biens = biens.filter(bureau__etage__batiment=campagne.batiment_cible)

                
                lignes_a_creer = [LigneInventairePatrimoine(campagne=campagne, immobilisation=bien) for bien in biens]

                LigneInventairePatrimoine.objects.bulk_create(lignes_a_creer)

                messages.success(request, f"Snapshot généré : {len(lignes_a_creer)} équipements trouvés.")


        elif action == 'demarrer' and campagne.statut == 'BROUILLON':

            if campagne.lignes.count() > 0:

                campagne.statut = 'EN_COURS'

                campagne.save()

                messages.success(request, "L'inventaire a démarré !")

            else:

                messages.error(request, "Générez la liste avant de démarrer.")


        elif action == 'cloturer' and campagne.statut == 'EN_COURS':

            with transaction.atomic():

                lignes_non_pointees = campagne.lignes.filter(etat_constate__isnull=True)

                nb_manquants = lignes_non_pointees.count()

                lignes_non_pointees.update(etat_constate='MANQUANT')


                if validation_active:

                    campagne.statut = 'EN_ATTENTE_VALIDATION'

                    campagne.save()

                    messages.warning(request, f"Inventaire soumis au superviseur. {nb_manquants} machines non scannées ont été déclarées manquantes.")

                else:

                    appliquer_reconciliation_inventaire(request, campagne)

                    messages.success(request, f"Inventaire clôturé. {nb_manquants} manquants enregistrés.")


        elif action == 'valider_inventaire' and campagne.statut == 'EN_ATTENTE_VALIDATION':

            if peut_valider:

                appliquer_reconciliation_inventaire(request, campagne)

                messages.success(request, "✅ Inventaire validé avec succès !")

            else:

                messages.error(request, "⛔ Autorisation refusée : vous n'êtes pas dans la liste des validateurs.")


        return redirect('patrimoine_detail_campagne', campagne_id=campagne.id)


    lignes = campagne.lignes.select_related('immobilisation', 'immobilisation__bureau', 'bureau_constate', 'scanne_par').all()

    total = lignes.count()

    pointes = lignes.exclude(etat_constate__isnull=True).count()

    
    stats = {

        'total': total,

        'pointes': pointes,

        'manquants': lignes.filter(etat_constate='MANQUANT').count(),

        'deplaces': lignes.filter(etat_constate='DEPLACE').count(),

        'rebuts': lignes.filter(etat_constate='A_REFORMER').count(),

        'progression': int((pointes / total * 100)) if total > 0 else 0

    }


    return render(request, 'patrimoine/detail_campagne_inventaire.html', {

        'campagne': campagne,

        'lignes': lignes,

        'stats': stats,

        'validation_active': validation_active,

        'peut_valider': peut_valider

    })


def appliquer_reconciliation_inventaire(request, campagne):

    with transaction.atomic():

        a_ete_valide = (campagne.statut == 'EN_ATTENTE_VALIDATION')

        user_actuel = request.user.get_full_name() or request.user.username

        date_heure = timezone.localtime().strftime('%d/%m/%Y à %H:%M')

        
        tech_scan = campagne.lignes.exclude(scanne_par__isnull=True).values(

            'scanne_par__first_name', 'scanne_par__last_name', 'scanne_par__username'

        ).annotate(total=Count('id')).order_by('-total').first()

        
        if tech_scan:

            nom_tech = f"{tech_scan['scanne_par__first_name']} {tech_scan['scanne_par__last_name']}".strip() or tech_scan['scanne_par__username']

        else:

            nom_tech = campagne.cree_par.get_full_name() if campagne.cree_par else "Équipe technique"


        if a_ete_valide:

            phrase_tracabilite = f"Inventorié sur le terrain par : {nom_tech} | Validé par : {user_actuel} le {date_heure}."

        else:

            phrase_tracabilite = f"Inventorié et clôturé par : {user_actuel} le {date_heure} (Sans double validation)."

            
        for ligne in campagne.lignes.filter(etat_constate='DEPLACE'):

            if ligne.bureau_constate:

                immo = ligne.immobilisation

                ancien_bureau = immo.bureau

                immo.bureau = ligne.bureau_constate

                immo.save()

                MouvementPatrimoine.objects.create(

                    immobilisation=immo, type_mouvement='MUTATION',

                    bureau_depart=ancien_bureau, bureau_arrivee=ligne.bureau_constate,

                    motif=f"Déplacé (Inventaire {campagne.reference}). {phrase_tracabilite}", 

                    effectue_par=request.user

                )


        for ligne in campagne.lignes.filter(etat_constate='A_REFORMER'):

            immo = ligne.immobilisation

            immo.statut = 'REFORME'

            immo.bureau = None

            immo.save()

            MouvementPatrimoine.objects.create(

                immobilisation=immo, type_mouvement='REFORME',

                motif=f"Mise au rebut (Inventaire {campagne.reference}). {phrase_tracabilite}", 

                effectue_par=request.user

            )


        campagne.lignes.filter(etat_constate__isnull=True).update(etat_constate='MANQUANT')

        
        for ligne in campagne.lignes.filter(etat_constate='MANQUANT'):

            immo = ligne.immobilisation

            immo.statut = 'DISPARU'  

            immo.save()

            MouvementPatrimoine.objects.create(

                immobilisation=immo, type_mouvement='PERTE',

                motif=f"⚠️ DÉCLARÉ PERDU (Inventaire {campagne.reference}). Non scanné. {phrase_tracabilite}", 

                effectue_par=request.user

            )


        campagne.statut = 'TERMINEE'

        campagne.date_fin_prevue = timezone.localtime().date()

        campagne.save()


@login_required(login_url='/auth/login/')

@patrimoine_required

@verifier_permission('accounts.menu_pat_inventaire')

def audit_scan_inventaire(request, campagne_id):

    campagne = get_object_or_404(CampagneInventairePatrimoine, id=campagne_id, statut='EN_COURS')

    bureaux = Bureau.objects.all().select_related('etage__batiment').order_by('etage__batiment__nom', 'nom')


    if request.method == 'POST':

        code_scanne = request.POST.get('code_patrimoine', '').strip()

        ligne_id = request.POST.get('ligne_id')

        
        if code_scanne and not ligne_id:

            ligne = LigneInventairePatrimoine.objects.filter(campagne=campagne, immobilisation__code_patrimoine__iexact=code_scanne).first()

            if not ligne:

                immo_intruse = Immobilisation.objects.filter(code_patrimoine__iexact=code_scanne).first()

                if immo_intruse:

                    ligne = LigneInventairePatrimoine.objects.create(

                        campagne=campagne, immobilisation=immo_intruse,

                        commentaire="⚠️ Ajouté pendant l'audit (Hors périmètre)"

                    )

                    messages.warning(request, "Attention : Équipement hors périmètre rajouté à l'inventaire.")

                else:

                    messages.error(request, f"⛔ Code inconnu : [{code_scanne}].")

                    return redirect('patrimoine_audit_scan', campagne_id=campagne.id)

            return render(request, 'patrimoine/audit_scan_inventaire.html', {'campagne': campagne, 'ligne_trouvee': ligne, 'bureaux': bureaux})


        if ligne_id:

            ligne = get_object_or_404(LigneInventairePatrimoine, id=ligne_id, campagne=campagne)

            etat = request.POST.get('etat_constate')

            ligne.etat_constate = etat

            ligne.bureau_constate_id = request.POST.get('bureau_constate') if etat == 'DEPLACE' else ligne.immobilisation.bureau_id

            ligne.scanne_par = request.user

            ligne.date_scan = timezone.now()

            ligne.save()

            messages.success(request, f"✅ Pointage enregistré pour {ligne.immobilisation.code_patrimoine}")

            return redirect('patrimoine_audit_scan', campagne_id=campagne.id)


    return render(request, 'patrimoine/audit_scan_inventaire.html', {'campagne': campagne, 'bureaux': bureaux})


@login_required(login_url='/auth/login/')

@patrimoine_required

@verifier_permission('accounts.menu_pat_inventaire')

def imprimer_fiche_comptage(request, campagne_id):

    campagne = get_object_or_404(CampagneInventairePatrimoine, id=campagne_id)

    lignes = campagne.lignes.select_related(

        'immobilisation', 'immobilisation__bureau', 'immobilisation__bureau__etage__batiment'

    ).order_by('immobilisation__bureau__etage__batiment__nom', 'immobilisation__bureau__nom', 'immobilisation__nom_affichage')


    context = {'campagne': campagne, 'lignes': lignes}


    try:

        html_string = render_to_string('patrimoine/imprimer_fiche_comptage.html', context, request=request)

        pdf_file = HTML(string=html_string, base_url=request.build_absolute_uri('/')).write_pdf()

    except Exception as e:

        logger.exception(f"[PDF] Erreur génération fiche de comptage {campagne.reference} : {e}")

        from django.conf import settings

        if settings.DEBUG:

            return HttpResponse(f"<h2>Erreur de génération PDF</h2><p style='color:red;'>{str(e)}</p>", content_type='text/html')

        raise


    response = HttpResponse(pdf_file, content_type='application/pdf')

    nom_fichier = f"Fiche_Comptage_{campagne.reference}.pdf"

    response['Content-Disposition'] = f'inline; filename="{nom_fichier}"'

    return response
