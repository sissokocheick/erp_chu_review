import logging
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q, Sum, Prefetch, Exists, OuterRef, Count
from django.utils import timezone
from django.http import JsonResponse
from django.urls import reverse
from datetime import datetime

from accounts.permissions import verifier_permission
from ..models import (
    DemandeMateriel, LigneDemande, LivraisonPartielle, LivraisonLigne,
    AccuseReception, BonMouvement, LigneBon, Mouvement,
    Magasin, Article, Service, CircuitValidation, MotifAnnulation, StockItem,
)
from ..decorators import magasin_requis, catch_errors
from ..services import (
    NumeroGenerator, PDFService, NotificationService, DemandeService
)
from ..services.livraison_service import LivraisonService
from ..services.parametre_service import get_or_create_logistique_config
# ── Fallback magasin_service (créé si module inexistant) ──
try:
    from ..services.magasin_service import get_magasins_autorises
except (ModuleNotFoundError, ImportError):
    def get_magasins_autorises(request):
        from ..models import Magasin
        return Magasin.objects.filter(entreprise=request.entreprise)

from .catalogue import paginer
from django.core.exceptions import ObjectDoesNotExist
from core.pdf_service import DocumentGenerator
from django.core.files.base import ContentFile
from django.template.loader import render_to_string
from django.http import HttpResponse


def _get_service_user(request):
    profil = None
    service_user = None
    try:
        profil = request.user.profil
    except (ObjectDoesNotExist, AttributeError):
        pass
    if profil:
        service_user = getattr(profil, 'service', None) or getattr(
            profil, 'service_demandeur', None
        )
        if not service_user and hasattr(profil, 'services'):
            service_user = profil.services.first()
    return service_user


def _is_ajax(request):
    """Détection robuste requête AJAX (fetch / XMLHttpRequest / HTMX)."""
    return (
        request.headers.get('x-requested-with') == 'XMLHttpRequest'
        or request.headers.get('HX-Request') == 'true'
    )


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_demandes')
@magasin_requis
@catch_errors(redirect_url='mes_demandes')
def mes_demandes(request):
    """Dispatcher : GET affiche, POST traite (création ou clôture)."""
    if request.method == 'POST':
        return _traiter_mes_demandes_post(request)
    return _afficher_mes_demandes(request)


def _afficher_mes_demandes(request):
    """Branche GET : liste des demandes de l'utilisateur."""
    entreprise = request.entreprise
    service_user = _get_service_user(request)

    # ═══════════════════════════════════════════════════════════════════════
    # RÉCUPÉRATION DU PARAMÈTRE DE CONFIDENTIALITÉ
    # ═══════════════════════════════════════════════════════════════════════
    config = get_or_create_logistique_config(entreprise)
    confidentialite = getattr(config, 'confidentialite_demandes', 'PERSONNELLE')

    # ── Filtre de base selon la confidentialité ──
    if confidentialite == 'SERVICE' and service_user:
        # Mode SERVICE : tous les agents du même service voient les demandes
        qs = DemandeMateriel.objects.filter(
            service_demandeur=service_user,
            magasin_cible__entreprise=entreprise
        )
    else:
        # Mode PERSONNELLE (défaut) : chaque agent ne voit que SES demandes
        qs = DemandeMateriel.objects.filter(
            demandeur=request.user,
            magasin_cible__entreprise=entreprise
        )

    qs = qs.select_related(
        'service_demandeur', 'magasin_cible', 'valide_par',
        'valide_par_chef', 'cloture_par', 'bon_sortie_lie'
    ).annotate(
        nb_lignes=Count('lignes_demande', distinct=True),
        nb_livraisons=Count('livraisons', distinct=True)
    ).order_by('-date_demande')

    statut_filtre = request.GET.get('statut_filtre', 'actives')
    # ── Détection livraisons non signées (reste active tant que pas signé) ──
    livraison_non_signee_subquery = LivraisonPartielle.objects.filter(
        demande=OuterRef('pk'),
        accuse__est_signe=False
    )
    qs = qs.annotate(a_livraison_non_signee=Exists(livraison_non_signee_subquery))

    # ── Filtre date ──
    date_range = request.GET.get('date_range', '').strip()
    if date_range:
        try:
            dates = date_range.split(' - ')
            if len(dates) == 2:
                d1 = datetime.strptime(dates[0].strip(), '%d/%m/%Y').date()
                d2 = datetime.strptime(dates[1].strip(), '%d/%m/%Y').date()
                qs = qs.filter(date_demande__date__gte=d1, date_demande__date__lte=d2)
        except ValueError:
            pass

    # ── Filtre recherche texte ──
    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(numero_demande__icontains=q) |
            Q(lignes_demande__article__designation__icontains=q) |
            Q(magasin_cible__nom__icontains=q)
        ).distinct()

    # ── Split actives / historique ──
    STATUTS_HISTORIQUE = ['RECEPTIONNE', 'CLOTUREE', 'REFUSEE', 'ANNULEE']
    if statut_filtre == 'historique':
        qs = qs.filter(statut__in=STATUTS_HISTORIQUE).exclude(a_livraison_non_signee=True)
    else:
        qs = qs.filter(~Q(statut__in=STATUTS_HISTORIQUE) | Q(a_livraison_non_signee=True))

    demandes_pagines, per_page = paginer(qs, request, per_page_key='per_page', default=10)

    magasins = Magasin.objects.filter(entreprise=entreprise).order_by('nom')
    magasin_id = request.session.get('magasin_actif_id')
    magasin_actif = Magasin.objects.filter(
        id=magasin_id, entreprise=entreprise
    ).first() if magasin_id else magasins.first()

    circuit = CircuitValidation.objects.filter(
        type_document='DEMANDE', est_actif=True, entreprise=entreprise
    ).first()

    context = {
        'demandes': demandes_pagines,
        'statut_filtre': statut_filtre,
        'q': q,
        'per_page': per_page,
        'a_un_service': service_user is not None,
        'magasins': magasins,
        'magasin_actif': magasin_actif,
        'articles': Article.objects.filter(entreprise=entreprise).order_by('designation'),
        'date_range': date_range,
        'circuit_actif': bool(circuit),
        # Passer l'info de confidentialité au template pour affichage éventuel
        'confidentialite_demandes': confidentialite,
    }

    # ── AJAX : retourne seulement le partial si requête XHR ──
    if _is_ajax(request):
        return render(request, 'stock/mes_demandes_lignes.html', context)

    return render(request, 'stock/mes_demandes.html', context)


def _traiter_mes_demandes_post(request):
    """Branche POST : clôture ou création d'une demande."""
    entreprise = request.entreprise
    action = request.POST.get('action')

    if action == 'cloturer_demande':
        return _cloturer_ma_demande(request)
    return _creer_ma_demande(request)


def _cloturer_ma_demande(request):
    """POST : clôture d'une demande par son demandeur."""
    demande = get_object_or_404(
        DemandeMateriel, id=request.POST.get('demande_id'),
        demandeur=request.user, magasin_cible__entreprise=request.entreprise
    )
    demande.statut = 'CLOTUREE'
    demande.cloture_par = request.user
    demande.date_cloture = timezone.now()
    demande.motif_cloture = request.POST.get('motif_cloture', "Plus besoin du reste")
    demande.save()
    messages.success(request, f"✅ La demande {demande.numero_demande} a été clôturée.")
    return redirect('mes_demandes')


def _creer_ma_demande(request):
    """POST : creation d une nouvelle demande."""
    entreprise = request.entreprise
    service_user = _get_service_user(request)

    if not service_user:
        messages.error(request, "Impossible : Vous n avez pas de service rattache.")
        return redirect('mes_demandes')

    # ── Verification : reception obligatoire de la livraison precedente ──
    config = get_or_create_logistique_config(entreprise)
    if getattr(config, 'obliger_reception_precedente', False):
        a_livraison_non_signee = LivraisonPartielle.objects.filter(
            demande__demandeur=request.user,
            demande__magasin_cible__entreprise=entreprise,
            accuse__est_signe=False
        ).exists()
        if a_livraison_non_signee:
            messages.error(
                request,
                "Vous devez receptionner votre livraison precedente (signer l accuse de reception) avant de faire une nouvelle demande."
            )
            return redirect('mes_demandes')

    magasin_cible_id = request.POST.get('magasin_cible')
    commentaire = request.POST.get('commentaire', '').strip()
    article_ids = request.POST.getlist('articles[]')
    quantites = request.POST.getlist('quantites[]')

    # ── Vérification autorisation magasin ──
    magasins_autorises = get_magasins_autorises(request)
    if magasin_cible_id and not magasins_autorises.filter(id=magasin_cible_id).exists():
        messages.error(request, "⛔ Vous n'avez pas accès à ce magasin cible.")
        return redirect('mes_demandes')

    if not article_ids:
        messages.error(request, "Votre demande est vide. Veuillez ajouter des articles.")
        return redirect('mes_demandes')

    with transaction.atomic():
        numero_demande = NumeroGenerator.generer_numero_demande(service_user, entreprise)
        circuit = CircuitValidation.objects.filter(
            type_document='DEMANDE', est_actif=True, entreprise=entreprise
        ).first()

        if circuit and circuit.est_actif:
            statut_initial = 'EN_ATTENTE_VALIDATION'
            msg_succes = f"✅ Demande {numero_demande} envoyée ! En attente de validation par votre hiérarchie."
        else:
            statut_initial = 'EN_ATTENTE'
            msg_succes = f"✅ Demande {numero_demande} transmise directement au magasin avec succès !"

        demande = DemandeMateriel.objects.create(
            numero_demande=numero_demande,
            demandeur=request.user,
            service_demandeur=service_user,
            magasin_cible_id=magasin_cible_id,
            statut=statut_initial,
            commentaire=commentaire
        )
        for aid, qte in zip(article_ids, quantites):
            if aid and qte and int(qte) > 0:
                LigneDemande.objects.create(
                    demande=demande, article_id=aid, quantite_demandee=int(qte)
                )

    # ── Génération du Bon de Demande PDF ──
    try:
        gen = DocumentGenerator(request=request)
        pdf_bytes = gen.bon_demande(demande)
        # Optionnel : sauvegarder le PDF sur la demande si champ fichier_pdf existe
        if hasattr(demande, 'fichier_pdf') and hasattr(demande.fichier_pdf, 'save'):
            demande.fichier_pdf.save(
                f"BD_{demande.numero_demande}.pdf",
                ContentFile(pdf_bytes),
                save=True
            )
    except Exception as e:
        logging.getLogger(__name__).warning(
            f"[PDF Demande] Génération échouée pour {demande.numero_demande} : {e}"
        )

    messages.success(request, msg_succes)
    return redirect('mes_demandes')


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_guichet')
@magasin_requis
@catch_errors(redirect_url='gestion_demandes')
def gestion_demandes(request):
    """Dispatcher : GET affiche, POST traite (livraison)."""
    if request.method == 'POST':
        return redirect('gestion_demandes')  # POST géré par valider_traitement_demande
    return _afficher_gestion_demandes(request)


def _afficher_gestion_demandes(request):
    """Branche GET : liste des demandes à traiter pour le magasin actif."""
    entreprise = request.entreprise
    magasin_id = request.session.get('magasin_actif_id')

    if not magasin_id:
        messages.error(request, "⚠️ Veuillez sélectionner un magasin.")
        return redirect('/')

    magasin_actif = Magasin.objects.filter(id=magasin_id, entreprise=entreprise).first()
    if not magasin_actif:
        request.session.pop('magasin_actif_id', None)
        messages.error(request, "⛔ Magasin inaccessible. Veuillez en choisir un autre.")
        return redirect('/')

    onglet = request.GET.get('onglet', 'en_attente')
    STATUTS_HISTORIQUE = ['RECEPTIONNE', 'CLOTUREE', 'REFUSEE', 'ANNULEE']
    STATUTS_A_TRAITER = ['EN_ATTENTE', 'EN_COURS', 'LIVRAISON_PARTIELLE']
    STATUTS_ATTENTE_SIGNATURE = ['LIVREE']

    bon_attente_subquery = LivraisonPartielle.objects.filter(
        demande=OuterRef('pk'), bon_sortie__statut_validation='ATTENTE'
    )
    livraison_non_signee_subquery = LivraisonPartielle.objects.filter(
        demande=OuterRef('pk'), accuse__est_signe=False
    )

    qs = DemandeMateriel.objects.filter(
        magasin_cible_id=magasin_id, magasin_cible__entreprise=entreprise
    ).select_related('demandeur', 'service_demandeur').prefetch_related(
        'lignes_demande__article',
        Prefetch('livraisons', queryset=LivraisonPartielle.objects.prefetch_related('accuse'))
    ).annotate(
        a_bon_en_attente=Exists(bon_attente_subquery),
        a_livraison_non_signee=Exists(livraison_non_signee_subquery)
    ).order_by('-date_demande')

    if onglet == 'historique':
        qs = qs.filter(statut__in=STATUTS_HISTORIQUE)
    elif onglet == 'attente_signature':
        qs = qs.filter(statut__in=STATUTS_ATTENTE_SIGNATURE, a_livraison_non_signee=True)
    else:
        qs = qs.filter(
            Q(statut__in=STATUTS_A_TRAITER) |
            Q(a_bon_en_attente=True)
        ).exclude(
            Q(statut__in=STATUTS_ATTENTE_SIGNATURE) & Q(a_livraison_non_signee=True)
        )

    q = request.GET.get('q', '').strip()
    if q:
        qs = qs.filter(
            Q(numero_demande__icontains=q) |
            Q(service_demandeur__nom__icontains=q) |
            Q(demandeur__username__icontains=q) |
            Q(lignes_demande__article__designation__icontains=q)
        ).distinct()
    if request.GET.get('statut'):
        qs = qs.filter(statut=request.GET.get('statut'))
    if request.GET.get('service'):
        qs = qs.filter(service_demandeur_id=request.GET.get('service'))

    demandes_pagines, per_page = paginer(qs, request, per_page_key='per_page', default=10)

    # Enrichissement des lignes avec stock disponible
    article_ids = {ligne.article_id for d in demandes_pagines for ligne in d.lignes_demande.all()}
    stocks_map = {}
    if article_ids:
        stocks_map = {
            s.article_id: s.quantite_physique
            for s in StockItem.objects.filter(article_id__in=article_ids, magasin_id=magasin_id)
            .only('article_id', 'quantite_physique')
        }
    for demande in demandes_pagines:
        for ligne in demande.lignes_demande.all():
            ligne.quantite_en_stock = stocks_map.get(ligne.article_id, 0)
        # Calcul du reste total (property read-only -> attribut dynamique)
        reste_total = sum(ligne.reste for ligne in demande.lignes_demande.all())
        setattr(demande, 'reste_calcule', reste_total)

    counts = {
        'en_attente': DemandeMateriel.objects.filter(
            magasin_cible_id=magasin_id
        ).filter(
            Q(statut__in=STATUTS_A_TRAITER) |
            Q(livraisons__bon_sortie__statut_validation='ATTENTE')
        ).exclude(
            Q(statut__in=STATUTS_ATTENTE_SIGNATURE) & Q(livraisons__accuse__est_signe=False)
        ).distinct().count(),
        'attente_signature': DemandeMateriel.objects.filter(
            magasin_cible_id=magasin_id, statut__in=STATUTS_ATTENTE_SIGNATURE,
            livraisons__accuse__est_signe=False
        ).distinct().count(),
        'historique': DemandeMateriel.objects.filter(
            magasin_cible_id=magasin_id, statut__in=STATUTS_HISTORIQUE
        ).distinct().count(),
    }

    context = {
        'demandes': demandes_pagines,
        'q': request.GET.get('q', ''),
        'per_page': per_page,
        'onglet': onglet,
        'counts': counts,
        'magasin_actif': magasin_actif,
        'motifs_annulation': MotifAnnulation.objects.filter(entreprise=entreprise, actif=True).order_by('libelle'),
        'services': Service.objects.filter(entreprise=entreprise).order_by('nom'),
        'a_un_service': _get_service_user(request) is not None or request.user.has_perm('accounts.menu_guichet'),
        'articles': Article.objects.filter(entreprise=entreprise).order_by('designation'),
        'date_range': request.GET.get('date_range', ''),
    }
    return render(request, 'stock/gestion_demandes.html', context)


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_guichet')
@magasin_requis
@catch_errors(redirect_url='gestion_demandes')
def valider_traitement_demande(request, demande_id):
    entreprise = request.entreprise

    if request.method != 'POST':
        return redirect('gestion_demandes')

    demande = get_object_or_404(
        DemandeMateriel, id=demande_id,
        magasin_cible__entreprise=entreprise
    )
    magasin_id = request.session.get('magasin_actif_id')

    if str(demande.magasin_cible_id) != str(magasin_id):
        messages.error(request, "⛔ Accès refusé.")
        return redirect('gestion_demandes')

    if demande.statut in ('RECEPTIONNE', 'CLOTUREE', 'REFUSEE'):
        messages.error(request, "⛔ Cette demande est déjà terminée.")
        return redirect('gestion_demandes')

    circuit_sortie = CircuitValidation.objects.filter(
        type_document='SORTIE', entreprise=entreprise, est_actif=True
    ).first()

    lignes = demande.lignes_demande.select_related('article').all()

    # Construction du mapping des quantités saisies + VALIDATION
    lignes_qte_map = {}
    for ligne in lignes:
        qte_str = request.POST.get(f'qte_accordee_{ligne.id}', '0').strip()
        qte = int(qte_str) if qte_str.isdigit() else 0

        # ═══════════════════════════════════════════════════════
        # VALIDATION : quantité livrée <= quantité demandée (reste)
        # ═══════════════════════════════════════════════════════
        if qte > ligne.reste:
            messages.error(
                request,
                f"⛔ Erreur : pour '{ligne.article.designation}', vous avez saisi {qte} "
                f"mais le reste à livrer est de {ligne.reste}. "
                f"La quantité livrée ne peut pas dépasser la quantité demandée."
            )
            return redirect('gestion_demandes')

        if qte > 0:
            lignes_qte_map[ligne.id] = qte

    try:
        livraison, bon, total_livre = LivraisonService.traiter_demande(
            demande=demande,
            magasin_id=magasin_id,
            lignes_qte_map=lignes_qte_map,
            user=request.user,
            cloturer=request.POST.get('cloturer_demande') == '1',
            motif_cloture=request.POST.get('motif_cloture', '').strip(),
        )
    except ValidationError as e:
        logger.exception("[Demandes] %s", e)
        messages.error(request, "❌ Une erreur est survenue. Veuillez réessayer.")
        return redirect('gestion_demandes')

    # Notification au demandeur
    NotificationService.creer(
        utilisateur=demande.demandeur,
        titre=f"Livraison #{livraison.numero_livraison}",
        message=f"Bon {bon.numero_bon} créé. {total_livre} unité(s) livrée(s).",
        url=reverse(
            'detail_livraisons_demande',
            kwargs={'demande_id': demande.id}
        ),
        type_notif='INFO'
    )

    demande.refresh_from_db()
    if demande.reste == 0:
        msg_etat = "✓ Tout livré !"
    elif request.POST.get('cloturer_demande') == '1':
        msg_etat = "✓ Livré et reliquat clôturé !"
    else:
        msg_etat = f"Reste : {demande.reste} unité(s)."

    messages.success(
        request,
        f"✅ Livraison #{livraison.numero_livraison} créée — {total_livre} unité(s). "
        f"Bon : {bon.numero_bon}. {msg_etat}"
        + (" En attente de validation hiérarchique." if circuit_sortie else "")
    )

    # ── Génération du PDF du Bon de Sortie ──
    try:
        gen = DocumentGenerator(request=request)

        # Déterminer si c'est une livraison partielle (recalculer après la livraison)
        demande.refresh_from_db()
        est_livraison_partielle = demande.reste > 0
        est_cloture = request.POST.get('cloturer_demande') == '1'  # ← NOUVEAU

        # Mettre à jour la livraison si nécessaire
        if livraison and livraison.est_partielle != est_livraison_partielle:
            livraison.est_partielle = est_livraison_partielle
            livraison.save(update_fields=['est_partielle'])

        pdf_bytes = gen.bon_sortie(
            bon,
            extra_context={
                'est_livraison_partielle': est_livraison_partielle,
                'est_cloture': est_cloture,  # ← NOUVEAU
            }
        )

        # Sauvegarder le PDF sur le bon si champ fichier_pdf existe
        if hasattr(bon, 'fichier_pdf') and hasattr(bon.fichier_pdf, 'save'):
            bon.fichier_pdf.save(
                f"BS_{bon.numero_bon}.pdf",
                ContentFile(pdf_bytes),
                save=True
            )
    except Exception as e:
        logging.getLogger(__name__).warning(
            f"[PDF] Pré-génération échouée pour {bon.numero_bon} : {e}"
        )

    url = reverse('gestion_demandes')
    demande.refresh_from_db()

    # Déterminer dynamiquement l'onglet cible selon l'état de la demande
    if request.POST.get('cloturer_demande') == '1' or demande.statut in ('CLOTUREE', 'RECEPTIONNE', 'REFUSEE', 'ANNULEE'):
        onglet_cible = 'historique'
    elif demande.statut == 'LIVREE' and demande.reste == 0:
        # Tout livré mais pas encore signé -> onglet "En attente signature"
        onglet_cible = 'attente_signature'
    else:
        # Reste à livrer ou partiel -> onglet "À Traiter"
        onglet_cible = 'en_attente'

    if circuit_sortie:
        return redirect(f"{url}?onglet={onglet_cible}")
    else:
        return redirect(f"{url}?onglet={onglet_cible}&print_bon={bon.id}")

@login_required(login_url='/auth/login/')
@magasin_requis
def api_statut_demande(request, demande_id):
    entreprise = request.entreprise
    demande = get_object_or_404(
        DemandeMateriel, id=demande_id,
        magasin_cible__entreprise=entreprise
    )

    profil = getattr(request.user, 'profil', None)
    est_magasinier = request.user.has_perm('accounts.menu_guichet')
    est_demandeur = (demande.demandeur == request.user)
    est_du_service = (profil and profil.service == demande.service_demandeur)

    if not (est_magasinier or est_demandeur or est_du_service or request.user.is_staff):
        return JsonResponse({'error': 'Accès refusé'}, status=403)

    livraisons_data = []
    for liv in demande.livraisons.select_related('livre_par').prefetch_related('accuse'):
        accuse = getattr(liv, 'accuse', None)
        livraisons_data.append({
            'numero': liv.numero_livraison,
            'quantite': liv.quantite_livree,
            'date': liv.date_livraison.strftime('%d/%m/%Y %H:%M'),
            'livre_par': liv.livre_par.get_full_name() if liv.livre_par else '—',
            'est_signe': accuse.est_signe if accuse else False,
            'signe_par': accuse.receptionne_par.get_full_name() if accuse and accuse.receptionne_par else '—',
            'date_signature': accuse.date_reception.strftime('%d/%m/%Y %H:%M') if accuse and accuse.date_reception else '—',
        })

    return JsonResponse({
        'statut': demande.statut,
        'statut_display': demande.get_statut_display(),
        'taux_service': demande.taux_service,
        'quantite_demandee': demande.quantite_demandee_totale,
        'quantite_servie': demande.quantite_servie_totale,
        'reste': demande.reste,
        'nb_livraisons': demande.livraisons.count(),
        'livraisons': livraisons_data,
    })


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_guichet')
@magasin_requis
@catch_errors(redirect_url='gestion_demandes')
def cloturer_demande(request, demande_id):
    entreprise = request.entreprise
    demande = get_object_or_404(
        DemandeMateriel, id=demande_id,
        magasin_cible__entreprise=entreprise
    )
    magasin_id = request.session.get('magasin_actif_id')

    if str(demande.magasin_cible_id) != str(magasin_id):
        messages.error(request, "⛔ Accès refusé.")
        return redirect('gestion_demandes')

    if demande.statut in ('RECEPTIONNE', 'CLOTUREE', 'REFUSEE'):
        messages.error(request, "Cette demande est déjà terminée.")
        return redirect('gestion_demandes')

    if request.method == 'POST':
        motif = request.POST.get('motif_cloture', '').strip()
        if not motif:
            messages.error(request, "⛔ Le motif de clôture est obligatoire.")
            return redirect('detail_livraisons_demande', demande_id=demande.id)

        demande.statut = 'CLOTUREE'
        demande.motif_cloture = motif
        demande.date_cloture = timezone.now()
        demande.cloture_par = request.user
        demande.save(
            update_fields=['statut', 'motif_cloture', 'date_cloture', 'cloture_par']
        )
        messages.success(
            request,
            f"✅ Demande {demande.numero_demande} clôturée. "
            f"Reliquat de {demande.reste} unité(s) abandonné."
        )
        return redirect('gestion_demandes')
    return redirect('detail_livraisons_demande', demande_id=demande.id)


@login_required(login_url='/auth/login/')
def signer_accuse_reception(request, accuse_id):
    entreprise = request.entreprise
    accuse = get_object_or_404(
        AccuseReception.objects.select_related(
            'livraison__demande__service_demandeur',
            'livraison__demande__demandeur',
            'livraison__livre_par',
        ).prefetch_related('livraison__lignes_livraison__article'),
        id=accuse_id
    )
    demande = accuse.livraison.demande
    livraison = accuse.livraison

    if demande.magasin_cible.entreprise != entreprise:
        messages.error(request, "⛔ Accès non autorisé.")
        return redirect('/')

    def get_bon_sortie_id():
        if hasattr(livraison, 'bon_sortie') and livraison.bon_sortie:
            return livraison.bon_sortie.id
        if getattr(demande, 'bon_sortie_lie', None):
            return demande.bon_sortie_lie.id
        return None

    bon = None
    if hasattr(livraison, 'bon_sortie') and livraison.bon_sortie:
        bon = livraison.bon_sortie
    elif getattr(demande, 'bon_sortie_lie', None):
        bon = demande.bon_sortie_lie

    if bon and bon.statut_validation == 'ATTENTE':
        circuit = CircuitValidation.objects.filter(
            type_document='SORTIE', entreprise=entreprise, est_actif=True
        ).prefetch_related('valideurs').first()
        est_valideur = (
            circuit and (
                circuit.valideurs.filter(id=request.user.id).exists()
                or request.user.is_superuser
            )
        )
        if not est_valideur:
            msg = "⛔ Signature bloquée. Ce bon est en attente de validation hiérarchique."
            if _is_ajax(request):
                return JsonResponse({'success': False, 'error': msg}, status=403)
            messages.error(request, msg)
            return redirect('mes_demandes')

    if _is_ajax(request):
        if request.method == 'POST':
            if accuse.est_signe:
                return JsonResponse(
                    {'success': False, 'error': "Cet accusé a déjà été signé."},
                    status=400
                )
            try:
                # CORRECTION : harmonisation avec le flux POST
                # Par défaut, signature dashboard = satisfait (pas de choix possible)
                accuse.signer(
                    request.user, est_satisfait=True,
                    texte_observations="Signé via le tableau de bord."
                )
                DemandeService.recalculer_statut_apres_signature(demande)
                if livraison.livre_par:
                    NotificationService.creer(
                        utilisateur=livraison.livre_par,
                        titre="Accusé signé",
                        message=f"Le service {demande.service_demandeur.nom} a confirmé la réception.",
                        url=reverse('gestion_demandes'),
                        type_notif='SUCCESS'
                    )

                bon_id = get_bon_sortie_id()
                return JsonResponse({
                    'success': True,
                    'message': f"Accusé de la livraison #{livraison.numero_livraison} signé avec succès.",
                    'bon_sortie_id': bon_id,
                    'redirect_url': (
                        f"{reverse('mes_demandes')}?print_bon={bon_id}&statut_filtre=historique"
                        if bon_id else None
                    )
                })
            except Exception as e:
                logger.exception("[SIGNATURE] Erreur signature accusé #%s : %s", accuse_id, e)
                return JsonResponse(
                    {'success': False, 'error': "Une erreur technique est survenue lors de la signature."},
                    status=500
                )
            return JsonResponse(
                {'success': False, 'error': 'Méthode non autorisée.'},
                status=405
            )
    profil = getattr(request.user, 'profil', None)
    est_magasinier = request.user.has_perm('accounts.menu_guichet')
    url_retour = 'gestion_demandes' if est_magasinier else 'mes_demandes'

    if accuse.est_signe:
        messages.info(request, "Cet accusé a déjà été signé.")
        return redirect(url_retour)

    service_user = profil.service if profil else None
    if not est_magasinier and service_user and service_user != demande.service_demandeur:
        messages.error(
            request,
            "⛔ Vous n'appartenez pas au service destinataire."
        )
        return redirect('mes_demandes')

    if request.method == 'POST':
        choix_satisfaction = request.POST.get('satisfaction')
        observations = request.POST.get('observations', '').strip()
        est_satisfait = True if choix_satisfaction == 'oui' else (
            False if choix_satisfaction == 'non' else None
        )

        if not getattr(profil, 'a_signature', False):
            messages.error(
                request,
                "⛔ Vous n'avez pas de signature enregistrée dans votre profil."
            )
            return redirect('signer_accuse_reception', accuse_id=accuse.id)

        accuse.signer(
            request.user, est_satisfait=est_satisfait,
            texte_observations=observations
        )
        DemandeService.recalculer_statut_apres_signature(demande)

        if livraison.livre_par:
            NotificationService.creer(
                utilisateur=livraison.livre_par,
                titre="Accusé signé",
                message=f"Le service {demande.service_demandeur.nom} a confirmé la réception.",
                url=reverse('gestion_demandes'),
                type_notif='SUCCESS'
            )
        messages.success(
            request,
            f"✅ Accusé #{livraison.numero_livraison} signé avec succès."
        )
        if demande.statut == 'RECEPTIONNE':
            messages.info(
                request,
                f"🎉 La demande {demande.numero_demande} est entièrement réceptionnée."
            )

        bon_sortie_id = get_bon_sortie_id()
        if bon_sortie_id:
            return redirect(
                f"{reverse('mes_demandes')}?print_bon={bon_sortie_id}&statut_filtre=historique"
            )
        return redirect('mes_demandes')

    context = {
        'accuse': accuse, 'livraison': livraison,
        'demande': demande, 'profil': profil,
        'a_signature': getattr(profil, 'a_signature', False),
        'signature_url': getattr(profil, 'signature_url', None),
        'url_retour': url_retour,
    }
    return render(request, 'stock/signer_accuse.html', context)


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_valider_demandes')
def demandes_a_valider(request):
    """
    Page de validation des demandes de matériel.
    Branchée sur CircuitValidation (type DEMANDE).
    Seuls les valideurs du circuit voient les demandes EN_ATTENTE_VALIDATION
    de leur propre service.
    """
    entreprise = request.entreprise

    # ── 1. Vérification du circuit DEMANDE ──
    circuit = CircuitValidation.objects.filter(
        type_document='DEMANDE', est_actif=True, entreprise=entreprise
    ).first()

    if not circuit:
        messages.error(request, "⛔ Le circuit de validation des demandes n'est pas activé.")
        return redirect('mes_demandes')

    # Vérification efficace : l'utilisateur est-il valideur ?
    if not circuit.valideurs.filter(id=request.user.id).exists():
        messages.error(request, "⛔ Vous n'êtes pas autorisé à valider les demandes.")
        return redirect('mes_demandes')

    # ── 2. Service de l'utilisateur (helper robuste) ──
    service_user = _get_service_user(request)
    if not service_user:
        messages.error(request, "Vous n'êtes rattaché à aucun service.")
        return redirect('mes_demandes')

    # ── 3. Traitement POST (validation / refus) ──
    if request.method == 'POST':
        action = request.POST.get('action')

        # --- Validation en lot ---
        if action == 'valider_lot':
            demande_ids = request.POST.getlist('demandes_cochees')
            if not demande_ids:
                messages.warning(request, "Aucune demande sélectionnée.")
                return redirect('demandes_a_valider')

            # ═══════════════════════════════════════════════════════════════════
            # ✅ CORRECTION : transaction.atomic + select_for_update()
            # Empêche les race conditions en cas de validation concurrente
            # ═══════════════════════════════════════════════════════════════════
            try:
                with transaction.atomic():
                    demandes_a_maj = DemandeMateriel.objects.select_for_update().filter(
                        id__in=demande_ids,
                        service_demandeur=service_user,
                        statut='EN_ATTENTE_VALIDATION',
                        service_demandeur__entreprise=entreprise
                    )
                    nb_maj = demandes_a_maj.count()
                    for d in demandes_a_maj:
                        d.statut = 'EN_ATTENTE'
                        d.valide_par_chef = request.user
                        d.date_validation_chef = timezone.now()
                        d.save()
            except Exception as e:
                logger.exception("[VALIDATION LOT] %s", e)
                messages.error(
                    request,
                    "❌ Une erreur est survenue lors de la validation en lot. "
                    "Veuillez réessayer."
                )
                return redirect('demandes_a_valider')

            # Notifications (hors transaction)
            for d in DemandeMateriel.objects.filter(id__in=demande_ids, statut='EN_ATTENTE'):
                NotificationService.creer(
                    utilisateur=d.demandeur,
                    titre="Demande approuvée",
                    message=f"Votre demande {d.numero_demande} est transmise au magasin.",
                    url=reverse('mes_demandes'),
                    type_notif='SUCCESS'
                )
            messages.success(request, f"✅ {nb_maj} demande(s) approuvée(s) en lot !")
            return redirect('demandes_a_valider')

        # --- Refus en lot ---
        elif action == 'refuser_lot':
            demande_ids = request.POST.getlist('demandes_cochees')
            motif = request.POST.get('motif_refus_lot', '').strip()
            if not demande_ids:
                messages.warning(request, "Aucune demande sélectionnée.")
                return redirect('demandes_a_valider')
            if not motif:
                messages.error(request, "Un motif de refus est obligatoire.")
                return redirect('demandes_a_valider')

            # ═══════════════════════════════════════════════════════════════════
            # ✅ CORRECTION : transaction.atomic + select_for_update()
            # Empêche les race conditions en cas de refus concurrent
            # ═══════════════════════════════════════════════════════════════════
            try:
                with transaction.atomic():
                    demandes_a_maj = DemandeMateriel.objects.select_for_update().filter(
                        id__in=demande_ids,
                        service_demandeur=service_user,
                        statut='EN_ATTENTE_VALIDATION',
                        service_demandeur__entreprise=entreprise
                    )
                    nb_maj = demandes_a_maj.count()
                    for d in demandes_a_maj:
                        d.statut = 'REFUSEE'
                        d.motif_cloture = motif
                        d.cloture_par = request.user
                        d.valide_par_chef = request.user
                        d.date_cloture = timezone.now()
                        d.date_validation_chef = timezone.now()
                        d.save()
            except Exception as e:
                logger.exception("[REFUS LOT] %s", e)
                messages.error(
                    request,
                    "❌ Une erreur est survenue lors du refus en lot. "
                    "Veuillez réessayer."
                )
                return redirect('demandes_a_valider')

            messages.success(request, f"❌ {nb_maj} demande(s) refusée(s) simultanément.")
            return redirect('demandes_a_valider')

        # --- Action unitaire ---
        demande_id = request.POST.get('demande_id')
        if demande_id:
            demande = get_object_or_404(
                DemandeMateriel,
                id=demande_id,
                service_demandeur=service_user,
                service_demandeur__entreprise=entreprise
            )
            if action == 'approuver':
                demande.statut = 'EN_ATTENTE'
                demande.valide_par_chef = request.user
                demande.date_validation_chef = timezone.now()
                demande.save()
                NotificationService.creer(
                    utilisateur=demande.demandeur,
                    titre="Demande approuvée",
                    message=f"Votre demande {demande.numero_demande} est transmise au magasin.",
                    url=reverse('mes_demandes'),
                    type_notif='SUCCESS'
                )
                messages.success(request, f"✅ Demande {demande.numero_demande} approuvée.")
            elif action == 'refuser':
                motif = request.POST.get('motif_refus', '').strip()
                if not motif:
                    messages.error(request, "❌ Motif de refus obligatoire.")
                else:
                    demande.statut = 'REFUSEE'
                    demande.motif_cloture = motif
                    demande.cloture_par = request.user
                    demande.valide_par_chef = request.user
                    demande.date_cloture = timezone.now()
                    demande.date_validation_chef = timezone.now()
                    demande.save()
                    messages.success(request, f"❌ Demande {demande.numero_demande} refusée.")
            return redirect('demandes_a_valider')

    # ── 4. Affichage GET ──
    onglet = request.GET.get('onglet', 'a_valider')
    q = request.GET.get('q', '')

    demandes_base = DemandeMateriel.objects.filter(
        service_demandeur=service_user,
        service_demandeur__entreprise=entreprise
    ).order_by('-date_demande')

    if onglet == 'historique':
        demandes = demandes_base.exclude(statut='EN_ATTENTE_VALIDATION')
    else:
        demandes = demandes_base.filter(statut='EN_ATTENTE_VALIDATION')

    if q:
        demandes = demandes.filter(
            Q(numero_demande__icontains=q) |
            Q(demandeur__username__icontains=q) |
            Q(demandeur__first_name__icontains=q) |
            Q(demandeur__last_name__icontains=q)
        ).distinct()

    demandes_pagines, per_page = paginer(demandes, request)

    counts = {
        'a_valider': demandes_base.filter(statut='EN_ATTENTE_VALIDATION').count(),
        'historique': demandes_base.exclude(statut='EN_ATTENTE_VALIDATION').count(),
    }

    context = {
        'demandes': demandes_pagines,
        'onglet': onglet,
        'q': q,
        'per_page': per_page,
        'counts': counts,
        'service_chef': service_user,
    }
    return render(request, 'stock/demandes_a_valider.html', context)

@login_required(login_url='/auth/login/')
@catch_errors(redirect_url='mes_demandes')
def annuler_demande(request, demande_id):
    entreprise = request.entreprise
    demande = get_object_or_404(
        DemandeMateriel, id=demande_id,
        magasin_cible__entreprise=entreprise
    )

    if demande.demandeur != request.user and not request.user.has_perm(
        'accounts.menu_guichet'
    ):
        messages.error(
            request,
            "⛔ Vous ne pouvez annuler que vos propres demandes."
        )
        return redirect('mes_demandes')

    # Cas spécial : bons en attente de validation
    livraisons_en_attente = demande.livraisons.filter(
        bon_sortie__statut_validation='ATTENTE'
    ).select_related('bon_sortie')

    if livraisons_en_attente.exists():
        try:
            statut, msg = LivraisonService.annuler_bons_en_attente(demande, request.user)
        except Exception as e:
            logger.exception("[Demandes] %s", e)
            messages.error(request, "❌ Une erreur est survenue lors de la validation.")
            return redirect('mes_demandes')
        messages.success(request, msg)
        return redirect('mes_demandes')

    # Cas normal
    try:
        statut, msg = DemandeService.annuler(demande, request.user)
        if statut == 'CLOTUREE':
            messages.warning(request, msg)
        else:
            messages.success(request, msg)
    except ValueError as e:
        logger.exception("[Demandes] %s", e)
        messages.error(request, "❌ Une erreur est survenue lors du refus.")

    return redirect('mes_demandes')


# ═══════════════════════════════════════════════════════════════════════════
# API : detail d une demande (pour accordéon lazy load)
# ═══════════════════════════════════════════════════════════════════════════

@login_required(login_url='/auth/login/')
def api_detail_demande(request, demande_id):
    """Renvoie le HTML du detail d une demande pour l accordéon."""
    entreprise = request.entreprise
    demande = get_object_or_404(
        DemandeMateriel.objects.select_related('service_demandeur').prefetch_related(
            'lignes_demande__article', 'livraisons__accuse', 'livraisons__bon_sortie'
        ),
        id=demande_id, demandeur=request.user, magasin_cible__entreprise=entreprise
    )
    html = render_to_string('stock/mes_demandes_detail.html', {'d': demande})
    return JsonResponse({'html': html})

# ═══════════════════════════════════════════════════════════════════════════
# BON DE DEMANDE PDF
# ═══════════════════════════════════════════════════════════════════════════

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_demandes')
def imprimer_bon_demande(request, demande_id):
    """Génère et retourne le PDF du Bon de Demande."""

    entreprise = request.entreprise
    demande = get_object_or_404(
        DemandeMateriel, id=demande_id,
        magasin_cible__entreprise=entreprise
    )

    # Vérification d'accès : demandeur, magasinier, ou staff
    profil = getattr(request.user, 'profil', None)
    est_magasinier = request.user.has_perm('accounts.menu_guichet')
    est_demandeur = (demande.demandeur == request.user)
    est_du_service = (profil and profil.service == demande.service_demandeur)

    if not (est_demandeur or est_magasinier or est_du_service or request.user.is_staff):
        messages.error(request, "⛔ Vous n'avez pas accès à ce document.")
        return redirect('mes_demandes')

    gen = DocumentGenerator(request=request)
    pdf_bytes = gen.bon_demande(demande)

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'inline; filename="BD_{demande.numero_demande}.pdf"'
    return response
