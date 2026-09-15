import json
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib import messages
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db.models import Sum, Count, Q, F, DecimalField
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.http import JsonResponse
from core.models import Service
from .models import Projet, ProjetBesoin, ProjetProforma, ProjetProformaLigne
from stock.models import Article, BonMouvement, LigneBon, Fournisseur
from accounts.permissions import verifier_permission

def _get_direction_technique_default():
    """Retourne le service Direction Technique par défaut (ou le crée si inexistant)."""
    svc = Service.objects.filter(nom__icontains='technique').first()
    if not svc:
        svc, _ = Service.objects.get_or_create(
            code='DIR_TECH',
            defaults={'nom': 'Direction des Services Techniques', 'poste': 'DST'}
        )
    return svc

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_projets')
def liste_projets(request):
    """Liste des projets haute performance avec pagination serveur, recherche débouncée et KPIs en 1 seule requête SQL."""
    q = request.GET.get('q', '').strip()
    statut = request.GET.get('statut', 'TOUS').strip()
    per_page = request.GET.get('per_page', '25')
    page = request.GET.get('page', 1)
    
    try:
        per_page_int = int(per_page)
        if per_page_int not in [15, 25, 50, 100]:
            per_page_int = 25
    except (ValueError, TypeError):
        per_page_int = 25

    base_qs = Projet.objects.filter(is_deleted=False)
    
    # Agrégation ultra-rapide des KPIs en 1 seule passe SQL
    kpis = base_qs.aggregate(
        total=Count('id'),
        en_cours=Count('id', filter=Q(statut='EN_COURS')),
        prepa=Count('id', filter=Q(statut='PREPARATION')),
        termine=Count('id', filter=Q(statut='TERMINE')),
        total_budget=Sum('budget_alloue')
    )
    total_projets = kpis['total'] or 0
    en_cours_count = kpis['en_cours'] or 0
    prepa_count = kpis['prepa'] or 0
    termine_count = kpis['termine'] or 0
    total_budget = kpis['total_budget'] or 0

    # QuerySet avec select_related pour supprimer les requêtes N+1
    qs = base_qs.select_related('chef_de_projet', 'fournisseur', 'direction_responsable', 'responsable_direction')
    if statut and statut != 'TOUS':
        qs = qs.filter(statut=statut)
    if q:
        qs = qs.filter(
            Q(nom__icontains=q) |
            Q(description__icontains=q) |
            Q(chef_de_projet__first_name__icontains=q) |
            Q(chef_de_projet__last_name__icontains=q) |
            Q(chef_de_projet__username__icontains=q) |
            Q(fournisseur__raison_sociale__icontains=q)
        )
    
    qs = qs.order_by('-date_creation')
    
    paginator = Paginator(qs, per_page_int)
    try:
        projets_page = paginator.page(page)
    except PageNotAnInteger:
        projets_page = paginator.page(1)
    except EmptyPage:
        projets_page = paginator.page(paginator.num_pages)
        
    context = {
        'projets': projets_page,
        'projets_page': projets_page,
        'total_projets': total_projets,
        'en_cours_count': en_cours_count,
        'prepa_count': prepa_count,
        'termine_count': termine_count,
        'total_budget': total_budget,
        'q': q,
        'statut_actif': statut,
        'per_page': str(per_page_int),
        'total_filtre': paginator.count,
    }
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' or request.GET.get('ajax') == '1':
        return render(request, 'projets/projets_lignes.html', context)
        
    return render(request, 'projets/liste.html', context)


@login_required(login_url='/auth/login/')
def api_recherche_projets(request):
    """API AJAX paginée ultra-rapide pour Select2 (recherche instantanée sur des milliers de projets)."""
    q = request.GET.get('q', '').strip()
    page = int(request.GET.get('page', 1))
    page_size = 25
    offset = (page - 1) * page_size
    
    qs = Projet.objects.filter(is_deleted=False).exclude(statut__in=['TERMINE', 'ANNULE']).select_related('fournisseur')
    if q:
        qs = qs.filter(Q(nom__icontains=q) | Q(fournisseur__raison_sociale__icontains=q))
    
    total = qs.count()
    projets = list(qs.order_by('nom')[offset:offset + page_size])
    
    results = []
    for p in projets:
        fourn_nom = f" ({p.fournisseur.raison_sociale})" if p.fournisseur else ""
        results.append({
            'id': p.id,
            'text': f"{p.nom}{fourn_nom}",
            'nom': p.nom,
            'fournisseur_id': p.fournisseur_id or '',
            'fournisseur_nom': p.fournisseur.raison_sociale if p.fournisseur else '',
            'meme_fournisseur': '1' if p.meme_fournisseur_livreur else '0'
        })
    
    return JsonResponse({
        'results': results,
        'pagination': {'more': (offset + page_size) < total}
    })

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_projets')
def api_recherche_articles(request):
    """API AJAX ultra-rapide pour Select2 (recherche paginée sur 100 000 articles avec prix fournisseur spécifique)."""
    from stock.models import Article, ArticleFournisseur
    q = request.GET.get('q', '').strip()
    fournisseur_id = request.GET.get('fournisseur_id')
    page = int(request.GET.get('page', 1))
    page_size = 25
    offset = (page - 1) * page_size
    
    qs = Article.objects.filter(is_deleted=False)
    if q:
        qs = qs.filter(Q(designation__icontains=q) | Q(reference__icontains=q))
    
    total = qs.count()
    articles = list(qs.order_by('designation')[offset:offset + page_size].values('id', 'designation', 'reference', 'prix_reference'))
    
    # Récupérer les tarifs spécifiques pour ce fournisseur si fourni
    tarifs_map = {}
    if fournisseur_id and str(fournisseur_id).isdigit():
        a_ids = [a['id'] for a in articles]
        tarifs = ArticleFournisseur.objects.filter(
            article_id__in=a_ids,
            fournisseur_id=int(fournisseur_id),
            is_deleted=False
        )
        for t in tarifs:
            tarifs_map[t.article_id] = float(t.prix_achat)
    
    results = []
    for a in articles:
        ref_txt = f" (Réf: {a['reference']})" if a.get('reference') else ""
        has_f_price = a['id'] in tarifs_map
        prix_applique = tarifs_map[a['id']] if has_f_price else float(a.get('prix_reference') or 0)
        results.append({
            'id': a['id'],
            'reference': a.get('reference') or '',
            'designation': a['designation'],
            'prix_reference': prix_applique,
            'prix_fournisseur_specifique': has_f_price,
            'text': f"{a['designation']}{ref_txt}"
        })
    
    return JsonResponse({
        'results': results,
        'pagination': {'more': (offset + page_size) < total}
    })

def _synchroniser_besoins_projet(projet):
    """Synchronise le modèle ProjetBesoin à partir de toutes les proformas ACTIVES du projet."""
    cumul_besoins = (
        ProjetProformaLigne.objects.filter(proforma__projet=projet, proforma__statut='ACTIF')
        .values('article_id')
        .annotate(total_prevu=Sum('quantite_prevue'))
    )
    articles_actifs = set()
    for row in cumul_besoins:
        aid = row['article_id']
        total_qte = row['total_prevu'] or 0
        articles_actifs.add(aid)
        ProjetBesoin.objects.update_or_create(
            projet=projet,
            article_id=aid,
            defaults={'quantite_prevue': total_qte}
        )
    ProjetBesoin.objects.filter(projet=projet).exclude(article_id__in=articles_actifs).delete()


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_projets')
def creer_projet(request):
    from stock.models import Article, Fournisseur

    if request.method == 'POST':
        nom = request.POST.get('nom')
        description = request.POST.get('description', '')
        date_debut = request.POST.get('date_debut') or None
        date_fin_prevue = request.POST.get('date_fin_prevue') or None
        budget = request.POST.get('budget_alloue') or None
        statut = request.POST.get('statut') or 'EN_COURS'
        
        fournisseur_id = request.POST.get('fournisseur') or None
        f_id = int(fournisseur_id) if fournisseur_id and str(fournisseur_id).strip().isdigit() else None
        meme_fournisseur_livreur = request.POST.get('meme_fournisseur_livreur') in ['on', '1', 'true', True]

        chef_id = request.POST.get('chef_de_projet')
        if chef_id and str(chef_id).strip().isdigit():
            chef_user = User.objects.filter(id=int(chef_id), is_active=True).first()
        else:
            chef_user = None

        dir_id = request.POST.get('direction_responsable')
        if dir_id and str(dir_id).strip().isdigit():
            dir_service = Service.objects.filter(id=int(dir_id)).first()
        else:
            dir_service = _get_direction_technique_default()

        resp_dir_id = request.POST.get('responsable_direction')
        if resp_dir_id and str(resp_dir_id).strip().isdigit():
            resp_dir_user = User.objects.filter(id=int(resp_dir_id), is_active=True).first()
        else:
            resp_dir_user = None

        projet = Projet.objects.create(
            nom=nom,
            description=description,
            date_debut=date_debut,
            date_fin_prevue=date_fin_prevue,
            budget_alloue=budget,
            statut=statut,
            fournisseur_id=f_id,
            meme_fournisseur_livreur=meme_fournisseur_livreur,
            chef_de_projet=chef_user or request.user,
            direction_responsable=dir_service,
            responsable_direction=resp_dir_user,
            cree_par=request.user
        )

        proformas_json = request.POST.get('proformas_json')
        if proformas_json and proformas_json.strip() and proformas_json.strip() != '[]':
            try:
                pf_list = json.loads(proformas_json)
                for pf_item in pf_list:
                    numero = pf_item.get('numero_proforma') or f"PF-{timezone.now().strftime('%Y%m')}-001"
                    date_pf = pf_item.get('date_proforma') or timezone.now().date()
                    fournisseur_id_item = pf_item.get('fournisseur_id') or f_id
                    f_pf_id = int(fournisseur_id_item) if fournisseur_id_item and str(fournisseur_id_item).isdigit() else f_id
                    objet = pf_item.get('objet') or "Proforma initiale"
                    lignes = pf_item.get('lignes', [])

                    if lignes:
                        proforma = ProjetProforma.objects.create(
                            projet=projet,
                            numero_proforma=numero,
                            date_proforma=date_pf,
                            fournisseur_id=f_pf_id,
                            objet=objet,
                            statut='ACTIF',
                            cree_par=request.user,
                            modifie_par=request.user,
                        )
                        for l in lignes:
                            aid = l.get('article_id')
                            qte = l.get('quantite')
                            pu = l.get('prix_unitaire') or 0
                            if aid and qte:
                                try:
                                    q = int(qte)
                                    if q > 0:
                                        ProjetProformaLigne.objects.create(
                                            proforma=proforma,
                                            article_id=int(aid),
                                            quantite_prevue=q,
                                            prix_unitaire_estime=Decimal(str(pu)) if pu else Decimal(0)
                                        )
                                except (ValueError, TypeError):
                                    pass
                _synchroniser_besoins_projet(projet)
            except json.JSONDecodeError:
                pass
        else:
            # Fallback legacy pour articles[] et quantites[]
            article_ids = request.POST.getlist('articles[]')
            quantites = request.POST.getlist('quantites[]')
            if any(aid and qte for aid, qte in zip(article_ids, quantites)):
                proforma = ProjetProforma.objects.create(
                    projet=projet,
                    numero_proforma=request.POST.get('numero_proforma') or f"PF-{timezone.now().strftime('%Y%m')}-001",
                    date_proforma=request.POST.get('date_proforma') or timezone.now().date(),
                    fournisseur_id=f_id,
                    objet=request.POST.get('objet_proforma', 'Proforma initiale'),
                    statut='ACTIF',
                    cree_par=request.user,
                    modifie_par=request.user,
                )
                for aid, qte in zip(article_ids, quantites):
                    if aid and qte:
                        try:
                            q = int(qte)
                            if q > 0:
                                ProjetProformaLigne.objects.create(
                                    proforma=proforma,
                                    article_id=int(aid),
                                    quantite_prevue=q
                                )
                        except ValueError:
                            pass
                _synchroniser_besoins_projet(projet)

        messages.success(request, f"Projet '{nom}' créé avec succès.")
        return redirect('projets:detail', projet_id=projet.id)
        
    # Optimisation : seulement les 20 premiers articles pour le premier rendu
    articles_initiaux = Article.objects.filter(is_deleted=False).order_by('designation')[:20]
    fournisseurs = Fournisseur.objects.filter(is_deleted=False).order_by('raison_sociale')
    users = User.objects.filter(is_active=True).select_related('profil', 'profil__service', 'profil__fonction').order_by('first_name', 'last_name', 'username')
    services = Service.objects.all().order_by('nom')
    dir_technique_defaut = _get_direction_technique_default()
    return render(request, 'projets/formulaire.html', {
        'action': 'Créer',
        'articles': articles_initiaux,
        'fournisseurs': fournisseurs,
        'users': users,
        'services': services,
        'dir_technique_defaut': dir_technique_defaut,
        'statut_choices': Projet.STATUT_CHOICES,
        'statut_default': 'EN_COURS',
        'proformas_initiales_json': '[]',
    })

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_projets')
def modifier_projet(request, projet_id):
    from stock.models import Article, Fournisseur
    from .models import ProjetBesoin

    projet = get_object_or_404(Projet, id=projet_id, is_deleted=False)

    if request.method == 'POST':
        projet.nom = request.POST.get('nom')
        projet.description = request.POST.get('description', '')
        projet.date_debut = request.POST.get('date_debut') or None
        projet.date_fin_prevue = request.POST.get('date_fin_prevue') or None
        projet.budget_alloue = request.POST.get('budget_alloue') or None
        projet.statut = request.POST.get('statut') or projet.statut
        
        fournisseur_id = request.POST.get('fournisseur') or None
        projet.fournisseur_id = int(fournisseur_id) if fournisseur_id and str(fournisseur_id).strip().isdigit() else None
        projet.meme_fournisseur_livreur = request.POST.get('meme_fournisseur_livreur') in ['on', '1', 'true', True]
        
        chef_id = request.POST.get('chef_de_projet')
        if chef_id and str(chef_id).strip().isdigit():
            chef_user = User.objects.filter(id=int(chef_id), is_active=True).first()
            if chef_user:
                projet.chef_de_projet = chef_user

        dir_id = request.POST.get('direction_responsable')
        if dir_id and str(dir_id).strip().isdigit():
            projet.direction_responsable = Service.objects.filter(id=int(dir_id)).first()
        elif dir_id == '':
            projet.direction_responsable = None

        resp_dir_id = request.POST.get('responsable_direction')
        if resp_dir_id and str(resp_dir_id).strip().isdigit():
            projet.responsable_direction = User.objects.filter(id=int(resp_dir_id), is_active=True).first()
        elif resp_dir_id == '':
            projet.responsable_direction = None

        projet.modifie_par = request.user
        projet.save()

        # Mise à jour des besoins proforma si soumis via JSON
        proformas_json = request.POST.get('proformas_json')
        if proformas_json is not None and proformas_json.strip():
            try:
                pf_list = json.loads(proformas_json)
                soumis_ids = []
                for pf_item in pf_list:
                    pf_id = pf_item.get('id')
                    numero = pf_item.get('numero_proforma') or f"PF-{timezone.now().strftime('%Y%m')}-001"
                    date_pf = pf_item.get('date_proforma') or timezone.now().date()
                    fournisseur_id_item = pf_item.get('fournisseur_id') or projet.fournisseur_id
                    f_pf_id = int(fournisseur_id_item) if fournisseur_id_item and str(fournisseur_id_item).isdigit() else projet.fournisseur_id
                    objet = pf_item.get('objet') or "Proforma initiale"
                    lignes = pf_item.get('lignes', [])

                    if pf_id:
                        try:
                            pf = ProjetProforma.objects.get(id=int(pf_id), projet=projet)
                            pf.numero_proforma = numero
                            pf.date_proforma = date_pf
                            pf.fournisseur_id = f_pf_id
                            pf.objet = objet
                            pf.statut = 'ACTIF'
                            pf.modifie_par = request.user
                            pf.save()
                            soumis_ids.append(pf.id)
                        except (ProjetProforma.DoesNotExist, ValueError):
                            pf = ProjetProforma.objects.create(
                                projet=projet,
                                numero_proforma=numero,
                                date_proforma=date_pf,
                                fournisseur_id=f_pf_id,
                                objet=objet,
                                statut='ACTIF',
                                cree_par=request.user,
                                modifie_par=request.user,
                            )
                            soumis_ids.append(pf.id)
                    else:
                        if lignes:
                            pf = ProjetProforma.objects.create(
                                projet=projet,
                                numero_proforma=numero,
                                date_proforma=date_pf,
                                fournisseur_id=f_pf_id,
                                objet=objet,
                                statut='ACTIF',
                                cree_par=request.user,
                                modifie_par=request.user,
                            )
                            soumis_ids.append(pf.id)

                    if lignes:
                        pf.lignes.all().delete()
                        for l in lignes:
                            aid = l.get('article_id')
                            qte = l.get('quantite')
                            pu = l.get('prix_unitaire') or 0
                            if aid and qte:
                                try:
                                    q = int(qte)
                                    if q > 0:
                                        ProjetProformaLigne.objects.create(
                                            proforma=pf,
                                            article_id=int(aid),
                                            quantite_prevue=q,
                                            prix_unitaire_estime=Decimal(str(pu)) if pu else Decimal(0)
                                        )
                                except (ValueError, TypeError):
                                    pass

                projet.proformas.filter(statut='ACTIF').exclude(id__in=soumis_ids).update(statut='ANNULE')
                _synchroniser_besoins_projet(projet)
            except json.JSONDecodeError:
                pass
        else:
            # Fallback legacy pour articles[] et quantites[]
            article_ids = request.POST.getlist('articles[]')
            quantites = request.POST.getlist('quantites[]')
            if article_ids and any(aid and qte for aid, qte in zip(article_ids, quantites)):
                pf = projet.proformas.filter(statut='ACTIF').order_by('id').first()
                if not pf:
                    pf = ProjetProforma.objects.create(
                        projet=projet,
                        numero_proforma=request.POST.get('numero_proforma') or f"PF-{timezone.now().strftime('%Y%m')}-001",
                        date_proforma=request.POST.get('date_proforma') or timezone.now().date(),
                        fournisseur_id=projet.fournisseur_id,
                        objet="Proforma initiale",
                        statut='ACTIF',
                        cree_par=request.user,
                        modifie_par=request.user,
                    )
                else:
                    if request.POST.get('numero_proforma'):
                        pf.numero_proforma = request.POST.get('numero_proforma')
                    if request.POST.get('date_proforma'):
                        pf.date_proforma = request.POST.get('date_proforma')
                    pf.save()
                pf.lignes.all().delete()
                for aid, qte in zip(article_ids, quantites):
                    if aid and qte:
                        try:
                            q = int(qte)
                            if q > 0:
                                ProjetProformaLigne.objects.create(
                                    proforma=pf,
                                    article_id=int(aid),
                                    quantite_prevue=q
                                )
                        except ValueError:
                            pass
                _synchroniser_besoins_projet(projet)

        messages.success(request, f"Projet '{projet.nom}' mis à jour avec succès.")
        return redirect('projets:detail', projet_id=projet.id)

    besoins = ProjetBesoin.objects.filter(projet=projet).select_related('article')
    articles_ids_besoins = [b.article_id for b in besoins]
    articles = Article.objects.filter(Q(id__in=articles_ids_besoins) | Q(is_deleted=False)).order_by('designation')[:50]
    fournisseurs = Fournisseur.objects.filter(is_deleted=False).order_by('raison_sociale')
    
    # Sérialisation des proformas actives pour le tableau et l'accordéon
    active_pfs = list(projet.proformas.filter(statut='ACTIF').prefetch_related('lignes__article', 'fournisseur'))
    proformas_data = []
    if active_pfs:
        for pf in active_pfs:
            proformas_data.append({
                'id': pf.id,
                'numero_proforma': pf.numero_proforma,
                'date_proforma': pf.date_proforma.strftime('%Y-%m-%d') if pf.date_proforma else '',
                'fournisseur_id': pf.fournisseur_id or '',
                'fournisseur_nom': pf.fournisseur.raison_sociale if pf.fournisseur else '',
                'objet': pf.objet or '',
                'lignes': [
                    {
                        'article_id': l.article_id,
                        'reference': l.article.reference or '',
                        'designation': l.article.designation,
                        'quantite': l.quantite_prevue,
                        'prix_unitaire': float(l.prix_unitaire_estime or 0),
                        'montant_total': float((l.quantite_prevue or 0) * (l.prix_unitaire_estime or 0))
                    } for l in pf.lignes.all()
                ]
            })
    elif besoins.exists():
        # Rétrocompatibilité si un ancien projet n'avait que ProjetBesoin
        proformas_data.append({
            'id': None,
            'numero_proforma': f"PF-{projet.date_creation.strftime('%Y%m') if projet.date_creation else 'INIT'}-001",
            'date_proforma': (projet.date_debut or timezone.now().date()).strftime('%Y-%m-%d'),
            'fournisseur_id': projet.fournisseur_id or '',
            'fournisseur_nom': projet.fournisseur.raison_sociale if projet.fournisseur else '',
            'objet': 'Besoins initiaux du chantier',
            'lignes': [
                {
                    'article_id': b.article_id,
                    'reference': b.article.reference or '',
                    'designation': b.article.designation,
                    'quantite': b.quantite_prevue,
                    'prix_unitaire': float(b.article.prix_reference or 0),
                    'montant_total': float((b.quantite_prevue or 0) * (b.article.prix_reference or 0))
                } for b in besoins
            ]
        })
    proformas_initiales_json = json.dumps(proformas_data)

    users = User.objects.filter(is_active=True).select_related('profil', 'profil__service', 'profil__fonction').order_by('first_name', 'last_name', 'username')
    services = Service.objects.all().order_by('nom')
    dir_technique_defaut = _get_direction_technique_default()
    return render(request, 'projets/formulaire.html', {
        'action': 'Modifier',
        'projet': projet,
        'besoins': besoins,
        'articles': articles,
        'fournisseurs': fournisseurs,
        'users': users,
        'services': services,
        'dir_technique_defaut': dir_technique_defaut,
        'statut_choices': Projet.STATUT_CHOICES,
        'statut_default': projet.statut,
        'proformas_initiales_json': proformas_initiales_json,
    })

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_projets')
def changer_statut(request, projet_id):
    projet = get_object_or_404(Projet, id=projet_id, is_deleted=False)
    if request.method == 'POST':
        nouveau_statut = request.POST.get('statut')
        if nouveau_statut in dict(Projet.STATUT_CHOICES):
            projet.statut = nouveau_statut
            if nouveau_statut == 'TERMINE' and not projet.date_fin_reelle:
                projet.date_fin_reelle = timezone.now().date()
            projet.modifie_par = request.user
            projet.save()
            messages.success(request, f"Le statut du projet a été changé en « {projet.get_statut_display()} ».")
    return redirect('projets:detail', projet_id=projet.id)

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_projets')
def detail_projet(request, projet_id):
    from .models import ProjetBesoin
    projet = get_object_or_404(
        Projet.objects.select_related(
            'chef_de_projet', 'chef_de_projet__profil',
            'responsable_direction', 'responsable_direction__profil',
            'direction_responsable', 'fournisseur'
        ),
        id=projet_id, is_deleted=False
    )
    
    bons_sortie = BonMouvement.objects.filter(
        projet=projet, type_bon__in=['SORTIE_PROJET', 'SORTIE'], est_annule=False
    ).select_related('cree_par').prefetch_related('lignes_bon').order_by('-date_bon')
    
    bons_retour = BonMouvement.objects.filter(
        projet=projet, type_bon__in=['RETOUR_PROJET', 'RETOUR_SERVICE'], est_annule=False
    ).select_related('cree_par').prefetch_related('lignes_bon').order_by('-date_bon')
    
    bons_entree = BonMouvement.objects.filter(
        projet=projet, type_bon='ENTREE', est_annule=False
    ).select_related('cree_par').prefetch_related('lignes_bon').order_by('-date_bon')
    
    # 1. Charger la Proforma (Prévu)
    besoins = ProjetBesoin.objects.filter(projet=projet).select_related('article')
    
    # 2. Aggrégations
    lignes_entree = LigneBon.objects.filter(bon__in=bons_entree).values('article__designation', 'article__id').annotate(
        total_recu=Sum('quantite'),
        valeur_recue=Sum(F('quantite') * Coalesce('prix_unitaire', 0.0, output_field=DecimalField()))
    )
    
    lignes_sortie = LigneBon.objects.filter(bon__in=bons_sortie).values('article__designation', 'article__id').annotate(
        total_sorti=Sum('quantite'),
        valeur_sortie=Sum(F('quantite') * Coalesce('prix_unitaire', 0.0, output_field=DecimalField()))
    )
    
    lignes_retour = LigneBon.objects.filter(bon__in=bons_retour).values('article__designation', 'article__id').annotate(
        total_retourne=Sum('quantite'),
        valeur_retournee=Sum(F('quantite') * Coalesce('prix_unitaire', 0.0, output_field=DecimalField()))
    )
    
    # Fusion
    bilan = {}
    
    # Init from Proforma
    for b in besoins:
        aid = b.article.id
        bilan[aid] = {
            'designation': b.article.designation,
            'prevu': b.quantite_prevue,
            'recu': 0, 'valeur_recue': 0,
            'sorti': 0, 'valeur_sortie': 0,
            'retourne': 0, 'valeur_retournee': 0,
            'net': 0, 'valeur_nette': 0
        }
        
    def _init_if_missing(aid, desig):
        if aid not in bilan:
            bilan[aid] = {
                'designation': desig, 'prevu': 0,
                'recu': 0, 'valeur_recue': 0,
                'sorti': 0, 'valeur_sortie': 0,
                'retourne': 0, 'valeur_retournee': 0,
                'net': 0, 'valeur_nette': 0
            }
            
    for l in lignes_entree:
        aid = l['article__id']
        _init_if_missing(aid, l['article__designation'])
        bilan[aid]['recu'] = l['total_recu']
        bilan[aid]['valeur_recue'] = l['valeur_recue']
        
    for l in lignes_sortie:
        aid = l['article__id']
        _init_if_missing(aid, l['article__designation'])
        bilan[aid]['sorti'] = l['total_sorti']
        bilan[aid]['valeur_sortie'] = l['valeur_sortie']

    for l in lignes_retour:
        aid = l['article__id']
        _init_if_missing(aid, l['article__designation'])
        bilan[aid]['retourne'] = l['total_retourne']
        bilan[aid]['valeur_retournee'] = l['valeur_retournee']
        
    # Calculs Net
    for aid, data in bilan.items():
        data['net'] = data['sorti'] - data['retourne']
        data['valeur_nette'] = data['valeur_sortie'] - data['valeur_retournee']
        # Progression réception
        data['progression_recu'] = min(100, int((data['recu'] / data['prevu']) * 100)) if data['prevu'] > 0 else (100 if data['recu'] > 0 else 0)
        # Alertes
        data['alerte_surconsommation'] = data['net'] > data['prevu'] if data['prevu'] > 0 else (data['net'] > 0)
        
    total_prevu = sum(item['prevu'] for item in bilan.values())
    total_recu = sum(item['recu'] for item in bilan.values())
    total_sorti = sum(item['sorti'] for item in bilan.values())
    total_retourne = sum(item['retourne'] for item in bilan.values())
    total_net = total_sorti - total_retourne
    total_valeur_nette = sum(item['valeur_nette'] for item in bilan.values())
    total_valeur_recue = sum(item['valeur_recue'] for item in bilan.values())
    total_surconsommations = sum(1 for item in bilan.values() if item.get('alerte_surconsommation'))
    progression_globale = min(100, int((total_recu / total_prevu) * 100)) if total_prevu > 0 else (100 if total_recu > 0 else 0)
    
    bilan_global = {
        'total_articles': len(bilan),
        'total_prevu': total_prevu,
        'total_recu': total_recu,
        'progression_globale': progression_globale,
        'total_sorti': total_sorti,
        'total_retourne': total_retourne,
        'total_net': total_net,
        'total_valeur_nette': total_valeur_nette,
        'total_valeur_recue': total_valeur_recue,
        'total_surconsommations': total_surconsommations,
    }
    
    # Proformas du projet
    proformas = projet.proformas.select_related('fournisseur', 'cree_par').prefetch_related('lignes__article').order_by('-date_proforma', '-date_creation')
    fournisseurs = Fournisseur.objects.all().order_by('raison_sociale')
    articles_initiaux = Article.objects.filter(is_deleted=False).order_by('designation')[:30]

    context = {
        'projet': projet,
        'proformas': proformas,
        'fournisseurs': fournisseurs,
        'articles': articles_initiaux,
        'bons_sortie': bons_sortie,
        'bons_retour': bons_retour,
        'bons_entree': bons_entree,
        'bilan': bilan.values(),
        'bilan_global': bilan_global,
        'total_valeur_nette': total_valeur_nette,
        'total_valeur_recue': total_valeur_recue
    }
    return render(request, 'projets/detail.html', context)


# ═════════════════════════════════════════════════════════════════════════════
# GESTION DES PROFORMAS / DEVIS FOURNISSEURS DU PROJET
# ═════════════════════════════════════════════════════════════════════════════

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_projets')
def creer_proforma(request, projet_id):
    """Crée une nouvelle proforma / devis prévisionnel pour un projet."""
    projet = get_object_or_404(Projet, id=projet_id, is_deleted=False)
    
    if projet.statut in ['TERMINE', 'ANNULE']:
        messages.error(request, f"Impossible d'ajouter une proforma : le projet est {projet.get_statut_display().lower()}.")
        return redirect('projets:detail', projet_id=projet.id)

    if request.method == 'POST':
        numero = (request.POST.get('numero_proforma') or '').strip()
        if not numero:
            count = projet.proformas.count() + 1
            numero = f"PF-{timezone.now().strftime('%Y%m')}-{count:03d}"
            
        date_pf = request.POST.get('date_proforma') or timezone.now().date()
        fournisseur_id = request.POST.get('fournisseur') or None
        f_id = int(fournisseur_id) if fournisseur_id and str(fournisseur_id).strip().isdigit() else projet.fournisseur_id
        objet = request.POST.get('objet', '').strip()
        fichier = request.FILES.get('fichier_joint')
        
        proforma = ProjetProforma.objects.create(
            projet=projet,
            numero_proforma=numero,
            date_proforma=date_pf,
            fournisseur_id=f_id,
            objet=objet,
            fichier_joint=fichier,
            statut='ACTIF',
            cree_par=request.user,
            modifie_par=request.user,
        )
        
        article_ids = request.POST.getlist('articles[]')
        quantites = request.POST.getlist('quantites[]')
        prix_unitaires = request.POST.getlist('prix_unitaires[]')
        
        for aid, qte, pu in zip(article_ids, quantites, prix_unitaires):
            if aid and qte:
                try:
                    q = int(qte)
                    pu_val = Decimal(str(pu).strip()) if pu and str(pu).strip() else Decimal('0')
                    if q > 0:
                        ProjetProformaLigne.objects.create(
                            proforma=proforma,
                            article_id=int(aid),
                            quantite_prevue=q,
                            prix_unitaire_estime=pu_val,
                        )
                except (ValueError, TypeError):
                    pass
                    
        _synchroniser_besoins_projet(projet)
        messages.success(request, f"Proforma « {proforma.numero_proforma} » enregistrée avec succès ({proforma.lignes.count()} articles).")
    
    return redirect('projets:detail', projet_id=projet.id)


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_projets')
def api_detail_proforma(request, proforma_id):
    """Retourne les détails d'une proforma pour affichage AJAX ou édition dans la modale."""
    proforma = get_object_or_404(
        ProjetProforma.objects.select_related('fournisseur', 'projet').prefetch_related('lignes__article'),
        id=proforma_id
    )
    lignes = []
    for l in proforma.lignes.all():
        lignes.append({
            'article_id': l.article.id,
            'designation': l.article.designation,
            'reference': l.article.reference or '',
            'quantite_prevue': l.quantite_prevue,
            'prix_unitaire_estime': float(l.prix_unitaire_estime or 0),
            'total_ligne': float((l.prix_unitaire_estime or 0) * l.quantite_prevue),
        })
    return JsonResponse({
        'id': proforma.id,
        'numero_proforma': proforma.numero_proforma,
        'date_proforma': str(proforma.date_proforma),
        'fournisseur_id': proforma.fournisseur_id,
        'fournisseur_nom': proforma.fournisseur.raison_sociale if proforma.fournisseur else '',
        'objet': proforma.objet or '',
        'statut': proforma.statut,
        'fichier_url': proforma.fichier_joint.url if proforma.fichier_joint else '',
        'total_articles': proforma.total_articles,
        'total_montant': float(proforma.total_montant_estime),
        'lignes': lignes,
    })


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_projets')
def modifier_proforma(request, projet_id, proforma_id):
    """Met à jour une proforma existante et ses lignes."""
    projet = get_object_or_404(Projet, id=projet_id, is_deleted=False)
    proforma = get_object_or_404(ProjetProforma, id=proforma_id, projet=projet)
    
    if projet.statut in ['TERMINE', 'ANNULE']:
        messages.error(request, f"Impossible de modifier une proforma : le projet est {projet.get_statut_display().lower()}.")
        return redirect('projets:detail', projet_id=projet.id)

    if request.method == 'POST':
        numero = (request.POST.get('numero_proforma') or '').strip()
        if numero:
            proforma.numero_proforma = numero
        date_pf = request.POST.get('date_proforma')
        if date_pf:
            proforma.date_proforma = date_pf
        fournisseur_id = request.POST.get('fournisseur') or None
        proforma.fournisseur_id = int(fournisseur_id) if fournisseur_id and str(fournisseur_id).strip().isdigit() else None
        proforma.objet = request.POST.get('objet', '').strip()
        
        if request.FILES.get('fichier_joint'):
            proforma.fichier_joint = request.FILES.get('fichier_joint')
            
        proforma.modifie_par = request.user
        proforma.save()
        
        # Remplacement des lignes
        article_ids = request.POST.getlist('articles[]')
        quantites = request.POST.getlist('quantites[]')
        prix_unitaires = request.POST.getlist('prix_unitaires[]')
        
        if article_ids:
            proforma.lignes.all().delete()
            for aid, qte, pu in zip(article_ids, quantites, prix_unitaires):
                if aid and qte:
                    try:
                        q = int(qte)
                        pu_val = Decimal(str(pu).strip()) if pu and str(pu).strip() else Decimal('0')
                        if q > 0:
                            ProjetProformaLigne.objects.create(
                                proforma=proforma,
                                article_id=int(aid),
                                quantite_prevue=q,
                                prix_unitaire_estime=pu_val,
                            )
                    except (ValueError, TypeError):
                        pass
                        
        _synchroniser_besoins_projet(projet)
        messages.success(request, f"Proforma « {proforma.numero_proforma} » mise à jour avec succès.")
        
    return redirect('projets:detail', projet_id=projet.id)


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_projets')
def annuler_proforma(request, projet_id, proforma_id):
    """Bascule le statut d'une proforma (Annulé / Actif) ou la supprime."""
    projet = get_object_or_404(Projet, id=projet_id, is_deleted=False)
    proforma = get_object_or_404(ProjetProforma, id=proforma_id, projet=projet)
    
    if projet.statut in ['TERMINE', 'ANNULE']:
        messages.error(request, f"Impossible de modifier les proformas : le projet est {projet.get_statut_display().lower()}.")
        return redirect('projets:detail', projet_id=projet.id)

    if request.method == 'POST':
        action = request.POST.get('action', 'annuler')
        if action == 'supprimer':
            num = proforma.numero_proforma
            proforma.delete()
            _synchroniser_besoins_projet(projet)
            messages.success(request, f"Proforma « {num} » définitivement supprimée.")
        elif proforma.statut == 'ACTIF':
            proforma.statut = 'ANNULE'
            proforma.modifie_par = request.user
            proforma.save()
            _synchroniser_besoins_projet(projet)
            messages.warning(request, f"Proforma « {proforma.numero_proforma} » annulée (les besoins ont été déduits du prévisionnel).")
        else:
            proforma.statut = 'ACTIF'
            proforma.modifie_par = request.user
            proforma.save()
            _synchroniser_besoins_projet(projet)
            messages.success(request, f"Proforma « {proforma.numero_proforma} » réactivée.")
            
    return redirect('projets:detail', projet_id=projet.id)


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_projets')
def imprimer_proforma(request, projet_id, proforma_id):
    """Génère le bordereau PDF officiel d'une proforma prévisionnelle de chantier."""
    from stock.pdf_utils import get_pdf_config, render_pdf_response, _get_signature_url
    
    projet = get_object_or_404(
        Projet.objects.select_related(
            'chef_de_projet', 'chef_de_projet__profil', 'chef_de_projet__profil__fonction',
            'responsable_direction', 'responsable_direction__profil', 'responsable_direction__profil__fonction',
            'direction_responsable', 'fournisseur'
        ),
        id=projet_id, is_deleted=False
    )
    proforma = get_object_or_404(
        ProjetProforma.objects.select_related('fournisseur', 'projet__chef_de_projet', 'cree_par').prefetch_related('lignes__article'),
        id=proforma_id, projet=projet
    )
    
    pdf_config, logo_url = get_pdf_config(None, 'PROFORMA', request)
    lignes = list(proforma.lignes.select_related('article').all())
    
    # Résolution des signatures pour la formule standard à 2 signatures
    chef = projet.chef_de_projet
    chef_signature_url = _get_signature_url(request, chef)
    chef_fonction = ''
    if chef and hasattr(chef, 'profil') and chef.profil.fonction:
        chef_fonction = chef.profil.fonction.nom or str(chef.profil.fonction)

    dir_resp = projet.responsable_direction
    dir_signature_url = _get_signature_url(request, dir_resp)
    dir_fonction = ''
    if dir_resp and hasattr(dir_resp, 'profil') and dir_resp.profil.fonction:
        dir_fonction = dir_resp.profil.fonction.nom or str(dir_resp.profil.fonction)

    context = {
        'proforma': proforma,
        'projet': projet,
        'lignes': lignes,
        'pdf_config': pdf_config,
        'logo_url': logo_url,
        'chef_signature_url': chef_signature_url,
        'chef_fonction': chef_fonction,
        'dir_signature_url': dir_signature_url,
        'dir_fonction': dir_fonction,
        'date_impression': timezone.now(),
        'edite_par': request.user,
    }
    return render_pdf_response(request, 'projets/pdf/proforma.html', context, f"PROFORMA_{proforma.numero_proforma}.pdf")

