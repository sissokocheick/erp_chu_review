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
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.contrib import messages
from django.utils import timezone
from django.template.loader import render_to_string
from django.conf import settings
from django.contrib.staticfiles.finders import find

try:
    import weasyprint
    from weasyprint import HTML
except (ImportError, OSError):
    weasyprint = None
    HTML = None

from stock.models import Magasin, ModeleDocumentMagasin

logger = logging.getLogger(__name__)


def _user_peut_configurer_magasin(user, magasin):
    """Vérifie que l'utilisateur a le droit de configurer les modèles PDF.
    
    Tout utilisateur avec la permission menu_modeles_pdf peut configurer
    n'importe quel magasin. Les superusers ont toujours accès.
    """
    if user.is_superuser:
        return True
    return user.has_perm('accounts.menu_modeles_pdf')


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
    # Permet jusqu'à 6 signatures personnalisables pour tous les types de documents
    return 6


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
    if 'cartouche_form_present' in request_post or 'cartouche_afficher_code_iso' in request_post:
        cfg['cartouche']['afficher_code_iso'] = request_post.get('cartouche_afficher_code_iso') == 'on'
    else:
        cfg['cartouche']['afficher_code_iso'] = True
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
    cfg['colonnes_visibles'] = {c['code']: c['visible'] for c in cfg['tableau']['colonnes']}
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
    if 'signatures_form_present' in request_post or 'encadrer_signatures' in request_post:
        cfg['encadrer_signatures'] = request_post.get('encadrer_signatures') == 'on'
    else:
        cfg['encadrer_signatures'] = True

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
    ctx['encadrer_signatures'] = cfg.get('encadrer_signatures', True)
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


def _get_logo_url(request, magasin=None):
    """Retourne l'URL ou data-URI du logo pour les modèles PDF."""
    try:
        from stock.pdf_utils import _static_logo_data_uri, _make_absolute_url
        if magasin and getattr(magasin, 'logo', None):
            try:
                return _make_absolute_url(request, magasin.logo.url)
            except Exception:
                pass
        from core.models import ConfigurationHopital
        hopital = ConfigurationHopital.get_instance()
        if hopital and hopital.logo:
            try:
                return _make_absolute_url(request, hopital.logo.url)
            except Exception:
                pass
        static_logo = _static_logo_data_uri()
        if static_logo:
            return static_logo
    except Exception as e:
        logger.warning(f"[PDF] Erreur récupération logo : {e}")
    return None


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

        return render(request, 'stock/modele_pdf_form.html', form_ctx)

    def post(self, request, magasin_id, type_doc='BS'):
        magasin = get_object_or_404(Magasin, pk=magasin_id)
        if not _user_peut_configurer_magasin(request.user, magasin):
            messages.error(request, "Vous n'avez pas l'autorisation de configurer ce magasin.")
            return redirect('accueil_personnalise')

        # ═══════════════════════════════════════════════════════════════
        # Le logo global n'est plus géré ici, il l'est via ConfigurationHopital
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

    def _generer_apercu(self, request, magasin, modele, override_config=None):
        """Génère un PDF d'aperçu avec des données factices."""
        base_config = modele.get_config_complete()
        if override_config is not None:
            config_preview = ModeleDocumentMagasin._deep_merge(base_config, override_config)
        elif request.method == 'POST' and request.POST:
            posted_config = _parse_post_to_config(request.POST, type_doc=modele.type_document)
            config_preview = ModeleDocumentMagasin._deep_merge(base_config, posted_config)
        else:
            config_preview = base_config

        # Parité avec pdf_utils : texte institutionnel centralisé depuis l'établissement
        from core.models import ConfigurationHopital
        hopital = ConfigurationHopital.objects.first()
        hopital_pied = (getattr(hopital, 'pied_page_pdf', None) or '').strip() if hopital else ''

        pied = config_preview.get('pied_de_page') or {}
        if not isinstance(pied, dict):
            pied = {'texte_personnalise': str(pied)}
            config_preview['pied_de_page'] = pied

        texte_pied_final = hopital_pied or (pied.get('texte_personnalise') or '').strip() or "Direction des Affaires Financières / Sous-Direction de la Logistique"
        pied['texte_personnalise'] = texte_pied_final
        config_preview['texte_institutionnel'] = texte_pied_final

        # Métadonnées et cartouche pour les templates
        meta = config_preview.get('metadonnees') or {}
        if not isinstance(meta, dict):
            meta = {}
            config_preview['metadonnees'] = meta

        cart = config_preview.get('cartouche') or {}
        if not isinstance(cart, dict):
            cart = {}
            config_preview['cartouche'] = cart
        if 'afficher_code_iso' not in cart:
            cart['afficher_code_iso'] = True

        config_preview['code_document'] = meta.get('code_document') or config_preview.get('code_document', '')
        config_preview['date_creation_doc'] = meta.get('date_creation_doc') or config_preview.get('date_creation_doc', '')
        config_preview['date_revision_doc'] = meta.get('date_revision_doc') or config_preview.get('date_revision_doc', '')
        config_preview['version_doc'] = meta.get('version_doc') or config_preview.get('version_doc', '')
        config_preview['ps2_label'] = meta.get('ps2_label') or config_preview.get('ps2_label', '')

        meta['code_document'] = config_preview['code_document']
        meta['date_creation_doc'] = config_preview['date_creation_doc']
        meta['date_revision_doc'] = config_preview['date_revision_doc']
        meta['version_doc'] = config_preview['version_doc']
        meta['ps2_label'] = config_preview['ps2_label']

        # Construction universelle des cases de signatures pour l'aperçu
        signature_cases = []
        mock_signataires = [
            ('Jean DUPONT', 'Magasinier'),
            ('Marie MARTIN', 'Chef de Service'),
            ('Paul KOUAME', 'Sous-Directeur Logistique'),
            ('Dr. KOUASSI', 'Directeur DAF'),
            ('A. TRAORE', 'Contrôleur'),
            ('Direction Générale', 'Directeur Général'),
        ]

        cfg_signatures = config_preview.get('signatures') or []
        for i, sig in enumerate(cfg_signatures):
            if sig.get('visible', True):
                label = sig.get('label') or sig.get('role') or f'Signature #{i+1}'
                role = sig.get('role', '')
                mock_nom, mock_fct = mock_signataires[min(i, len(mock_signataires) - 1)]
                fonction = role.replace('_', ' ').capitalize() if role else mock_fct
                case = {
                    'label': label,
                    'role': role,
                    'user_name': mock_nom,
                    'has_signature': False,
                    'signature_path': None,
                    'fonction': fonction if config_preview.get('afficher_fonction_signataire', True) else '',
                    'default_text': '(Signature)',
                    'date': timezone.now(),
                    'position': sig.get('position', 'left'),
                    'style': sig.get('style', 'ligne_pointillee'),
                }
                signature_cases.append(case)

        # Assurer que colonnes_visibles est injecté pour les templates
        if 'colonnes_visibles' not in config_preview or not config_preview['colonnes_visibles']:
            colonnes_cfg = (config_preview.get('tableau') or {}).get('colonnes') or []
            if colonnes_cfg:
                config_preview['colonnes_visibles'] = {
                    c['code']: c.get('visible', True)
                    for c in colonnes_cfg
                    if isinstance(c, dict) and 'code' in c
                }
            else:
                all_cols = _colonnes_par_type(modele.type_document)
                config_preview['colonnes_visibles'] = {c['code']: True for c in all_cols}

        try:
            template_name = _TEMPLATE_MAP.get(modele.type_document, 'stock/pdf/bon_sortie.html')
            logo_url = _get_logo_url(request, magasin=magasin)

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
                    {'idx': 1, 'reference': 'ART-001', 'designation': 'Gants chirurgicaux stériles T7', 'unite': 'Boîte', 'quantite': 10, 'numero_lot': 'LOT-2026-A', 'date_peremption': timezone.now(), 'prix_unitaire': Decimal('2500.00'), 'montant': Decimal('25000.00')},
                    {'idx': 2, 'reference': 'ART-002', 'designation': 'Compresses stériles 10x10cm', 'unite': 'Sachet', 'quantite': 50, 'numero_lot': 'LOT-2026-B', 'date_peremption': timezone.now(), 'prix_unitaire': Decimal('500.00'), 'montant': Decimal('25000.00')},
                ]
                pages = [{'numero': 1, 'lignes': lignes_data, 'est_derniere_page': True, 'hauteur_ligne': '12.00'}]
                context = {
                    'pdf_config': config_preview,
                    'demande': demande_apercu,
                    'lignes_data': lignes_data,
                    'pages': pages,
                    'est_multi_page': False,
                    'total_qte': sum(l['quantite'] for l in lignes_data),
                    'magasin': magasin,
                    'service': service,
                    'service_code': service_code,
                    'service_poste': service_poste,
                    'signatures_config': signature_cases,
                    'signature_cases': signature_cases,
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
                    {'idx': 1, 'reference': 'ART-001', 'designation': 'Gants chirurgicaux stériles T7', 'unite': 'Boîte', 'quantite': 100, 'prix_unitaire': Decimal('2500.00'), 'montant': Decimal('250000.00')},
                    {'idx': 2, 'reference': 'ART-002', 'designation': 'Compresses stériles 10x10cm', 'unite': 'Sachet', 'quantite': 500, 'prix_unitaire': Decimal('500.00'), 'montant': Decimal('250000.00')},
                ]
                pages = [{'numero': 1, 'lignes': lignes_data, 'est_derniere_page': True, 'hauteur_ligne': '12.00'}]
                context = {
                    'pdf_config': config_preview,
                    'commande': commande,
                    'magasin': magasin,
                    'lignes_data': lignes_data,
                    'pages': pages,
                    'est_multi_page': False,
                    'total_qte': sum(l['quantite'] for l in lignes_data),
                    'signatures_config': signature_cases,
                    'signature_cases': signature_cases,
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
                    {'idx': 1, 'reference': 'ART-001', 'designation': 'Gants chirurgicaux stériles T7', 'unite': 'Boîte', 'quantite': 100, 'quantite_recue': 100, 'numero_lot': 'LOT-2026-A', 'date_peremption': timezone.now(), 'prix_unitaire': Decimal('2500.00'), 'montant': Decimal('250000.00')},
                    {'idx': 2, 'reference': 'ART-002', 'designation': 'Compresses stériles 10x10cm', 'unite': 'Sachet', 'quantite': 500, 'quantite_recue': 500, 'numero_lot': 'LOT-2026-B', 'date_peremption': timezone.now(), 'prix_unitaire': Decimal('500.00'), 'montant': Decimal('250000.00')},
                ]
                pages = [{'numero': 1, 'lignes': lignes_data, 'est_derniere_page': True, 'hauteur_ligne': '12.00'}]
                context = {
                    'pdf_config': config_preview,
                    'bon': bon,
                    'magasin': magasin,
                    'lignes_data': lignes_data,
                    'pages': pages,
                    'est_multi_page': False,
                    'est_reception_partielle': False,
                    'numero_livraison': None,
                    'commande': commande,
                    'a_lots': True,
                    'signatures_config': signature_cases,
                    'signature_cases': signature_cases,
                    'total_qte': sum(l['quantite'] for l in lignes_data),
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
                    {'idx': 1, 'reference': 'ART-001', 'designation': 'Gants chirurgicaux stériles T7', 'unite': 'Boîte', 'quantite': 5, 'numero_lot': 'LOT-2026-A', 'date_peremption': timezone.now(), 'prix_unitaire': Decimal('2500.00'), 'montant': Decimal('12500.00')},
                    {'idx': 2, 'reference': 'ART-002', 'designation': 'Compresses stériles 10x10cm', 'unite': 'Sachet', 'quantite': 20, 'numero_lot': 'LOT-2026-B', 'date_peremption': timezone.now(), 'prix_unitaire': Decimal('500.00'), 'montant': Decimal('10000.00')},
                ]
                pages = [{'numero': 1, 'lignes': lignes_data, 'est_derniere_page': True, 'hauteur_ligne': '12.00'}]
                context = {
                    'pdf_config': config_preview,
                    'bon': bon,
                    'magasin': magasin,
                    'service': service,
                    'service_code': service_code,
                    'service_poste': service_poste,
                    'lignes_data': lignes_data,
                    'pages': pages,
                    'est_multi_page': False,
                    'a_lots': True,
                    'total_qte': sum(l['quantite'] for l in lignes_data),
                    'signatures_config': signature_cases,
                    'signature_cases': signature_cases,
                    'logo_url': logo_url,
                }

            else:  # BS (default)
                bon = SimpleNamespace(
                    numero_bon='BS-APERCU-001',
                    date_bon=timezone.now(),
                )
                demande = SimpleNamespace(numero_demande='DEM-2026-0001')
                lignes_data = [
                    {'idx': 1, 'reference': 'ART-001', 'designation': 'Gants chirurgicaux stériles T7', 'unite': 'Boîte', 'quantite': 10, 'quantite_servie': 10, 'numero_lot': 'LOT-2026-A', 'date_peremption': timezone.now(), 'prix_unitaire': Decimal('2500.00'), 'montant': Decimal('25000.00')},
                    {'idx': 2, 'reference': 'ART-002', 'designation': 'Compresses stériles 10x10cm', 'unite': 'Sachet', 'quantite': 50, 'quantite_servie': 50, 'numero_lot': 'LOT-2026-B', 'date_peremption': timezone.now(), 'prix_unitaire': Decimal('500.00'), 'montant': Decimal('25000.00')},
                ]
                sondage_data = {'satisfaction': 'satisfait', 'observations': 'Délai respecté, matériel conforme.'}
                pages = [{'numero': 1, 'lignes': lignes_data, 'est_derniere_page': True, 'hauteur_ligne': '12.00'}]

                context = {
                    'pdf_config': config_preview,
                    'bon': bon,
                    'magasin': magasin,
                    'service': service,
                    'service_code': service_code,
                    'service_poste': service_poste,
                    'demande': demande,
                    'lignes_data': lignes_data,
                    'pages': pages,
                    'est_multi_page': False,
                    'a_lots': True,
                    'espaceur_mm': 0.0,
                    'total_qte_demandee': sum(l['quantite'] for l in lignes_data),
                    'total_qte_servie': sum(l['quantite_servie'] for l in lignes_data),
                    'total_qte': sum(l['quantite_servie'] for l in lignes_data),
                    'signatures_config': signature_cases,
                    'signature_cases': signature_cases,
                    'sondage_data': sondage_data,
                    'est_livraison_partielle': False,
                    'est_cloture': True,
                    'numero_livraison': None,
                    'logo_url': logo_url,
                }

            html_string = render_to_string(template_name, context, request=request)
            pdf_bytes = None

            # 1. Tentative avec Chromium (Playwright) si disponible
            try:
                from core.pdf_chromium import html_to_pdf
                pdf_bytes = html_to_pdf(html_string)
            except Exception as e_chrom:
                logger.debug(f"[PDF Aperçu] Chromium indisponible ({e_chrom}), tentative WeasyPrint")

            # 2. Tentative avec WeasyPrint si Chromium échoue ou est absent
            if pdf_bytes is None and HTML is not None:
                try:
                    pdf_bytes = HTML(
                        string=html_string,
                        base_url=request.build_absolute_uri('/')
                    ).write_pdf()
                except Exception as e_wp:
                    logger.warning(f"[PDF Aperçu] WeasyPrint a échoué ({e_wp}), repli ReportLab")

            # 3. Secours universel avec ReportLab si aucun moteur HTML->PDF n'est prêt
            if pdf_bytes is None:
                from stock.pdf_utils import _pdf_fallback
                pdf_bytes = _pdf_fallback(context, html_string)

            response = HttpResponse(pdf_bytes, content_type='application/pdf')
            filename = f'apercu_{modele.type_document.lower()}.pdf'
            response['Content-Disposition'] = f'inline; filename="{filename}"'
            response['X-Frame-Options'] = 'SAMEORIGIN'
            return response

        except Exception as e:
            logger.exception("[PDF Aperçu] Erreur génération")
            if request.headers.get('x-requested-with') == 'XMLHttpRequest' or request.headers.get('X-Requested-With') == 'XMLHttpRequest':
                return HttpResponse(f"Erreur lors de la génération de l'aperçu : {e}", status=500, content_type='text/plain; charset=utf-8')
            messages.error(request, f"Erreur lors de la génération de l'aperçu : {e}")
            return redirect('modele_pdf_config', magasin_id=magasin.id, type_doc=modele.type_document)


@method_decorator(login_required, name='dispatch')
class ModelePDFApercuView(LoginRequiredMixin, UserPassesTestMixin, View):
    """Génère l'aperçu PDF sous forme d'URL HTTP directe compatible avec les iframes (Brave, Chrome, Firefox)."""

    def test_func(self):
        magasin = get_object_or_404(Magasin, pk=self.kwargs['magasin_id'])
        return _user_peut_configurer_magasin(self.request.user, magasin)

    def post(self, request, magasin_id, type_doc='BS'):
        """Stocke temporairement en session la configuration éditée et renvoie l'URL de chargement HTTP."""
        magasin = get_object_or_404(Magasin, pk=magasin_id)
        config_preview = _parse_post_to_config(request.POST, type_doc=type_doc)
        session_key = f'pdf_preview_{magasin.id}_{type_doc}'
        request.session[session_key] = config_preview
        request.session.modified = True

        preview_url = reverse('modele_pdf_apercu', kwargs={'magasin_id': magasin.id, 'type_doc': type_doc})
        ts = int(timezone.now().timestamp())
        return JsonResponse({'ok': True, 'url': f"{preview_url}?_t={ts}"})

    def get(self, request, magasin_id, type_doc='BS'):
        """Retourne le flux PDF directement en réponse HTTP avec en-têtes SAMEORIGIN."""
        magasin = get_object_or_404(Magasin, pk=magasin_id)
        modele = ModeleDocumentMagasin.objects.filter(magasin=magasin, type_document=type_doc).first()
        if not modele:
            modele = ModeleDocumentMagasin(magasin=magasin, type_document=type_doc)

        session_key = f'pdf_preview_{magasin.id}_{type_doc}'
        config_override = request.session.get(session_key)

        view_config = ModelePDFConfigView()
        return view_config._generer_apercu(request, magasin, modele, override_config=config_override)
