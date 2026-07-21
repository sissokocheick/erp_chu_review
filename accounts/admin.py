# accounts/admin.py — VERSION CORRIGÉE
from django.contrib import admin
from .models import (
    Entreprise, Profil, Specialite, Fonction,
    ConfigDocument, MenuAccess, Notification,
    JournalAudit, AuditConnexion, RoleEntreprise
)


@admin.register(Entreprise)
class EntrepriseAdmin(admin.ModelAdmin):
    list_display = ('nom', 'email_contact', 'telephone', 'est_active', 'date_creation')
    search_fields = ('nom',)
    list_filter = ('est_active',)


@admin.register(Profil)
class ProfilAdmin(admin.ModelAdmin):
    list_display = ('user', 'entreprise', 'contact', 'specialite')
    list_filter = ('entreprise',)
    search_fields = ('user__username', 'user__first_name', 'user__last_name')

    # ⚡ CORRECTION : Filtre automatique par entreprise pour non-superusers
    # avec gestion robuste du cas profil=None
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        profil = getattr(request.user, 'profil', None)
        if profil and profil.entreprise:
            return qs.filter(entreprise=profil.entreprise)
        return qs.none()


@admin.register(Specialite)
class SpecialiteAdmin(admin.ModelAdmin):
    list_display = ('nom', 'entreprise', 'date_creation', 'cree_par')
    list_filter = ('entreprise',)
    search_fields = ('nom', 'entreprise__nom')

    # ⚡ CORRECTION : Filtre automatique par entreprise pour non-superusers
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        profil = getattr(request.user, 'profil', None)
        if profil and profil.entreprise:
            return qs.filter(entreprise=profil.entreprise)
        return qs.none()


@admin.register(Fonction)
class FonctionAdmin(admin.ModelAdmin):
    list_display = ('nom', 'entreprise', 'date_creation')
    list_filter = ('entreprise',)
    search_fields = ('nom',)

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        profil = getattr(request.user, 'profil', None)
        if profil and profil.entreprise:
            return qs.filter(entreprise=profil.entreprise)
        return qs.none()


@admin.register(ConfigDocument)
class ConfigDocumentAdmin(admin.ModelAdmin):
    list_display = ('entreprise', 'type_doc', 'code_document', 'version_doc')
    list_filter = ('entreprise', 'type_doc')


@admin.register(MenuAccess)
class MenuAccessAdmin(admin.ModelAdmin):
    list_display = ('nom', 'description')


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('utilisateur', 'titre', 'type_notif', 'est_lue', 'date_creation')
    list_filter = ('type_notif', 'est_lue')


@admin.register(JournalAudit)
class JournalAuditAdmin(admin.ModelAdmin):
    list_display = ('date_action', 'utilisateur', 'action', 'type_action', 'entreprise')
    list_filter = ('type_action', 'entreprise')
    date_hierarchy = 'date_action'
    readonly_fields = ('date_action',)


@admin.register(AuditConnexion)
class AuditConnexionAdmin(admin.ModelAdmin):
    list_display = ('date_creation', 'utilisateur', 'type_action', 'adresse_ip')
    list_filter = ('type_action',)
    date_hierarchy = 'date_creation'
    readonly_fields = ('date_creation',)


@admin.register(RoleEntreprise)
class RoleEntrepriseAdmin(admin.ModelAdmin):
    list_display = ('groupe', 'entreprise', 'description')
    list_filter = ('entreprise',)
