# stock/admin.py — AJOUT AU DÉBUT
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

# ⚡ AJOUT : Mixin pour filtrer par entreprise dans l'admin
class TenantAdminMixin:
    """Filtre les querysets par entreprise active pour les non-superusers."""
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        # Pour les non-superusers, on filtre par leur entreprise
        if hasattr(request.user, 'profil') and request.user.profil:
            entreprise = request.user.profil.entreprise
            if entreprise:
                return qs.filter(entreprise=entreprise)
        return qs.none()

@admin.register(Fournisseur)
class FournisseurAdmin(TenantAdminMixin, SimpleHistoryAdmin):
    list_display = ('code', 'raison_sociale', 'entreprise', 'est_agree', 'note_evaluation')
    search_fields = ('code', 'raison_sociale')
    list_filter = ('est_agree', 'entreprise')

@admin.register(FamilleArticle)
class FamilleArticleAdmin(TenantAdminMixin, SimpleHistoryAdmin):
    list_display = ('code', 'intitule', 'entreprise')
    search_fields = ('code', 'intitule')
    list_filter = ('entreprise',)

@admin.register(Article)
class ArticleAdmin(TenantAdminMixin, SimpleHistoryAdmin):
    list_display = ('designation', 'famille', 'entreprise', 'unite_distribution', 'seuil_minimum', 'seuil_critique')
    search_fields = ('reference', 'designation')
    list_filter = ('famille', 'entreprise')
    autocomplete_fields = ['famille']

@admin.register(Magasin)
class MagasinAdmin(TenantAdminMixin, SimpleHistoryAdmin):
    list_display = ('nom', 'localisation', 'entreprise')
    search_fields = ('nom',)
    list_filter = ('entreprise',)

@admin.register(StockItem)
class StockItemAdmin(SimpleHistoryAdmin):
    list_display = ('article', 'magasin', 'quantite_physique', 'batch_number', 'expiry_date')
    list_filter = ('magasin__entreprise', 'magasin', 'article__famille')
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
    list_filter = ('type_mouvement', 'date_mouvement', 'magasin__entreprise', 'magasin')
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
class CommandeAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ('numero_commande', 'fournisseur', 'date_commande', 'statut', 'magasin')
    list_filter = ('statut', 'date_commande', 'fournisseur__entreprise')
    search_fields = ('numero_commande', 'fournisseur__raison_sociale')
    inlines = [LigneCommandeInline]

class CircuitValidateurInline(admin.TabularInline):
    """
    ✅ CORRECTION : Inline pour gérer les valideurs avec ordre.
    Remplace filter_horizontal qui ne fonctionne pas avec through.
    """
    model = CircuitValidateur
    extra = 1
    autocomplete_fields = ['valideur']


@admin.register(CircuitValidation)
class CircuitValidationAdmin(TenantAdminMixin, admin.ModelAdmin):
    list_display = ('type_document', 'entreprise', 'est_actif')
    list_filter = ('est_actif', 'entreprise')
    # ✅ CORRECTION : filter_horizontal retiré car valideurs utilise through
    inlines = [CircuitValidateurInline]