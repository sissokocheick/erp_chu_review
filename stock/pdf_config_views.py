# stock/pdf_config_views.py
# Views pour configurer les modèles de documents PDF par magasin

import json
import logging
from decimal import Decimal
from types import SimpleNamespace

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.mixins import LoginRequiredMixin, UserPassesTestMixin
from django.views import View
from django.http import HttpResponse, JsonResponse
from django.utils.decorators import method_decorator
from django.contrib import messages
from django.utils import timezone
from django.template.loader import render_to_string

try:
    import weasyprint
except ImportError:
    weasyprint = None

from stock.models import Magasin, ModeleDocumentMagasin, BonMouvement, Article
from accounts.models import Entreprise

logger = logging.getLogger(__name__)


def _user_peut_configurer_magasin(user, magasin):
    """
    Vérifie que l'utilisateur a le droit de configurer ce magasin.
    """
    # Superuser = accès total
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
    # Default = BS (et tous les autres mouvements)
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
    """Nombre max de signatures selon le type de document."""
    mapping = {
        'BDM': 2,  # Bon de Demande : Demandeur + Chef
        'BS': 4,   # Bon de Sortie : 4 cases
        'BE': 2,   # Bon d'Entrée : Magasinier + Responsable
        'BR': 3,   # Bon de Retour : Demandeur + Responsable + Magasinier
        'BSHS': 2, # Hors Stock : Demandeur + Magasinier
        'BC': 2,   # Commande : Demandeur + Vu pour exécution
    }
    return mapping.get(type_doc, 4)


def _parse_post_to_config(request_post, type_doc='BS'):
    """Transforme les données POST du formulaire en dict JSON structuré.

    Adapte automatiquement les colonnes, signatures et options selon type_doc.
    """
    cfg = {
        'cartouche': {},
        'tableau': {},
        'signatures': [],
        'sondage': {},
        'pied_de_page': {},
        'metadonnees': {},
        'service_demandeur': {},
    }

    # ── CARTOUCHE (commun à tous) ──
    for key in [
        'afficher_logo', 'afficher_republique', 'afficher_devise',
        'afficher_direction', 'afficher_sous_direction', 'afficher_service',
        'afficher_telephone', 'afficher_cc', 'afficher_ifu',
        'afficher_rccm', 'afficher_code_iso'
    ]:
        cfg['cartouche'][key] = request_post.get(f'cartouche_{key}') == 'on'
    cfg['cartouche']['position_logo'] = request_post.get('cartouche_position_logo', 'left')
    cfg['cartouche']['trait_separation_epaisseur'] = int(request_post.get('cartouche_trait_separation_epaisseur', 1) or 1)
    cfg['cartouche']['trait_separation_couleur'] = request_post.get('cartouche_trait_separation_couleur', '#000000')

    # ── TABLEAU (spécifique au type) ──
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

    # ── SIGNATURES (max adaptatif selon type_doc) ──
    max_sig = _nb_signatures_max(type_doc)
    for i in range(1, max_sig + 1):
        prefix = f'signatures_{i}'
        if request_post.get(f'{prefix}_label'):
            cfg['signatures'].append({
                'ordre': i,
                'role': request_post.get(f'{prefix}_role', ''),
                'label': request_post.get(f'{prefix}_label', ''),
                'visible': request_post.get(f'{prefix}_visible') == 'on',
                'position': request_post.get(f'{prefix}_position', 'left'),
                'style': request_post.get(f'{prefix}_style', 'ligne_pointillee'),
                'condition': request_post.get(f'{prefix}_condition', 'toujours'),
            })

    # ── SERVICE DEMANDEUR (uniquement pour BS, BR, BSHS) ──
    if type_doc in ('BS', 'BR', 'BSHS'):
        cfg['service_demandeur'] = {
            'encadrer': request_post.get('service_demandeur_encadrer') == 'on',
            'position': request_post.get('service_demandeur_position', 'left'),
        }

    # ── SONDAGE (uniquement pour BS) ──
    if type_doc == 'BS':
        cfg['sondage']['afficher'] = request_post.get('sondage_afficher') == 'on'
        cfg['sondage']['trait_separation'] = request_post.get('sondage_trait_separation') == 'on'
        cfg['sondage']['style_cases'] = request_post.get('sondage_style_cases') == 'on'

    # ── PIED DE PAGE (commun) ──
    cfg['pied_de_page']['texte_personnalise'] = request_post.get('pied_de_page_texte_personnalise', '')
    cfg['pied_de_page']['afficher_numero_page'] = request_post.get('pied_de_page_afficher_numero_page') == 'on'
    cfg['pied_de_page']['afficher_date_generation'] = request_post.get('pied_de_page_afficher_date_generation') == 'on'
    cfg['pied_de_page']['afficher_trait_couleur'] = request_post.get('pied_de_page_afficher_trait_couleur') == 'on'
    cfg['pied_de_page']['trait_couleur'] = request_post.get('pied_de_page_trait_couleur', '#17a2b8')

    # ── MÉTADONNÉES (commun) ──
    cfg['metadonnees']['code_document'] = request_post.get('metadonnees_code_document', '')
    cfg['metadonnees']['date_creation_doc'] = request_post.get('metadonnees_date_creation_doc', '')
    cfg['metadonnees']['date_revision_doc'] = request_post.get('metadonnees_date_revision_doc', '')
    cfg['metadonnees']['version_doc'] = request_post.get('metadonnees_version_doc', '')
    cfg['metadonnees']['ps2_label'] = request_post.get('metadonnees_ps2_label', '')

    # ── Labels direction (commun) ──
    cfg['direction_label'] = request_post.get('direction_label', '')
    cfg['sous_direction_label'] = request_post.get('sous_direction_label', '')
    cfg['service_label'] = request_post.get('service_label', '')
    cfg['couleur_principale'] = request_post.get('couleur_principale', '#1c5b96')

    return cfg


def _config_to_form_context(cfg):
    """Aplatit le dict JSON en variables de template pour pré-remplir le formulaire."""
    ctx = {}
    # Cartouche
    for k, v in cfg.get('cartouche', {}).items():
        ctx[f'cartouche_{k}'] = v
    # Tableau
    for k, v in cfg.get('tableau', {}).items():
        if k == 'colonnes':
            ctx['tableau_colonnes'] = [c['code'] for c in v if c.get('visible', False)]
        else:
            ctx[f'tableau_{k}'] = v
    # Signatures
    for sig in cfg.get('signatures', []):
        i = sig['ordre']
        for k, v in sig.items():
            ctx[f'signatures_{i}_{k}'] = v
    # Sondage
    for k, v in cfg.get('sondage', {}).items():
        ctx[f'sondage_{k}'] = v
    # Service demandeur
    for k, v in cfg.get('service_demandeur', {}).items():
        ctx[f'service_demandeur_{k}'] = v
    # Pied de page
    for k, v in cfg.get('pied_de_page', {}).items():
        ctx[f'pied_de_page_{k}'] = v
    # Métadonnées
    for k, v in cfg.get('metadonnees', {}).items():
        ctx[f'metadonnees_{k}'] = v
    # Labels globaux
    ctx['direction_label'] = cfg.get('direction_label', '')
    ctx['sous_direction_label'] = cfg.get('sous_direction_label', '')
    ctx['service_label'] = cfg.get('service_label', '')
    ctx['couleur_principale'] = cfg.get('couleur_principale', '#1c5b96')
    return ctx


_LEGACY_MAP = {
    'BS': 'BON_SORTIE',
    'BE': 'BON_ENTREE',
    'BR': 'BON_RETOUR',
    'BSHS': 'BON_HS',
    'BC': 'COMMANDE',
    'BDM': 'DEMANDE',
}


@method_decorator(login_required, name='dispatch')
class ModelePDFConfigView(LoginRequiredMixin, UserPassesTestMixin, View):
    # Permission gérée par test_func + _user_peut_configurer_magasin

    def test_func(self):
        magasin = get_object_or_404(Magasin, pk=self.kwargs['magasin_id'])
        return _user_peut_configurer_magasin(self.request.user, magasin)

    def get(self, request, magasin_id, type_doc='BS'):
        magasin = get_object_or_404(Magasin, pk=magasin_id)
        if not _user_peut_configurer_magasin(request.user, magasin):
            messages.error(request, "Vous n'avez pas l'autorisation de configurer ce magasin.")
            return redirect('accueil_personnalise')

        # Récupérer ou créer le modèle
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

        # Construire le contexte du formulaire
        config_complete = modele.get_config_complete(type_doc_legacy=_LEGACY_MAP.get(type_doc, 'BON_SORTIE'))
        form_ctx = _config_to_form_context(config_complete)
        form_ctx['magasin'] = magasin
        form_ctx['type_doc'] = type_doc
        form_ctx['type_doc_label'] = modele.get_type_document_display()
        form_ctx['modele'] = modele
        form_ctx['nb_signatures_max'] = _nb_signatures_max(type_doc)

        return render(request, 'stock/modele_pdf_form.html', form_ctx)

    def post(self, request, magasin_id, type_doc='BS'):
        magasin = get_object_or_404(Magasin, pk=magasin_id)
        if not _user_peut_configurer_magasin(request.user, magasin):
            messages.error(request, "Vous n'avez pas l'autorisation de configurer ce magasin.")
            return redirect('accueil_personnalise')

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
            return redirect('accounts:accueil_personnalise')

        # Si c'est un aperçu
        if request.POST.get('action') == 'apercu':
            return self._generer_apercu(request, magasin, modele)

        # Sinon : sauvegarde
        config = _parse_post_to_config(request.POST, type_doc=type_doc)
        modele.config = config
        modele.est_actif = True
        modele.modifie_par = request.user
        modele.save()

        messages.success(request, f"Modèle {modele.get_type_document_display()} sauvegardé avec succès pour {magasin.nom}.")
        return redirect('modele_pdf_config', magasin_id=magasin.id, type_doc=type_doc)

    def _generer_apercu(self, request, magasin, modele):
        """Génère un PDF d'aperçu avec des données factices (squelette).

        ✅ CORRECTION : Plus d'écriture en base de données.
        La config preview est passée directement au contexte du template.
        """
        config_preview = _parse_post_to_config(request.POST, type_doc=modele.type_document)

        try:
            if not weasyprint:
                messages.error(request, "WeasyPrint n'est pas installé.")
                return redirect('modele_pdf_config', magasin_id=magasin.id, type_doc=modele.type_document)

            # ═══════════════════════════════════════════════════════════
            # SQUELETTE : données factices selon le type de document
            # ═══════════════════════════════════════════════════════════

            if modele.type_document == 'BDM':
                # ── Squelette Bon de Demande ──
                demande_apercu = SimpleNamespace(
                    numero_demande='DEM-APERCU-001',
                    date_demande=timezone.now(),
                    commentaire='Exemple de commentaire pour la demande.',
                )
                service = SimpleNamespace(nom='ORTHO-TRAUMATO-CHIRURGIE PLASTIQUE')
                service_code = '411OTC'
                service_poste = '231'

                lignes_data = [
                    {
                        'idx': 1,
                        'reference': 'ART-001',
                        'designation': 'Gants chirurgicaux stériles T7',
                        'unite': 'Boîte',
                        'quantite': 10,
                    },
                    {
                        'idx': 2,
                        'reference': 'ART-002',
                        'designation': 'Compresses stériles 10x10cm',
                        'unite': 'Sachet',
                        'quantite': 50,
                    },
                ]

                signatures_config = [
                    {
                        'label': 'Le demandeur',
                        'sous_label': service.nom,
                        'user_name': 'Jean DUPONT',
                        'signature_path': None,
                        'date': timezone.now(),
                    },
                    {
                        'label': 'Vu pour exécution',
                        'sous_label': 'Chef de Service',
                        'user_name': 'Marie MARTIN',
                        'signature_path': None,
                        'date': timezone.now(),
                    },
                ]

                try:
                    from core.pdf_pagination import paginer_bon_sortie
                    pagination_result = paginer_bon_sortie(lignes_data, config_preview)
                    pages = [
                        {
                            'numero': p.numero,
                            'lignes': p.lignes,
                            'est_derniere_page': p.est_derniere_page,
                            'espaceur_rows': list(range(p.espaceur_lignes)),
                        }
                        for p in pagination_result.pages
                    ]
                    est_multi_page = pagination_result.est_multi_page
                    espaceur_mm = pagination_result.espaceur_mm
                except ImportError:
                    pages = [{'numero': 1, 'lignes': lignes_data, 'est_derniere_page': True}]
                    est_multi_page = False
                    espaceur_mm = 0.0

                context = {
                    'pdf_config': config_preview,
                    'demande': demande_apercu,
                    'lignes_data': lignes_data,
                    'pages': pages,
                    'est_multi_page': est_multi_page,
                    'total_qte': sum(l['quantite'] for l in lignes_data),
                    'magasin': magasin,
                    'service': service,
                    'service_code': service_code,
                    'service_poste': service_poste,
                    'signatures_config': signatures_config,
                    'espaceur_mm': espaceur_mm,
                    'entreprise': magasin.entreprise,
                    'logo_url': None,
                    'type_bon_label': "BON DE DEMANDE",
                    'doc_subtitle': "DE MATERIELS ET FOURNITURES",
                }
                template_name = 'stock/pdf/bon_demande.html'

            else:
                # ── Squelette Bon de Sortie (et autres mouvements) ──
                bon = SimpleNamespace(
                    numero_bon='BS-APERCU-001',
                    date_bon=timezone.now(),
                )

                service = SimpleNamespace(nom='ORTHO-TRAUMATO-CHIRURGIE PLASTIQUE')
                service_code = '411OTC'
                service_poste = '231'
                demande = SimpleNamespace(numero_demande='DEM-2026-0001')

                lignes_data = [
                    {
                        'idx': 1,
                        'reference': 'ART-001',
                        'designation': 'Gants chirurgicaux stériles T7',
                        'unite': 'Boîte',
                        'quantite': 10,
                        'quantite_servie': 10,
                        'numero_lot': 'LOT-2026-A',
                        'date_peremption': timezone.now(),
                        'prix_unitaire': Decimal('2500.00'),
                    },
                    {
                        'idx': 2,
                        'reference': 'ART-002',
                        'designation': 'Compresses stériles 10x10cm',
                        'unite': 'Sachet',
                        'quantite': 50,
                        'quantite_servie': 50,
                        'numero_lot': 'LOT-2026-B',
                        'date_peremption': timezone.now(),
                        'prix_unitaire': Decimal('500.00'),
                    },
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

                sondage_data = {
                    'satisfaction': 'satisfait',
                    'observations': 'Délai respecté, matériel conforme.',
                }

                try:
                    from core.pdf_pagination import paginer_bon_sortie
                    pagination_result = paginer_bon_sortie(lignes_data, config_preview)
                    pages = [
                        {
                            'numero': p.numero,
                            'lignes': p.lignes,
                            'est_derniere_page': p.est_derniere_page,
                            'espaceur_rows': list(range(p.espaceur_lignes)),
                        }
                        for p in pagination_result.pages
                    ]
                    est_multi_page = pagination_result.est_multi_page
                    espaceur_mm = pagination_result.espaceur_mm
                except ImportError:
                    pages = [{'numero': 1, 'lignes': lignes_data, 'est_derniere_page': True}]
                    est_multi_page = False
                    espaceur_mm = 0.0

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
                    'est_multi_page': est_multi_page,
                    'espaceur_mm': espaceur_mm,
                    'total_qte_demandee': sum(l['quantite'] for l in lignes_data),
                    'total_qte_servie': sum(l['quantite_servie'] for l in lignes_data),
                    'signatures_config': signatures_config,
                    'sondage_data': sondage_data,
                    'entreprise': magasin.entreprise,
                    'logo_url': None,
                }
                template_name = 'stock/pdf/bon_sortie.html'

            html_string = render_to_string(template_name, context, request=request)
            # Essayer Chromium/Playwright en priorite, fallback WeasyPrint
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
