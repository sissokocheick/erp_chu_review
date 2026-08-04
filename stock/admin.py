# stock/admin.py — MONO-TENANT
from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils import timezone
from simple_history.admin import SimpleHistoryAdmin
from .models import (
    Article, Magasin, Fournisseur, FamilleArticle,
    Mouvement, BonMouvement, LigneBon, MotifAnnulation,
    Commande, LigneCommande, StockItem, CircuitValidation,
    CircuitValidateur
)


@admin.register(Fournisseur)
class FournisseurAdmin(SimpleHistoryAdmin):
    list_display = ('code', 'raison_sociale', 'est_agree', 'note_evaluation')
    search_fields = ('code', 'raison_sociale')
    list_filter = ('est_agree',)


@admin.register(FamilleArticle)
class FamilleArticleAdmin(SimpleHistoryAdmin):
    list_display = ('code', 'intitule')
    search_fields = ('code', 'intitule')


@admin.register(Article)
class ArticleAdmin(SimpleHistoryAdmin):
    list_display = ('designation', 'famille', 'unite_distribution', 'seuil_minimum', 'seuil_critique')
    search_fields = ('reference', 'designation')
    list_filter = ('famille',)
    autocomplete_fields = ['famille']


@admin.register(Magasin)
class MagasinAdmin(SimpleHistoryAdmin):
    list_display = ('nom', 'localisation')
    search_fields = ('nom',)


@admin.register(StockItem)
class StockItemAdmin(SimpleHistoryAdmin):
    list_display = ('article', 'magasin', 'quantite_physique', 'batch_number', 'expiry_date')
    list_filter = ('magasin', 'article__famille')
    search_fields = ('article__designation', 'batch_number')
    autocomplete_fields = ['article', 'magasin']

    def has_add_permission(self, request):
        return False
    def has_change_permission(self, request, obj=None):
        return False
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Mouvement)
class MouvementAdmin(SimpleHistoryAdmin):
    list_display = ('type_mouvement', 'article', 'quantite', 'date_mouvement', 'utilisateur', 'imprimer_bon')
    list_filter = ('type_mouvement', 'date_mouvement', 'magasin')
    search_fields = ('article__designation', 'reference_document')
    autocomplete_fields = ['article', 'magasin', 'utilisateur', 'service_demandeur', 'fournisseur']

    def has_change_permission(self, request, obj=None):
        return False
    def has_delete_permission(self, request, obj=None):
        return False

    def imprimer_bon(self, obj):
        if obj.type_mouvement == 'SORTIE':
            url = reverse('imprimer_bon_multi_lignes', args=[obj.id])
            bouton_html = f'''
                <a class="button" href="#"
                   onclick="window.open('{url}', 'VisionneusePDF', 'width=800,height=650,top=100,left=200'); return false;"
                   style="background-color: #417690; color: white; padding: 5px 10px; border-radius: 3px; text-decoration: none;">
                   🖨️ Imprimer
                </a>
            '''
            return format_html(bouton_html)
        return "-"
    imprimer_bon.short_description = "Action"


class LigneCommandeInline(admin.TabularInline):
    model = LigneCommande
    extra = 0


@admin.register(Commande)
class CommandeAdmin(admin.ModelAdmin):
    list_display = ('numero_commande', 'fournisseur', 'date_commande', 'statut', 'magasin')
    list_filter = ('statut', 'date_commande')
    search_fields = ('numero_commande', 'fournisseur__raison_sociale')
    inlines = [LigneCommandeInline]


class CircuitValidateurInline(admin.TabularInline):
    model = CircuitValidateur
    extra = 1
    autocomplete_fields = ['valideur']


@admin.register(CircuitValidation)
class CircuitValidationAdmin(admin.ModelAdmin):
    list_display = ('type_document', 'est_actif')
    list_filter = ('est_actif',)
    inlines = [CircuitValidateurInline]