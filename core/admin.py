# core/admin.py — CORRIGÉ (v2)
from django.contrib import admin
from .models import ConfigurationHopital, Service


@admin.register(ConfigurationHopital)
class ConfigurationHopitalAdmin(admin.ModelAdmin):
    list_display = ('nom', 'telephone', 'date_creation')
    readonly_fields = ('date_creation', 'date_modification', 'cree_par', 'modifie_par')
    search_fields = ('nom',)


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ('code', 'nom', 'entreprise', 'date_creation')
    search_fields = ('code', 'nom')
    list_filter = ('entreprise',)
    readonly_fields = ('date_creation', 'date_modification', 'cree_par', 'modifie_par')
    # ✅ CORRECTION: raw_id_fields pour éviter chargement massif des FK
    raw_id_fields = ('entreprise', 'cree_par', 'modifie_par')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        # ✅ CORRECTION: hasattr complet pour éviter AttributeError
        if hasattr(request.user, 'profil') and request.user.profil is not None:
            return qs.filter(entreprise=request.user.profil.entreprise)
        return qs.none()
