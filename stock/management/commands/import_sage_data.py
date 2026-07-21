# stock/management/commands/import_sage_data.py
# -*- coding: utf-8 -*-
"""
Commande d'importation des données Sage 100 Gestion Commerciale
vers le module Stock de l'ERP CHU Angré.

Usage :
    python manage.py import_sage_data --entreprise-id 1 [--dry-run] [--skip-articles]
"""

import logging
from django.core.management.base import BaseCommand
from django.db import transaction
from stock.models import FamilleArticle, Article, Fournisseur
from core.models import Service
from accounts.models import Entreprise

logger = logging.getLogger(__name__)

# =============================================================================
# 1. DONNÉES BRUTES EXTRAITES DES PDFs
# =============================================================================

FAMILLES_DATA = [
    {"code": "AFE", "intitule": "AUTRES FOURNITURES D'EXPLOITATION", "type": "D", "methode": "CMUP", "categorie": "Exploitation"},
    {"code": "AMB", "intitule": "AUTRES MATERIELS DE BUREAU", "type": "T", "methode": "CMUP", "categorie": "Matériel Bureau"},
    {"code": "FHS", "intitule": "FOURNITURES D'HYGIENE ET DE SOINS", "type": "D", "methode": "CMUP", "categorie": "Hygiène"},
    {"code": "FOB", "intitule": "FOURNITURES DE BUREAU", "type": "D", "methode": "CMUP", "categorie": "Bureau"},
    {"code": "FOH", "intitule": "FOURNITURES HÔTELIERES", "type": "D", "methode": "CMUP", "categorie": "Hôtelier"},
    {"code": "FOI", "intitule": "FOURNITURES INFORMATIQUES", "type": "T", "methode": "CMUP", "categorie": "Informatique"},
    {"code": "HHP", "intitule": "HABILLEMENT HORS PERSONNEL", "type": "D", "methode": "CMUP", "categorie": "Habillement Patient"},
    {"code": "HLO", "intitule": "HABILLEMENT ET LINGE OPERATOIRE", "type": "D", "methode": "CMUP", "categorie": "Habillement Personnel"},
    {"code": "IMM", "intitule": "IMPRIMES MEDICAUX", "type": "D", "methode": "CMUP", "categorie": "Imprimés Médicaux"},
    {"code": "INM", "intitule": "IMPRIMES NON MEDICAUX", "type": "D", "methode": "CMUP", "categorie": "Imprimés Administratifs"},
    {"code": "MCE", "intitule": "MACHINES COMPTABLES ET EQUIPEMENTS", "type": "T", "methode": "CMUP", "categorie": "Matériel Comptable"},
    {"code": "MMB", "intitule": "MOBILIER ET MATERIEL DE BUREAU", "type": "T", "methode": "CMUP", "categorie": "Mobilier"},
    {"code": "POP", "intitule": "PETITS OUTILLAGES & PIECES DE RECHANGE", "type": "D", "methode": "CMUP", "categorie": "Outillage"},
    {"code": "PRA", "intitule": "PRODUITS ALIMENTAIRES", "type": "D", "methode": "CMUP", "categorie": "Alimentation"},
    {"code": "PRE", "intitule": "PRODUITS D'ENTRETIEN", "type": "D", "methode": "CMUP", "categorie": "Entretien"},
]

FOURNISSEURS_DATA = [
    {"code": "401BUR", "raison_sociale": "BUROMAT", "telephone": "0759861067"},
    {"code": "401EDI", "raison_sociale": "EDJEHOU DANHI IMPRIM", "telephone": "0787027003"},
    {"code": "401EFB", "raison_sociale": "ETS F.B.", "telephone": "0758613881"},
    {"code": "401EFT", "raison_sociale": "E.F.T.P.", "telephone": "0707369416"},
    {"code": "401ENA", "raison_sociale": "ENAC-CI", "telephone": "0564839550"},
    {"code": "401ESO", "raison_sociale": "ETS SOUFA", "telephone": "0707888143"},
    {"code": "401EUR", "raison_sociale": "EURO-TEL HOLDING", "telephone": "0778411641"},
    {"code": "401FAD", "raison_sociale": "FADIKCIS", "telephone": "0707085438"},
    {"code": "401FAP", "raison_sociale": "FAM ACTIV PLUS", "telephone": "0102486028"},
    {"code": "401ICS", "raison_sociale": "IVOIRE CARTES SYSTEM", "telephone": ""},
    {"code": "401IG2", "raison_sociale": "INGENIERIE GENIE CIVIL", "telephone": "0700024196"},
    {"code": "401IGM", "raison_sociale": "IMPRIMERIE GRANDE MA", "telephone": ""},
    {"code": "401KAD", "raison_sociale": "KADY IMPRIM", "telephone": "0787313569"},
    {"code": "401KAM", "raison_sociale": "KAMI SERVICES", "telephone": "0707609491"},
    {"code": "401KER", "raison_sociale": "KERSI SARL", "telephone": "2735962417"},
    {"code": "401KOG", "raison_sociale": "KOUMBA GROUP", "telephone": "0710073423"},
    {"code": "401LIM", "raison_sociale": "LIMA ENTREPRISE", "telephone": "0504372662"},
    {"code": "401MAB", "raison_sociale": "MAB CONSULTING", "telephone": "0701644810"},
    {"code": "401MAI", "raison_sociale": "MAISSA PRESTIGE & SERVICES", "telephone": "0707464625"},
    {"code": "401MMD", "raison_sociale": "MMD HOLDING BUSINESS", "telephone": "0749871100"},
    {"code": "401NAM", "raison_sociale": "NAMA-CO Sarl", "telephone": ""},
    {"code": "401PIP", "raison_sociale": "PIPAD - DEMBELE SIAKA", "telephone": "0787478175"},
    {"code": "401PRO", "raison_sociale": "PROMOVET", "telephone": "0103124760"},
    {"code": "401SAL", "raison_sociale": "SANGARE LAMINE", "telephone": "0749514923"},
    {"code": "401SOS", "raison_sociale": "SOSEK", "telephone": "0544870051"},
]

# Données extraites de CLIENTS (SERVICES).pdf
# Mapping : code = N° client, nom = Raison sociale, poste_telephone = Téléphone (poste interne)
SERVICES_DATA = [
    {"code": "411AGC", "nom": "AGENCE COMPTABLE", "poste_telephone": "106"},
    {"code": "411ANE", "nom": "ANESTHESIE & REANIMATION", "poste_telephone": "144"},
    {"code": "411BME", "nom": "BIOLOGIE MEDICALE", "poste_telephone": "136"},
    {"code": "411COB", "nom": "CONTRÔLE BUDGETAIRE", "poste_telephone": "107"},
    {"code": "411DAF", "nom": "DIRECTION DES AFFAIRES FINANCIERES", "poste_telephone": "103"},
    {"code": "411DGL", "nom": "DIRECTION GENERALE", "poste_telephone": "121"},
    {"code": "411DMS", "nom": "DIRECTION MEDICALE ET SOINS", "poste_telephone": "102"},
    {"code": "411DRH", "nom": "DIRECTION DES RESSOURCES HUMAINES", "poste_telephone": "104"},
    {"code": "411DSI", "nom": "DIRECTION SOINS INFIRMIERS", "poste_telephone": "359"},
    {"code": "411DTE", "nom": "DIRECTION TECHNIQUE", "poste_telephone": "105"},
    {"code": "411GYO", "nom": "GYNECOLOGIE OBSTETRICALE", "poste_telephone": "142"},
    {"code": "411IME", "nom": "IMAGERIE MEDICALE", "poste_telephone": "127"},
    {"code": "411MIG", "nom": "MEDECINE INTERNE & GERIATRIE", "poste_telephone": "130"},
    {"code": "411MPR", "nom": "MEDECINE PHYSIQUE & READAPTATION", "poste_telephone": "147"},
    {"code": "411MTP", "nom": "MEDECINE TRAVAIL & PATHOLOGIE PROFESSIONNELLE", "poste_telephone": "191"},
    {"code": "411OTC", "nom": "ORTHO-TRAUMATO-CHIRURGIE PLASTIQUE", "poste_telephone": "194"},
    {"code": "411PHA", "nom": "PHARMACIE", "poste_telephone": "156"},
    {"code": "411PMS", "nom": "PEDIATRIE MEDICALE & SPECIALITES", "poste_telephone": "146"},
]

# Structure : (reference, famille_code, designation, unite, seuil_min, seuil_critique)
ARTICLES_DATA = [
    # ======================= MMB =======================
    ("2261MMB00001", "MMB", "BANQUETTE - 3 PLACES", "Unité", 2, 1),
    ("2261MMB00002", "MMB", "BUREAU AGENT", "Unité", 2, 1),
    ("2261MMB00003", "MMB", "BUREAU DIRECTEUR", "Unité", 2, 1),
    ("2261MMB00004", "MMB", "CHAISE EN PLASTIQUE", "Unité", 5, 2),
    ("2261MMB00005", "MMB", "CHAISE VISITEUR", "Unité", 5, 2),
    ("2261MMB00006", "MMB", "ETAGERE DE RANGEMENT - Métallique", "Unité", 2, 1),
    ("2261MMB00007", "MMB", "FAUTEUIL AGENT", "Unité", 2, 1),
    ("2261MMB00008", "MMB", "FAUTEUIL DIRECTEUR", "Unité", 2, 1),
    ("2261MMB00009", "MMB", "FAUTEUIL ORTHOPEDIQUE", "Unité", 1, 1),
    ("2261MMB00010", "MMB", "FAUTEUIL RELAX", "Unité", 1, 1),
    ("2261MMB00011", "MMB", "FAUTEUIL VISITEUR", "Unité", 2, 1),
    ("2261MMB00012", "MMB", "PLACARD DE RANGEMENT - Horizontal", "Unité", 2, 1),
    ("2261MMB00013", "MMB", "PLACARD DE RANGEMENT - Vertical", "Unité", 2, 1),
    ("2261MMB00014", "MMB", "TABLE DE CONFERENCE", "Unité", 1, 1),
    ("2261MMB00015", "MMB", "TABLE DE REUNION MODULABLE", "Unité", 1, 1),
    ("2261MMB00016", "MMB", "TABLE D'ORDINATEUR", "Unité", 3, 1),
    ("2261MMB00017", "MMB", "TABLE ORDINAIRE", "Unité", 3, 1),
    ("2261MMB00018", "MMB", "TABLEAU A MARKER EFFACABLE", "Unité", 2, 1),
    ("2261MMB00019", "MMB", "TABLEAU D'AFFICHAGE - Grand", "Unité", 1, 1),
    ("2261MMB00020", "MMB", "TABLEAU D'AFFICHAGE - Petit", "Unité", 2, 1),
    ("2261MMB00021", "MMB", "TABLEAU PADEX A TREPIED", "Unité", 1, 1),

    # ======================= MCE =======================
    ("2262MCE00001", "MCE", "IMPRIMANTE DE CODE BARRE", "Pièce", 1, 1),
    ("2262MCE00002", "MCE", "IMPRIMANTE DE CARTE BADGE", "Pièce", 1, 1),
    ("2262MCE00003", "MCE", "IMPRIMANTE DE CHEQUES BANCAIRES", "Pièce", 1, 1),
    ("2262MCE00004", "MCE", "IMPRIMANTE MATRICELLE", "Pièce", 1, 1),
    ("2262MCE00005", "MCE", "IMPRIMANTE MULTIFONCTION - Couleur", "Pièce", 1, 1),
    ("2262MCE00006", "MCE", "IMPRIMANTE MULTIFONCTION - Noir/Blanc", "Pièce", 2, 1),
    ("2262MCE00007", "MCE", "IMPRIMANTE SIMPLE - Couleur", "Pièce", 1, 1),
    ("2262MCE00008", "MCE", "IMPRIMANTE SIMPLE - Noir/Blanc", "Pièce", 2, 1),
    ("2262MCE00009", "MCE", "LECTEUR DE CODE BARRE", "Pièce", 2, 1),
    ("2262MCE00010", "MCE", "ORDINATEUR DE BUREAU", "Pièce", 3, 1),
    ("2262MCE00011", "MCE", "ORDINATEUR PORTABLE", "Pièce", 2, 1),
    ("2262MCE00012", "MCE", "SCA", "Pièce", 1, 1),
    ("2262MCE00013", "MCE", "SCANNER - ScanJet (Grand)", "Pièce", 1, 1),
    ("2262MCE00014", "MCE", "SCANNER - ScanJet (Petit)", "Pièce", 1, 1),

    # ======================= AMB =======================
    ("2269AMB00001", "AMB", "APPAREIL PHOTO NUMERIQUE", "Pièce", 1, 1),
    ("2269AMB00002", "AMB", "ARMOIRE DE TEMPERATURE", "Pièce", 1, 1),
    ("2269AMB00003", "AMB", "BROYEUSE DE PAPIER - Grand", "Pièce", 1, 1),
    ("2269AMB00004", "AMB", "BROYEUSE DE PAPIER - Petit", "Pièce", 2, 1),
    ("2269AMB00005", "AMB", "CAISSE METALIQUE", "Pièce", 2, 1),
    ("2269AMB00006", "AMB", "CALCULATRICE A IMPRESSION", "Pièce", 2, 1),
    ("2269AMB00007", "AMB", "CAMESCOPE NUMERIQUE", "Pièce", 1, 1),
    ("2269AMB00008", "AMB", "CONGELATEUR HORIZONTAL", "Pièce", 1, 1),
    ("2269AMB00009", "AMB", "DETECTEUR DE BILLETS DE BANQUE", "Pièce", 2, 1),
    ("2269AMB00010", "AMB", "ENREGISTREUR PROFESSIONNEL", "Pièce", 1, 1),
    ("2269AMB00011", "AMB", "MACHINE DE RELIURE", "Pièce", 1, 1),
    ("2269AMB00012", "AMB", "PHOTOCOPIEUSE - Couleur", "Pièce", 1, 1),
    ("2269AMB00013", "AMB", "PHOTOCOPIEUSE - Noir/Blanc", "Pièce", 2, 1),
    ("2269AMB00014", "AMB", "PLATEAU D'ARMOIRE DE TEMPERATURE", "Pièce", 2, 1),
    ("2269AMB00015", "AMB", "POINTEUR DE VIDEO-PROJECTEUR", "Pièce", 2, 1),
    ("2269AMB00016", "AMB", "REFRIGERATEUR VERTICAL - Grand", "Pièce", 1, 1),
    ("2269AMB00017", "AMB", "REFRIGERATEUR VERTICAL - Petit", "Pièce", 1, 1),
    ("2269AMB00018", "AMB", "VENTILATEUR MULTIFONCTION", "Pièce", 3, 1),
    ("2269AMB00019", "AMB", "VIDEO-PROJECTEUR", "Pièce", 2, 1),

    # ======================= PRA =======================
    ("6005PRA00001", "PRA", "BONNET ROUGE - 150g", "Boîte", 10, 5),
    ("6005PRA00002", "PRA", "CANNETTE DE SUCRERIE - 400ml", "Pack", 10, 5),
    ("6005PRA00003", "PRA", "EAU MINERALE - 1 500ml", "Bouteille", 20, 10),
    ("6005PRA00004", "PRA", "EAU MINERALE - 330ml", "Pack", 20, 10),
    ("6005PRA00005", "PRA", "EAU MINERALE - 500ml", "Pack", 20, 10),

    # ======================= HHP =======================
    ("6017HHP00001", "HHP", "CASAQUE PATIENT 'CHIRURGIE'", "Unité", 10, 5),
    ("6017HHP00002", "HHP", "CASAQUE PATIENT 'ENDOSCOPIE DIGESTIVE'", "Unité", 5, 2),
    ("6017HHP00003", "HHP", "CASAQUE PATIENT 'GYNECOLOGIE OBSTETRICALE'", "Unité", 10, 5),
    ("6017HHP00004", "HHP", "CASAQUE PATIENT 'IMAGERIE MEDICALE'", "Unité", 5, 2),
    ("6017HHP00005", "HHP", "CASAQUE PATIENT 'MEDECINE INTERNE & GERIATRIE'", "Unité", 10, 5),
    ("6017HHP00006", "HHP", "CASAQUE PATIENT 'PEDIATRIE MEDICALE & SPECIALITES'", "Unité", 10, 5),
    ("6017HHP00007", "HHP", "CASAQUE PATIENT 'REANIMATION'", "Unité", 5, 2),
    ("6017HHP00008", "HHP", "CASAQUE PATIENT 'URGENCES CHIRURGIE'", "Unité", 5, 2),
    ("6017HHP00009", "HHP", "CASAQUE PATIENT 'URGENCES MEDECINE INTERNE & GERIATRIE'", "Unité", 5, 2),
    ("6017HHP00010", "HHP", "CASAQUE PATIENT 'URGENCES GYNECOLOGIE OBSTETRICALE'", "Unité", 5, 2),
    ("6017HHP00011", "HHP", "POCHE DE KANGOUROU - Taille L", "Unité", 5, 2),
    ("6017HHP00012", "HHP", "POCHE DE KANGOUROU - Taille M", "Unité", 5, 2),
    ("6017HHP00013", "HHP", "POCHE DE KANGOUROU - Taille S", "Unité", 5, 2),
    ("6017HHP00014", "HHP", "POCHE DE KANGOUROU - Taille XL", "Unité", 5, 2),
    ("6017HHP00015", "HHP", "POCHE DE KANGOUROU - Taille XXL", "Unité", 5, 2),
    ("6017HHP00016", "HHP", "POCHE DE KANGOUROU - Taille XXXL", "Unité", 5, 2),
    ("6017HHP00017", "HHP", "POCHE DE KANGOUROU - Taille XXXXL", "Unité", 5, 2),

    # ======================= FOB (pages 4-9) =======================
    ("6190FOB00001", "FOB", "AGRAFES N° 10", "Paquet/1000", 10, 5),
    ("6190FOB00002", "FOB", "AGRAFES N° 23/15", "Paquet/1000", 10, 5),
    ("6190FOB00003", "FOB", "AGRAFES N° 24/6", "Paquet/1000", 10, 5),
    ("6190FOB00004", "FOB", "AGRAFES N° 8/4", "Paquet/1000", 10, 5),
    ("6190FOB00005", "FOB", "AGRAFEUSE N° 10", "Unité", 3, 1),
    ("6190FOB00006", "FOB", "AGRAFEUSE N° 12", "Unité", 3, 1),
    ("6190FOB00007", "FOB", "AGRAFEUSE N° 23/6", "Unité", 3, 1),
    ("6190FOB00008", "FOB", "AGRAFEUSE N° 8", "Unité", 3, 1),
    ("6190FOB00009", "FOB", "ATTACHE ELASTIQUE - Grand", "Paquet", 5, 2),
    ("6190FOB00010", "FOB", "ATTACHE ELASTIQUE - Petit", "Paquet", 5, 2),
    ("6190FOB00011", "FOB", "BAGUETTE DE RELIURE - 12mm", "Unité", 5, 2),
    ("6190FOB00012", "FOB", "BAGUETTE DE RELIURE - 4mm", "Unité", 5, 2),
    ("6190FOB00013", "FOB", "BAGUETTE DE RELIURE - 3mm", "Paquet", 5, 2),
    ("6190FOB00014", "FOB", "BAGUETTE DE RELIURE - 6mm", "Paquet", 5, 2),
    ("6190FOB00015", "FOB", "BAGUETTE DE RELIURE - 8mm", "Paquet", 5, 2),
    ("6190FOB00016", "FOB", "BLANCO & DILUANT", "Ensemble", 3, 1),
    ("6190FOB00017", "FOB", "BLOC NOTE - Format A4", "Unité", 10, 5),
    ("6190FOB00018", "FOB", "BLOC NOTE - Format A5", "Unité", 10, 5),
    ("6190FOB00019", "FOB", "BOÎTE DE PUNAISES", "Unité", 5, 2),
    ("6190FOB00020", "FOB", "CACHET DATEUR", "Unité", 2, 1),
    ("6190FOB00021", "FOB", "CACHET NUMEROTEUR", "Unité", 2, 1),
    ("6190FOB00022", "FOB", "CAHIER - 100 Pages", "Unité", 10, 5),
    ("6190FOB00023", "FOB", "CAHIER - 200 Pages", "Unité", 10, 5),
    ("6190FOB00024", "FOB", "CAHIER - 300 Pages", "Unité", 10, 5),
    ("6190FOB00025", "FOB", "CAHIER - 32 Pages", "Unité", 10, 5),
    ("6190FOB00026", "FOB", "CAHIER ETUDIANT - 100 Pages", "Unité", 10, 5),
    ("6190FOB00027", "FOB", "CAHIER ETUDIANT - 200 Pages", "Unité", 10, 5),
    ("6190FOB00028", "FOB", "CAHIER ETUDIANT - 300 Pages", "Unité", 10, 5),
    ("6190FOB00029", "FOB", "CALCULATRICE DE BUREAU", "Unité", 3, 1),
    ("6190FOB00030", "FOB", "CARTON D'ARCHIVES", "Unité", 10, 5),
    ("6190FOB00031", "FOB", "CHEMISE A RABAT", "Unité", 10, 5),
    ("6190FOB00032", "FOB", "CHEMISE A SANGLE", "Unité", 10, 5),
    ("6190FOB00033", "FOB", "CHEMISE CARTONNEE", "Paquet", 10, 5),
    ("6190FOB00034", "FOB", "CHIFFON MOUILLEUR", "Unité", 5, 2),
    ("6190FOB00035", "FOB", "CLASSEUR D'ARCHIVAGE", "Unité", 5, 2),
    ("6190FOB00036", "FOB", "CLASSEUR D'ECOLIER", "Unité", 5, 2),
    ("6190FOB00037", "FOB", "COLLE A PAPIER", "Unité", 5, 2),
    ("6190FOB00038", "FOB", "CORBEILLE A PAPIER", "Unité", 5, 2),
    ("6190FOB00039", "FOB", "COUVERTURE DE RELIURE - A4", "Paquet", 10, 5),
    ("6190FOB00040", "FOB", "CRAYON A PAPIER", "Unité", 10, 5),
    ("6190FOB00041", "FOB", "DECOUPE PAPIER - A4", "Unité", 2, 1),
    ("6190FOB00042", "FOB", "ENCRE DE CACHET - Bleu", "Unité", 3, 1),
    ("6190FOB00043", "FOB", "ENCRE DE CACHET - Noir", "Unité", 3, 1),
    ("6190FOB00044", "FOB", "ENCRE DE CACHET - Rouge", "Unité", 3, 1),
    ("6190FOB00045", "FOB", "ENCREUR - Bleu", "Unité", 3, 1),
    ("6190FOB00046", "FOB", "ENCREUR - Noir", "Unité", 3, 1),
    ("6190FOB00047", "FOB", "ENCREUR - Rouge", "Unité", 3, 1),
    ("6190FOB00048", "FOB", "ENVELOPPE BLANCHE - A5", "Paquet", 10, 5),
    ("6190FOB00049", "FOB", "ENVELOPPE BLANCHE - C5", "Paquet", 10, 5),
    ("6190FOB00050", "FOB", "ENVELOPPE BLANCHE - C6", "Paquet", 10, 5),
    ("6190FOB00051", "FOB", "ENVELOPPE BLANCHE - DL à fenêtre", "Paquet", 10, 5),
    ("6190FOB00052", "FOB", "ENVELOPPE BLANCHE - DL sans fenêtre", "Paquet", 10, 5),
    ("6190FOB00053", "FOB", "ENVELOPPE KAKI - A2", "Paquet/10", 5, 2),
    ("6190FOB00054", "FOB", "ENVELOPPE KAKI - A2", "Paquet/50", 5, 2),
    ("6190FOB00055", "FOB", "ENVELOPPE KAKI - A3", "Paquet", 5, 2),
    ("6190FOB00056", "FOB", "ENVELOPPE KAKI - A4", "Paquet", 10, 5),
    ("6190FOB00057", "FOB", "ENVELOPPE KAKI - A5", "Paquet", 10, 5),
    ("6190FOB00058", "FOB", "ENVELOPPE KAKI - A6", "Paquet", 10, 5),
    ("6190FOB00059", "FOB", "ENVELOPPE KAKI - C3", "Paquet", 5, 2),
    ("6190FOB00060", "FOB", "ENVELOPPE KAKI - C4", "Paquet", 5, 2),
    ("6190FOB00061", "FOB", "ENVELOPPE KAKI - C5", "Paquet", 10, 5),
    ("6190FOB00062", "FOB", "ENVELOPPE KAKI - C6", "Paquet", 10, 5),
    ("6190FOB00063", "FOB", "ETAGERE DE RANGEMENT SUR BUREAU", "Unité", 2, 1),
    ("6190FOB00064", "FOB", "PAPIER BRISTOL", "Paquet", 10, 5),
    ("6190FOB00065", "FOB", "GOMME BLANCHE", "Unité", 5, 2),
    ("6190FOB00066", "FOB", "INTERCALAIRE - Pochet double vue", "Paquet/50", 5, 2),
    ("6190FOB00067", "FOB", "INTERCALAIRE - PVC escalier alphabétique", "Paquet", 5, 2),
    ("6190FOB00068", "FOB", "INTERCALAIRE - PVC escalier numérique", "Paquet", 5, 2),
    ("6190FOB00069", "FOB", "MARKER EFFACABLE", "Unité", 5, 2),
    ("6190FOB00070", "FOB", "MARKER PERMANENT", "Unité", 5, 2),
    ("6190FOB00071", "FOB", "MARKER SURLIGNEUR", "Unité", 5, 2),
    ("6190FOB00072", "FOB", "OTE-AGRAFES", "Unité", 3, 1),
    ("6190FOB00073", "FOB", "PAIRE DE CISEAUX - 17cm", "Unité", 3, 1),
    ("6190FOB00074", "FOB", "PAIRE DE CISEAUX - 21cm", "Unité", 3, 1),
    ("6190FOB00075", "FOB", "PAIRE DE CISEAUX - 27cm", "Unité", 3, 1),
    ("6190FOB00076", "FOB", "PAPIER CARBONE - Bleu", "Paquet", 5, 2),
    ("6190FOB00077", "FOB", "PAPIER CARBONE - Noir", "Paquet", 5, 2),
    ("6190FOB00078", "FOB", "PAPIER CUBE", "Boîte", 5, 2),
    ("6190FOB00079", "FOB", "PAPIER RAME - A4", "Paquet", 20, 10),
    ("6190FOB00080", "FOB", "PAPIER RAME - A3", "Paquet", 10, 5),
    ("6190FOB00081", "FOB", "PAPIER PADEX", "Rouleau", 5, 2),
    ("6190FOB00082", "FOB", "PARAPHEUR - 12 divisions", "Unité", 2, 1),
    ("6190FOB00083", "FOB", "PARAPHEUR - 16 divisions", "Unité", 2, 1),
    ("6190FOB00084", "FOB", "PARAPHEUR - 18 divisions", "Unité", 2, 1),
    ("6190FOB00085", "FOB", "PARAPHEUR - 24 divisions", "Unité", 2, 1),
    ("6190FOB00086", "FOB", "PERFOREUSE DE PAPIER", "Unité", 2, 1),
    ("6190FOB00087", "FOB", "PORTE-STYLOS", "Unité", 3, 1),
    ("6190FOB00088", "FOB", "POST-IT (Petit)", "Unité", 5, 2),
    ("6190FOB00089", "FOB", "POST-IT (Moyen)", "Unité", 5, 2),
    ("6190FOB00090", "FOB", "PROTEGE-DOCUMENT A INTERCALAIRE (10 Feuilles)", "Unité", 5, 2),
    ("6190FOB00091", "FOB", "PROTEGE-DOCUMENT A INTERCALAIRE (50 Feuilles)", "Unité", 5, 2),
    ("6190FOB00092", "FOB", "REGISTRE 12 MAINS - 26x40", "Unité", 3, 1),
    ("6190FOB00093", "FOB", "REGISTRE 10 MAINS - 26x40", "Unité", 3, 1),
    ("6190FOB00094", "FOB", "REGISTRE 8 MAINS - 26x40", "Unité", 3, 1),
    ("6190FOB00095", "FOB", "REGISTRE 8 MAINS - 24x32", "Unité", 3, 1),
    ("6190FOB00096", "FOB", "REGISTRE 6 MAINS - 24x32", "Unité", 3, 1),
    ("6190FOB00097", "FOB", "REGISTRE 5 MAINS - 24x32", "Unité", 3, 1),
    ("6190FOB00098", "FOB", "REGISTRE 5 MAINS - A4", "Unité", 3, 1),
    ("6190FOB00099", "FOB", "REGISTRE 6 MAINS - A4", "Unité", 3, 1),
    ("6190FOB00100", "FOB", "REGISTRE 8 MAINS - A4", "Unité", 3, 1),
    ("6190FOB00101", "FOB", "REGISTRE - COURRIER DEPART", "Unité", 3, 1),
    ("6190FOB00102", "FOB", "REGISTRE - COURRIER ARRIVEE", "Unité", 3, 1),
    ("6190FOB00103", "FOB", "REGISTRE - TRANSMISSION", "Unité", 3, 1),
    ("6190FOB00104", "FOB", "REGLE GEOMETRIQUE (alluminium) - 30cm", "Unité", 3, 1),
    ("6190FOB00105", "FOB", "REGLE GEOMETRIQUE (alluminium) - 20cm", "Unité", 3, 1),
    ("6190FOB00106", "FOB", "REGLE GEOMETRIQUE (plastique) - 30cm", "Unité", 3, 1),
    ("6190FOB00107", "FOB", "REGLE GEOMETRIQUE (plastique) - 50cm", "Unité", 3, 1),
    ("6190FOB00108", "FOB", "RUBAN ADHESIF (papier) - Grand", "Rouleau", 5, 2),
    ("6190FOB00109", "FOB", "RUBAN ADHESIF (papier) - Petit", "Rouleau", 5, 2),
    ("6190FOB00110", "FOB", "RUBAN ADHESIF (transparent) - Grand", "Rouleau", 5, 2),
    ("6190FOB00111", "FOB", "RUBAN ADHESIF (transparent) - Petit", "Unité", 5, 2),
    ("6190FOB00112", "FOB", "SOUS-CHEMISE", "Paquet", 10, 5),
    ("6190FOB00113", "FOB", "SOUS-MAINS (plastique) - A4", "Unité", 3, 1),
    ("6190FOB00114", "FOB", "SPIRALE DE RELIURE - 6mm", "Paquet", 5, 2),
    ("6190FOB00115", "FOB", "SPIRALE DE RELIURE - 10mm", "Paquet", 5, 2),
    ("6190FOB00116", "FOB", "SPIRALE DE RELIURE - 14mm", "Paquet", 5, 2),
    ("6190FOB00117", "FOB", "SPIRALE DE RELIURE - 18mm", "Paquet", 5, 2),
    ("6190FOB00118", "FOB", "SPIRALE DE RELIURE - 22mm", "Paquet", 5, 2),
    ("6190FOB00119", "FOB", "SPIRALE DE RELIURE - 26mm", "Paquet", 5, 2),
    ("6190FOB00120", "FOB", "SPIRALE DE RELIURE - 30mm", "Paquet", 5, 2),
    ("6190FOB00121", "FOB", "SPIRALE DE RELIURE - 32mm", "Paquet", 5, 2),
    ("6190FOB00122", "FOB", "SPIRALE DE RELIURE - 35mm", "Paquet", 5, 2),
    ("6190FOB00123", "FOB", "STYLO A BILLE - Bleu", "Unité", 20, 10),
    ("6190FOB00124", "FOB", "STYLO A BILLE - Noir", "Unité", 20, 10),
    ("6190FOB00125", "FOB", "STYLO A BILLE - Rouge", "Unité", 10, 5),
    ("6190FOB00126", "FOB", "STYLO A BILLE - Vert", "Unité", 10, 5),
    ("6190FOB00127", "FOB", "STYLO FEUTRE (signature) - Bleu", "Unité", 10, 5),
    ("6190FOB00128", "FOB", "STYLO FEUTRE (signature) - Noir", "Unité", 10, 5),
    ("6190FOB00129", "FOB", "STYLO FEUTRE (signature) - Rouge", "Unité", 10, 5),
    ("6190FOB00130", "FOB", "STYLO FEUTRE (signature) - Vert", "Unité", 10, 5),
    ("6190FOB00131", "FOB", "STYLO FEUTRE - Bout fin", "Paquet", 5, 2),
    ("6190FOB00132", "FOB", "TAILLE-CRAYON", "Unité", 5, 2),
    ("6190FOB00133", "FOB", "TONER C-EXV33 - Canon iR 2520i", "Unité", 2, 1),
    ("6190FOB00134", "FOB", "TONER C-EXV42 - Canon iR 2204i", "Unité", 2, 1),
    ("6190FOB00135", "FOB", "TONER C-EXV54 - Canon iR 3125i (Bleu)", "Unité", 2, 1),
    ("6190FOB00136", "FOB", "TONER C-EXV54 - Canon iR 3125i (Jaune)", "Unité", 2, 1),
    ("6190FOB00137", "FOB", "TONER C-EXV54 - Canon iR 3125i (Noir)", "Unité", 2, 1),
    ("6190FOB00138", "FOB", "TONER C-EXV54 - Canon iR 3125i (Rouge)", "Unité", 2, 1),
    ("6190FOB00139", "FOB", "TONER C-EXV59 - Canon iR 2630i", "Unité", 2, 1),
    ("6190FOB00140", "FOB", "TONER C-EXV60 - Canon iR 2425i", "Unité", 2, 1),
    ("6190FOB00141", "FOB", "TRANSPARENT DE RELIURE - A4", "Paquet", 5, 2),
    ("6190FOB00142", "FOB", "TROMBONE - 25mm", "Paquet", 5, 2),
    ("6190FOB00143", "FOB", "TROMBONE - 32mm", "Paquet", 5, 2),
    ("6190FOB00144", "FOB", "TROMBONE - 50mm", "Paquet", 5, 2),
    ("6190FOB00145", "FOB", "TROMBONE PAPILLON - 40mm", "Boîte", 3, 1),
    ("6190FOB00146", "FOB", "TROMBONE PAPILLON - 60mm", "Boîte", 3, 1),
    ("6190FOB00147", "FOB", "ENSEMBLE GEOMETRIQUE", "Ensemble", 3, 1),

    # ======================= FOI =======================
    ("6191FOI00001", "FOI", "CARBONE DE CODE BARRE", "Rouleau", 3, 1),
    ("6191FOI00002", "FOI", "CLE USB - 2 Go", "Unité", 5, 2),
    ("6191FOI00003", "FOI", "CLE USB - 4 Go", "Unité", 5, 2),
    ("6191FOI00004", "FOI", "CLE USB - 8 Go", "Unité", 5, 2),
    ("6191FOI00005", "FOI", "CLE USB - 16 Go", "Unité", 5, 2),
    ("6191FOI00006", "FOI", "CLE USB - 32 Go", "Unité", 5, 2),
    ("6191FOI00007", "FOI", "DISQUE DUR EXTERNE - 1 To", "Unité", 2, 1),
    ("6191FOI00008", "FOI", "DISQUE DUR EXTERNE - 8 To", "Unité", 1, 1),
    ("6191FOI00009", "FOI", "DISQUE DUR EXTERNE - 500 Go", "Unité", 2, 1),
    ("6191FOI00010", "FOI", "DVD-RW & POCHETTE", "Unité", 5, 2),
    ("6191FOI00011", "FOI", "TAMBOUR HP - 19A", "Unité", 2, 1),
    ("6191FOI00012", "FOI", "TAMBOUR HP - 32A", "Unité", 2, 1),
    ("6191FOI00013", "FOI", "TUBE D'ENCRE HP - 106A", "Unité", 3, 1),
    ("6191FOI00014", "FOI", "TUBE D'ENCRE HP - 107A", "Unité", 3, 1),
    ("6191FOI00015", "FOI", "TUBE D'ENCRE HP - 117A (Bleu)", "Unité", 3, 1),
    ("6191FOI00016", "FOI", "TUBE D'ENCRE HP - 117A (Jaune)", "Unité", 3, 1),
    ("6191FOI00017", "FOI", "TUBE D'ENCRE HP - 117A (Noir)", "Unité", 5, 2),
    ("6191FOI00018", "FOI", "TUBE D'ENCRE HP - 117A (Rouge)", "Unité", 3, 1),
    ("6191FOI00019", "FOI", "TUBE D'ENCRE HP - 123 Couleur", "Unité", 3, 1),
    ("6191FOI00020", "FOI", "TUBE D'ENCRE HP - 123 Noir", "Unité", 3, 1),
    ("6191FOI00021", "FOI", "TUBE D'ENCRE HP - 17A", "Unité", 3, 1),
    ("6191FOI00022", "FOI", "TUBE D'ENCRE HP - 203A (Bleu)", "Unité", 3, 1),
    ("6191FOI00023", "FOI", "TUBE D'ENCRE HP - 203A (Jaune)", "Unité", 3, 1),
    ("6191FOI00024", "FOI", "TUBE D'ENCRE HP - 203A (Noir)", "Unité", 5, 2),
    ("6191FOI00025", "FOI", "TUBE D'ENCRE HP - 203A (Rouge)", "Unité", 3, 1),
    ("6191FOI00026", "FOI", "TUBE D'ENCRE HP - 205A (Bleu)", "Unité", 3, 1),
    ("6191FOI00027", "FOI", "TUBE D'ENCRE HP - 205A (Jaune)", "Unité", 3, 1),
    ("6191FOI00028", "FOI", "TUBE D'ENCRE HP - 205A (Noir)", "Unité", 5, 2),
    ("6191FOI00029", "FOI", "TUBE D'ENCRE HP - 205A (Rouge)", "Unité", 3, 1),
    ("6191FOI00030", "FOI", "TUBE D'ENCRE HP - 207A (Bleu)", "Unité", 3, 1),
    ("6191FOI00031", "FOI", "TUBE D'ENCRE HP - 207A (Jaune)", "Unité", 3, 1),
    ("6191FOI00032", "FOI", "TUBE D'ENCRE HP - 207A (Noir)", "Unité", 5, 2),
    ("6191FOI00033", "FOI", "TUBE D'ENCRE HP - 207A (Rouge)", "Unité", 3, 1),
    ("6191FOI00034", "FOI", "TUBE D'ENCRE HP - 216A (Bleu)", "Unité", 3, 1),
    ("6191FOI00035", "FOI", "TUBE D'ENCRE HP - 216A (Jaune)", "Unité", 3, 1),
    ("6191FOI00036", "FOI", "TUBE D'ENCRE HP - 216A (Noir)", "Unité", 5, 2),
    ("6191FOI00037", "FOI", "TUBE D'ENCRE HP - 216A (Rouge)", "Unité", 3, 1),
    ("6191FOI00038", "FOI", "TUBE D'ENCRE HP - 26A", "Unité", 3, 1),
    ("6191FOI00039", "FOI", "TUBE D'ENCRE HP - 30A", "Unité", 3, 1),
    ("6191FOI00040", "FOI", "TUBE D'ENCRE HP - 410A (Bleu)", "Unité", 3, 1),
    ("6191FOI00041", "FOI", "TUBE D'ENCRE HP - 410A (Jaune)", "Unité", 3, 1),
    ("6191FOI00042", "FOI", "TUBE D'ENCRE HP - 410A (Noir)", "Unité", 5, 2),
    ("6191FOI00043", "FOI", "TUBE D'ENCRE HP - 410A (Rouge)", "Unité", 3, 1),
    ("6191FOI00044", "FOI", "TUBE D'ENCRE HP - 508A (Bleu)", "Unité", 3, 1),
    ("6191FOI00045", "FOI", "TUBE D'ENCRE HP - 508A (Jaune)", "Unité", 3, 1),
    ("6191FOI00046", "FOI", "TUBE D'ENCRE HP - 508A (Noir)", "Unité", 5, 2),
    ("6191FOI00047", "FOI", "TUBE D'ENCRE HP - 508A (Rouge)", "Unité", 3, 1),
    ("6191FOI00048", "FOI", "TUBE D'ENCRE HP - 59A", "Unité", 3, 1),
    ("6191FOI00049", "FOI", "TUBE D'ENCRE HP - 63 Couleur", "Unité", 3, 1),
    ("6191FOI00050", "FOI", "TUBE D'ENCRE HP - 63 Noir", "Unité", 3, 1),
    ("6191FOI00051", "FOI", "TUBE D'ENCRE HP - 80A", "Unité", 3, 1),
    ("6191FOI00052", "FOI", "TUBE D'ENCRE HP - 83A", "Unité", 3, 1),
    ("6191FOI00053", "FOI", "TUBE D'ENCRE HP - 85A", "Unité", 3, 1),
    ("6191FOI00054", "FOI", "ETIQUETTE DE CODE BARRE", "Rouleau", 3, 1),
    ("6191FOI00055", "FOI", "RUBAN D'IMPRIMANTE DE BADGE", "Unité", 2, 1),
    ("6191FOI00056", "FOI", "ONDULEUR - 650 VA", "Unité", 2, 1),
    ("6191FOI00057", "FOI", "ONDULEUR - 1000 VA", "Unité", 2, 1),
    ("6191FOI00058", "FOI", "ONDULEUR - 2000 VA", "Unité", 1, 1),

    # ======================= HLO (pages 12-16) =======================
    ("61925HLO0001", "HLO", "BABOUCHE MEDICALE - Pointure 36", "Paire", 5, 2),
    ("61925HLO0002", "HLO", "BABOUCHE MEDICALE - Pointure 37", "Paire", 5, 2),
    ("61925HLO0003", "HLO", "BABOUCHE MEDICALE - Pointure 38", "Paire", 5, 2),
    ("61925HLO0004", "HLO", "BABOUCHE MEDICALE - Pointure 39", "Paire", 5, 2),
    ("61925HLO0005", "HLO", "BABOUCHE MEDICALE - Pointure 40", "Paire", 5, 2),
    ("61925HLO0006", "HLO", "BABOUCHE MEDICALE - Pointure 41", "Paire", 5, 2),
    ("61925HLO0007", "HLO", "BABOUCHE MEDICALE - Pointure 42", "Paire", 5, 2),
    ("61925HLO0008", "HLO", "BABOUCHE MEDICALE - Pointure 43", "Paire", 5, 2),
    ("61925HLO0010", "HLO", "BABOUCHE MEDICALE - Pointure 44", "Paire", 5, 2),
    ("61925HLO0011", "HLO", "BABOUCHE MEDICALE - Pointure 45", "Paire", 5, 2),
    ("61925HLO0012", "HLO", "BAVETTE EN TISSU", "Unité", 10, 5),
    ("61925HLO0013", "HLO", "BLOUSE 'A.P.A - MPR'", "Ensemble", 5, 2),
    ("61925HLO0014", "HLO", "BLOUSE 'D.E.S - MPR'", "Ensemble", 5, 2),
    ("61925HLO0015", "HLO", "BLOUSE 'A.S.H'", "Ensemble", 5, 2),
    ("61925HLO0016", "HLO", "BLOUSE 'ADMINISTRATION'", "Unité", 5, 2),
    ("61925HLO0017", "HLO", "BLOUSE 'AGENT D'HYGIENE'", "Ensemble", 5, 2),
    ("61925HLO0018", "HLO", "BLOUSE 'AGENT DE SAISIE - IMAGERIE MEDICALE'", "Ensemble", 5, 2),
    ("61925HLO0019", "HLO", "BLOUSE 'AIDE-SOIGNANT'", "Ensemble", 10, 5),
    ("61925HLO0020", "HLO", "BLOUSE 'AMBULANCIER'", "Ensemble", 5, 2),
    ("61925HLO0021", "HLO", "BLOUSE 'ARCHIVES GENERALES'", "Ensemble", 5, 2),
    ("61925HLO0022", "HLO", "BLOUSE 'ASSISTANT CHEF DE CLINIQUE'", "Ensemble", 5, 2),
    ("61925HLO0023", "HLO", "BLOUSE 'ASSISTANT SOCIAL'", "Ensemble", 5, 2),
    ("61925HLO0024", "HLO", "BLOUSE 'AUXILIAIRE - BIOLOGIE MEDICALE'", "Ensemble", 5, 2),
    ("61925HLO0025", "HLO", "BLOUSE 'AUXILIAIRE - HYGIENE & ASSAINISSEMENT'", "Ensemble", 5, 2),
    ("61925HLO0026", "HLO", "BLOUSE 'AUXILIAIRE - IMAGERIE MEDICALE'", "Ensemble", 5, 2),
    ("61925HLO0027", "HLO", "BLOUSE 'AUXILIAIRE - P.G.P'", "Ensemble", 5, 2),
    ("61925HLO0028", "HLO", "BLOUSE 'AUXILIAIRE - SOINS INFIRMIERS'", "Ensemble", 10, 5),
    ("61925HLO0029", "HLO", "BLOUSE 'AUXILIAIRE - SOINS OBSTETRICAUX'", "Ensemble", 5, 2),
    ("61925HLO0030", "HLO", "BLOUSE 'AUXILIAIRE DE PHARMACIE'", "Ensemble", 5, 2),
    ("61925HLO0031", "HLO", "BLOUSE 'BRANCARDIER'", "Ensemble", 5, 2),
    ("61925HLO0032", "HLO", "BLOUSE 'CHEF DE SERVICE'", "Ensemble", 5, 2),
    ("61925HLO0033", "HLO", "BLOUSE 'EDUCATEUR PRESCOLAIRE'", "Ensemble", 5, 2),
    ("61925HLO0034", "HLO", "BLOUSE 'EDUCATRICE SPECIALISEE'", "Ensemble", 5, 2),
    ("61925HLO0035", "HLO", "BLOUSE 'ELECTRICIEN'", "Ensemble", 5, 2),
    ("61925HLO0036", "HLO", "BLOUSE 'FRIGORISTE'", "Ensemble", 5, 2),
    ("61925HLO0037", "HLO", "BLOUSE 'GERONTOLOGUE'", "Ensemble", 5, 2),
    ("61925HLO0038", "HLO", "BLOUSE 'I.A.D.E'", "Ensemble", 5, 2),
    ("61925HLO0039", "HLO", "BLOUSE 'I.B.O'", "Ensemble", 5, 2),
    ("61925HLO0040", "HLO", "BLOUSE 'I.D.E'", "Ensemble", 10, 5),
    ("61925HLO0041", "HLO", "BLOUSE 'I.D.E.S'", "Ensemble", 5, 2),
    ("61925HLO0042", "HLO", "BLOUSE 'INFORMATICIEN'", "Ensemble", 5, 2),
    ("61925HLO0043", "HLO", "BLOUSE 'INGENIEUR - BIOLOGIE MEDICALE'", "Ensemble", 5, 2),
    ("61925HLO0044", "HLO", "BLOUSE 'INGENIEUR - IMAGERIE MEDICALE'", "Ensemble", 5, 2),
    ("61925HLO0045", "HLO", "BLOUSE 'INGENIEUR DES TECHNIQUES DE SOINS - SANTE PUBLIQUE'", "Ensemble", 5, 2),
    ("61925HLO0046", "HLO", "BLOUSE 'INSPECTEUR DE SOINS'", "Ensemble", 5, 2),
    ("61925HLO0047", "HLO", "BLOUSE 'INTERNE'", "Ensemble", 10, 5),
    ("61925HLO0048", "HLO", "BLOUSE 'KINESITHERAPEUTE'", "Ensemble", 5, 2),
    ("61925HLO0049", "HLO", "BLOUSE 'MAITRE ASSISTANT'", "Ensemble", 5, 2),
    ("61925HLO0050", "HLO", "BLOUSE 'MANUTENTIONNAIRE'", "Ensemble", 5, 2),
    ("61925HLO0051", "HLO", "BLOUSE 'MEDECIN'", "Ensemble", 10, 5),
    ("61925HLO0052", "HLO", "BLOUSE 'BIOLOGISTE'", "Ensemble", 5, 2),
    ("61925HLO0053", "HLO", "BLOUSE 'D.E.S - PEDIATRIE MEDICALE & SPECIALITES'", "Ensemble", 5, 2),
    ("61925HLO0054", "HLO", "BLOUSE 'DENTISTE'", "Ensemble", 5, 2),
    ("61925HLO0055", "HLO", "BLOUSE 'MEDECIN GENERALISTE'", "Ensemble", 10, 5),
    ("61925HLO0056", "HLO", "BLOUSE 'MEDECIN SPECIALISTE - SANTE AU TRAVAIL'", "Ensemble", 5, 2),
    ("61925HLO0057", "HLO", "BLOUSE 'MEDECIN URGENTISTE'", "Ensemble", 5, 2),
    ("61925HLO0058", "HLO", "BLOUSE 'MENUISIER'", "Ensemble", 5, 2),
    ("61925HLO0059", "HLO", "BLOUSE 'P.G.P'", "Ensemble", 5, 2),
    ("61925HLO0060", "HLO", "BLOUSE 'PHARMACIEN'", "Ensemble", 5, 2),
    ("61925HLO0061", "HLO", "BLOUSE 'PLOMBIER'", "Ensemble", 5, 2),
    ("61925HLO0062", "HLO", "BLOUSE 'POMPIER CIVIL'", "Ensemble", 5, 2),
    ("61925HLO0063", "HLO", "BLOUSE 'PROFESSEUR'", "Ensemble", 5, 2),
    ("61925HLO0064", "HLO", "BLOUSE 'PUERICULTRICE'", "Ensemble", 5, 2),
    ("61925HLO0065", "HLO", "BLOUSE 'S.U.S'", "Ensemble", 5, 2),
    ("61925HLO0066", "HLO", "BLOUSE 'S.U.S-DELEGUE'", "Ensemble", 5, 2),
    ("61925HLO0067", "HLO", "BLOUSE 'S.U.S-DELEGUEE PUERICULTRICE'", "Ensemble", 5, 2),
    ("61925HLO0068", "HLO", "BLOUSE 'S.U.S-DELEGUEE SAGE-FEMME'", "Ensemble", 5, 2),
    ("61925HLO0069", "HLO", "BLOUSE 'SECRETAIRE'", "Ensemble", 5, 2),
    ("61925HLO0070", "HLO", "BLOUSE 'SERVICE QUALITE'", "Ensemble", 5, 2),
    ("61925HLO0071", "HLO", "BLOUSE 'STAGIAIRE'", "Ensemble", 10, 5),
    ("61925HLO0072", "HLO", "BLOUSE 'SURVEILLANT GENERAL'", "Ensemble", 5, 2),
    ("61925HLO0073", "HLO", "BLOUSE 'T.S - BIOLOGIE MEDICALE'", "Ensemble", 5, 2),
    ("61925HLO0074", "HLO", "BLOUSE 'T.S - BIOMEDICAL'", "Ensemble", 5, 2),
    ("61925HLO0075", "HLO", "BLOUSE 'T.S.H.A'", "Ensemble", 5, 2),
    ("61925HLO0076", "HLO", "BLOUSE 'T.S.I.M'", "Ensemble", 5, 2),
    ("61925HLO0077", "HLO", "BLOUSE 'T.S.S'", "Ensemble", 5, 2),
    ("61925HLO0078", "HLO", "CALOT EN TISSU - Vert", "Unité", 10, 5),
    ("61925HLO0079", "HLO", "CASAQUE MEDECIN 'BLOC OPERATOIRE'", "Unité", 5, 2),
    ("61925HLO0080", "HLO", "CASAQUE MEDECIN 'ENDOSCOPIE DIGESTIVE'", "Unité", 5, 2),
    ("61925HLO0081", "HLO", "CASAQUE MEDECIN 'GYNECOLOGIE OBSTERICALE'", "Unité", 5, 2),
    ("61925HLO0082", "HLO", "CHAMP DOUBLE - 50x50", "Unité", 10, 5),
    ("61925HLO0083", "HLO", "CHAMP NON TROUE - 120x180", "Unité", 5, 2),
    ("61925HLO0084", "HLO", "CHAMP NON TROU - 150x200", "Unité", 5, 2),
    ("61925HLO0085", "HLO", "CHAMP NON TROUE - 60x70", "Unité", 10, 5),
    ("61925HLO0086", "HLO", "CHAMP NON TROUE - 70x150", "Unité", 5, 2),
    ("61925HLO0087", "HLO", "CHAMP NON TROUE - 75x90", "Unité", 10, 5),
    ("61925HLO0088", "HLO", "CHAMP NON TROUE - 90x90", "Unité", 10, 5),
    ("61925HLO0089", "HLO", "CHAMP NON TROUE - 90x125", "Unité", 5, 2),
    ("61925HLO0090", "HLO", "CHAMP TROUE - 120x180", "Unité", 5, 2),
    ("61925HLO0091", "HLO", "CHAMP TROUE - 150x200", "Unité", 5, 2),
    ("61925HLO0092", "HLO", "CHAMP TROUE - 90x90", "Unité", 10, 5),
    ("61925HLO0093", "HLO", "CHAMP TROUE (15/18) - 90x90", "Unité", 5, 2),
    ("61925HLO0094", "HLO", "MANTEAU IMPERMEABLE", "Ensemble", 5, 2),
    ("61925HLO0095", "HLO", "PYJAMA DE TRAVAIL 'BLOC OPERATOIRE'", "Ensemble", 5, 2),
    ("61925HLO0096", "HLO", "PYJAMA DE TRAVAIL 'GYNECOLOGIE OBSTETRIQUE'", "Ensemble", 5, 2),
    ("61925HLO0097", "HLO", "PYJAMA DE TRAVAIL 'REANIMATION'", "Ensemble", 5, 2),
    ("61925HLO0098", "HLO", "PYJAMA DE TRAVAIL (Bleu) 'STERILISATION'", "Ensemble", 5, 2),
    ("61925HLO0099", "HLO", "PYJAMA DE TRAVAIL (Jaune) 'STERILISATION'", "Ensemble", 5, 2),
    ("61925HLO0100", "HLO", "SURCHAUSSURES (Beige) 'BLOC OPERATOIRE'", "Paire", 5, 2),
    ("61925HLO0101", "HLO", "SURCHAUSSURES (Vert) 'GYNECOLOGIE OBSTETRICALE'", "Paire", 5, 2),
    ("61925HLO0102", "HLO", "BLOUSE 'D.E.S - CHIRURGIE'", "Unité", 5, 2),
    ("61925HLO0103", "HLO", "BLOUSE 'D.E.S - GERIATRIE'", "Ensemble", 5, 2),
    ("61925HLO0104", "HLO", "BLOUSE 'D.E.S - IMAGERIE MEDICALE'", "Ensemble", 5, 2),
    ("61925HLO0105", "HLO", "BLOUSE 'ASSISTANT MPR'", "Ensemble", 5, 2),
    ("61925HLO0106", "HLO", "BLOUSE 'SAGE-FEMME'", "Ensemble", 5, 2),
    ("61925HLO0107", "HLO", "BLOUSE 'VISITEUR - STERILISATION'", "Ensemble", 5, 2),
    ("61925HLO0108", "HLO", "BLOUSE 'BUREAU DES ENTREES'", "Unité", 5, 2),
    ("61925HLO0109", "HLO", "BLOUSE 'INGENIEUR DES TECHNIQUES SANITAIRES : BIO-MEDICAL'", "Ensemble", 5, 2),
    ("61925HLO0110", "HLO", "BLOUSE 'S/D SIM'", "Ensemble", 5, 2),

    # ======================= FOH =======================
    ("61926FOH0001", "FOH", "COUETTE BEBE NEONATALOGIE - 1m x 1m", "Unité", 3, 1),
    ("61926FOH0002", "FOH", "COUETTE CAT.A - GYNECOLOGIE OBSTETRICALE (HOSPIT)", "Unité", 5, 2),
    ("61926FOH0003", "FOH", "COUETTE CAT.A - MEDECINE INTERNE & GERIATRIE (HOSPIT)", "Unité", 5, 2),
    ("61926FOH0004", "FOH", "COUETTE CAT.A - ORTHO, TRAUMATO, CHIRURGIE PLASTIQUE (HOSPIT)", "Unité", 5, 2),
    ("61926FOH0005", "FOH", "COUETTE CAT.A - PEDIATRIE MEDICALE & SPECIALITES (HOSPIT)", "Unité", 5, 2),
    ("61926FOH0006", "FOH", "COUETTE CAT.A - REANIMATION", "Unité", 3, 1),
    ("61926FOH0007", "FOH", "COUETTE CAT.O - GYNECOLOGIE OBSTETRICALE (HOSPIT)", "Unité", 5, 2),
    ("61926FOH0008", "FOH", "COUETTE CAT.O - MEDECINE INTERNE & GERIATRIE (HOSPIT)", "Unité", 5, 2),
    ("61926FOH0009", "FOH", "COUETTE CAT.O - ORTHO, TRAUMATO, CHIRURGIE PLASTIQUE (HOSPIT)", "Unité", 5, 2),
    ("61926FOH0010", "FOH", "COUETTE CAT.O - PEDIATRIE MEDICALE & SPECIALITES (HOSPIT)", "Unité", 5, 2),
    ("61926FOH0011", "FOH", "COUETTE BEBE - PEDIATRIE MEDICALE & SPECIALITES (HOSPIT)", "Unité", 3, 1),
    ("61926FOH0012", "FOH", "COUETTE CAT.O - GYNECOLOGIE OBSTETRICALE (SUITE DE COUCHES)", "Unité", 5, 2),
    ("61926FOH0013", "FOH", "COUETTE CAT.O - GYNECOLOGIE OBSTETRICALE (URGENCES)", "Unité", 5, 2),
    ("61926FOH0014", "FOH", "COUETTE CAT.O - MEDECINE INTERNE & GERIATRIE (URGENCES)", "Unité", 5, 2),
    ("61926FOH0015", "FOH", "COUETTE CAT.O - ORTHO, TRAUMATO, CHIRURGIE PLASTIQUE (URGENCES)", "Unité", 5, 2),
    ("61926FOH0016", "FOH", "COUETTE CAT.O - PEDIATRIE MEDICALE & SPECIALITES (URGENCES)", "Unité", 5, 2),
    ("61926FOH0017", "FOH", "DRAP DE LIT - COCAN", "Unité", 10, 5),
    ("61926FOH0018", "FOH", "DRAP DE LIT 1,75m x 1m - PEDIATRIE MEDICALE & SPECIALITES", "Unité", 5, 2),
    ("61926FOH0019", "FOH", "DRAP DE LIT 1,75m x 1m - SALLE D'ACCOUCHEMENT", "Unité", 5, 2),
    ("61926FOH0020", "FOH", "DRAP DE LIT 1,75m x 1m - SUITE DE COUCHES", "Unité", 5, 2),
    ("61926FOH0021", "FOH", "DRAP DE LIT 1m x 0,75m - GYNECOLOGIE OBSTETRICALE", "Unité", 5, 2),
    ("61926FOH0022", "FOH", "DRAP DE LIT 1m x 0,75m - PEDIATRIE MEDICALE & SPECIALITES", "Unité", 5, 2),
    ("61926FOH0023", "FOH", "DRAP DE LIT 2,5m x 1,5m - ANESTHESIE & REANIMATION", "Unité", 10, 5),
    ("61926FOH0024", "FOH", "DRAP DE LIT 2,5m x 1,5m - ORTHO, TRAUMATO, CHIRURGIE PLASTIQUE", "Unité", 10, 5),
    ("61926FOH0025", "FOH", "DRAP DE LIT 2,5m x 1,5m - ENDOSCOPIE DIGESTIVE", "Unité", 5, 2),
    ("61926FOH0026", "FOH", "DRAP DE LIT 2,5m x 1,5m - GYNECOLOGIE OBSTETRICALE", "Unité", 10, 5),
    ("61926FOH0027", "FOH", "DRAP DE LIT 2,5m x 1,5m - MEDECINE DU TRAVAIL", "Unité", 5, 2),
    ("61926FOH0028", "FOH", "DRAP DE LIT 2,5m x 1,5m - MEDECINE INTERNE & GERIATRIE", "Unité", 10, 5),
    ("61926FOH0029", "FOH", "DRAP DE LIT 2,5m x 1,5m - MEDECINE PHYSIQUE & READAPTATION", "Unité", 5, 2),
    ("61926FOH0030", "FOH", "DRAP DE LIT 2,5m x 1,5m - PEDIATRIE MEDICALE & SPECIALITES", "Unité", 10, 5),
    ("61926FOH0031", "FOH", "DRAP DE LIT 2,5m x 1,5m - SALLE D'ACCOUCHEMENT", "Unité", 5, 2),
    ("61926FOH0032", "FOH", "DRAP DE LIT 2,5m x 1,5m - STERILISATION", "Unité", 5, 2),
    ("61926FOH0033", "FOH", "DRAP DE LIT 2,5m x 1,5m - SUITE DE COUCHES", "Unité", 5, 2),
    ("61926FOH0034", "FOH", "DRAP DE LIT 2,5m x 1,5m - URGENCES CHIRURGIE", "Unité", 5, 2),
    ("61926FOH0035", "FOH", "DRAP DE LIT 2,5m x 1,5m - URGENCES GYNECOLOGIE OBSTETRICALE", "Unité", 5, 2),
    ("61926FOH0036", "FOH", "DRAP DE LIT 2,5m x 1,5m - URGENCES MEDECINE INTERNE & GERIATRIE", "Unité", 5, 2),
    ("61926FOH0037", "FOH", "DRAP DE LIT 2,5m x 1,5m - URGENCES PEDIATRIE MEDICALE", "Unité", 5, 2),
    ("61926FOH0038", "FOH", "DRAP DE LIT 2,5m x 1,5m - URGENCES TRAUMATOLOGIE", "Unité", 5, 2),
    ("61926FOH0039", "FOH", "DRAP DE LIT 2,5m x 1,5m - IMAGERIE MEDICALE", "Unité", 5, 2),
    ("61926FOH0040", "FOH", "OREILLER - Adulte", "Unité", 10, 5),
    ("61926FOH0041", "FOH", "OREILLER - Enfant", "Unité", 5, 2),
    ("61926FOH0042", "FOH", "TAIE D'OREILLER - COCAN", "Unité", 10, 5),
    ("61926FOH0043", "FOH", "TAIE D'OREILLER - Adulte", "Unité", 10, 5),
    ("61926FOH0044", "FOH", "TAIE D'OREILLER - Enfant", "Unité", 5, 2),
    ("61926FOH0045", "FOH", "THERMOS DE GAVAGE", "Unité", 3, 1),
    ("61926FOH0046", "FOH", "THERMOS D'EAU CHAUDE", "Unité", 3, 1),

    # ======================= IMM (Imprimés Médicaux) =======================
    ("61927IMM0001", "IMM", "ARRET DE SCOLARITE", "Bloc", 10, 5),
    ("61927IMM0002", "IMM", "ARRET DE TRAVAIL", "Bloc", 10, 5),
    ("61927IMM0003", "IMM", "ATTESTATION DE PRE-ENREGISTREMENT DE NAISSANCE", "Carnet", 5, 2),
    ("61927IMM0004", "IMM", "ATTESTATION MEDICALE DE DECES", "Carnet", 5, 2),
    ("61927IMM0005", "IMM", "ATTESTATION MEDICALE DE NAISSANCE", "Carnet", 5, 2),
    ("61927IMM0006", "IMM", "AVIS", "Bloc", 10, 5),
    ("61927IMM0007", "IMM", "AVIS D'HOSPITALISATION", "Bloc", 10, 5),
    ("61927IMM0008", "IMM", "BILAN DE KINESITHERAPIE", "Unité", 5, 2),
    ("61927IMM0009", "IMM", "BILAN KINE A L'ENTREE", "Unité", 5, 2),
    ("61927IMM0010", "IMM", "BILAN KINE DE FIN DE SEANCES", "Unité", 5, 2),
    ("61927IMM0011", "IMM", "BON DE COMMANDE INTERNE", "Carnet", 5, 2),
    ("61927IMM0012", "IMM", "BON DE DEPOT ET LIVRAISON DU MATERIEL", "Carnet", 5, 2),
    ("61927IMM0013", "IMM", "BON DE REPAS", "Bloc", 10, 5),
    ("61927IMM0014", "IMM", "BON DE SANG", "Bloc", 5, 2),
    ("61927IMM0015", "IMM", "BON DE TRACABILITE DES BOITES DU BLOC OPERATOIRE", "Carnet", 3, 1),
    ("61927IMM0016", "IMM", "BON DE TRACABILITE DES EMBALLAGES INDIVIDUELS", "Carnet", 3, 1),
    ("61927IMM0017", "IMM", "BON DE TRACABILITE DES INSTRUMENTS DU BLOC OPERATOIRE", "Carnet", 3, 1),
    ("61927IMM0018", "IMM", "BON POUR LA DESINFECTION DES LOCAUX", "Carnet", 3, 1),
    ("61927IMM0019", "IMM", "BORDEREAU DE TRANSMISSION DES ATTESTATIONS DE PRE-ENREGISTREMENT", "Carnet", 3, 1),
    ("61927IMM0020", "IMM", "BORDEREAU DE TRANSMISSION DES ATTESTATIONS MEDICALES", "Carnet", 3, 1),
    ("61927IMM0021", "IMM", "BORDEREAU D'ECHANGE ET DE TRANSFERT DES PRODUITS PHARMACIE", "Carnet", 3, 1),
    ("61927IMM0022", "IMM", "BULLETIN DE CONSULTATION", "Bloc", 10, 5),
    ("61927IMM0023", "IMM", "BULLETIN DE SOINS ET PROTHESES DENTAIRES", "Bloc", 5, 2),
    ("61927IMM0024", "IMM", "BULLETIN D'IMAGERIE MEDICALE", "Bloc", 10, 5),
    ("61927IMM0025", "IMM", "CAHIER DE DOTATION DES SERVICES EN PRODUITS & CONSOMMABLES", "Unité", 3, 1),
    ("61927IMM0026", "IMM", "CAHIER DE SUIVI", "Unité", 3, 1),
    ("61927IMM0027", "IMM", "CAHIER D'ECHANGE ET DE TRANSFERT", "Unité", 3, 1),
    ("61927IMM0028", "IMM", "CAHIER D'OBSERVATION DE MALADES - GYNECOLOGIE OBSTETRICALE", "Unité", 3, 1),
    ("61927IMM0029", "IMM", "CAHIER D'OBSERVATION DE MALADES - MEDECINE PHYSIQUE & READAPTATION", "Unité", 3, 1),
    ("61927IMM0030", "IMM", "CAHIER D'OBSERVATION DE MALADES - MEDECINE INTERNE (URGENCES)", "Unité", 3, 1),
    ("61927IMM0031", "IMM", "CAHIER D'OBSERVATION DE MALADES - MEDECINE INTERNE (HOSPIT)", "Unité", 3, 1),
    ("61927IMM0032", "IMM", "CARNET DE SANTE MERE-ENFANT", "Unité", 5, 2),
    ("61927IMM0033", "IMM", "CARTE AUDIOGRAMME", "Unité", 5, 2),
    ("61927IMM0034", "IMM", "CARTE ECG", "Unité", 5, 2),
    ("61927IMM0035", "IMM", "CARTE ETIQUETTE BEBE - Bleue", "Unité", 10, 5),
    ("61927IMM0036", "IMM", "CARTE ETIQUETTE BEBE - Rose", "Unité", 10, 5),
    ("61927IMM0037", "IMM", "CARTE ETIQUETTE BEBE NEONATALOGIE - Bleue", "Unité", 5, 2),
    ("61927IMM0038", "IMM", "CARTE ETIQUETTE BEBE NEONATALOGIE - Rose", "Unité", 5, 2),
    ("61927IMM0039", "IMM", "CARTE RDV CONSULTATION - ANESTHESIE & REANIMATION", "Unité", 5, 2),
    ("61927IMM0040", "IMM", "CARTE RDV CONSULTATION - GYNECOLOGIE OBSTETRICALE", "Unité", 5, 2),
    ("61927IMM0041", "IMM", "CARTE RDV CONSULTATION - MEDECINE DU TRAVAIL", "Unité", 5, 2),
    ("61927IMM0042", "IMM", "CARTE RDV CONSULTATION - MEDECINE INTERNE & GERIATRIE", "Unité", 5, 2),
    ("61927IMM0043", "IMM", "CARTE RDV CONSULTATION - MEDECINE PHYSIQUE & READAPTATION", "Unité", 5, 2),
    ("61927IMM0044", "IMM", "CARTE RDV CONSULTATION - ORTHO, TRAUMATO, CHIRURGIE PLASTIQUE", "Unité", 5, 2),
    ("61927IMM0045", "IMM", "CARTE RDV CONSULTATION - PEDIATRIE MEDICALE & SPECIALITES", "Unité", 5, 2),
    ("61927IMM0046", "IMM", "CARTE : FICHE DE LIAISON - MEDECINE PHYSIQUE & READAPTATION", "Unité", 5, 2),
    ("61927IMM0047", "IMM", "CARTE : FICHE DE SUIVI DES SOINS - MEDECINE PHYSIQUE & READAPTATION", "Unité", 5, 2),
    ("61927IMM0048", "IMM", "CARTE : GYNECOLOGIE OBSTETRICALE", "Unité", 5, 2),
    ("61927IMM0049", "IMM", "CERTIFICAT DE DECES OU DE MORTALITE", "Unité", 5, 2),
    ("61927IMM0050", "IMM", "CERTIFICAT DE GENRE DE MORT", "Unité", 5, 2),
    ("61927IMM0051", "IMM", "CERTIFICAT DE GROSSESSE", "Bloc", 5, 2),
    ("61927IMM0052", "IMM", "CERTIFICAT DE NON CONTAGION", "Bloc", 5, 2),
    ("61927IMM0053", "IMM", "CERTIFICAT D'HOSPITALISATION", "Bloc", 5, 2),
    ("61927IMM0054", "IMM", "CERTIFICAT MEDICAL DE L'ACCOMPAGNANT", "Bloc", 5, 2),
    ("61927IMM0055", "IMM", "CERTIFICAT MEDICAL DE NAISSANCE", "Carnet", 5, 2),
    ("61927IMM0056", "IMM", "CHEMISE DE COLOSCOPIE", "Unité", 5, 2),
    ("61927IMM0057", "IMM", "CHEMISE DE CONSULTATION M.P.R - Adulte", "Unité", 5, 2),
    ("61927IMM0058", "IMM", "CHEMISE DE CONSULTATION M.P.R - Enfant", "Unité", 5, 2),
    ("61927IMM0059", "IMM", "CHEMISE DE FIBROSCAN", "Unité", 5, 2),
    ("61927IMM0060", "IMM", "CHEMISE DE GASTROSCOPIE", "Unité", 5, 2),
    ("61927IMM0061", "IMM", "CHEMISE D'ECHOGRAPHIE", "Unité", 5, 2),
    ("61927IMM0062", "IMM", "CHEMISE DES ACTES MEDICAUX (Dossier Rose)", "Unité", 5, 2),
    ("61927IMM0063", "IMM", "CHEMISE D'EXPLORATION CARDIO-VASCULAIRE", "Unité", 5, 2),
    ("61927IMM0064", "IMM", "CONSENTEMENT PREALABLE A UNE INTERVENTION CHIRURGICALE", "Unité", 5, 2),
    ("61927IMM0065", "IMM", "DOSSIER INDIVIDUEL DE CONSULTATION DE PLANIFICATION FAMILIALE", "Unité", 5, 2),
    ("61927IMM0066", "IMM", "DOSSIER INDIVIDUEL DU PATIENT", "Unité", 5, 2),
    ("61927IMM0067", "IMM", "DOSSIER MEDICAL - MEDECINE DU TRAVAIL", "Unité", 5, 2),
    ("61927IMM0068", "IMM", "DOSSIER OBSTETRICAL D'ACCOUCHEMENT", "Unité", 5, 2),
    ("61927IMM0069", "IMM", "FEUILLE D'ALIMENTATION", "Unité", 10, 5),
    ("61927IMM0070", "IMM", "FEUILLE D'ANESTHESIE", "Unité", 5, 2),
    ("61927IMM0071", "IMM", "FEUILLE DE BIOLOGIE", "Unité", 10, 5),
    ("61927IMM0072", "IMM", "FEUILLE DE PRESCRIPTION MEDICALE", "Unité", 10, 5),
    ("61927IMM0073", "IMM", "FEUILLE DE SOINS DE L'AIDE-SOIGNANT", "Unité", 10, 5),
    ("61927IMM0074", "IMM", "FEUILLE DE SURVEILLANCE INFIRMIERE", "Unité", 10, 5),
    ("61927IMM0075", "IMM", "FEUILLE DE TEMPERATURE", "Unité", 10, 5),
    ("61927IMM0076", "IMM", "FICHE D'ADMISSION", "Liasse", 10, 5),
    ("61927IMM0077", "IMM", "FICHE DE CONSOMMATION PHARMACIE", "Carnet", 5, 2),
    ("61927IMM0078", "IMM", "BULLETIN D'ANALYSES BIOLOGIQUES - Laboratoire Central", "Unité", 10, 5),
    ("61927IMM0079", "IMM", "BULLETIN D'ANALYSES BIOLOGIQUES - Unité des Urgences", "Unité", 10, 5),
    ("61927IMM0080", "IMM", "FICHE DE DISPENSE D'EDUCATION PHYSIQUE", "Bloc", 5, 2),
    ("61927IMM0081", "IMM", "FICHE DE LIAISON - MEDECINE PHYSIQUE & READAPTATION", "Unité", 5, 2),
    ("61927IMM0082", "IMM", "FICHE DE LIVRAISON & DE TRACABILITE DES DMIS", "Unité", 3, 1),
    ("61927IMM0083", "IMM", "FICHE DE REQUETE OPERATOIRE", "Unité", 5, 2),
    ("61927IMM0084", "IMM", "FICHE DE STOCK DE PHARMACIE", "Unité", 3, 1),
    ("61927IMM0085", "IMM", "FICHE DE SURVEILLANCE SSPI", "Unité", 5, 2),
    ("61927IMM0086", "IMM", "FICHE DE TRAITEMENT DES NON-CONFORMITES", "Liasse", 3, 1),
    ("61927IMM0087", "IMM", "FICHE D'IDENTIFICATION DU PATIENT AUX URGENCES - Adulte", "Liasse", 10, 5),
    ("61927IMM0088", "IMM", "FICHE D'IDENTIFICATION DU PATIENT AUX URGENCES - Enfant", "Liasse", 10, 5),
    ("61927IMM0089", "IMM", "FICHE KINE - CONSIGNES", "Unité", 5, 2),
    ("61927IMM0090", "IMM", "INTERCALAIRE - Dossier Médecine du Travail", "Unité", 5, 2),
    ("61927IMM0091", "IMM", "INTERCALAIRE - Dossier Médical", "Unité", 5, 2),
    ("61927IMM0092", "IMM", "ORDONNANCIER D'OPHTALMOLOGIE", "Bloc", 5, 2),
    ("61927IMM0093", "IMM", "ORDONNANCIER EXTERNE", "Bloc", 5, 2),
    ("61927IMM0094", "IMM", "ORDONNANCIER INTERNE", "Bloc", 5, 2),
    ("61927IMM0095", "IMM", "POCHETTE DE RADIOLOGIE - A2", "Unité", 3, 1),
    ("61927IMM0096", "IMM", "POCHETTE DE RADIOLOGIE - A3", "Unité", 3, 1),
    ("61927IMM0097", "IMM", "POCHETTE DE RADIOLOGIE - A4", "Unité", 5, 2),
    ("61927IMM0098", "IMM", "PROCES-VERBAL DE CONSTATATION DE DECES", "Bloc", 3, 1),
    ("61927IMM0099", "IMM", "RAPPORT MEDICAL", "Unité", 5, 2),
    ("61927IMM0100", "IMM", "REGISTRE D'ACCOUCHEMENT", "Unité", 3, 1),
    ("61927IMM0101", "IMM", "REGISTRE DE CONSULTATION CURATIVE", "Unité", 3, 1),
    ("61927IMM0102", "IMM", "REGISTRE DE CONSULTATION DE PLANIFICATION FAMILIALE", "Unité", 3, 1),
    ("61927IMM0103", "IMM", "REGISTRE DE CONSULTATION POST-NATALE", "Unité", 3, 1),
    ("61927IMM0104", "IMM", "REGISTRE DE CONSULTATION PRENATALE", "Unité", 3, 1),
    ("61927IMM0105", "IMM", "REGISTRE DE DEPISTAGE PAR LES TESTS RAPIDES", "Unité", 3, 1),
    ("61927IMM0106", "IMM", "REGISTRE DE L'ANESTHESISTE", "Unité", 3, 1),
    ("61927IMM0107", "IMM", "REGISTRE DE L'INSTRUMENTISTE", "Unité", 3, 1),
    ("61927IMM0108", "IMM", "REGISTRE DE REFERENCE ET CONTRE-REFERENCE", "Unité", 3, 1),
    ("61927IMM0109", "IMM", "REGISTRE DE SALLE DE SURVEILLANCE POST-INTERVENTIONNELLE", "Unité", 3, 1),
    ("61927IMM0110", "IMM", "REGISTRE DE SUIVI DES ACTES OPERATOIRES", "Unité", 3, 1),
    ("61927IMM0111", "IMM", "REGISTRE DE SUIVI DES ACTIVITES DE LA BANQUE DE SANG", "Unité", 3, 1),
    ("61927IMM0112", "IMM", "REGISTRE DE SUIVI DES REFERENCES & CONTRE-REFERENCES", "Unité", 3, 1),
    ("61927IMM0113", "IMM", "REGISTRE DE SUIVI ET DE GESTION DES CHARGES VIRALES", "Unité", 3, 1),
    ("61927IMM0114", "IMM", "REGISTRE DE SUIVI PTME MERE-ENFANT", "Unité", 3, 1),
    ("61927IMM0115", "IMM", "REGISTRE DE VACCINATION", "Unité", 3, 1),
    ("61927IMM0116", "IMM", "REGISTRE DE VISITE POUR LES SOINS ET SOUTIENS", "Unité", 3, 1),
    ("61927IMM0117", "IMM", "REGISTRE ENTREE-SORTIE", "Unité", 3, 1),
    ("61927IMM0118", "IMM", "REGISTRE INDEX TESTING", "Unité", 3, 1),

    # ======================= INM (Imprimés Non Médicaux) =======================
    ("61928INM0001", "INM", "CHEMISE DE DOSSIER - ASSISTANCE SOCIALE (DRH)", "Unité", 5, 2),
    ("61928INM0002", "INM", "CHEMISE DE DOSSIER - PERSONNEL (DRH)", "Unité", 5, 2),
    ("61928INM0003", "INM", "FICHE DE DEMANDE D'INTERVENTION (DT)", "Carnet", 3, 1),
    ("61928INM0004", "INM", "TICKET DE RESTAURANT", "Carnet", 10, 5),
    ("61928INM0005", "INM", "FEUILLES DE RECU SECURISE", "Unité", 10, 5),
    ("61928INM0006", "INM", "FEUILLES DE RECU SPECIAL", "Unité", 10, 5),
    ("61928INM0007", "INM", "FEUILLES DE FACTURE SECURISEE", "Unité", 10, 5),
    ("61928INM0008", "INM", "CARNET DE RECUS SECURISES", "Unité", 5, 2),
    ("61928INM0009", "INM", "CARNET DE FACTURES SECURISEES", "Unité", 5, 2),

    # ======================= FHS =======================
    ("6193FHS00001", "FHS", "ALEZE EN SKAI (Beige) - Petit", "Unité", 5, 2),
    ("6193FHS00002", "FHS", "ALEZE EN SKAI (Beige) - Standard", "Unité", 5, 2),
    ("6193FHS00003", "FHS", "ALEZE EN SKAI (Verte) - Standard", "Unité", 5, 2),
    ("6193FHS00004", "FHS", "ALEZE EN PLASTIQUE", "Unité", 5, 2),
    ("6193FHS00005", "FHS", "BALAI A MANCHE", "Unité", 5, 2),
    ("6193FHS00006", "FHS", "BOCAL DE LAIT", "Unité", 3, 1),
    ("6193FHS00007", "FHS", "BROSSE A ONGLE", "Unité", 5, 2),
    ("6193FHS00008", "FHS", "BROSSE A MANCHE", "Unité", 5, 2),
    ("6193FHS00009", "FHS", "CHAMP ABDOMINAL (Couche carrée)", "Unité", 10, 5),
    ("6193FHS00010", "FHS", "CHIFFON MOUSSE SEC", "Unité", 10, 5),
    ("6193FHS00011", "FHS", "COUCHE A USAGE UNIQUE - Adulte", "Unité", 20, 10),
    ("6193FHS00012", "FHS", "COUCHE A USAGE UNIQUE - Enfant", "Unité", 20, 10),
    ("6193FHS00013", "FHS", "COUCHE CULOTTE A USAGE UNIQUE - Adulte", "Unité", 10, 5),
    ("6193FHS00014", "FHS", "ECOUVILLON DE FLACON (Stérilisation)", "Unité", 10, 5),
    ("6193FHS00015", "FHS", "ECOUVILLON DE BIBERON", "Unité", 10, 5),
    ("6193FHS00016", "FHS", "EPONGE DE BAIN HYGIENIQUE - Simple", "Unité", 10, 5),
    ("6193FHS00017", "FHS", "EPONGE DE BAIN HYGIENIQUE - à filet", "Unité", 10, 5),
    ("6193FHS00018", "FHS", "ESSUIE-TOUT", "Rouleau", 10, 5),
    ("6193FHS00019", "FHS", "FLACON DE DESODORISANT", "Unité", 5, 2),
    ("6193FHS00020", "FHS", "FLACON D'INSECTICIDE", "Unité", 5, 2),
    ("6193FHS00021", "FHS", "GANT DE CUISINE", "Unité", 5, 2),
    ("6193FHS00022", "FHS", "GANT DE MENAGE", "Paire", 10, 5),
    ("6193FHS00023", "FHS", "GANT EN CUIR", "Paire", 3, 1),
    ("6193FHS00024", "FHS", "GOBELET JETABLE", "Unité", 50, 20),
    ("6193FHS00025", "FHS", "MOUCHOIR A USAGE UNIQUE", "Unité", 50, 20),
    ("6193FHS00026", "FHS", "MOUCHOIR NETTY (Souple et absorbant)", "Unité", 20, 10),
    ("6193FHS00027", "FHS", "PAPIER HYGIENIQUE", "Rouleau", 20, 10),
    ("6193FHS00028", "FHS", "RACLETTE SOL", "Unité", 3, 1),
    ("6193FHS00029", "FHS", "RASOIR A USAGE UNIQUE", "Unité", 10, 5),
    ("6193FHS00030", "FHS", "SAC POUBELLE BLEU - 100 Litres", "Rouleau", 10, 5),
    ("6193FHS00031", "FHS", "SAC POUBELLE JAUNE - 100 Litres", "Rouleau", 10, 5),
    ("6193FHS00032", "FHS", "SAC POUBELLE MARRON - 100 Litres", "Rouleau", 10, 5),
    ("6193FHS00033", "FHS", "SAC POUBELLE NOIR - 100 Litres", "Rouleau", 10, 5),
    ("6193FHS00034", "FHS", "SAC POUBELLE ROUGE - 100 Litres", "Rouleau", 10, 5),
    ("6193FHS00035", "FHS", "SAC POUBELLE NOIR - 240 Litres", "Rouleau", 5, 2),
    ("6193FHS00036", "FHS", "SAC POUBELLE NOIR - 30 Litres", "Rouleau", 10, 5),
    ("6193FHS00037", "FHS", "SAC POUBELLE BLEU - 50 Litres", "Rouleau", 10, 5),
    ("6193FHS00038", "FHS", "SAC POUBELLE JAUNE - 50 Litres", "Rouleau", 10, 5),
    ("6193FHS00039", "FHS", "SAC POUBELLE MARRON - 50 Litres", "Rouleau", 10, 5),
    ("6193FHS00040", "FHS", "SAC POUBELLE NOIR - 50 Litres", "Rouleau", 10, 5),
    ("6193FHS00041", "FHS", "SAC POUBELLE ROUGE - 50 Litres", "Rouleau", 10, 5),
    ("6193FHS00042", "FHS", "SEAU DE BAIN", "Unité", 3, 1),
    ("6193FHS00043", "FHS", "SEAU ESSOREUR", "Unité", 3, 1),
    ("6193FHS00044", "FHS", "SERPILLERE A MANCHE", "Unité", 5, 2),
    ("6193FHS00045", "FHS", "SERPILLERE D'ENTRETIEN", "Unité", 5, 2),
    ("6193FHS00046", "FHS", "SERPILLERE EN PEAU DE CHAMOIS", "Unité", 3, 1),
    ("6193FHS00047", "FHS", "SERVIETTE DE BAIN", "Unité", 10, 5),
    ("6193FHS00048", "FHS", "SERVIETTE HYGIENIQUE DE TABLE (Néonatalogie)", "Unité", 10, 5),
    ("6193FHS00049", "FHS", "SERVIETTE HYGIENIQUE POST-ACCOUCHEMENT", "Unité", 10, 5),
    ("6193FHS00050", "FHS", "SLIP A USAGE UNIQUE", "Unité", 20, 10),
    ("6193FHS00051", "FHS", "TABLIER A USAGE UNIQUE", "Unité", 10, 5),
    ("6193FHS00052", "FHS", "TABLIER DE PROTECTION", "Unité", 5, 2),
    ("6193FHS00053", "FHS", "TABLIER EN PLASTIQUE", "Unité", 5, 2),
    ("6193FHS00054", "FHS", "TABLIER EN SKAI (Beige)", "Unité", 3, 1),
    ("6193FHS00055", "FHS", "TABLIER EN SKAI (Vert)", "Unité", 3, 1),
    ("6193FHS00056", "FHS", "SAC POUBELLE JAUNE - 30 Litres", "Unité", 10, 5),
    ("6193FHS00057", "FHS", "SAC POUBELLE JAUNE - 240 Litres", "Rouleau", 5, 2),
    ("6193FHS00058", "FHS", "GEL HYDROALCOOLIQUE", "Pot", 10, 5),
    ("6193FHS00059", "FHS", "STERILISEUR DE BIBERON", "Unité", 2, 1),

    # ======================= PRE =======================
    ("6198PRE00001", "PRE", "EAU DE JAVEL - 1Litre", "Pot", 10, 5),
    ("6198PRE00002", "PRE", "EAU DE JAVEL - 10 Litres", "Pot", 5, 2),
    ("6198PRE00003", "PRE", "EAU DE JAVEL - 20 Litres", "Pot", 3, 1),
    ("6198PRE00004", "PRE", "EAU DE JAVEL - 350 ml", "Pot", 10, 5),
    ("6198PRE00005", "PRE", "GEL DOUCHE", "Pot", 10, 5),
    ("6198PRE00006", "PRE", "POUDRE PARFUMEE", "Pot", 5, 2),
    ("6198PRE00007", "PRE", "SAVON DE BAIN (25g)", "Unité", 50, 20),
    ("6198PRE00008", "PRE", "SAVON LIQUIDE DE MAIN (350ml)", "Pot", 10, 5),
    ("6198PRE00009", "PRE", "SAVON LIQUIDE MULTI-USAGE (1 litre)", "Pot", 10, 5),
    ("6198PRE00010", "PRE", "SAVON LIQUIDE MULTI-USAGE (20 Litres)", "Pot", 3, 1),

    # ======================= AFE =======================
    ("6199AFE00001", "AFE", "BAC DE TREMPAGE - 10 Litres", "Unité", 2, 1),
    ("6199AFE00002", "AFE", "BAC DE TREMPAGE - 20 Litres", "Unité", 2, 1),
    ("6199AFE00003", "AFE", "BAC DE TREMPAGE - 30 Litres", "Unité", 2, 1),
    ("6199AFE00004", "AFE", "BAC DE TREMPAGE - 5 Litres", "Unité", 3, 1),
    ("6199AFE00005", "AFE", "BAC DE TREMPAGE - 50 Litres", "Unité", 2, 1),
    ("6199AFE00006", "AFE", "BAC DE TREMPAGE - 60 Litres", "Unité", 2, 1),
    ("6199AFE00007", "AFE", "BAC DE TREMPAGE - 70 Litres", "Unité", 2, 1),
    ("6199AFE00008", "AFE", "BIBERION - 150ml", "Unité", 5, 2),
    ("6199AFE00009", "AFE", "BIBERON - 250ml", "Unité", 5, 2),
    ("6199AFE00010", "AFE", "BIBERON - 330ml", "Unité", 5, 2),
    ("6199AFE00011", "AFE", "BOUILLOIRE ELECTRIQUE", "Unité", 2, 1),
    ("6199AFE00012", "AFE", "CARAFE GRADUEE", "Unité", 3, 1),
    ("6199AFE00013", "AFE", "FOUET DE LAIT (Petit)", "Unité", 3, 1),
    ("6199AFE00014", "AFE", "GLACIERE - 10 Litres", "Unité", 2, 1),
    ("6199AFE00015", "AFE", "GLACIERE - 20 Litres", "Unité", 2, 1),
    ("6199AFE00016", "AFE", "GLACIERE - 4 Litres", "Unité", 3, 1),
    ("6199AFE00017", "AFE", "GLACIERE - 8 Litres", "Unité", 3, 1),
    ("6199AFE00018", "AFE", "METRE RUBAN", "Unité", 2, 1),
    ("6199AFE00019", "AFE", "MULTIPRISE ANTI-FOUDRE", "Unité", 3, 1),
    ("6199AFE00020", "AFE", "PAPIER ALLU", "Rouleau", 5, 2),
    ("6199AFE00021", "AFE", "PILE ALCALINE 9V (6LF22)", "Unité", 10, 5),
    ("6199AFE00022", "AFE", "PILE ALCALINE 1,5V (AA)", "Unité", 20, 10),
    ("6199AFE00023", "AFE", "PILE ALCALINE 1,5V (AAA)", "Unité", 20, 10),
    ("6199AFE00024", "AFE", "PILE ALCALINE 1,55V (LR41)", "Unité", 5, 2),
    ("6199AFE00025", "AFE", "PILE C2 1,5V (CLR14)", "Unité", 5, 2),
    ("6199AFE00026", "AFE", "PILE LITHIUM 3V (CR2032)", "Unité", 5, 2),
    ("6199AFE00027", "AFE", "PILE LITHIUM 6V (K223LA-1)", "Unité", 3, 1),
    ("6199AFE00028", "AFE", "STABILISATEUR D'ELECTRICITE - 1000 VA", "Unité", 2, 1),
    ("6199AFE00029", "AFE", "STABILISATEUR D'ELECTRICITE - 2000 VA", "Unité", 2, 1),
    ("6199AFE00030", "AFE", "STABILISATEUR D'ELECTRICITE - 3000 VA", "Unité", 1, 1),
    ("6199AFE00031", "AFE", "STABILISATEUR D'ELECTRICITE - 5000 VA", "Unité", 1, 1),
    ("6199AFE00032", "AFE", "BAC DE TREMPAGE - 100 Litres", "Unité", 1, 1),
]


class Command(BaseCommand):
    help = "Importe les données Sage 100 (familles, fournisseurs, services, articles)"

    def add_arguments(self, parser):
        parser.add_argument(
            '--entreprise-id',
            type=int,
            required=True,
            help="ID de l'entreprise (tenant) cible"
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
        entreprise_id = options['entreprise_id']
        dry_run = options['dry_run']
        skip_articles = options['skip_articles']
        skip_services = options['skip_services']

        self.stdout.write(self.style.NOTICE(f"Entreprise cible : {entreprise_id}"))
        if dry_run:
            self.stdout.write(self.style.WARNING("MODE DRY-RUN — Aucune écriture en base"))

        try:
            entreprise = Entreprise.objects.get(pk=entreprise_id)
        except Entreprise.DoesNotExist:
            self.stdout.write(self.style.ERROR(f"Entreprise {entreprise_id} introuvable."))
            return

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
                        entreprise=entreprise,
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
                        entreprise=entreprise,
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
                            entreprise=entreprise,
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
                            entreprise=entreprise,
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
