from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction, IntegrityError
from django.db.models import Q, F, Sum
from django.http import HttpResponse, FileResponse
from django.utils import timezone
from django.views.decorators.http import require_POST
from decimal import Decimal
from datetime import timedelta, datetime
import logging

from accounts.permissions import verifier_permission
from ..models import (
    Commande, LigneCommande, BonMouvement, LigneBon,
    Fournisseur, Article, Magasin, Mouvement, CircuitValidation,
    BonDeLivraison, FamilleArticle, StockItem)
from stock.services.isolation_service import get_magasins_autorises
from ..decorators import magasin_requis, catch_errors
from ..services import NumeroGenerator, NotificationService
from ..services.bon_service import BonService
from ..services.stock_transaction_service import StockTransactionService
from .catalogue import paginer
from .common_views import render_liste, get_magasin_actif, build_redirect_url, filtrer_texte
from django.urls import reverse
from core.models import ConfigurationHopital
from django.db.models import Sum, Count, Case, When, Value, IntegerField
from collections import defaultdict

# Constante : taille maximale de fichier upload (1 Mo)
MAX_FILE_SIZE = 1024 * 1024  # 1 Mo en octets

logger = logging.getLogger(__name__)

def _safe_delete(obj, user=None):
    """
    Supprime ou désactive un objet sans dépendance à une méthode soft_delete.
    Ordre : soft_delete() > is_deleted > est_actif/actif/is_active > hard delete.
    """
    if hasattr(obj, 'soft_delete') and callable(getattr(obj, 'soft_delete')):
        obj.soft_delete(user)
        return
    if hasattr(obj, 'is_deleted'):
        obj.is_deleted = True
        obj.save(update_fields=['is_deleted'])
        return
    for attr in ('est_actif', 'actif', 'is_active'):
        if hasattr(obj, attr):
            setattr(obj, attr, False)
            obj.save(update_fields=[attr])
            return
    obj.delete()

# ══════════════════════════════════════════════════════════════════════════════
# COMMANDES (ACHATS)
# ══════════════════════════════════════════════════════════════════════════════

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_commandes')
@magasin_requis
@catch_errors(redirect_url='liste_commandes')
def liste_commandes(request):
    magasin_actif_id = request.session.get('magasin_actif_id')

    commandes = Commande.objects.select_related(
        'fournisseur', 'cree_par', 'famille'
    ).prefetch_related('lignes_commande__article', 'bons_reception')

    if magasin_actif_id:
        commandes = commandes.filter(magasin_id=magasin_actif_id)

    onglet = request.GET.get('onglet', 'en_cours')
    if onglet == 'historique':
        commandes = commandes.filter(
            statut__in=['LIVRE_TOTAL', 'SOLDE', 'ANNULE']
        ).order_by('-date_commande')
    else:
        commandes = commandes.exclude(
            statut__in=['LIVRE_TOTAL', 'SOLDE', 'ANNULE']
        ).order_by('-date_commande')

    fournisseurs = Fournisseur.objects.all().order_by('raison_sociale')
    articles = Article.objects.all().select_related('famille').order_by('designation')
    familles = FamilleArticle.objects.all().order_by('intitule')

    statut_filtre = request.GET.get('statut', '')
    if statut_filtre:
        commandes = commandes.filter(statut=statut_filtre)

    q = request.GET.get('q', '')
    if q:
        commandes = filtrer_texte(commandes, q, [
            'numero_commande', 'fournisseur__raison_sociale',
            'lignes_commande__article__designation'
        ])
    fournisseur_filtre = request.GET.get('fournisseur', '')
    if fournisseur_filtre:
        commandes = commandes.filter(fournisseur_id=fournisseur_filtre)

    # ═══════════════════════════════════════════════════════
    # FILTRE PAR FAMILLE dans la liste
    # ═══════════════════════════════════════════════════════
    famille_liste_filtre = request.GET.get('famille_liste')
    if famille_liste_filtre:
        commandes = commandes.filter(famille_id=famille_liste_filtre)
    # ═══════════════════════════════════════════════════════

    # ← FIX : Définir famille_filtre ici pour le context GET
    famille_filtre = request.GET.get('famille', '')

    commandes_pagines, per_page = paginer(commandes, request)

    # ═══════════════════════════════════════════════════════════════════
    # ✅ CORRECTION : Fail-closed — pas de circuit = pas de validation
    # ═══════════════════════════════════════════════════════════════════
    peut_valider = request.user.is_superuser
    if not peut_valider:
        try:
            circuit = CircuitValidation.objects.get(
                type_document='COMMANDE'
            )
            if circuit.est_actif and circuit.valideurs.filter(id=request.user.id).exists():
                peut_valider = True
        except CircuitValidation.DoesNotExist:
            # FAIL-CLOSED : pas de circuit = pas de validation possible
            peut_valider = False
            logger.warning(
                f"[COMMANDE] Pas de circuit de validation configuré "
                f"None"
            )

    peut_creer = (request.user.has_perm('accounts.menu_commandes') or request.user.is_superuser)

    if request.method == 'POST':
        fournisseur_id = request.POST.get('fournisseur')
        famille_id = request.POST.get('famille')
        article_ids = request.POST.getlist('articles[]')
        quantites = request.POST.getlist('quantites[]')
        prix_unitaires = request.POST.getlist('prix_unitaires[]')

        # ── Validation famille obligatoire ──
        if not famille_id:
            messages.error(request, "❌ Veuillez sélectionner une famille d'articles.")
            return redirect('liste_commandes')

        if not article_ids:
            messages.error(request, "❌ Impossible d'enregistrer une commande vide.")
        elif not magasin_actif_id:
            messages.error(request, "❌ Veuillez sélectionner un magasin.")
        else:
            # ── Validation : tous les articles doivent appartenir à la famille ──
            famille = get_object_or_404(FamilleArticle, id=famille_id)
            if article_ids:
                articles_hors_famille = Article.objects.filter(
                    id__in=article_ids
                ).exclude(famille=famille)
                if articles_hors_famille.exists():
                    noms = ", ".join(a.designation for a in articles_hors_famille[:3])
                    messages.error(
                        request,
                        f"❌ Article(s) incompatible(s) avec la famille {famille.intitule} : {noms}..."
                    )
                    return redirect('liste_commandes')

            # ── Validation date livraison ──
            date_livraison_prevue = request.POST.get('date_livraison_prevue') or None
            if date_livraison_prevue:
                try:
                    date_obj = datetime.strptime(date_livraison_prevue, '%Y-%m-%d').date()
                    if date_obj < timezone.now().date():
                        messages.error(request, "❌ La date de livraison prévue ne peut pas être dans le passé.")
                        return redirect('liste_commandes')
                except ValueError:
                    messages.error(request, "❌ Format de date de livraison invalide.")
                    return redirect('liste_commandes')

            delai_raw = request.POST.get('delai_livraison', '').strip()
            delai_livraison = int(delai_raw) if delai_raw.isdigit() else None

            try:
                with transaction.atomic():
                    commande = Commande(
                        fournisseur_id=fournisseur_id,
                        magasin_id=magasin_actif_id,
                        famille=famille,
                        cree_par=request.user, modifie_par=request.user,
                        objet=request.POST.get('objet', '').strip() or None,
                        delai_livraison=delai_livraison,
                        date_livraison_prevue=date_livraison_prevue)
                    commande.save()
            except IntegrityError:
                messages.error(request, "⛔ Erreur de génération de numéro unique. Veuillez réessayer.")
                return redirect('liste_commandes')

            while len(prix_unitaires) < len(article_ids):
                prix_unitaires.append('')
            for aid, qte, pu in zip(article_ids, quantites, prix_unitaires):
                if aid and qte and int(qte) > 0:
                    pu_val = Decimal(pu.replace(' ', '').replace(',', '.').strip()) if pu and pu.strip() else None
                    LigneCommande.objects.create(
                        commande=commande, article_id=aid,
                        quantite_demandee=int(qte),
                        prix_unitaire=pu_val, quantite_recue=0
                    )
            messages.success(request, f"📝 Commande {commande.numero_commande} créée ({famille.intitule}).")
            return redirect('liste_commandes')

    context = {
        'commandes': commandes_pagines,
        'fournisseurs': fournisseurs,
        'articles': articles,
        'familles': familles,
        'famille_filtre': famille_filtre or '',
        'famille_liste_filtre': famille_liste_filtre or '',
        'q_commande': q,
        'per_page': per_page,
        'peut_valider': peut_valider,
        'peut_creer': peut_creer,
        'date_du_jour': timezone.now().date().isoformat(),
    }
    if request.headers.get('x-requested-with') == 'XMLHttpRequest':
        return render(request, 'stock/commandes_lignes.html', context)
    return render(request, 'stock/liste_commandes.html', context)

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_reception_commande')
@magasin_requis
@catch_errors(redirect_url='liste_commandes')
def receptionner_commande(request, commande_id):
    commande = get_object_or_404(
        Commande.objects.prefetch_related('lignes_commande__article'),
        id=commande_id)

    if commande.statut == 'LIVRE_TOTAL':
        messages.warning(
            request,
            f"La commande {commande.numero_commande} est déjà totalement livrée."
        )
        return redirect('liste_commandes')

    # Circuit de validation : une commande non approuvée ne peut pas être
    # réceptionnée (l'action doit attendre la validation des validateurs).
    if commande.statut_validation != 'VALIDE':
        messages.error(
            request,
            f"⛔ La commande {commande.numero_commande} n'est pas encore approuvée "
            "— la réception est impossible tant que les validateurs du circuit "
            "ne l'ont pas validée."
        )
        return redirect('liste_commandes')

    magasins = Magasin.objects.all()
    magasin_id_actif = request.session.get('magasin_actif_id')
    magasin_actif = Magasin.objects.filter(
        id=magasin_id_actif
    ).first()

    if request.method == 'POST':
        magasin_id = request.POST.get('magasin') or (
            magasin_actif.id if magasin_actif else None
        )
        if not magasin_id:
            messages.error(request, "❌ Veuillez sélectionner un magasin de réception.")
            return redirect('receptionner_commande', commande_id=commande.id)

        # CORRECTION : validation du magasin
        try:
            magasin = Magasin.objects.get(
                id=magasin_id, is_deleted=False
            )
        except Magasin.DoesNotExist:
            messages.error(request, "⛔ Magasin invalide ou inactif.")
            return redirect('receptionner_commande', commande_id=commande.id)

        magasins_autorises = get_magasins_autorises(request)
        if magasin not in magasins_autorises:
            messages.error(request, "⛔ Vous n'avez pas accès à ce magasin.")
            return redirect('receptionner_commande', commande_id=commande.id)

        reference_bl = request.POST.get('reference_externe')
        ligne_ids = request.POST.getlist('ligne_ids[]')
        quantites = request.POST.getlist('quantites[]')
        lots = request.POST.getlist('lots[]')
        peremptions = request.POST.getlist('peremptions[]')
        prix_unitaires = request.POST.getlist('prix_unitaires[]')

        while len(prix_unitaires) < len(ligne_ids):
            prix_unitaires.append('')
        while len(lots) < len(ligne_ids):
            lots.append('')
        while len(peremptions) < len(ligne_ids):
            peremptions.append('')

        # ✅ CORRECTION SANITAIRE : bloquer les lots déjà périmés AVANT toute écriture
        # Les lignes doivent appartenir à CETTE commande (sinon un ID forgé
        # permettrait de recevoir les lignes d'une autre commande).
        ids = [int(l) for l in ligne_ids if l.strip().isdigit()]
        lc_map = {
            lc.id: lc
            for lc in LigneCommande.objects.filter(
                id__in=ids, commande=commande
            ).select_related('article')
        }
        ids_inconnus = [l for l in ids if l not in lc_map]
        if ids_inconnus:
            messages.error(
                request,
                "⛔ Certaines lignes de réception n'appartiennent pas à cette commande."
            )
            return redirect('receptionner_commande', commande_id=commande.id)
        erreurs_peremption = []
        for lid, peremp in zip(ligne_ids, peremptions):
            if not (peremp and peremp.strip()):
                continue
            lc = lc_map.get(int(lid)) if lid.strip().isdigit() else None
            erreur = BonService._verifier_peremption(
                lc.article if lc else None, peremp
            )
            if erreur:
                erreurs_peremption.append(erreur)
        if erreurs_peremption:
            for e in erreurs_peremption[:5]:
                messages.error(request, e)
            if len(erreurs_peremption) > 5:
                messages.error(request, f"… et {len(erreurs_peremption) - 5} autre(s) ligne(s).")
            return redirect('receptionner_commande', commande_id=commande.id)

        total_reception = sum(
            int(q) for q in quantites if q.strip().isdigit()
        )
        if total_reception <= 0:
            messages.error(request, "❌ Aucune quantité à réceptionner.")
            return redirect('receptionner_commande', commande_id=commande.id)

        try:
            with transaction.atomic():
                numero_livraison = BonService.calculer_numero_livraison(commande)
                # Statut décidé ici (plus de recalcul dans BonMouvement.save())
                circuit_validation = CircuitValidation.objects.filter(
                    type_document='ENTREE', est_actif=True, is_deleted=False
                ).first()
                statut_bon = 'ATTENTE' if circuit_validation else 'VALIDE'
                bon = BonMouvement(
                    type_bon='ENTREE', magasin_id=magasin_id,
                    fournisseur=commande.fournisseur,
                    reference_externe=reference_bl,
                    cree_par=request.user, modifie_par=request.user,
                    commande_liee=commande,
                    numero_livraison=numero_livraison,
                    statut_validation=statut_bon
                )
                bon.save()

                circuit_actif = (bon.statut_validation == 'ATTENTE')

                for lid, qte, lot, peremp, pu in zip(
                    ligne_ids, quantites, lots, peremptions, prix_unitaires
                ):
                    qte_recue = int(qte) if qte.strip().isdigit() else 0
                    if qte_recue > 0:
                        if not lid.strip().isdigit() or int(lid) not in lc_map:
                            raise ValueError(
                                f"Ligne de réception {lid} inconnue pour la "
                                f"commande {commande.numero_commande}."
                            )
                        ligne_cmd = LigneCommande.objects.select_for_update().get(id=lid)
                        if qte_recue > ligne_cmd.reliquat:
                            raise ValueError(
                                f"Réception {qte_recue} '{ligne_cmd.article.designation}' "
                                f"impossible : reliquat = {ligne_cmd.reliquat}"
                            )
                        article = ligne_cmd.article
                        date_p = peremp if peremp and peremp.strip() else None
                        pu_val = Decimal(
                            pu.replace(' ', '').replace(',', '.').strip()
                        ) if pu and pu.strip() else None

                        reliquat_avant = ligne_cmd.reliquat
                        reliquat_apres = max(0, reliquat_avant - qte_recue)

                        LigneBon.objects.create(
                            bon=bon, article=article, quantite=qte_recue,
                            numero_lot=lot, date_peremption=date_p,
                            prix_unitaire=pu_val,
                            quantite_demandee=reliquat_avant,
                            reste=reliquat_apres)

                        if not circuit_actif:
                            mouvement = Mouvement(
                                type_mouvement='ENTREE', article=article,
                                magasin_id=magasin_id,
                                fournisseur=commande.fournisseur,
                                quantite=qte_recue, prix_unitaire=pu_val,
                                reference_document=f"{bon.numero_bon} (Réf Cmd: {commande.numero_commande})",
                                utilisateur=request.user,
                                commentaire=f"Réception commande {commande.numero_commande}",
                                numero_lot=lot, date_peremption=date_p)
                            StockTransactionService.executer(mouvement)

                        ligne_cmd.quantite_recue += qte_recue
                        ligne_cmd.save()

                lignes_incompletes = LigneCommande.objects.filter(
                    commande_id=commande.id,
                    quantite_recue__lt=F('quantite_demandee')
                ).count()
                if lignes_incompletes == 0:
                    commande.statut = 'LIVRE_TOTAL'
                    msg = "✅ Commande TOTALEMENT réceptionnée !"
                else:
                    commande.statut = 'LIVRE_PARTIEL'
                    msg = "⚠️ Réception partielle enregistrée."
                commande.save()

        except IntegrityError:
            messages.error(request, "⛔ Erreur de génération de numéro unique pour le bon. Veuillez réessayer.")
            return redirect('receptionner_commande', commande_id=commande.id)
        except ValueError as ve:
            # ✅ CORRECTION : Message générique + log serveur
            messages.error(request, "❌ Erreur de validation lors de la réception.")
            logger.exception("[RECEPTION] %s", ve)
            return redirect('receptionner_commande', commande_id=commande.id)

        if circuit_actif:
            messages.info(
                request,
                f"⏳ Bon d'entrée {bon.numero_bon} créé en ATTENTE de validation. "
                f"Les mouvements de stock seront appliqués après validation."
            )
            return redirect('liste_receptions')

        messages.success(request, msg)
        return redirect(f"{reverse('liste_receptions')}?print_bon={bon.id}")

    context = {'commande': commande, 'magasins': magasins, 'magasin_actif': magasin_actif}
    return render(request, 'stock/receptionner_commande.html', context)

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_commandes')
@magasin_requis
@catch_errors(redirect_url='liste_commandes')
def valider_commande(request, commande_id):
    commande = get_object_or_404(
        Commande, id=commande_id)

    if request.method != 'POST':
        messages.error(request, "❌ Cette action doit être effectuée en POST.")
        return redirect('liste_commandes')

    # ✅ CORRECTION : Fail-closed complet
    peut_valider = request.user.is_superuser
    try:
        circuit = CircuitValidation.objects.get(
            type_document='COMMANDE'
        )
        if circuit.est_actif and not circuit.valideurs.filter(id=request.user.id).exists() and not request.user.is_superuser:
            messages.error(
                request,
                "❌ Vous n'êtes pas valideur pour les commandes."
            )
            return redirect('liste_commandes')
        if circuit.est_actif:
            peut_valider = True
    except CircuitValidation.DoesNotExist:
        # FAIL-CLOSED : pas de circuit = seul le superuser peut valider
        peut_valider = False
        logger.warning(
            "[COMMANDE] Pas de circuit de validation configuré "
            "pour le type COMMANDE"
        )

    if not peut_valider:
        messages.error(request, "❌ Vous n'êtes pas autorisé à valider les commandes.")
        return redirect('liste_commandes')

    if commande.statut_validation == 'VALIDE':
        messages.warning(
            request,
            f"La commande {commande.numero_commande} est déjà validée."
        )
    else:
        commande.statut_validation = 'VALIDE'
        commande.valide_par = request.user
        commande.date_validation = timezone.now()
        commande.save()
        messages.success(
            request,
            f"✅ Commande {commande.numero_commande} approuvée !"
        )
    return redirect('liste_commandes')

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_commandes')
@magasin_requis
@catch_errors(redirect_url='liste_commandes')
def supprimer_commande(request, commande_id):
    commande = get_object_or_404(
        Commande, id=commande_id)
    # Vérification des dépendances avant suppression
    deps = []
    if commande.bons_reception.exists():
        deps.append(f"{commande.bons_reception.count()} bon(s) de réception")
    if hasattr(commande, 'bons_livraison') and commande.bons_livraison_commande.exists():
        deps.append(f"{commande.bons_livraison_commande.count()} bon(s) de livraison")
    if commande.lignes_commande.exists():
        deps.append(f"{commande.lignes_commande.count()} ligne(s) de commande")

    if deps:
        messages.error(
            request,
            f"⛔ Impossible de supprimer : commande utilisée par {', '.join(deps)}."
        )
        return redirect('liste_commandes')

    if commande.statut_validation != 'VALIDE':
        numero = commande.numero_commande
        _safe_delete(commande, request.user)
        messages.success(
            request,
            f"Le brouillon de commande {numero} a été supprimé."
        )
    else:
        messages.error(
            request,
            "Action refusée : Impossible de supprimer une commande validée."
        )
    return redirect('liste_commandes')

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_commandes')
@magasin_requis
@transaction.atomic
@catch_errors(redirect_url='liste_commandes')
def modifier_commande(request, commande_id):
    commande = get_object_or_404(
        Commande.objects.select_related('famille'),
        id=commande_id)

    if commande.statut != 'EN_ATTENTE':
        messages.error(request, "Impossible de modifier : commande déjà en cours de réception ou clôturée.")
        return redirect('liste_commandes')

    if request.method == 'POST':
        fournisseur_id = request.POST.get('fournisseur')
        famille_id = request.POST.get('famille')

        # ── Validation famille obligatoire ──
        if not famille_id:
            messages.error(request, "❌ Veuillez sélectionner une famille d'articles.")
            return redirect('liste_commandes')

        famille = get_object_or_404(FamilleArticle, id=famille_id)

        # ═══════════════════════════════════════════════════════
        # ✅ VALIDATION SUR LA MODIFICATION
        # ═══════════════════════════════════════════════════════
        date_livraison_prevue = request.POST.get('date_livraison_prevue') or None
        if date_livraison_prevue:
            try:
                date_obj = datetime.strptime(date_livraison_prevue, '%Y-%m-%d').date()
                if date_obj < timezone.now().date():
                    messages.error(request, "❌ La date de livraison prévue ne peut pas être dans le passé.")
                    return redirect('liste_commandes')
            except ValueError:
                messages.error(request, "❌ Format de date de livraison invalide.")
                return redirect('liste_commandes')

        delai_raw = request.POST.get('delai_livraison', '').strip()
        delai_livraison = int(delai_raw) if delai_raw.isdigit() else None
        # ═══════════════════════════════════════════════════════

        # ── Validation : cohérence articles vs famille ──
        articles_ids = request.POST.getlist('articles[]')
        if articles_ids:
            articles_hors_famille = Article.objects.filter(
                id__in=articles_ids
            ).exclude(famille=famille)
            if articles_hors_famille.exists():
                noms = ", ".join(a.designation for a in articles_hors_famille[:3])
                messages.error(
                    request,
                    f"❌ Article(s) incompatible(s) avec la famille {famille.intitule} : {noms}..."
                )
                return redirect('liste_commandes')

        if fournisseur_id:
            commande.fournisseur_id = fournisseur_id
        commande.famille = famille
        commande.objet = request.POST.get('objet', '').strip() or None
        commande.delai_livraison = delai_livraison
        commande.date_livraison_prevue = date_livraison_prevue
        commande.modifie_par = request.user
        commande.save()

        commande.lignes_commande.all().delete()
        quantites = request.POST.getlist('quantites[]')
        prix_unitaires = request.POST.getlist('prix_unitaires[]')
        while len(prix_unitaires) < len(articles_ids):
            prix_unitaires.append('')
        for art_id, qte, pu in zip(articles_ids, quantites, prix_unitaires):
            if art_id and qte and int(qte) > 0:
                pu_val = Decimal(pu.replace(' ', '').replace(',', '.').strip()) if pu and pu.strip() else None
                LigneCommande.objects.create(
                    commande=commande, article_id=art_id,
                    quantite_demandee=int(qte), quantite_recue=0, prix_unitaire=pu_val
                )
        messages.success(request, f"La commande {commande.numero_commande} a été mise à jour ({famille.intitule}).")
        return redirect('liste_commandes')

    fournisseurs = Fournisseur.objects.all()
    articles = Article.objects.all().select_related('famille')
    
    # Si la commande a déjà une famille, on pré-filtre les articles
    if commande.famille_id:
        articles = articles.filter(famille=commande.famille)
    
    familles = FamilleArticle.objects.all().order_by('intitule')
    
    context = {
        'commande': commande,
        'fournisseurs': fournisseurs,
        'articles': articles,
        'familles': familles,
        'date_du_jour': timezone.now().date().isoformat()
    }
    return render(request, 'stock/modifier_commande.html', context)

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_commandes')
@require_POST
@catch_errors(redirect_url='liste_commandes')
def solder_commande(request, commande_id):
    commande = get_object_or_404(
        Commande, id=commande_id)
    if commande.statut in ['EN_ATTENTE', 'LIVRE_PARTIEL']:
        commande.statut = 'SOLDE'
        commande.save()
        messages.success(
            request,
            f"La commande {commande.numero_commande} a été soldée et clôturée définitivement."
        )
    else:
        messages.error(
            request,
            "Cette commande ne peut pas être soldée dans son état actuel."
        )
    return redirect('liste_commandes')

# ══════════════════════════════════════════════════════════════════════════════
# RÉCEPTIONS
# ══════════════════════════════════════════════════════════════════════════════

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_reception_commande')
@magasin_requis
@catch_errors(redirect_url='liste_commandes')
def liste_receptions(request):
    """Vue liste des réceptions (GET uniquement, POST géré par receptionner_commande)."""
    magasin_actif_id = request.session.get('magasin_actif_id')

    onglet = request.GET.get('onglet', 'en_cours')
    statuts = ['LIVRE_TOTAL', 'SOLDE', 'ANNULE'] if onglet == 'terminees' else ['EN_ATTENTE', 'LIVRE_PARTIEL']

    qs = Commande.objects.select_related('fournisseur', 'cree_par', 'famille').prefetch_related(
        'lignes_commande__article', 'bons_reception__magasin', 'bons_livraison_commande'
    ).filter( statut__in=statuts).order_by('-date_commande')

    if magasin_actif_id:
        qs = qs.filter(magasin_id=magasin_actif_id)

    if request.GET.get('fournisseur'):
        qs = qs.filter(fournisseur_id=request.GET.get('fournisseur'))

    q = request.GET.get('q', '')
    if q:
        qs = filtrer_texte(qs, q, [
            'numero_commande', 'fournisseur__raison_sociale',
            'lignes_commande__article__designation'
        ])

    commandes_pagines, per_page = paginer(qs, request)

    config = ConfigurationHopital.objects.first()
    delai_jours = getattr(config, 'delai_remplacement_bon_jours', 2) if config else 2

    # ✅ reliquat est maintenant un champ DB (PositiveIntegerField)
    # L'annotate fonctionne normalement avec Sum/Count/filter

    commandes_annotated = Commande.objects.filter(
        id__in=[c.id for c in commandes_pagines]
    ).annotate(
        reliquat_total=Sum('lignes_commande__reliquat'),
        qte_demandee_total=Sum('lignes_commande__quantite_demandee'),
        qte_recue_total=Sum('lignes_commande__quantite_recue'),
        nb_lignes_reliquat=Count(
            'lignes_commande',
            filter=Q(lignes_commande__reliquat__gt=0)
        )
    )
    cmd_data_map = {c.id: c for c in commandes_annotated}

    commandes_data = []
    total_lignes = 0
    total_reliquat = 0
    for cmd in commandes_pagines:
        annotated = cmd_data_map.get(cmd.id, cmd)
        reliquat_total = getattr(annotated, 'reliquat_total', 0) or 0
        qte_demandee_total = getattr(annotated, 'qte_demandee_total', 0) or 0
        qte_recue_total = getattr(annotated, 'qte_recue_total', 0) or 0
        nb_lignes_reliquat = getattr(annotated, 'nb_lignes_reliquat', 0) or 0

        bons_livraison = list(cmd.bons_livraison_commande.all())
        bls_data = []
        for bl in bons_livraison:
            delai_ecoule = (timezone.now() - bl.date_upload).days
            bls_data.append({'bl': bl, 'peut_remplacer': delai_ecoule <= delai_jours})

        bons_entree_data = []
        premier_bon_sans_bl = None
        for be in cmd.bons_reception.all():
            bl = be.bons_livraison_entree.first()
            bons_entree_data.append({'bon': be, 'bl': bl, 'has_bl': bool(bl)})
            if not bl and not premier_bon_sans_bl:
                premier_bon_sans_bl = be

        commandes_data.append({
            'commande': cmd,
            'reliquat_total': reliquat_total,
            'qte_demandee_total': qte_demandee_total,
            'qte_recue_total': qte_recue_total,
            'nb_lignes_reliquat': nb_lignes_reliquat,
            'pourcentage': round((qte_recue_total / qte_demandee_total) * 100, 1) if qte_demandee_total else 0,
            'has_doc': bool(bons_livraison),
            'nb_bl': len(bons_livraison),
            'nb_receptions': cmd.bons_reception.count(),
            'bls_data': bls_data,
            'bons_entree_data': bons_entree_data,
            'premier_bon_sans_bl_id': premier_bon_sans_bl.id if premier_bon_sans_bl else None,
        })
        total_lignes += nb_lignes_reliquat
        total_reliquat += reliquat_total

    counts = {
        'en_cours': Commande.objects.filter( statut__in=['EN_ATTENTE', 'LIVRE_PARTIEL']).count(),
        'terminees': Commande.objects.filter( statut__in=['LIVRE_TOTAL', 'SOLDE', 'ANNULE']).count(),
    }

    context = {
        'commandes_data': commandes_data,
        'commandes': commandes_pagines,
        'fournisseurs': Fournisseur.objects.all().order_by('raison_sociale'),
        'q_commande': q,
        'per_page': per_page,
        'onglet': onglet,
        'counts': counts,
        'total_lignes': total_lignes,
        'total_reliquat': total_reliquat,
        'magasin_actif': get_magasin_actif(request),
        'delai_jours': delai_jours,
        'peut_creer': request.user.has_perm('accounts.menu_reception_commande') or request.user.is_superuser,
    }
    return render(request, 'stock/liste_receptions.html', context)

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_reception_commande')
@require_POST
@catch_errors(redirect_url='liste_receptions')
def joindre_bon_livraison(request, commande_id):
    commande = get_object_or_404(
        Commande, id=commande_id)

    if not commande.bons_reception.exists():
        messages.error(request, "⛔ Impossible de joindre un bon : la commande n'a pas encore été réceptionnée.")
        return redirect('liste_receptions')

    fichier = request.FILES.get('document_livraison')
    if not fichier:
        messages.error(request, "⛔ Aucun fichier sélectionné.")
        return redirect('liste_receptions')

    if fichier.size > MAX_FILE_SIZE:
        messages.error(request, f"⛔ Fichier trop lourd ({fichier.size // 1024} Ko). Maximum 1 Mo.")
        return redirect('liste_receptions')

    if not fichier.name.lower().endswith(('.pdf', '.jpg', '.jpeg', '.png')):
        messages.error(request, "⛔ Format invalide. Seuls PDF, JPG et PNG sont acceptés.")
        return redirect('liste_receptions')

    # ── Récupération du bon d'entrée lié (optionnel mais recommandé) ──
    bon_entree_id = request.POST.get('bon_entree_id')
    bon_entree = None
    if bon_entree_id:
        bon_entree = get_object_or_404(
            BonMouvement,
            id=bon_entree_id,
            commande_liee=commande,
            type_bon='ENTREE')
        # Vérifie qu'il n'y a pas déjà un BL pour cette réception
        if BonDeLivraison.objects.filter(bon_entree=bon_entree).exists():
            messages.error(request, "⛔ Un BL est déjà joint à cette réception.")
            return redirect('liste_receptions')

    # ── Création du BL (stockage moderne 1-to-many) ──
    BonDeLivraison.objects.create(
        commande=commande,
        bon_entree=bon_entree,
        fichier=fichier,
        upload_par=request.user,
        reference_bl=request.POST.get('reference_bl', '').strip() or None
    )

    messages.success(
        request,
        f"✅ Bon de livraison ajouté à la commande {commande.numero_commande}."
    )
    return redirect('liste_receptions')

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_reception_commande')
@require_POST
@catch_errors(redirect_url='liste_receptions')
def remplacer_bon_livraison(request, bon_id):
    bon = get_object_or_404(
        BonDeLivraison,
        id=bon_id)

    config = ConfigurationHopital.objects.first()
    delai_jours = getattr(config, 'delai_remplacement_bon_jours', 2) if config else 2

    delai_ecoule = (timezone.now() - bon.date_upload).days
    if delai_ecoule > delai_jours:
        messages.error(
            request,
            f"⛔ Remplacement impossible : le délai de {delai_jours} jour(s) est dépassé."
        )
        return redirect('liste_receptions')

    fichier = request.FILES.get('document_livraison')
    if not fichier:
        messages.error(request, "⛔ Aucun fichier sélectionné.")
        return redirect('liste_receptions')

    if fichier.size > MAX_FILE_SIZE:
        messages.error(request, f"⛔ Fichier trop lourd ({fichier.size // 1024} Ko). Maximum 1 Mo.")
        return redirect('liste_receptions')

    if not fichier.name.lower().endswith(('.pdf', '.jpg', '.jpeg', '.png')):
        messages.error(request, "⛔ Format invalide. Seuls PDF, JPG et PNG sont acceptés.")
        return redirect('liste_receptions')

    try:
        bon.fichier.delete(save=False)
    except Exception as e:
        logger.warning("[joindre_bon_livraison] Suppression ancien fichier BL %s échouée : %s", bon.id, e)

    bon.fichier = fichier
    bon.date_upload = timezone.now()
    bon.upload_par = request.user
    ref = request.POST.get('reference_bl', '').strip()
    if ref:
        bon.reference_bl = ref
    bon.save()

    messages.success(
        request,
        f"✅ Bon de livraison remplacé pour la commande {bon.commande.numero_commande}."
    )
    return redirect('liste_receptions')

@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_reception_commande')
def voir_bon_livraison(request, bon_id):
    bon = get_object_or_404(
        BonDeLivraison,
        id=bon_id)
    if bon.fichier:
        content_type = 'application/pdf' if bon.fichier.name.endswith('.pdf') else 'image/jpeg'
        return FileResponse(bon.fichier.open(), content_type=content_type)
    return HttpResponse("Aucun document joint.", status=404)



# ══════════════════════════════════════════════════════════════════════════════
# SUGGESTIONS DE RÉAPPROVISIONNEMENT
# ══════════════════════════════════════════════════════════════════════════════

def _statut_suggestion(stock, seuil_critique, seuil_minimum):
    """Statut d'alerte d'un stock par rapport aux seuils de l'article."""
    if seuil_critique is not None and stock <= seuil_critique:
        return 'CRITIQUE'
    if seuil_minimum is not None and stock <= seuil_minimum:
        return 'ALERTE'
    return 'OK'


def _qte_recommandee(article, stock):
    """Quantité à commander pour remonter au niveau cible (seuil max sinon
    double du seuil min)."""
    cible = article.seuil_maximum if (article.seuil_maximum or 0) > 0 \
        else (article.seuil_minimum or 0) * 2
    return max(cible - stock, 1)


@login_required(login_url='/auth/login/')
@verifier_permission('accounts.menu_commandes')
@magasin_requis
@catch_errors(redirect_url='liste_commandes')
def suggestions_reappro(request):
    """Suggestions automatiques de commandes : articles sous seuil dans le
    magasin actif, avec quantité recommandée, convertibles en commandes
    fournisseur en un clic (une commande par famille)."""
    magasin = get_magasin_actif(request)
    famille_filtre = request.GET.get('famille', '')
    q = request.GET.get('q', '').strip()

    # ── POST : conversion des suggestions sélectionnées en commandes ──
    if request.method == 'POST':
        fournisseur_id = request.POST.get('fournisseur')
        objet = request.POST.get('objet', '').strip() or None
        article_ids = request.POST.getlist('articles[]')
        quantites = request.POST.getlist('quantites[]')

        if not magasin:
            messages.error(request, "❌ Veuillez sélectionner un magasin.")
            return redirect('suggestions_reappro')

        if not fournisseur_id:
            messages.error(
                request, "❌ Sélectionnez un fournisseur pour créer la commande.")
            return redirect('suggestions_reappro')

        fournisseur = get_object_or_404(Fournisseur, id=fournisseur_id)

        if not article_ids:
            messages.error(
                request, "❌ Sélectionnez au moins un article à commander.")
            return redirect('suggestions_reappro')

        # (article_id, quantite) validés
        lignes_valides = []
        articles_map = {
            a.id: a for a in Article.objects.filter(
                id__in=[int(aid) for aid in article_ids if aid])
        }
        for aid, qte in zip(article_ids, quantites):
            if not aid or not qte:
                continue
            try:
                qte_int = int(qte)
            except (TypeError, ValueError):
                continue
            if qte_int <= 0 or int(aid) not in articles_map:
                continue
            lignes_valides.append((int(aid), qte_int))

        if not lignes_valides:
            messages.error(
                request, "❌ Aucune quantité valide à commander.")
            return redirect('suggestions_reappro')

        # Groupement par famille → une commande par famille
        par_famille = defaultdict(list)
        for aid, qte in lignes_valides:
            par_famille[articles_map[aid].famille_id].append((aid, qte))

        commandes_crees = []
        try:
            with transaction.atomic():
                for famille_id, lignes_famille in par_famille.items():
                    famille = FamilleArticle.objects.get(id=famille_id)
                    commande = Commande(
                        fournisseur=fournisseur,
                        magasin=magasin,
                        famille=famille,
                        cree_par=request.user,
                        modifie_par=request.user,
                        objet=objet or f"Réappro {famille.intitule}",
                    )
                    commande.save()
                    for aid, qte in lignes_famille:
                        article = articles_map[aid]
                        LigneCommande.objects.create(
                            commande=commande,
                            article=article,
                            quantite_demandee=qte,
                            quantite_recue=0,
                            prix_unitaire=article.prix_reference,
                        )
                    commandes_crees.append(
                        f"{commande.numero_commande} ({famille.intitule}, "
                        f"{len(lignes_famille)} article(s))")
        except IntegrityError:
            logger.exception("[REAPPRO] Erreur création commande")
            messages.error(
                request, "⛔ Erreur lors de la création. Veuillez réessayer.")
            return redirect('suggestions_reappro')

        messages.success(
            request,
            f"✅ {len(commandes_crees)} commande(s) créée(s) : "
            + ", ".join(commandes_crees)
            + ". Elles apparaissent dans la liste des commandes.")
        return redirect('liste_commandes')

    # ── GET : calcul des suggestions ──
    stocks = StockItem.objects.select_related('article__famille', 'magasin').filter(
        magasin=magasin,
        batch_number__isnull=True,
        quantite_physique__gte=0,
        article__seuil_minimum__gt=0,
    )

    if famille_filtre:
        stocks = stocks.filter(article__famille_id=famille_filtre)
    if q:
        stocks = stocks.filter(
            Q(article__designation__icontains=q) |
            Q(article__reference__icontains=q)
        )

    suggestions = []
    for s in stocks:
        art = s.article
        if s.quantite_physique > art.seuil_minimum:
            continue  # au-dessus du seuil : pas de suggestion
        qte_rec = _qte_recommandee(art, s.quantite_physique)
        valeur = Decimal(str(art.prix_reference or 0)) * qte_rec
        suggestions.append({
            'article': art,
            'stock': s.quantite_physique,
            'seuil_minimum': art.seuil_minimum,
            'seuil_critique': art.seuil_critique,
            'seuil_maximum': art.seuil_maximum,
            'qte_recommandee': qte_rec,
            'valeur_estimee': valeur,
            'statut': _statut_suggestion(
                s.quantite_physique, art.seuil_critique, art.seuil_minimum),
        })

    # Tri : CRITIQUE d'abord, puis ratio stock/seuil croissant
    def _cle(sug):
        ratio = (sug['stock'] / sug['seuil_minimum']) \
            if sug['seuil_minimum'] else 1
        return (0 if sug['statut'] == 'CRITIQUE' else 1, ratio)

    suggestions.sort(key=_cle)

    nb_critiques = sum(1 for s in suggestions if s['statut'] == 'CRITIQUE')
    valeur_totale = sum(s['valeur_estimee'] for s in suggestions)

    familles = FamilleArticle.objects.all().order_by('intitule')

    context = {
        'suggestions': suggestions,
        'familles': familles,
        'famille_filtre': famille_filtre,
        'q_reappro': q,
        'magasin': magasin,
        'nb_suggestions': len(suggestions),
        'nb_critiques': nb_critiques,
        'valeur_totale': valeur_totale,
        'fournisseurs': Fournisseur.objects.all().order_by('raison_sociale'),
    }
    return render(request, 'stock/suggestions_reappro.html', context)
