# -*- coding: utf-8 -*-
"""Crawl toutes les pages GET de l'app et remonte les erreurs."""
import os, sys, io, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

import django
django.setup()

from django.test import Client
from django.contrib.auth.models import User
from django.urls import get_resolver
from stock.models import Magasin

c = Client()
admin = User.objects.get(username='admin')
c.force_login(admin)

# Session magasin
mag = Magasin.objects.filter(is_deleted=False).first() or Magasin.objects.first()
if mag:
    s = c.session
    s['magasin_actif_id'] = str(mag.id)
    s.save()
    print(f"MAGASIN: {mag.nom} (id={mag.id})")
else:
    print("AUCUN MAGASIN")

# Liste manuelle des URLs à tester (GET)
urls = [
    '/', '/articles/', '/familles/', '/entrees/', '/sorties/',
    '/stock/retours-services/', '/ajustements/', '/inventaires/',
    '/etat-stock/', '/administration/historique/', '/bons/hors-stock/',
    '/stock/peremptions/', '/livraisons/', '/commandes/', '/receptions/',
    '/mes-demandes/', '/gestion-demandes/', '/valider-demandes/',
    '/parametres/logistique/', '/parametres/administratifs/',
    '/magasins/2/parametres/',
    '/rapports/', '/stats/demandes/', '/stats/sondages/',
    '/stats/satisfaction-services/', '/notifications/',
    '/accueil/',
    '/auth/', '/auth/accueil/', '/auth/profil/', '/auth/roles/',
    '/auth/utilisateurs/',
    '/auth/journal-audit/', '/auth/securite/mots-de-passe/',
    '/auth/circuits-validation/', '/auth/parametres/documents-pdf/',
    '/patrimoine/', '/patrimoine/sas/',
    '/patrimoine/contrats/', '/patrimoine/interventions/',
    '/patrimoine/portail/', '/patrimoine/import/', '/patrimoine/parametres/',
    '/patrimoine/export/', '/patrimoine/mes-tickets/',
    '/patrimoine/interventions/dispatch/', '/patrimoine/mes-interventions/',
    '/patrimoine/inventaires/', '/patrimoine/rebuts/', '/patrimoine/pertes/',
    '/magasin/2/modele-pdf/BS/', '/magasin/2/modele-pdf/',
]

# URLs avec paramètres d'ID (à tester si les objets existent)
from stock.models import (BonMouvement, Commande, DemandeMateriel, Ajustement,
                          CampagneInventaire, Article)
AjustementStock = Ajustement

# IDs réels par type de bon (le type est porté par BonMouvement)
bs = BonMouvement.objects.filter(type_bon__in=['BS', 'SORTIE']).first()
be = BonMouvement.objects.filter(type_bon__in=['BE', 'ENTREE']).first()
br = BonMouvement.objects.filter(type_bon__in=['BR', 'RETOUR']).first()
bhs = BonMouvement.objects.filter(type_bon__in=['HS', 'HORS_STOCK']).first()
from patrimoine.models import Immobilisation, ContratMaintenance
BienImmo = Immobilisation
Contrat = ContratMaintenance
InterventionTicket = None

def first_id(model):
    try:
        obj = model.objects.first()
        return obj.id if obj else None
    except Exception:
        return None

params = {
    '/articles/{id}/historique/': first_id(Article),
    '/entrees/apercu/{id}/': be.id if be else None,
    '/entrees/{id}/pdf/': be.id if be else None,
    '/entrees/{id}/annuler/': be.id if be else None,
    '/sorties/valider/{id}/': bs.id if bs else None,
    '/bon/{id}/imprimer/': bs.id if bs else None,
    '/retours-services/apercu/{id}/': br.id if br else None,
    '/stock/retours-services/imprimer/{id}/': br.id if br else None,
    '/ajustements/imprimer/{id}/': first_id(AjustementStock),
    '/inventaires/{id}/fiche/': first_id(CampagneInventaire),
    '/inventaires/{id}/resultat/': first_id(CampagneInventaire),
    '/inventaires/{id}/saisir/': first_id(CampagneInventaire),
    '/article/{id}/imprimer/': first_id(Article),
    '/bons/hors-stock/{id}/apercu/': bhs.id if bhs else None,
    '/bons/hors-stock/{id}/imprimer/': bhs.id if bhs else None,
    '/commande/{id}/imprimer/': first_id(Commande),
    '/commande/{id}/receptionner/': first_id(Commande),
    '/commande/{id}/valider/': first_id(Commande),
    '/commandes/{id}/supprimer/': first_id(Commande),
    '/commandes/{id}/solder/': first_id(Commande),
    '/demande/{id}/pdf/': first_id(DemandeMateriel),
    '/demandes/{id}/livraisons/': first_id(DemandeMateriel),
    '/patrimoine/{id}/': first_id(BienImmo),
    '/patrimoine/{id}/modifier/': first_id(BienImmo),
    '/patrimoine/contrats/{id}/': first_id(Contrat),
}

results = {'OK': [], 'REDIRECT': [], '404': [], '500': [], 'ERROR': []}

def test_url(url, label):
    try:
        r = c.get(url, follow=False)
        if r.status_code == 200:
            results['OK'].append(label)
        elif r.status_code in (301, 302):
            results['REDIRECT'].append(f"{label} -> {r.get('Location','?')}")
        elif r.status_code == 404:
            results['404'].append(f"{label} ({url})")
        else:
            results['500'].append(f"{label} [{r.status_code}] ({url})")
    except Exception as e:
        results['ERROR'].append(f"{label} ({url}) : {type(e).__name__}: {e}")
        traceback.print_exc()

for url in urls:
    test_url(url, url)

for pattern, obj_id in params.items():
    if obj_id:
        url = pattern.format(id=obj_id)
        test_url(url, url)

print("\n" + "=" * 60)
print(f"TOTAL: {sum(len(v) for v in results.values())}")
print(f"OK: {len(results['OK'])}  REDIRECT: {len(results['REDIRECT'])}  "
      f"404: {len(results['404'])}  500: {len(results['500'])}  ERROR: {len(results['ERROR'])}")
print("=" * 60)

if results['404']:
    print("\n--- 404 ---")
    for x in results['404']:
        print(" ", x)
if results['500']:
    print("\n--- 500 ---")
    for x in results['500']:
        print(" ", x)
if results['ERROR']:
    print("\n--- EXCEPTIONS ---")
    for x in results['ERROR']:
        print(" ", x)
if results['REDIRECT']:
    print("\n--- REDIRECTS ---")
    for x in results['REDIRECT']:
        print(" ", x)
