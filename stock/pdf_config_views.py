# stock/pdf_config_views.py
# Views pour configurer les modèles de documents PDF par magasin

import json
import logging
import os
from decimal import Decimal
from types import SimpleNamespace

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views import View
from django.http import HttpResponse
from django.utils.decorators import method_decorator
from django.contrib import messages
from django.utils import timezone
from django.template.loader import render_to_string
from django.conf import settings
from django.contrib.staticfiles.finders import find

try:
    import weasyprint
except ImportError:
    weasyprint = None

from stock.models import Magasin, ModeleDocumentMagasin, ParametrePDF

logger = logging.getLogger(__name__)


def _user_peut_configurer_magasin(user, magasin):
    """Vérifie que l'utilisateur a le droit de configurer ce magasin."""
    if user.is_superuser:
        return True
    if not user.has_perm('accounts.menu_modeles_pdf'):
        return False
    if magasin.responsable == user:
        return True
    profil = getattr(user, 'profil', None)
    if profil and profil.magasins_autorises.filter(pk=magasin.pk).exists():
        return True
    return False


def _get_logo_url(request):
    """Retourne l'URL absolue du logo global pour les PDF."""
    return ParametrePDF.get_logo_url(request)


def _colonnes_par_type(type_doc):
    """Retourne la définition des colonnes selon le type de document."""
    if type_doc == 'BDM':
        return [
            {'code': 'numero', 'label': 'N°', 'largeur': '8%', 'obligatoire': True},
            {'code': 'reference', 'label': 'Code', 'largeur': '15%', 'obligatoire': True},
            {'code': 'designation', 'label': 'Désignation', 'largeur': '47%', 'obligatoire': True},
            {'code': 'unite', 'label': 'Unité', 'largeur': '15%', 'obligatoire': True},
            {'code': 'quantite', 'label': 'Qté demandée', 'largeur': '15%', 'obligatoire': True},
        ]
    return [
        {'code': 'numero', 'label': 'N°', 'largeur': '5%', 'obligatoire': True},
        {'code': 'reference', 'label': 'Code', 'largeur': '12%', 'obligatoire': True},
        {'code': 'designation', 'label': 'Désignation', 'largeur': '30%', 'obligatoire': True},
        {'code': 'unite', 'label': 'Unité', 'largeur': '8%', 'obligatoire': True},
        {'code': 'quantite', 'label': 'Qté', 'largeur': '8%', 'obligatoire': True},
        {'code': 'quantite_servie', 'label': 'Qté servie', 'largeur': '8%', 'obligatoire': False},
        {'code': 'lot', 'label': 'N° Lot', 'largeur': '12%', 'obligatoire': False},
        {'code': 'peremption', 'label': 'Péremption', 'largeur': '12%', 'obligatoire': False},
        {'code': 'prix_unitaire', 'label': 'P.U.', 'largeur': '10%', 'obligatoire': False},
        {'code': 'montant', 'label': 'Montant', 'largeur': '12%', 'obligatoire': False},
    ]


def _nb_signatures_max(type_doc):
    # Aligné sur les formats officiels CHU Angré (voir pdf/)
    mapping = {'BDM': 2, 'BS': 6, 'BE': 2, 'BR': 2, 'BSHS': 2, 'BC': 3}
    return mapping.get(type_doc, 6)


def _parse_post_to_config(request_post, type_doc='BS'):
    """Transforme les données POST du formulaire en dict JSON structuré."""
    cfg = {
        'cartouche': {},
        'tableau': {},
        'signatures': [],
        'sondage': {},
        'pied_de_page': {},
        'metadonnees': {},
        'service_demandeur': {},
    }

        # CARTOUCHE
    cfg['cartouche']['afficher_code_iso'] = request_post.get('cartouche_afficher_code_iso') == 'on'
    cfg['cartouche']['position_logo'] = request_post.get('cartouche_position_logo', 'left')
    cfg['cartouche']['trait_separation_epaisseur'] = int(request_post.get('cartouche_trait_separation_epaisseur', 1) or 1)
    cfg['cartouche']['trait_separation_couleur'] = request_post.get('cartouche_trait_separation_couleur', '#000000')

    # TABLEAU
    colonnes_codes = request_post.getlist('tableau_colonnes')
    all_colonnes_def = _colonnes_par_type(type_doc)
    cfg['tableau']['colonnes'] = [
        {**c, 'visible': c['code'] in colonnes_codes or c.get('obligatoire', False)}
        for c in all_colonnes_def
    ]
    cfg['tableau']['lignes_dynamiques'] = request_post.get('tableau_lignes_dynamiques') == 'on'
    cfg['tableau']['lignes_minimum'] = int(request_post.get('tableau_lignes_minimum', 10) or 10)
    cfg['tableau']['alternance_couleurs'] = request_post.get('tableau_alternance_couleurs') == 'on'
    cfg['tableau']['bordure_style'] = request_post.get('tableau_bordure_style', 'solid')
    cfg['tableau']['bordure_epaisseur'] = request_post.get('tableau_bordure_epaisseur', 'normal')

    # SIGNATURES
    max_sig = _nb_signatures_max(type_doc)
    for i in range(1, max_sig + 1):
        prefix = f'signatures_{i}'
        label = request_post.get(f'{prefix}_label', '').strip()
        if label or request_post.get(f'{prefix}_visible') == 'on':
            cfg['signatures'].append({
                'ordre': i,
                'role': request_post.get(f'{prefix}_role', ''),
                'label': label,
                'visible': request_post.get(f'{prefix}_visible') == 'on',
                'position': request_post.get(f'{prefix}_position', 'left'),
                'style': request_post.get(f'{prefix}_style', 'ligne_pointillee'),
                'condition': request_post.get(f'{prefix}_condition', 'toujours'),
            })

    cfg['afficher_fonction_signataire'] = request_post.get('afficher_fonction_signataire') == 'on'

    if type_doc in ('BS', 'BR', 'BSHS'):
        cfg['service_demandeur'] = {
            'encadrer': request_post.get('service_demandeur_encadrer') == 'on',
            'position': request_post.get('service_demandeur_position', 'left'),
        }

    if type_doc == 'BS':
        cfg['sondage']['afficher'] = request_post.get('sondage_afficher') == 'on'
        cfg['sondage']['trait_separation'] = request_post.get('sondage_trait_separation') == 'on'
        cfg['sondage']['style_cases'] = request_post.get('sondage_style_cases') == 'on'

    # MÉTADONNÉES
    cfg['metadonnees']['code_document'] = request_post.get('metadonnees_code_document', '')
    cfg['metadonnees']['date_creation_doc'] = request_post.get('metadonnees_date_creation_doc', '')
    cfg['metadonnees']['date_revision_doc'] = request_post.get('metadonnees_date_revision_doc', '')
    cfg['metadonnees']['version_doc'] = request_post.get('metadonnees_version_doc', '')
    cfg['metadonnees']['ps2_label'] = request_post.get('metadonnees_ps2_label', '')

    return cfg


def _config_to_form_context(cfg):
    """Aplatit le dict JSON en variables de template pour pré-remplir le formulaire."""
    ctx = {}
    for k, v in cfg.get('cartouche', {}).items():
        ctx[f'cartouche_{k}'] = v
    for k, v in cfg.get('tableau', {}).items():
        if k == 'colonnes':
            ctx['tableau_colonnes'] = [c['code'] for c in v if c.get('visible', False)]
        else:
            ctx[f'tableau_{k}'] = v
    for sig in cfg.get('signatures', []):
        i = sig['ordre']
        for k, v in sig.items():
            ctx[f'signatures_{i}_{k}'] = v
    for k, v in cfg.get('sondage', {}).items():
        ctx[f'sondage_{k}'] = v
    ctx['afficher_fonction_signataire'] = cfg.get('afficher_fonction_signataire', False)
    for k, v in cfg.get('service_demandeur', {}).items():
        ctx[f'service_demandeur_{k}'] = v
    for k, v in cfg.get('metadonnees', {}).items():
        ctx[f'metadonnees_{k}'] = v
    return ctx


_LEGACY_MAP = {
    'BS': 'BON_SORTIE', 'BE': 'BON_ENTREE', 'BR': 'BON_RETOUR',
    'BSHS': 'BON_HS', 'BC': 'COMMANDE', 'BDM': 'DEMANDE',
}

_TEMPLATE_MAP = {
    'BDM': 'stock/pdf/bon_demande.html',
    'BS': 'stock/pdf/bon_sortie.html',
    'BE': 'stock/pdf/bon_entree.html',
    'BR': 'stock/pdf/bon_retour.html',
    'BSHS': 'stock/pdf/bon_hors_stock.html',
    'BC': 'stock/pdf/bon_commande.html',
}


@method_decorator(login_required, name='dispatch')
class ModelePDFConfigView(LoginRequiredMixin, UserPassesTestMixin, View):

    def test_func(self):
        magasin = get_object_or_404(Magasin, pk=self.kwargs['magasin_id'])
        return _user_peut_configurer_magasin(self.request.user, magasin)

    def get(self, request, magasin_id, type_doc='BS'):
        magasin = get_object_or_404(Magasin, pk=magasin_id)
        if not _user_peut_configurer_magasin(request.user, magasin):
            messages.error(request, "Vous n'avez pas l'autorisation de configurer ce magasin.")
            return redirect('accueil_personnalise')

        modele, created = ModeleDocumentMagasin.objects.get_or_create(
            magasin=magasin,
            type_document=type_doc,
            defaults={
                'est_actif': True,
                'config': {},
                'cree_par': request.user,
                'modifie_par': request.user,
            }
        )

        try:
            config_complete = modele.get_config_complete(type_doc_legacy=_LEGACY_MAP.get(type_doc, 'BON_SORTIE'))
        except AttributeError:
            config_complete = modele.config or {}

        form_ctx = _config_to_form_context(config_complete)
        form_ctx['magasin'] = magasin
        form_ctx['type_doc'] = type_doc
        form_ctx['type_doc_label'] = modele.get_type_document_display()
        form_ctx['modele'] = modele
        form_ctx['nb_signatures_max'] = _nb_signatures_max(type_doc)
        form_ctx['colonnes_def'] = _colonnes_par_type(type_doc)

        # Logo global
        param_pdf = ParametrePDF.get_instance()
        form_ctx['logo_global'] = param_pdf.logo
        form_ctx['logo_global_url'] = ParametrePDF.get_logo_url(request)

        return render(request, 'stock/modele_pdf_form.html', form_ctx)

    def post(self, request, magasin_id, type_doc='BS'):
        magasin = get_object_or_404(Magasin, pk=magasin_id)
        if not _user_peut_configurer_magasin(request.user, magasin):
            messages.error(request, "Vous n'avez pas l'autorisation de configurer ce magasin.")
            return redirect('accueil_personnalise')

        # ═══════════════════════════════════════════════════════════════
        # GESTION DU LOGO GLOBAL (upload ou suppression)
        # ═══════════════════════════════════════════════════════════════
        if request.FILES.get('logo_global'):
            param_pdf = ParametrePDF.get_instance()
            # Supprimer l'ancien logo s'il existe
            if param_pdf.logo:
                try:
                    old_path = param_pdf.logo.path
                    if os.path.isfile(old_path):
                        os.remove(old_path)
                except Exception:
                    pass
            param_pdf.logo = request.FILES['logo_global']
            param_pdf.modifie_par = request.user
            param_pdf.save()
            messages.success(request, "Logo global mis à jour avec succès.")
            return redirect('modele_pdf_config', magasin_id=magasin.id, type_doc=type_doc)

        if request.POST.get('action_logo') == 'supprimer':
            param_pdf = ParametrePDF.get_instance()
            if param_pdf.logo:
                try:
                    old_path = param_pdf.logo.path
                    if os.path.isfile(old_path):
                        os.remove(old_path)
                except Exception:
                    pass
                param_pdf.logo.delete(save=False)
                param_pdf.modifie_par = request.user
                param_pdf.save()
                messages.success(request, "Logo global supprimé.")
            return redirect('modele_pdf_config', magasin_id=magasin.id, type_doc=type_doc)

        # ═══════════════════════════════════════════════════════════════
        # CONFIGURATION DU MODÈLE
        # ═══════════════════════════════════════════════════════════════
        try:
            modele, _ = ModeleDocumentMagasin.objects.get_or_create(
                magasin=magasin,
                type_document=type_doc,
                defaults={
                    'est_actif': True,
                    'config': {},
                    'cree_par': request.user,
                }
            )
        except Exception as e:
            messages.error(request, f"Erreur lors de la creation du modele : {e}.")
            return redirect('accueil_personnalise')

        if request.POST.get('action') == 'apercu':
            return self._generer_apercu(request, magasin, modele)

        config = _parse_post_to_config(request.POST, type_doc=type_doc)
        modele.config = config
        modele.est_actif = True
        modele.modifie_par = request.user
        modele.save()

        messages.success(request, f"Modèle {modele.get_type_document_display()} sauvegardé avec succès pour {magasin.nom}.")
        return redirect('modele_pdf_config', magasin_id=magasin.id, type_doc=type_doc)

    def _generer_apercu(self, request, magasin, modele):
        """Génère un PDF d'aperçu avec des données factices."""
        config_preview = _parse_post_to_config(request.POST, type_doc=modele.type_document)
        # Parité avec pdf_utils : texte institutionnel manquant -> VariableDoesNotExist en DEBUG
        config_preview['texte_institutionnel'] = (
            config_preview.get('texte_institutionnel')
            or (config_preview.get('pied_de_page') or {}).get('texte_personnalise')
            or "Direction des Affaires Financières / Sous-Direction de la Logistique"
        )

        try:
            if not weasyprint:
                messages.error(request, "WeasyPrint n'est pas installé.")
                return redirect('modele_pdf_config', magasin_id=magasin.id, type_doc=modele.type_document)

            template_name = _TEMPLATE_MAP.get(modele.type_document, 'stock/pdf/bon_sortie.html')
            logo_url = _get_logo_url(request)

            service = SimpleNamespace(nom='ORTHO-TRAUMATO-CHIRURGIE PLASTIQUE')
            service_code = '411OTC'
            service_poste = '231'

            if modele.type_document == 'BDM':
                demande_apercu = SimpleNamespace(
                    numero_demande='DEM-APERCU-001',
                    date_demande=timezone.now(),
                    commentaire='Exemple de commentaire pour la demande.',
                )
                lignes_data = [
                    {'idx': 1, 'reference': 'ART-001', 'designation': 'Gants chirurgicaux stériles T7', 'unite': 'Boîte', 'quantite': 10},
                    {'idx': 2, 'reference': 'ART-002', 'designation': 'Compresses stériles 10x10cm', 'unite': 'Sachet', 'quantite': 50},
                ]
                signatures_config = [
                    {'label': 'Le demandeur', 'sous_label': service.nom, 'user_name': 'Jean DUPONT', 'signature_path': None, 'date': timezone.now()},
                    {'label': 'Vu pour exécution', 'sous_label': 'Chef de Service', 'user_name': 'Marie MARTIN', 'signature_path': None, 'date': timezone.now()},
                ]
                context = {
                    'pdf_config': config_preview,
                    'demande': demande_apercu,
                    'lignes_data': lignes_data,
                    'pages': [{'numero': 1, 'lignes': lignes_data, 'est_derniere_page': True}],
                    'est_multi_page': False,
                    'total_qte': sum(l['quantite'] for l in lignes_data),
                    'magasin': magasin,
                    'service': service,
                    'service_code': service_code,
                    'service_poste': service_poste,
                    'signatures_config': signatures_config,
                    'espaceur_mm': 0.0,
                    'logo_url': logo_url,
                    'type_bon_label': "BON DE DEMANDE",
                    'doc_subtitle': "DE MATERIELS ET FOURNITURES",
                    'demandeur_nom': 'Jean DUPONT',
                    'demandeur_fonction': 'Infirmier',
                    'signature_url': None,
                }

            elif modele.type_document == 'BC':
                commande = SimpleNamespace(
                    numero_commande='BC-APERCU-001',
                    date_commande=timezone.now(),
                    objet='Fournitures médicales diverses',
                    delai_livraison='15 jours',
                    date_livraison_prevue=timezone.now(),
                )
                fournisseur = SimpleNamespace(
                    raison_sociale="PHARMA COTE D'IVOIRE",
                    contact='M. KOUAME',
                    telephone='07 XX XX XX XX',
                )
                commande.fournisseur = fournisseur
                lignes_data = [
                    {'idx': 1, 'reference': 'ART-001', 'designation': 'Gants chirurgicaux stériles T7', 'unite': 'Boîte', 'quantite': 100},
                    {'idx': 2, 'reference': 'ART-002', 'designation': 'Compresses stériles 10x10cm', 'unite': 'Sachet', 'quantite': 500},
                ]
                signatures_config = [
                    {'label': 'Demandeur', 'user_name': 'Jean DUPONT', 'signature_path': None, 'date': timezone.now()},
                    {'label': 'Vu pour exécution', 'user_name': 'Marie MARTIN', 'signature_path': None, 'date': timezone.now()},
                ]
                context = {
                    'pdf_config': config_preview,
                    'commande': commande,
                    'magasin': magasin,
                    'lignes_data': lignes_data,
                    'signatures_config': signatures_config,
                    'logo_url': logo_url,
                }

            elif modele.type_document == 'BE':
                bon = SimpleNamespace(
                    numero_bon='BE-APERCU-001',
                    date_bon=timezone.now(),
                    reference_externe='BL-2026-001',
                )
                fournisseur = SimpleNamespace(
                    raison_sociale="PHARMA COTE D'IVOIRE",
                    telephone='07 XX XX XX XX',
                )
                bon.fournisseur = fournisseur
                commande = SimpleNamespace(numero_commande='BC-2026-0001')
                lignes_data = [
                    {'idx': 1, 'reference': 'ART-001', 'designation': 'Gants chirurgicaux stériles T7', 'unite': 'Boîte', 'quantite': 100, 'quantite_recue': 100},
                    {'idx': 2, 'reference': 'ART-002', 'designation': 'Compresses stériles 10x10cm', 'unite': 'Sachet', 'quantite': 500, 'quantite_recue': 500},
                ]
                context = {
                    'pdf_config': config_preview,
                    'bon': bon,
                    'magasin': magasin,
                    'lignes_data': lignes_data,
                    'est_reception_partielle': False,
                    'numero_livraison': None,
                    'commande': commande,
                    'saisisseur_nom': 'Jean DUPONT',
                    'saisisseur_signature': None,
                    'saisisseur_fonction': 'Magasinier',
                    'saisisseur_date': timezone.now(),
                    'logo_url': logo_url,
                }

            elif modele.type_document in ('BR', 'BSHS'):
                bon = SimpleNamespace(
                    numero_bon=f'{modele.type_document}-APERCU-001',
                    date_bon=timezone.now(),
                )
                lignes_data = [
                    {'idx': 1, 'reference': 'ART-001', 'designation': 'Gants chirurgicaux stériles T7', 'unite': 'Boîte', 'quantite': 5},
                    {'idx': 2, 'reference': 'ART-002', 'designation': 'Compresses stériles 10x10cm', 'unite': 'Sachet', 'quantite': 20},
                ]
                signatures_config = [
                    {'label': 'Demandeur', 'user_name': 'Jean DUPONT', 'sous_label': 'Infirmier', 'date': timezone.now()},
                    {'label': 'Responsable', 'user_name': 'Marie MARTIN', 'sous_label': 'Chef de Service', 'date': timezone.now()},
                ]
                if modele.type_document == 'BR':
                    signatures_config.append({'label': 'Magasinier', 'user_name': 'Paul KOUAME', 'sous_label': 'Responsable Stock', 'date': timezone.now()})

                context = {
                    'pdf_config': config_preview,
                    'bon': bon,
                    'magasin': magasin,
                    'service': service,
                    'service_code': service_code,
                    'service_poste': service_poste,
                    'lignes_data': lignes_data,
                    'signatures_config': signatures_config,
                    'logo_url': logo_url,
                }

            else:  # BS (default)
                bon = SimpleNamespace(
                    numero_bon='BS-APERCU-001',
                    date_bon=timezone.now(),
                )
                demande = SimpleNamespace(numero_demande='DEM-2026-0001')
                lignes_data = [
                    {'idx': 1, 'reference': 'ART-001', 'designation': 'Gants chirurgicaux stériles T7', 'unite': 'Boîte', 'quantite': 10, 'quantite_servie': 10, 'numero_lot': 'LOT-2026-A', 'date_peremption': timezone.now(), 'prix_unitaire': Decimal('2500.00')},
                    {'idx': 2, 'reference': 'ART-002', 'designation': 'Compresses stériles 10x10cm', 'unite': 'Sachet', 'quantite': 50, 'quantite_servie': 50, 'numero_lot': 'LOT-2026-B', 'date_peremption': timezone.now(), 'prix_unitaire': Decimal('500.00')},
                ]
                signatures_config = []
                for sig in config_preview.get('signatures', []):
                    if sig.get('visible'):
                        signatures_config.append({
                            'label': sig.get('label', ''),
                            'sous_label': sig.get('role', ''),
                            'position': sig.get('position', 'left'),
                            'style': sig.get('style', 'ligne_pointillee'),
                            'user_name': 'Jean DUPONT',
                            'date': timezone.now(),
                            'signature_path': None,
                        })

                sondage_data = {'satisfaction': 'satisfait', 'observations': 'Délai respecté, matériel conforme.'}

                signature_cases = []
                for sig in config_preview.get('signatures', []):
                    if sig.get('visible'):
                        signature_cases.append({
                            'label': sig.get('label', ''),
                            'has_signature': False,
                            'user_name': 'Jean DUPONT',
                            'signature_path': None,
                            'fonction': sig.get('role', ''),
                            'default_text': '(Signature)',
                            'date': timezone.now(),
                        })

                context = {
                    'pdf_config': config_preview,
                    'bon': bon,
                    'magasin': magasin,
                    'service': service,
                    'service_code': service_code,
                    'service_poste': service_poste,
                    'demande': demande,
                    'lignes_data': lignes_data,
                    'pages': [{'numero': 1, 'lignes': lignes_data, 'est_derniere_page': True}],
                    'est_multi_page': False,
                    'espaceur_mm': 0.0,
                    'total_qte_demandee': sum(l['quantite'] for l in lignes_data),
                    'total_qte_servie': sum(l['quantite_servie'] for l in lignes_data),
                    'signatures_config': signatures_config,
                    'signature_cases': signature_cases,
                    'sondage_data': sondage_data,
                    'est_livraison_partielle': False,
                    'est_cloture': True,
                    'numero_livraison': None,
                    'logo_url': logo_url,
                }

            html_string = render_to_string(template_name, context, request=request)
            try:
                from core.pdf_chromium import html_to_pdf
                pdf_bytes = html_to_pdf(html_string)
            except Exception:
                pdf_bytes = weasyprint.HTML(
                    string=html_string,
                    base_url=request.build_absolute_uri('/')
                ).write_pdf()

            response = HttpResponse(pdf_bytes, content_type='application/pdf')
            filename = f'apercu_{modele.type_document.lower()}.pdf'
            response['Content-Disposition'] = f'inline; filename="{filename}"'
            return response

        except Exception as e:
            logger.exception("[PDF Aperçu] Erreur génération")
            messages.error(request, f"Erreur lors de la génération de l'aperçu : {e}")
            return redirect('modele_pdf_config', magasin_id=magasin.id, type_doc=modele.type_document)
