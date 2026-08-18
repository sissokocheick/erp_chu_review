# -*- coding: utf-8 -*-
"""Parametres, schemas, types d equipement, endpoints AJAX."""
import logging
import json

from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.db import transaction

from accounts.permissions import verifier_permission

from ..models import (
    TypeEquipement, CategoriePatrimoine,
    Batiment, Etage, Bureau, Marque, Modele,
)
from .common import patrimoine_required

logger = logging.getLogger(__name__)


@login_required(login_url='/auth/login/')

@patrimoine_required

@verifier_permission('accounts.menu_pat_parametres')

def parametres(request):

    params = ParametresPatrimoine.objects.first()

    
    if request.method == 'POST':

        action  = request.POST.get('action')

        item_id = request.POST.get('item_id')

        
        try:

            if action == 'toggle_chef':

                user_id = request.POST.get('user_id')

                utilisateur = User.objects.get(id=user_id)

                
                # 🔒 Protection : vérifier que le user a un profil

                if not hasattr(utilisateur, 'profil') or utilisateur.profil is None:

                    messages.error(request, "❌ Cet utilisateur n'a pas de profil configuré. Créez-le d'abord dans la gestion des utilisateurs.")

                    return redirect('patrimoine_parametres')

                
                # Sécurité : on ne peut promouvoir que des gens de SON service (ou superuser)

                if not request.user.is_superuser and hasattr(request.user, 'profil') and request.user.profil.service:

                    if not utilisateur.profil.service or utilisateur.profil.service != request.user.profil.service:

                        messages.error(request, "⛔ Vous ne pouvez promouvoir que des membres de votre propre service.")

                        return redirect('patrimoine_parametres')

                
                nouveau_statut = not utilisateur.profil.est_chef_service

                utilisateur.profil.est_chef_service = nouveau_statut

                utilisateur.profil.save()

                titre = "promu chef de service" if nouveau_statut else "retiré du rôle de chef"

                messages.success(request, f"✅ {utilisateur.get_full_name() or utilisateur.username} a été {titre}.")


            elif action == 'save_visibilite':

                nouveau_mode = request.POST.get('mode_visibilite')

                if nouveau_mode in ['GLOBAL', 'DIRECT', 'DISPATCH']:

                    params.mode_visibilite_interventions = nouveau_mode

                
                nouveau_perimetre = request.POST.get('perimetre_declaration')

                if nouveau_perimetre in ['LIBRE', 'SERVICE', 'BUREAU']:

                    params.perimetre_declaration = nouveau_perimetre

                    
                magasin_id = request.POST.get('magasin_pieces')

                if magasin_id:

                    params.magasin_pieces_id = magasin_id

                else:

                    params.magasin_pieces = None

                    
                params.validation_inventaire_active = (request.POST.get('validation_inventaire') == 'on')

                params.save()

                
                validateurs_ids = request.POST.getlist('validateurs_inventaire')

                params.validateurs_inventaire.set(validateurs_ids)

                
                messages.success(request, "✅ Configuration et workflows mis à jour.")


            elif action == 'save_technicien':

                user_id = request.POST.get('user_id')

                categories_ids = request.POST.getlist('categories') 

                utilisateur = User.objects.get(id=user_id)

                
                # 🔒 Protection profil

                if not hasattr(utilisateur, 'profil') or utilisateur.profil is None:

                    messages.error(request, "❌ Cet utilisateur n'a pas de profil configuré.")

                    return redirect('patrimoine_parametres')

                    
                utilisateur.profil.domaines_intervention.set(categories_ids)

                messages.success(request, f"✅ Compétences mises à jour pour {utilisateur.get_full_name() or utilisateur.username}.")


            elif action == 'save_batiment':

                data = {'nom': request.POST.get('nom', '').upper(), 'code': request.POST.get('code', '').upper()}

                services_ids = request.POST.getlist('services')

                if item_id: 

                    batiment = Batiment.objects.get(pk=item_id)

                    Batiment.objects.filter(pk=item_id).update(**data, modifie_par=request.user)

                else: 

                    batiment = Batiment.objects.create(**data, cree_par=request.user)

                batiment.services.set(services_ids)

                for b in Bureau.objects.filter(etage__batiment=batiment):

                    b.services.set(services_ids)

                messages.success(request, "Bâtiment et ses bureaux mis à jour.")


            elif action == 'save_etage':

                nom = request.POST.get('nom', '').upper()

                batiment_id = request.POST.get('batiment_id')

                services_ids = request.POST.getlist('services')

                if item_id: 

                    etage = Etage.objects.get(pk=item_id)

                    Etage.objects.filter(pk=item_id).update(nom=nom, modifie_par=request.user)

                else: 

                    etage = Etage.objects.create(nom=nom, batiment_id=batiment_id, cree_par=request.user)

                etage.services.set(services_ids)

                for b in Bureau.objects.filter(etage=etage):

                    b.services.set(services_ids)

                messages.success(request, "Étage et ses bureaux mis à jour.")


            elif action == 'save_bureau':

                nom = request.POST.get('nom', '').upper()

                etage_id = request.POST.get('etage_id')

                services_ids = request.POST.getlist('services') 

                if item_id: 

                    bureau = Bureau.objects.get(pk=item_id)

                    bureau.nom = nom

                    bureau.modifie_par = request.user

                    bureau.save()

                else: 

                    bureau = Bureau.objects.create(nom=nom, etage_id=etage_id, cree_par=request.user)

                bureau.services.set(services_ids)

                messages.success(request, "Bureau enregistré et services liés.")

                
            elif action == 'assigner_bureau':

                user_id = request.POST.get('user_id')

                bureau_id = request.POST.get('bureau_id')

                utilisateur = User.objects.get(id=user_id)

                
                # 🔒 Protection profil

                if not hasattr(utilisateur, 'profil') or utilisateur.profil is None:

                    messages.error(request, "❌ Cet utilisateur n'a pas de profil configuré.")

                    return redirect('patrimoine_parametres')

                    
                utilisateur.profil.bureau_id = bureau_id if bureau_id else None

                utilisateur.profil.save()

                messages.success(request, f"✅ Bureau assigné à {utilisateur.get_full_name() or utilisateur.username}.")


            elif action == 'save_categorie':

                data = {'nom': request.POST.get('nom', '').upper(), 'code': request.POST.get('code', '').upper(), 'icone': request.POST.get('icone', 'fas fa-box'), 'couleur': request.POST.get('couleur', '#1c5b96'), 'modifie_par': request.user}

                if item_id: CategoriePatrimoine.objects.filter(pk=item_id).update(**data)

                else: data['cree_par'] = request.user; CategoriePatrimoine.objects.create(**data)

                messages.success(request, "Catégorie enregistrée.")

            elif action == 'delete_categorie':

                CategoriePatrimoine.objects.get(pk=item_id).delete()

                messages.success(request, "Catégorie supprimée.")


            elif action == 'save_type':

                data = {'categorie_id': request.POST.get('categorie'), 'nom': request.POST.get('nom', '').upper(), 'code': request.POST.get('code', '').upper(), 'duree_amortissement_defaut': int(request.POST.get('duree', 5)), 'mode_amortissement': request.POST.get('mode', 'LINEAIRE'), 'modifie_par': request.user}

                if item_id: TypeEquipement.objects.filter(pk=item_id).update(**data)

                else: data['cree_par'] = request.user; TypeEquipement.objects.create(**data)

                messages.success(request, "Type enregistré.")

            elif action == 'delete_type':

                TypeEquipement.objects.get(pk=item_id).delete()

                messages.success(request, "Type supprimé.")


            elif action == 'save_marque':

                nom = request.POST.get('nom', '').upper()

                if item_id: Marque.objects.filter(pk=item_id).update(nom=nom, modifie_par=request.user)

                else: Marque.objects.get_or_create(nom=nom, defaults={'cree_par': request.user})

                messages.success(request, "Marque enregistrée.")

            elif action == 'delete_marque':

                Marque.objects.get(pk=item_id).delete()

                messages.success(request, "Marque supprimée.")


            elif action == 'save_fournisseur':

                if item_id:

                    Fournisseur.objects.filter(id=item_id).update(raison_sociale=request.POST.get('raison_sociale'), telephone=request.POST.get('telephone'))

                    messages.success(request, "🏢 Fournisseur modifié.")

                else:

                    Fournisseur.objects.create(raison_sociale=request.POST.get('raison_sociale'), telephone=request.POST.get('telephone'), cree_par=request.user)

                    messages.success(request, "🏢 Nouveau fournisseur ajouté.")

            elif action == 'delete_fournisseur':

                Fournisseur.objects.filter(id=item_id).delete()

                messages.success(request, "🗑️ Fournisseur supprimé.")


            elif action == 'save_tech_externe':

                if item_id:

                    TechnicienPrestataire.objects.filter(id=item_id).update(fournisseur_id=request.POST.get('fournisseur_id'), nom=request.POST.get('nom'), telephone=request.POST.get('telephone'), specialite=request.POST.get('specialite', ''))

                    messages.success(request, "👷 Technicien externe mis à jour.")

                else:

                    TechnicienPrestataire.objects.create(fournisseur_id=request.POST.get('fournisseur_id'), nom=request.POST.get('nom'), telephone=request.POST.get('telephone'), specialite=request.POST.get('specialite', ''))

                    messages.success(request, "👷 Technicien externe ajouté.")

            elif action == 'delete_tech_externe':

                TechnicienPrestataire.objects.filter(id=item_id).delete()

                messages.success(request, "🗑️ Technicien externe supprimé.")


            elif action == 'save_type_contrat':

                if item_id:

                    TypeContrat.objects.filter(id=item_id).update(nom=request.POST.get('nom'), description=request.POST.get('description', ''))

                    messages.success(request, "📄 Type de contrat modifié.")

                else:

                    TypeContrat.objects.create(nom=request.POST.get('nom'), description=request.POST.get('description', ''))

                    messages.success(request, "📄 Nouveau type de contrat créé.")

            elif action == 'delete_type_contrat':

                TypeContrat.objects.filter(id=item_id).delete()

                messages.success(request, "🗑️ Type de contrat supprimé.")

                
        except ProtectedError:

            messages.error(request, "⛔ Impossible de supprimer — élément utilisé ailleurs.")

        except Exception as e:

            messages.error(request, f"❌ Erreur : {e}")


        return redirect('patrimoine_parametres')


    # 🔒 FILTRAGE : on n'affiche que les users AYANT un profil

    utilisateurs = User.objects.select_related(

        'profil', 'profil__service', 'profil__bureau'

    ).prefetch_related(

        'profil__domaines_intervention'

    ).filter(

        is_active=True, 

        profil__isnull=False

    ).order_by('first_name')

    
    from stock.models import Magasin, Fournisseur


    context = {

        'categories': CategoriePatrimoine.objects.prefetch_related('types_equipements').order_by('ordre', 'nom'),

        'types': TypeEquipement.objects.select_related('categorie').order_by('categorie', 'nom'),

        'marques': Marque.objects.all().order_by('nom'),

        'batiments': Batiment.objects.prefetch_related('etages__bureaux').order_by('code'),

        'params': params, 

        'utilisateurs': utilisateurs, 

        'magasins': Magasin.objects.all().order_by('nom'),

        'services': Service.objects.all().order_by('nom'),

        'fournisseurs': Fournisseur.objects.all().order_by('raison_sociale'),

        'techniciens': TechnicienPrestataire.objects.all().select_related('fournisseur').order_by('fournisseur__raison_sociale', 'nom'),

        'types_contrat': TypeContrat.objects.all().order_by('nom'),

        'etages_connus': list(Etage.objects.values_list('nom', flat=True).distinct().order_by('nom')),

    }

    return render(request, 'patrimoine/parametres.html', context)


@login_required(login_url='/auth/login/')

@patrimoine_required

@verifier_permission('accounts.menu_pat_parametres')

def editer_schema(request, pk):

    te = get_object_or_404(TypeEquipement, pk=pk)

    if request.method == 'POST':

        try:

            schema_raw = request.POST.get('specs_schema', '[]')

            schema = json.loads(schema_raw)

            for champ in schema:

                if 'key' not in champ or 'label' not in champ:

                    raise ValueError(f"Champ invalide : {champ}")

            te.specs_schema = schema

            te.modifie_par = request.user

            te.save()

            messages.success(request, f"✅ Schéma mis à jour.")

            return redirect('patrimoine_parametres')

        except json.JSONDecodeError:

            messages.error(request, "❌ JSON invalide.")

        except Exception as e:

            messages.error(request, f"❌ Erreur : {e}")

    return render(request, 'patrimoine/editer_schema.html', {'te': te})


@login_required(login_url="/auth/login/")

def ajax_modeles(request):

    marque_id = request.GET.get('marque')

    return JsonResponse(list(Modele.objects.filter(marque_id=marque_id).values('id', 'nom').order_by('nom')), safe=False)


@login_required(login_url="/auth/login/")

def ajax_batiments(request):

    service_id = request.GET.get('service')

    qs = Batiment.objects.all()

    if service_id:

        qs = qs.filter(etages__bureaux__services__id=service_id).distinct()

    return JsonResponse(list(qs.values('id', 'nom').order_by('nom')), safe=False)


@login_required(login_url="/auth/login/")

def ajax_localisation(request):

    service_id = request.GET.get('service')

    batiment_id = request.GET.get('batiment')

    etage_id = request.GET.get('etage')

    bureau_id = request.GET.get('bureau')


    qs_b = Bureau.objects.all()

    qs_e = Etage.objects.all()

    qs_bat = Batiment.objects.all()

    qs_s = Service.objects.all()


    if service_id:

        qs_b = qs_b.filter(services__id=service_id)

        qs_e = qs_e.filter(bureaux__services__id=service_id).distinct()

        qs_bat = qs_bat.filter(etages__bureaux__services__id=service_id).distinct()

    
    if batiment_id:

        qs_b = qs_b.filter(etage__batiment_id=batiment_id)

        qs_e = qs_e.filter(batiment_id=batiment_id)

        qs_s = qs_s.filter(bureaux_occupes__etage__batiment_id=batiment_id).distinct()

        
    if etage_id:

        qs_b = qs_b.filter(etage_id=etage_id)

        qs_bat = qs_bat.filter(etages__id=etage_id).distinct()

        qs_s = qs_s.filter(bureaux_occupes__etage_id=etage_id).distinct()

        
    if bureau_id:

        qs_e = qs_e.filter(bureaux__id=bureau_id).distinct()

        qs_bat = qs_bat.filter(etages__bureaux__id=bureau_id).distinct()

        qs_s = qs_s.filter(bureaux_occupes__id=bureau_id).distinct()


    return JsonResponse({

        'services': list(qs_s.values('id', 'nom').order_by('nom')),

        'batiments': list(qs_bat.values('id', 'nom').order_by('nom')),

        'etages': list(qs_e.values('id', 'nom').order_by('nom')),

        'bureaux': list(qs_b.values('id', 'nom').order_by('nom'))

    })


@login_required(login_url="/auth/login/")

def ajax_specs_schema(request):

    try:

        te = TypeEquipement.objects.get(pk=request.GET.get('type'))

        return JsonResponse({'schema': te.specs_schema, 'duree': te.duree_amortissement_defaut, 'mode': te.mode_amortissement})

    except TypeEquipement.DoesNotExist:

        return JsonResponse({'schema': [], 'duree': 5, 'mode': 'LINEAIRE'})


@login_required(login_url="/auth/login/")

def ajax_vnc(request, pk):

    try:

        immo = Immobilisation.objects.get(pk=pk)

        return JsonResponse({'vnc': str(immo.vnc), 'taux_amorti': str(immo.taux_amorti_pct), 'annees_ecoulees': str(immo.annees_ecoulees), 'est_totalement_amorti': immo.est_totalement_amorti})

    except Immobilisation.DoesNotExist:

        return JsonResponse({'error': 'not found'}, status=404)


@login_required(login_url='/auth/login/')

@patrimoine_required

@verifier_permission('accounts.menu_pat_parametres')

def creer_type_equipement(request):

    if request.method == 'POST':

        try:

            specs_schema = json.loads(request.POST.get('specs_schema_cache', '[]'))

            TypeEquipement.objects.create(

                nom=request.POST.get('nom'), code=request.POST.get('code'), categorie_id=request.POST.get('categorie'),

                duree_amortissement_defaut=request.POST.get('duree_amortissement_defaut', 5), specs_schema=specs_schema, cree_par=request.user

            )

            messages.success(request, "Type créé avec succès !")

            return redirect('patrimoine_registre')

        except Exception as e:

            messages.error(request, f"Erreur : {e}")

    return render(request, 'patrimoine/creer_type_equipement.html', {'categories': CategoriePatrimoine.objects.all()})


@login_required(login_url='/auth/login/')

@patrimoine_required

@verifier_permission('accounts.menu_pat_parametres')

def api_type_specs(request, type_id):

    try:

        return JsonResponse({'specs': TypeEquipement.objects.get(id=type_id).specs_schema})

    except TypeEquipement.DoesNotExist:

        return JsonResponse({'specs': []})
