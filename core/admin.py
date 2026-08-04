# core/admin.py — CORRIGÉ (mono-tenant)
from django.contrib import admin
from .models import ConfigurationHopital, Service


@admin.register(ConfigurationHopital)
class ConfigurationHopitalAdmin(admin.ModelAdmin):
    list_display = ('nom', 'telephone', 'date_creation')
    readonly_fields = ('date_creation', 'date_modification', 'cree_par', 'modifie_par')
    search_fields = ('nom',)


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ('code', 'nom', 'date_creation')
    search_fields = ('code', 'nom')
    readonly_fields = ('date_creation', 'date_modification', 'cree_par', 'modifie_par')
    raw_id_fields = ('cree_par', 'modifie_par')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # En mono-tenant, tout le monde voit tous les services
        # (ou on peut filtrer plus tard selon les besoins)
        return qs