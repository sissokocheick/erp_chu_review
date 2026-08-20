# -*- coding: utf-8 -*-
# core/pdf_service.py — CORRIGÉ (mono-tenant v1)
import functools
import os
import base64
import copy
import logging
from decimal import Decimal

from django.template.loader import render_to_string
from django.utils import timezone

from weasyprint import HTML

try:
    from core.pdf_pagination import paginer_bon_sortie, pt_to_mm
except ImportError:
    paginer_bon_sortie = None
    pt_to_mm = None

logger = logging.getLogger(__name__)


class DocumentGenerator:
    def __init__(self, request=None):
        self.request = request
        # Mono-tenant : la configuration est toujours l'unique singleton
        # ConfigurationHopital (ex-modèle de tenant supprimé).
        from core.models import ConfigurationHopital
        self.config = ConfigurationHopital.get_instance()

    @staticmethod
    @functools.lru_cache(maxsize=128)
    def _img_url_cached(path: str, mtime: float) -> str:
        if not path or not os.path.exists(path):
            logger.warning(f"[PDF] Image introuvable sur le disque : {path}")
            return ""
        ext = os.path.splitext(path)[1].lower()
        mime = {
            '.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
            '.gif': 'image/gif', '.webp': 'image/webp', '.bmp': 'image/bmp',
        }.get(ext, 'image/png')
        try:
            with open(path, 'rb') as fimg:
                data = base64.b64encode(fimg.read()).decode('ascii')
            logger.debug(f"[PDF] Logo encodé base64 OK ({len(data)} chars)")
            return f"data:{mime};base64,{data}"
        except Exception as e:
            logger.warning(f"[PDF] Base64 échoué pour {path} : {e}")
        try:
            from pathlib import Path
            uri = Path(path).as_uri()
            return uri
        except Exception as e:
            logger.warning(f"[PDF] URI fichier échoué pour {path} : {e}")
        return ""


    def _get_logo_url(self):
        """Retourne le logo depuis ConfigurationHopital."""
        if self.config and hasattr(self.config, 'logo') and self.config.logo:
            return self._img_url(self.config.logo)
        return ''
        for attr in ('code', 'numero', 'numero_service', 'reference'):
            if hasattr(service_obj, attr):
                val = getattr(service_obj, attr)
                if val:
                    return str(val)
        return ''

    def bon_sortie(self, bon, extra_context=None):
        from stock.models import LivraisonPartielle, AccuseReception
        from django.contrib.auth.models import User

        lignes_brutes = list(bon.lignes_bon.select_related('article__famille').all())
        lignes_data = []
        total_qte_demandee = 0
        total_qte_servie = 0

        livraison = LivraisonPartielle.objects.filter(bon_sortie=bon).first()
        demande = self._resolve_demande(bon, livraison)

        qte_demandee_par_article = {}
        if livraison and hasattr(livraison, 'lignes_livraison'):
            for ll in livraison.lignes_livraison.all():
                qte_demandee_par_article[ll.article_id] = ll.quantite_demandee

        if not qte_demandee_par_article and demande and hasattr(demande, 'lignes_demande'):
            for ld in demande.lignes_demande.all():
                qte_demandee_par_article[ld.article_id] = ld.quantite_demandee

        for idx, l in enumerate(lignes_brutes, 1):
            qte_servie = l.quantite
            qte_demandee = qte_demandee_par_article.get(l.article_id, qte_servie)

            if hasattr(l, 'ligne_livraison') and l.ligne_livraison and getattr(l.ligne_livraison, 'quantite_demandee', None):
                qte_demandee = l.ligne_livraison.quantite_demandee
            elif hasattr(l, 'ligne_demande') and l.ligne_demande and getattr(l.ligne_demande, 'quantite_demandee', None):
                qte_demandee = l.ligne_demande.quantite_demandee

            reste = max(0, qte_demandee - qte_servie)
            lignes_data.append({
                'idx': idx,
                'reference': l.article.reference,
                'designation': l.article.designation,
                'unite': l.article.unite_distribution,
                'quantite': qte_demandee,
                'quantite_servie': qte_servie,
                'reste': reste,
                'numero_lot': getattr(l, 'numero_lot', None) or '',
                'date_peremption': getattr(l, 'date_peremption', None),
                'prix_unitaire': l.prix_unitaire,
            })
            total_qte_demandee += qte_demandee
            total_qte_servie += qte_servie

        accuse = None
        sondage_data = None
        if livraison:
            try:
                accuse = livraison.accuse
                if accuse and accuse.est_signe:
                    sondage_data = {
                        'satisfaction': 'satisfait' if accuse.satisfait is True else ('insatisfait' if accuse.satisfait is False else 'passable'),
                        'observations': accuse.observations or '',
                    }
            except AccuseReception.DoesNotExist:
                pass

        config = self._get_pdf_config(type_doc='BON_SORTIE', magasin=bon.magasin)
        _sig = self._user_signature

        chef_service = None
        emission_date = None
        if demande:
            chef_service = getattr(demande, 'cree_par', None) or getattr(demande, 'demandeur', None)
            emission_date = getattr(demande, 'date_creation', None) or getattr(demande, 'date_demande', None)
        if not chef_service:
            chef_service = getattr(bon, 'cree_par', None)
            emission_date = getattr(bon, 'date_bon', None) or getattr(bon, 'date_creation', None)

        vu_par = None
        validation_date = None
        if getattr(bon, 'statut_validation', None) == 'VALIDE' and bon.valide_par:
            vu_par = bon.valide_par
            validation_date = getattr(bon, 'date_validation', None)

        magasinier = bon.cree_par
        if not magasinier:
            logger.warning(f"[PDF] Bon {bon.pk}: cree_par est None — case 'SORTIE EFFECTUÉE' sera vide")
        sortie_date = getattr(bon, 'date_bon', None)

        receptionnaire = None
        reception_date = None
        if accuse and getattr(accuse, 'est_signe', False):
            receptionnaire = getattr(accuse, 'receptionne_par', None)
            reception_date = getattr(accuse, 'date_reception', None)

        emission_nom = self._get_user_name(chef_service) if chef_service else None
        emission_fonction = self._get_user_fonction(chef_service, "")
        emission_sig = _sig(chef_service)
        emission_has_sig = bool(emission_sig)

        vu_nom = self._get_user_name(vu_par) if vu_par else None
        vu_fonction = self._get_user_fonction(vu_par, "")
        vu_sig = _sig(vu_par)

        sortie_nom = self._get_user_name(magasinier) if magasinier else None
        sortie_fonction = self._get_user_fonction(magasinier, "")
        sortie_sig = _sig(magasinier)

        reception_nom = self._get_user_name(receptionnaire) if receptionnaire else None
        reception_fonction = self._get_user_fonction(receptionnaire, "")
        reception_sig = _sig(receptionnaire)

        signature_cases = [
            {'label': 'ÉMISSION', 'user_name': emission_nom, 'fonction': emission_fonction,
             'signature_path': emission_sig, 'date': emission_date, 'has_signature': emission_has_sig, 'default_text': ''},
            {'label': 'VU POUR EXÉCUTION', 'user_name': vu_nom, 'fonction': vu_fonction,
             'signature_path': vu_sig, 'date': validation_date, 'has_signature': bool(vu_sig), 'default_text': 'Sous-Direction de la Logistique'},
            {'label': 'SORTIE EFFECTUÉE', 'user_name': sortie_nom, 'fonction': sortie_fonction,
             'signature_path': sortie_sig, 'date': sortie_date, 'has_signature': bool(sortie_sig), 'default_text': ''},
            {'label': 'RÉCEPTION', 'user_name': reception_nom, 'fonction': reception_fonction,
             'signature_path': reception_sig, 'date': reception_date, 'has_signature': bool(reception_sig), 'default_text': ''},
        ]

        date_bon_str = bon.date_bon.strftime('%d/%m/%Y') if bon.date_bon else ''
        case_labels = [
            "Émission",
            "Vu pour exécution",
            f"Sortie effectuée le {date_bon_str}",
            "Réception"
        ]
        case_sous_labels = [
            self._get_user_fonction(chef_service, "DEMANDEUR"),
            self._get_user_fonction(vu_par, "VALIDEUR"),
            self._get_user_fonction(magasinier, "MAGASINIER"),
            self._get_user_fonction(receptionnaire, "RÉCEPTIONNÉ PAR")
        ]
        users = [chef_service, vu_par, magasinier, receptionnaire]
        dates = [emission_date, validation_date, sortie_date, reception_date]

        workflow_steps = []
        for i in range(4):
            user = users[i]
            dt = dates[i]
            if user:
                workflow_steps.append({
                    'label': case_labels[i],
                    'sous_label': case_sous_labels[i],
                    'user_name': self._get_user_name(user),
                    'signature_path': _sig(user),
                    'date': dt,
                })
            else:
                workflow_steps.append({
                    'label': case_labels[i],
                    'sous_label': case_sous_labels[i],
                    'user_name': '',
                    'signature_path': '',
                    'date': '',
                })

        signatures_config = []
        sig_cfg_list = config.get('signatures', [])
        for i, sig_cfg in enumerate(sig_cfg_list):
            if not sig_cfg.get('visible', True):
                continue
            case = signature_cases[i] if i < len(signature_cases) else {}
            signatures_config.append({
                'ordre': sig_cfg.get('ordre', i + 1),
                'role': sig_cfg.get('role', ''),
                'label': case.get('label', ''),
                'sous_label': case.get('fonction', ''),
                'user_name': case.get('user_name'),
                'signature_path': case.get('signature_path'),
                'date': case.get('date'),
                'position': sig_cfg.get('position', 'left'),
                'style': sig_cfg.get('style', 'ligne_pointillee'),
            })

        pagination = self._paginate(lignes_data, config)
        pages = pagination['pages']
        est_multi_page = pagination['est_multi_page']
        espaceur_mm = pagination['espaceur_mm']

        service_code = self._extract_service_code(bon.service_demandeur)

        est_livraison_partielle = False
        for ligne in lignes_data:
            if ligne.get('reste', 0) > 0:
                est_livraison_partielle = True
                break
        if extra_context and extra_context.get('est_livraison_partielle') is not None:
            est_livraison_partielle = extra_context.get('est_livraison_partielle')
        est_cloture = extra_context.get('est_cloture', False) if extra_context else False
        colspan_quantite = 3 if (est_livraison_partielle and not est_cloture) else 2

        ctx = self._base_context({
            'bon': bon,
            'lignes_data': lignes_data,
            'pages': pages,
            'est_multi_page': est_multi_page,
            'total_qte_demandee': total_qte_demandee,
            'total_qte_servie': total_qte_servie,
            'magasin': bon.magasin,
            'service': bon.service_demandeur,
            'service_code': service_code,
            'demande': demande,
            'accuse': accuse,
            'sondage_data': sondage_data,
            'workflow_steps': workflow_steps,
            'signatures_config': signatures_config,
            'signature_cases': signature_cases,
            'colspan_quantite': colspan_quantite,
            'est_livraison_partielle': est_livraison_partielle,
            'est_cloture': est_cloture,
            'numero_livraison': getattr(livraison, 'numero_livraison', None) if livraison else None,
            'pdf_config': config,
            'espaceur_mm': espaceur_mm,
            'logo_url': self._get_logo_url(),
            'cachet_url': self._img_url(self.config.cachet) if self.config and hasattr(self.config, 'cachet') and self.config.cachet else None,
            'service_poste': getattr(bon.service_demandeur, 'poste', '') if bon.service_demandeur else '',
        })
        if extra_context:
            ctx.update(extra_context)
        return self._render_bytes('stock/pdf/bon_sortie.html', ctx)

    def bon_demande(self, demande, extra_context=None):
        lignes_brutes = list(demande.lignes_demande.select_related('article').all())
        lignes_data = []
        total_qte = 0
        for idx, l in enumerate(lignes_brutes, 1):
            qte = l.quantite_demandee or 0
            lignes_data.append({
                'idx': idx,
                'reference': getattr(l.article, 'reference', '') or '',
                'designation': getattr(l.article, 'designation', '') or '',
                'unite': getattr(l.article, 'unite_distribution', 'U') or 'U',
                'quantite': qte,
            })
            total_qte += qte

        config = self._get_pdf_config(type_doc='DEMANDE', magasin=demande.magasin_cible)

        demandeur = self.request.user if self.request and hasattr(self.request, 'user') else None
        demandeur_nom = self._get_user_name(demandeur) if demandeur else ""
        demandeur_fonction = self._get_user_fonction(demandeur, "")

        if not demandeur_fonction and demandeur:
            profil = getattr(demandeur, 'profil', None)
            if profil:
                for attr in ('fonction', 'poste', 'role'):
                    val = getattr(profil, attr, None)
                    if val:
                        if hasattr(val, 'nom'):
                            demandeur_fonction = val.nom
                        else:
                            demandeur_fonction = str(val)
                        break
        if not demandeur_fonction and demande.service_demandeur:
            demandeur_fonction = getattr(demande.service_demandeur, 'nom', '')

        signature_url = None
        if demandeur:
            profil = getattr(demandeur, 'profil', None)
            if profil and hasattr(profil, 'signature') and profil.signature:
                signature_url = self._img_url(profil.signature)
            elif hasattr(demandeur, 'signature') and demandeur.signature:
                signature_url = self._img_url(demandeur.signature)

        pagination = self._paginate(lignes_data, config)
        pages = pagination['pages']
        est_multi_page = pagination['est_multi_page']
        espaceur_mm = pagination['espaceur_mm']

        service_code = self._extract_service_code(demande.service_demandeur)

        ctx = self._base_context({
            'demande': demande,
            'lignes_data': lignes_data,
            'pages': pages,
            'est_multi_page': est_multi_page,
            'total_qte': total_qte,
            'magasin': demande.magasin_cible,
            'service': demande.service_demandeur,
            'service_code': service_code,
            'pdf_config': config,
            'espaceur_mm': espaceur_mm,
            'logo_url': self._get_logo_url(),
            'cachet_url': self._img_url(self.config.cachet) if self.config and hasattr(self.config, 'cachet') and self.config.cachet else None,
            'type_bon_label': "BON DE DEMANDE",
            'doc_subtitle': "DE MATERIELS ET FOURNITURES",
            'service_poste': getattr(demande.service_demandeur, 'poste', '') if demande.service_demandeur else '',
            'demandeur_nom': demandeur_nom,
            'demandeur_fonction': demandeur_fonction,
            'signature_url': signature_url,
        })
        if extra_context:
            ctx.update(extra_context)
        return self._render_bytes('stock/pdf/bon_demande.html', ctx)

    def bon_entree(self, bon, extra_context=None):
        lignes_brutes = list(bon.lignes_bon.select_related('article__famille').all())
        total_qte = sum(l.quantite for l in lignes_brutes)
        total_montant = sum(
            (l.quantite * l.prix_unitaire) if l.prix_unitaire else Decimal('0')
            for l in lignes_brutes
        )
        config = self._get_pdf_config(type_doc='BON_ENTREE', magasin=bon.magasin)

        _sig = self._user_signature

        commande = getattr(bon, 'commande_liee', None)

        lignes_data = []
        total_qte_demandee = 0
        total_qte_recue = 0
        est_reception_partielle = False

        for idx, l in enumerate(lignes_brutes, 1):
            qte_recue = l.quantite
            qte_demandee = getattr(l, 'quantite_demandee', 0) or qte_recue

            if not qte_demandee and commande:
                ligne_cmd = commande.lignes_commande.filter(article=l.article).first()
                if ligne_cmd:
                    qte_demandee = ligne_cmd.quantite_demandee

            reliquat = getattr(l, 'reste', 0)
            if not reliquat and qte_demandee:
                reliquat = max(0, qte_demandee - qte_recue)

            if reliquat > 0:
                est_reception_partielle = True

            lignes_data.append({
                'idx': idx,
                'reference': getattr(l.article, 'reference', '') or '',
                'designation': getattr(l.article, 'designation', '') or '',
                'unite': getattr(l.article, 'unite_mesure', 'Unité') or 'Unité',
                'quantite': qte_demandee,
                'quantite_recue': qte_recue,
                'reliquat': reliquat,
                'numero_lot': getattr(l, 'numero_lot', None) or '',
                'date_peremption': getattr(l, 'date_peremption', None),
                'prix_unitaire': l.prix_unitaire,
            })
            total_qte_demandee += qte_demandee
            total_qte_recue += qte_recue

        if not est_reception_partielle and commande:
            for ligne_cmd in commande.lignes_commande.all():
                if ligne_cmd.reliquat > 0:
                    est_reception_partielle = True
                    break

        numero_livraison = getattr(bon, 'numero_livraison', None)

        valideur = None
        if getattr(bon, 'statut_validation', None) == 'VALIDE':
            valideur = getattr(bon, 'valide_par', None)
        magasinier = bon.cree_par

        saisisseur = magasinier or valideur or bon.cree_par

        signatures_config = []
        sigs_cfg = config.get('signatures', [])

        sig1 = sigs_cfg[0] if len(sigs_cfg) > 0 else {'label': 'Le Responsable', 'role': 'responsable', 'visible': True}
        if sig1.get('visible', True):
            signatures_config.append({
                'label': sig1.get('label', 'Le Responsable'),
                'user_name': self._get_user_name(valideur) if valideur else None,
                'sous_label': self._get_user_fonction(valideur, "Responsable") if valideur else "Responsable",
                'signature_path': _sig(valideur),
                'date': getattr(bon, 'date_validation', None),
            })
        sig2 = sigs_cfg[1] if len(sigs_cfg) > 1 else {'label': 'Le Magasinier', 'role': 'magasinier', 'visible': True}
        if sig2.get('visible', True):
            signatures_config.append({
                'label': sig2.get('label', 'Le Magasinier'),
                'user_name': self._get_user_name(magasinier),
                'sous_label': self._get_user_fonction(magasinier, bon.magasin.nom if bon.magasin else 'Magasinier'),
                'signature_path': _sig(magasinier),
                'date': getattr(bon, 'date_bon', None),
            })

        pagination = self._paginate(lignes_data, config)
        pages = pagination['pages']
        est_multi_page = pagination['est_multi_page']
        espaceur_mm = pagination['espaceur_mm']

        ctx = self._base_context({
            'bon': bon,
            'lignes': lignes_brutes,
            'lignes_data': lignes_data,
            'pages': pages,
            'est_multi_page': est_multi_page,
            'total_qte': total_qte,
            'total_qte_demandee': total_qte_demandee,
            'total_qte_recue': total_qte_recue,
            'total_montant': total_montant,
            'magasin': bon.magasin,
            'fournisseur': bon.fournisseur,
            'commande': commande,
            'numero_livraison': numero_livraison,
            'pdf_config': config,
            'type_bon_label': "BON D'ENTRÉE",
            'logo_url': self._get_logo_url(),
            'cachet_url': self._img_url(self.config.cachet) if self.config and hasattr(self.config, 'cachet') and self.config.cachet else None,
            'signatures_config': signatures_config,
            'est_reception_partielle': est_reception_partielle,
            'espaceur_mm': espaceur_mm,
            'saisisseur_nom': self._get_user_name(saisisseur),
            'saisisseur_fonction': self._get_user_fonction(saisisseur, "Magasinier"),
            'saisisseur_date': getattr(bon, 'date_bon', None) or getattr(bon, 'date_creation', None),
            'saisisseur_signature': _sig(saisisseur),
        })
        if extra_context:
            ctx.update(extra_context)
        return self._render_bytes('stock/pdf/bon_entree.html', ctx)

    def bon_retour(self, bon, extra_context=None):
        lignes_brutes = list(bon.lignes_bon.select_related('article__famille').all())
        total_qte = sum(l.quantite for l in lignes_brutes)

        lignes_data = []
        for ligne in lignes_brutes:
            article = ligne.article
            unite = 'U'
            for attr in ('unite_distribution', 'unite_mesure', 'unite'):
                if hasattr(article, attr):
                    val = getattr(article, attr)
                    if val:
                        unite = val
                        break
            lignes_data.append({
                'reference': getattr(article, 'reference', '') or '',
                'designation': getattr(article, 'designation', '') or '',
                'unite': unite,
                'quantite': ligne.quantite,
            })

        config = self._get_pdf_config(type_doc='BON_RETOUR', magasin=bon.magasin)

        _sig = self._user_signature

        demandeur = getattr(bon, 'demandeur', None) or bon.cree_par
        valideur = None
        if getattr(bon, 'statut_validation', None) == 'VALIDE':
            valideur = getattr(bon, 'valide_par', None)
        magasinier = bon.cree_par

        signatures_config = []
        sigs_cfg = config.get('signatures', [])
        role_users = {
            'demandeur': demandeur,
            'responsable': valideur,
            'magasinier': magasinier,
        }
        role_labels_default = {
            'demandeur': 'Le demandeur',
            'responsable': 'Vu pour exécution',
            'magasinier': 'Le Magasinier',
        }
        role_sous_default = {
            'demandeur': bon.service_demandeur.nom if bon.service_demandeur else '',
            'responsable': bon.magasin.nom if bon.magasin else '',
            'magasinier': bon.magasin.nom if bon.magasin else '',
        }
        role_dates = {
            'demandeur': getattr(bon, 'date_creation', None),
            'responsable': getattr(bon, 'date_validation', None),
            'magasinier': getattr(bon, 'date_bon', None),
        }

        for i, sig_cfg in enumerate(sigs_cfg[:3]):
            if not sig_cfg.get('visible', True):
                continue
            role = sig_cfg.get('role', '')
            user = role_users.get(role)
            signatures_config.append({
                'label': sig_cfg.get('label', role_labels_default.get(role, '')),
                'user_name': self._get_user_name(user) if user else None,
                'sous_label': self._get_user_fonction(user, role_sous_default.get(role, '')) if user else role_sous_default.get(role, ''),
                'signature_path': _sig(user),
                'date': role_dates.get(role) if user else None,
            })

        pagination = self._paginate(lignes_data, config)
        pages = pagination['pages']
        est_multi_page = pagination['est_multi_page']
        espaceur_mm = pagination['espaceur_mm']

        ctx = self._base_context({
            'bon': bon,
            'lignes': lignes_brutes,
            'lignes_data': lignes_data,
            'pages': pages,
            'est_multi_page': est_multi_page,
            'total_qte': total_qte,
            'magasin': bon.magasin,
            'service': bon.service_demandeur,
            'signatures_config': signatures_config,
            'pdf_config': config,
            'type_bon_label': "BON DE RETOUR",
            'doc_subtitle': "DE MATERIELS ET FOURNITURES",
            'logo_url': self._get_logo_url(),
            'cachet_url': self._img_url(self.config.cachet) if self.config and hasattr(self.config, 'cachet') and self.config.cachet else None,
            'service_poste': getattr(bon.service_demandeur, 'poste', '') if bon.service_demandeur else '',
            'espaceur_mm': espaceur_mm,
        })
        if extra_context:
            ctx.update(extra_context)
        return self._render_bytes('stock/pdf/bon_retour.html', ctx)

    def bon_hors_stock(self, bon, extra_context=None):
        lignes_brutes = list(bon.lignes_bon.select_related('article__famille').all())
        total_qte = sum(l.quantite for l in lignes_brutes)

        lignes_data = []
        for ligne in lignes_brutes:
            article = ligne.article
            unite = 'U'
            for attr in ('unite_distribution', 'unite_mesure', 'unite'):
                if hasattr(article, attr):
                    val = getattr(article, attr)
                    if val:
                        unite = val
                        break
            lignes_data.append({
                'reference': getattr(article, 'reference', '') or '',
                'designation': getattr(article, 'designation', '') or '',
                'unite': unite,
                'quantite': ligne.quantite,
            })

        config = self._get_pdf_config(type_doc='BON_HS', magasin=bon.magasin)

        _sig = self._user_signature

        sous_directeur = getattr(bon, 'valide_par', None)
        magasinier = bon.cree_par
        service_user = bon.service_demandeur
        service_user_nom = getattr(service_user, 'nom', '') if service_user else ''

        signatures_config = [
            {
                'label': 'Sous-Directeur Logistique',
                'user_name': self._get_user_name(sous_directeur) if sous_directeur else None,
                'sous_label': self._get_user_fonction(sous_directeur, 'Sous-Directeur') if sous_directeur else '',
                'signature_path': _sig(sous_directeur),
                'date': getattr(bon, 'date_validation', None) if sous_directeur else None,
            },
            {
                'label': 'Service Economique',
                'user_name': self._get_user_name(magasinier),
                'sous_label': self._get_user_fonction(magasinier, bon.magasin.nom if bon.magasin else 'Service Économique'),
                'signature_path': _sig(magasinier),
                'date': getattr(bon, 'date_bon', None) or getattr(bon, 'date_creation', None),
            },
            {
                'label': 'Service Utilisateur',
                'user_name': service_user_nom or None,
                'sous_label': '',
                'signature_path': '',
                'date': None,
            },
        ]

        pagination = self._paginate(lignes_data, config)
        pages = pagination['pages']
        est_multi_page = pagination['est_multi_page']
        espaceur_mm = pagination['espaceur_mm']

        ctx = self._base_context({
            'bon': bon,
            'lignes': lignes_brutes,
            'lignes_data': lignes_data,
            'pages': pages,
            'est_multi_page': est_multi_page,
            'total_qte': total_qte,
            'magasin': bon.magasin,
            'service': bon.service_demandeur,
            'fournisseur': bon.fournisseur,
            'logo_url': self._get_logo_url(),
            'pdf_config': config,
            'type_bon_label': "BON DE SORTIE",
            'doc_subtitle': "HORS STOCK",
            'service_poste': getattr(bon.service_demandeur, 'poste', '') if bon.service_demandeur else '',
            'signatures_config': signatures_config,
            'espaceur_mm': espaceur_mm,
        })
        if extra_context:
            ctx.update(extra_context)
        return self._render_bytes('stock/pdf/bon_hors_stock.html', ctx)

    def bon_commande(self, commande, extra_context=None):
        lignes_brutes = list(commande.lignes_commande.select_related('article').all())
        lignes_data = []
        for idx, l in enumerate(lignes_brutes, 1):
            lignes_data.append({
                'idx': idx,
                'reference': getattr(l.article, 'reference', '') or '',
                'designation': getattr(l.article, 'designation', '') or '',
                'unite': getattr(l.article, 'unite_distribution', 'U') or 'U',
                'quantite': getattr(l, 'quantite', getattr(l, 'quantite_demandee', 0)),
            })

        config = self._get_pdf_config(type_doc='COMMANDE', magasin=getattr(commande, 'magasin', None))

        e = self.config
        nom_etablissement = (
            getattr(e, 'raison_sociale', None)
            or getattr(e, 'nom', None)
            or getattr(e, 'designation', None)
            or ""
        )
        footer_line1 = nom_etablissement.upper() if e else ""

        parts = []
        if e:
            if getattr(e, 'adresse', None):         parts.append(e.adresse)
            if getattr(e, 'telephone', None):     parts.append(f"Tél : {e.telephone}")
            # ✅ CORRECTION MONO-TENANT : ConfigurationHopital utilise 'email_contact'
            # et n'a pas de champ 'poste'. Les champs 'raison_sociale' et 'designation'
            # n'existent pas non plus mais sont des fallbacks après 'nom' qui existe.
            if getattr(e, 'email_contact', None):   parts.append(f"Email : {e.email_contact}")
            if getattr(e, 'cc', None):              parts.append(f"CC N° : {e.cc}")
        footer_line2 = "  •  ".join(parts)

        footer_line3 = config.get(
            'sous_direction_label',
            'Direction des Affaires Financières'
        )

        _sig = self._user_signature

        demandeur = commande.cree_par
        valideur = None
        if getattr(commande, 'statut_validation', None) == 'VALIDE':
            valideur = getattr(commande, 'valide_par', None)

        signatures_config = []
        sigs_cfg = config.get('signatures', [])
        sig1 = sigs_cfg[0] if len(sigs_cfg) > 0 else {'label': 'Demandeur', 'role': 'demandeur', 'visible': True}
        if sig1.get('visible', True):
            signatures_config.append({
                'label': sig1.get('label', 'Demandeur'),
                'sous_label': self._get_user_fonction(demandeur, getattr(commande.magasin, 'nom', '') or "Service demandeur"),
                'user_name': self._get_user_name(demandeur),
                'signature_path': _sig(demandeur),
                'date': getattr(commande, 'date_commande', None),
            })
        sig2 = sigs_cfg[1] if len(sigs_cfg) > 1 else {'label': 'Vu pour exécution', 'role': 'responsable', 'visible': True}
        if sig2.get('visible', True) and valideur:
            signatures_config.append({
                'label': sig2.get('label', 'Vu pour exécution'),
                'sous_label': self._get_user_fonction(valideur, (
                    getattr(getattr(valideur, 'profil', object()), 'poste', '')
                    or getattr(valideur, 'poste', '')
                    or "Responsable"
                )),
                'user_name': self._get_user_name(valideur),
                'signature_path': _sig(valideur),
                'date': getattr(commande, 'date_validation', None),
            })

        pagination = self._paginate(lignes_data, config)
        pages = pagination['pages']
        est_multi_page = pagination['est_multi_page']
        espaceur_mm = pagination['espaceur_mm']

        ctx = self._base_context({
            'commande': commande,
            'lignes_data': lignes_data,
            'pages': pages,
            'est_multi_page': est_multi_page,
            'signatures_config': signatures_config,
            'pdf_config': config,
            'logo_url': self._img_url(e.logo) if e else None,
            'footer_line1': footer_line1,
            'footer_line2': footer_line2,
            'footer_line3': footer_line3,
            'espaceur_mm': espaceur_mm,
        })
        if extra_context:
            ctx.update(extra_context)
        return self._render_bytes('stock/pdf/bon_commande.html', ctx)

    def etat_stock(self, stocks_data, titre_periode="Actuel", date_debut=None,
                   date_fin=None, utilisateur=None, extra_context=None):
        config = self._get_pdf_config(type_doc='ETAT_STOCK')
        ctx = self._base_context({
            'stocks_data': stocks_data,
            'titre_periode': titre_periode,
            'date_debut': date_debut,
            'date_fin': date_fin,
            'utilisateur': utilisateur,
            'pdf_config': config,
            'type_bon_label': "ÉTAT DU STOCK",
            'logo_url': self._get_logo_url(),
            'cachet_url': self._img_url(self.config.cachet) if self.config and hasattr(self.config, 'cachet') and self.config.cachet else None,
        })
        if extra_context:
            ctx.update(extra_context)
        return self._render_bytes('stock/pdf/etat_stock.html', ctx)

    def ajustement(self, ajustement, extra_context=None):
        config = self._get_pdf_config(type_doc='AJUSTEMENT', magasin=getattr(ajustement, 'magasin', None))

        _sig = self._user_signature

        valideur = None
        if getattr(ajustement, 'statut_validation', None) == 'VALIDE':
            valideur = getattr(ajustement, 'valide_par', None)
        magasinier = ajustement.cree_par

        signatures_config = []
        sigs_cfg = config.get('signatures', [])
        sig1 = sigs_cfg[0] if len(sigs_cfg) > 0 else {'label': 'Le Magasinier', 'role': 'magasinier', 'visible': True}
        if sig1.get('visible', True):
            signatures_config.append({
                'label': sig1.get('label', 'Le Magasinier'),
                'user_name': self._get_user_name(magasinier),
                'sous_label': self._get_user_fonction(magasinier, (getattr(ajustement, 'magasin', None) and ajustement.magasin.nom) or 'Magasinier'),
                'signature_path': _sig(magasinier),
                'date': getattr(ajustement, 'date_creation', None),
            })
        sig2 = sigs_cfg[1] if len(sigs_cfg) > 1 else {'label': 'Le Responsable', 'role': 'responsable', 'visible': True}
        if sig2.get('visible', True) and valideur:
            signatures_config.append({
                'label': sig2.get('label', 'Le Responsable'),
                'user_name': self._get_user_name(valideur),
                'sous_label': self._get_user_fonction(valideur, "Responsable"),
                'signature_path': _sig(valideur),
                'date': getattr(ajustement, 'date_validation', None),
            })

        ctx = self._base_context({
            'ajustement': ajustement,
            'signatures_config': signatures_config,
            'pdf_config': config,
            'type_bon_label': "BON D'AJUSTEMENT DE STOCK",
            'logo_url': self._get_logo_url(),
            'cachet_url': self._img_url(self.config.cachet) if self.config and hasattr(self.config, 'cachet') and self.config.cachet else None,
        })
        if extra_context:
            ctx.update(extra_context)
        return self._render_bytes('stock/pdf/ajustement.html', ctx)

    def historique_article(self, article, mouvements, tri='date_desc', utilisateur=None, extra_context=None):
        config = self._get_pdf_config(type_doc='HISTORIQUE')
        ctx = self._base_context({
            'article': article,
            'mouvements': mouvements,
            'tri': tri,
            'utilisateur': utilisateur,
            'pdf_config': config,
            'type_bon_label': f"HISTORIQUE – {article.designation}",
            'logo_url': self._get_logo_url(),
            'cachet_url': self._img_url(self.config.cachet) if self.config and hasattr(self.config, 'cachet') and self.config.cachet else None,
        })
        if extra_context:
            ctx.update(extra_context)
        return self._render_bytes('stock/pdf/historique_article.html', ctx)

    def fiche_comptage(self, campagne, lignes, edite_par=None, date_impression=None, extra_context=None):
        config = self._get_pdf_config(type_doc='INVENTAIRE')

        imprimeur_sig = self._user_signature(edite_par)

        ctx = self._base_context({
            'campagne': campagne,
            'lignes': lignes,
            'edite_par': edite_par,
            'date_impression': date_impression or timezone.now(),
            'pdf_config': config,
            'type_bon_label': f"FICHE DE COMPTAGE – {campagne.titre}",
            'logo_url': self._get_logo_url(),
            'cachet_url': self._img_url(self.config.cachet) if self.config and hasattr(self.config, 'cachet') and self.config.cachet else None,
            'imprimeur_sig': imprimeur_sig,
        })
        if extra_context:
            ctx.update(extra_context)
        return self._render_bytes('stock/pdf/fiche_comptage.html', ctx)

    def resultat_inventaire(self, campagne, lignes_data, total_ecarts,
                            valeur_totale_ecart, date_impression=None, extra_context=None):
        config = self._get_pdf_config(type_doc='INVENTAIRE')

        saisisseur_sig = self._user_signature(getattr(campagne, 'cree_par', None))
        valideur_sig   = self._user_signature(getattr(campagne, 'valide_par', None))

        ctx = self._base_context({
            'campagne': campagne,
            'lignes_data': lignes_data,
            'total_ecarts': total_ecarts,
            'valeur_totale_ecart': valeur_totale_ecart,
            'date_impression': date_impression or timezone.now(),
            'pdf_config': config,
            'type_bon_label': f"RÉSULTAT INVENTAIRE – {campagne.titre}",
            'logo_url': self._get_logo_url(),
            'cachet_url': self._img_url(self.config.cachet) if self.config and hasattr(self.config, 'cachet') and self.config.cachet else None,
            'saisisseur_sig': saisisseur_sig,
            'valideur_sig': valideur_sig,
        })
        if extra_context:
            ctx.update(extra_context)
        return self._render_bytes('stock/pdf/resultat_inventaire.html', ctx)

    def rapport_consommation(self, consommations, date_debut, date_fin, service=None,
                             edite_par=None, extra_context=None):
        config = self._get_pdf_config(type_doc='RAPPORT')
        ctx = self._base_context({
            'consommations': consommations,
            'date_debut': date_debut,
            'date_fin': date_fin,
            'service': service,
            'edite_par': edite_par,
            'pdf_config': config,
            'logo_url': self._get_logo_url(),
        })
        if extra_context:
            ctx.update(extra_context)
        return self._render_bytes('stock/pdf/rapport_consommation.html', ctx)
