from django.contrib import admin
# ⚠️ Ajoute bien "Etage" dans l'import ici :
from .models import Immobilisation, Marque, Modele, Batiment, Etage, Bureau

admin.site.register(Immobilisation)
admin.site.register(Marque)
admin.site.register(Modele)
admin.site.register(Batiment)
admin.site.register(Etage)
admin.site.register(Bureau)