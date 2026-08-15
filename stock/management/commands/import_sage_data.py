# -*- coding: utf-8 -*-
# stock/management/commands/import_sage_data.py
# -*- coding: utf-8 -*-
"""
Commande d'importation des données Sage 100 Gestion Commerciale
vers le module Stock de l'ERP CHU Angré.

Usage :
    python manage.py import_sage_data [--dry-run] [--skip-articles] [--skip-services]
"""

import logging
from django.core.management.base import BaseCommand
from django.db import transaction
from stock.models import FamilleArticle, Article, Fournisseur
from core.models import Service

logger = logging.getLogger(__name__)

# =============================================================================
# 1. DONNÉES BRUTES EXTRAITES DES PDFs
# =============================================================================

# =============================================================================
# 2. CHARGEMENT DES DONNÉES DEPUIS LES FICHIERS CSV (data_sage/)
# =============================================================================
# Les données d'import vivent dans des fichiers CSV (stock/management/commands/
# data_sage/) et non dans le code : familles.csv, fournisseurs.csv,
# services.csv, articles.csv. Modifier un CSV suffit pour mettre à jour l'import.

import csv as _csv
from pathlib import Path as _Path

_DATA_SAGE_DIR = _Path(__file__).resolve().parent / "data_sage"


def _lire_csv(nom_fichier):
    """Lit un CSV (séparateur ';') et retourne une liste de dicts."""
    chemin = _DATA_SAGE_DIR / nom_fichier
    if not chemin.exists():
        raise FileNotFoundError(
            f"Fichier de données manquant : {chemin} — "
            f"prévoir data_sage/{nom_fichier}"
        )
    with open(chemin, encoding='utf-8-sig', newline='') as f:
        return list(_csv.DictReader(f, delimiter=';'))


def _charger_donnees():
    """Charge les 4 jeux de données depuis les CSV (les articles restent des tuples)."""
    familles = _lire_csv('familles.csv')
    fournisseurs = _lire_csv('fournisseurs.csv')
    services = _lire_csv('services.csv')
    articles = []
    for row in _lire_csv('articles.csv'):
        articles.append((
            row['reference'].strip(),
            row['famille_code'].strip(),
            row['designation'].strip(),
            row['unite'].strip(),
            int(row['seuil_min']),
            int(row['seuil_critique']),
        ))
    return familles, fournisseurs, services, articles


FAMILLES_DATA, FOURNISSEURS_DATA, SERVICES_DATA, ARTICLES_DATA = _charger_donnees()


class Command(BaseCommand):
    help = "Importe les données Sage 100 (familles, fournisseurs, services, articles)"

    def add_arguments(self, parser):
        parser.add_argument(
            '--entreprise-id',
            type=int,
            required=False,
            help="(Ignoré — mode mono-tenant, conservé pour compatibilité)"
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help="Simule l'import sans écrire en base"
        )
        parser.add_argument(
            '--skip-articles',
            action='store_true',
            help="Ignore l'import des articles (utile si déjà importés)"
        )
        parser.add_argument(
            '--skip-services',
            action='store_true',
            help="Ignore l'import des services"
        )
    def handle(self, *args, **options):
        # Robustesse console Windows (cp1252 ne sait pas encoder ▶, é...)
        try:
            import sys
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        except Exception:
            pass

        dry_run = options['dry_run']
        skip_articles = options['skip_articles']
        skip_services = options['skip_services']

        self.stdout.write(self.style.NOTICE("Mode mono-tenant : import global (paramètre --entreprise-id ignoré)"))
        if dry_run:
            self.stdout.write(self.style.WARNING("MODE DRY-RUN — Aucune écriture en base"))

        stats = {"familles": 0, "fournisseurs": 0, "services": 0, "articles": 0, "erreurs": 0}

        # -----------------------------------------------------------------
        # ÉTAPE 1 : FAMILLES
        # -----------------------------------------------------------------
        self.stdout.write(self.style.NOTICE("\n▶ Import des familles d'articles..."))
        familles_map = {}
        for data in FAMILLES_DATA:
            try:
                if not dry_run:
                    famille, created = FamilleArticle.objects.get_or_create(
                        code=data["code"],
                        defaults={
                            "intitule": data["intitule"],
                            "type_famille": data["type"],
                            "methode_valorisation": data["methode"],
                            "categorie": data["categorie"],
                            "est_centralise": False,
                            "gere_lots_peremption": False,
                        }
                    )
                    familles_map[data["code"]] = famille
                    if created:
                        stats["familles"] += 1
                else:
                    familles_map[data["code"]] = None
                    stats["familles"] += 1
            except Exception as e:
                stats["erreurs"] += 1
                self.stdout.write(self.style.ERROR(f"  ✗ Famille {data['code']}: {e}"))

        self.stdout.write(self.style.SUCCESS(f"  ✓ {stats['familles']} familles prêtes"))

        # -----------------------------------------------------------------
        # ÉTAPE 2 : FOURNISSEURS
        # -----------------------------------------------------------------
        self.stdout.write(self.style.NOTICE("\n▶ Import des fournisseurs..."))
        for data in FOURNISSEURS_DATA:
            try:
                if not dry_run:
                    _, created = Fournisseur.objects.get_or_create(
                        code=data["code"],
                        defaults={
                            "raison_sociale": data["raison_sociale"],
                            "telephone": data["telephone"],
                            "est_agree": True,
                            "note_evaluation": 5,
                        }
                    )
                    if created:
                        stats["fournisseurs"] += 1
                else:
                    stats["fournisseurs"] += 1
            except Exception as e:
                stats["erreurs"] += 1
                self.stdout.write(self.style.ERROR(f"  ✗ Fournisseur {data['code']}: {e}"))

        self.stdout.write(self.style.SUCCESS(f"  ✓ {stats['fournisseurs']} fournisseurs importés"))

        # -----------------------------------------------------------------
        # ÉTAPE 3 : SERVICES (CLIENTS)
        # -----------------------------------------------------------------
        if not skip_services:
            self.stdout.write(self.style.NOTICE("\n▶ Import des services (clients)..."))
            for data in SERVICES_DATA:
                try:
                    if not dry_run:
                        service, created = Service.objects.get_or_create(
                            code=data["code"],
                            defaults={
                                "nom": data["nom"],
                                "poste_telephone": data.get("poste_telephone", ""),
                            }
                        )
                        if created:
                            stats["services"] += 1
                    else:
                        stats["services"] += 1
                except Exception as e:
                    stats["erreurs"] += 1
                    self.stdout.write(self.style.ERROR(f"  ✗ Service {data['code']}: {e}"))

            self.stdout.write(self.style.SUCCESS(f"  ✓ {stats['services']} services importés"))

        # -----------------------------------------------------------------
        # ÉTAPE 4 : ARTICLES
        # -----------------------------------------------------------------
        if not skip_articles:
            self.stdout.write(self.style.NOTICE("\n▶ Import des articles..."))
            for ref, fam_code, design, unite, seuil_min, seuil_crit in ARTICLES_DATA:
                try:
                    famille = familles_map.get(fam_code)
                    if not famille and not dry_run:
                        self.stdout.write(self.style.WARNING(f"  ⚠ Famille {fam_code} manquante pour {ref}"))
                        stats["erreurs"] += 1
                        continue

                    if not dry_run:
                        article, created = Article.objects.get_or_create(

                            reference=ref,
                            defaults={
                                "famille": famille,
                                "designation": design,
                                "unite_distribution": unite,
                                "seuil_minimum": seuil_min,
                                "seuil_critique": seuil_crit,
                                "prix_reference": 0,
                            }
                        )
                        if created:
                            stats["articles"] += 1
                    else:
                        stats["articles"] += 1

                except Exception as e:
                    stats["erreurs"] += 1
                    self.stdout.write(self.style.ERROR(f"  ✗ Article {ref}: {e}"))

            self.stdout.write(self.style.SUCCESS(f"  ✓ {stats['articles']} articles importés"))

        # -----------------------------------------------------------------
        # RÉCAPITULATIF
        # -----------------------------------------------------------------
        self.stdout.write("\n" + "=" * 50)
        self.stdout.write(self.style.NOTICE("RÉCAPITULATIF"))
        self.stdout.write(f"  Familles      : {stats['familles']}")
        self.stdout.write(f"  Fournisseurs  : {stats['fournisseurs']}")
        self.stdout.write(f"  Services      : {stats['services']}")
        self.stdout.write(f"  Articles      : {stats['articles']}")
        if stats["erreurs"]:
            self.stdout.write(self.style.ERROR(f"  Erreurs       : {stats['erreurs']}"))
        self.stdout.write("=" * 50)
