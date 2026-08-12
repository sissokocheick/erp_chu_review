# -*- coding: utf-8 -*-
"""
Factories de test partagées entre les modules de tests du projet.

Permet de créer rapidement les objets métier (familles, articles, magasins,
utilisateurs, mouvements, bons...) avec des valeurs par défaut cohérentes.
"""
from decimal import Decimal

from django.contrib.auth import get_user_model

from core.models import ConfigurationHopital
from stock.models import (
    FamilleArticle, Article, Magasin, StockItem, Mouvement, Fournisseur,
)

User = get_user_model()


def creer_config_hopital():
    """Retourne (et crée si besoin) le singleton ConfigurationHopital."""
    return ConfigurationHopital.get_instance()


def creer_utilisateur(username="user_test", password="testpass123", **kwargs):
    """Crée un utilisateur simple (profil auto-créé par signal)."""
    return User.objects.create_user(username=username, password=password, **kwargs)


def creer_superuser(username="super_test", password="testpass123"):
    return User.objects.create_superuser(username=username, password=password)


def desactiver_changement_mdp(user):
    """Désactive l'obligation de changement de MDP (évite le middleware de
    redirection dans les tests de vues).
    """
    profil = user.profil
    if profil.doit_changer_mdp:
        profil.doit_changer_mdp = False
        profil.save(update_fields=['doit_changer_mdp'])
    return user


def creer_famille(code="FAM01", intitule="Famille Test", type_famille="MED",
                  methode_valorisation="CMUP", **kwargs):
    return FamilleArticle.objects.create(
        code=code, intitule=intitule, type_famille=type_famille,
        methode_valorisation=methode_valorisation, **kwargs
    )


def creer_article(famille=None, designation="Article Test", reference=None,
                  unite_distribution="UNITE", prix_reference=None, **kwargs):
    if famille is None:
        famille = creer_famille()
    return Article.objects.create(
        famille=famille, designation=designation, reference=reference,
        unite_distribution=unite_distribution,
        prix_reference=prix_reference, **kwargs
    )


def creer_magasin(nom="Magasin Principal", **kwargs):
    return Magasin.objects.create(nom=nom, **kwargs)


def creer_stock(article, magasin, quantite=0, valeur_cmup=Decimal('0.00'),
                batch_number=None, expiry_date=None):
    return StockItem.objects.create(
        article=article, magasin=magasin, quantite_physique=quantite,
        valeur_cmup=valeur_cmup, batch_number=batch_number,
        expiry_date=expiry_date,
    )


def creer_fournisseur(nom="Fournisseur Test", **kwargs):
    return Fournisseur.objects.create(nom=nom, **kwargs)


def creer_mouvement(article, magasin, utilisateur, type_mouvement, quantite,
                    prix_unitaire=None, numero_lot=None, date_peremption=None,
                    date_mouvement=None, update_stock=True):
    """Crée un mouvement (mise à jour de stock par défaut).

    Note : `update_stock` est un argument de save(), pas de create() —
    on construit donc l'objet puis on appelle save() explicitement.
    """
    kwargs = {}
    if date_mouvement is not None:
        # Ne pas écraser la valeur par défaut du modèle (timezone.now)
        kwargs['date_mouvement'] = date_mouvement
    mvt = Mouvement(
        article=article, magasin=magasin, utilisateur=utilisateur,
        type_mouvement=type_mouvement, quantite=quantite,
        prix_unitaire=prix_unitaire, numero_lot=numero_lot,
        date_peremption=date_peremption, **kwargs,
    )
    mvt.save(update_stock=update_stock)
    return mvt


def entrer_stock(article, magasin, utilisateur, quantite, prix_unitaire,
                 **kwargs):
    """Entrée de stock standard avec prix (base CMUP)."""
    return creer_mouvement(article, magasin, utilisateur, 'ENTREE', quantite,
                           prix_unitaire=prix_unitaire, **kwargs)
