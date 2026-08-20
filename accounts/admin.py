from django.contrib import admin
from django.contrib.auth.models import User, Group
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html
from .models import (
    Profil, Specialite, Fonction, 
    MenuAccess, Notification, JournalAudit, AuditConnexion,
    ConfigSecurite,
)


# ==========================================================
# INLINE : PROFIL DANS USER
# ==========================================================
class ProfilInline(admin.StackedInline):
    model = Profil
    fk_name = 'user'                      # ← obligatoire (plusieurs FK vers User)
    can_delete = False
    verbose_name_plural = 'Profil utilisateur'
    fields = (
        'service', 'specialite', 'contact', 'photo', 'signature',
        'a_signature', 'fonction', 'theme_preference',
        'magasins_autorises', 'bureau', 'domaines_intervention',
        'est_chef_service', 'date_derniere_photo', 'nb_changements_photo'
    )
    filter_horizontal = ('magasins_autorises', 'domaines_intervention')
    readonly_fields = ('date_derniere_photo', 'nb_changements_photo')


# ==========================================================
# USER ADMIN PERSONNALISÉ
# ==========================================================
class CustomUserAdmin(BaseUserAdmin):
    inlines = (ProfilInline,)
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff', 'get_service')
    list_filter = ('is_staff', 'is_superuser', 'is_active', 'profil__service')

    def get_service(self, obj):
        try:
            return obj.profil.service.nom if obj.profil.service else "—"
        except Exception:
            return "—"
    get_service.short_description = "Service"


# Désenregistrer l'admin User par défaut et réenregistrer le custom
admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)


# ==========================================================
# PROFIL ADMIN
# ==========================================================
@admin.register(Profil)
class ProfilAdmin(admin.ModelAdmin):
    list_display = ('user', 'service', 'specialite', 'contact', 'est_chef_service')
    list_filter = ('service', 'est_chef_service', 'theme_preference')
    search_fields = ('user__username', 'user__first_name', 'user__last_name', 'contact')
    filter_horizontal = ('magasins_autorises', 'domaines_intervention')
    readonly_fields = ('date_creation', 'date_modification', 'date_derniere_photo', 'nb_changements_photo')


# ==========================================================
# SPÉCIALITÉ
# ==========================================================
@admin.register(Specialite)
class SpecialiteAdmin(admin.ModelAdmin):
    list_display = ('nom', 'date_creation')
    search_fields = ('nom',)


# ==========================================================
# FONCTION
# ==========================================================
@admin.register(Fonction)
class FonctionAdmin(admin.ModelAdmin):
    list_display = ('nom', 'date_creation')
    search_fields = ('nom',)



# ==========================================================
# MENU ACCESS
# ==========================================================
@admin.register(MenuAccess)
class MenuAccessAdmin(admin.ModelAdmin):
    list_display = ('nom', 'description')
    search_fields = ('nom',)


# ==========================================================
# NOTIFICATIONS
# ==========================================================
@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('utilisateur', 'titre', 'type_notif', 'est_lue', 'date_creation')
    list_filter = ('type_notif', 'est_lue')
    search_fields = ('titre', 'message', 'utilisateur__username')


# ==========================================================
# JOURNAL D'AUDIT
# ==========================================================
@admin.register(JournalAudit)
class JournalAuditAdmin(admin.ModelAdmin):
    list_display = ('date_action', 'utilisateur', 'action', 'type_action', 'modele_concerne')
    list_filter = ('type_action', 'modele_concerne')
    search_fields = ('action', 'utilisateur__username')
    readonly_fields = ('date_action',)
    date_hierarchy = 'date_action'


# ==========================================================
# AUDIT CONNEXIONS
# ==========================================================
@admin.register(AuditConnexion)
class AuditConnexionAdmin(admin.ModelAdmin):
    list_display = ('date_creation', 'utilisateur', 'type_action', 'adresse_ip')
    list_filter = ('type_action',)
    search_fields = ('utilisateur__username', 'description')
    readonly_fields = ('date_creation',)
    date_hierarchy = 'date_creation'

# ==========================================================
# CONFIG SÉCURITÉ (singleton)
# ==========================================================
@admin.register(ConfigSecurite)
class ConfigSecuriteAdmin(admin.ModelAdmin):
    list_display = ('type_mot_de_passe', 'date_modification')
    readonly_fields = ('date_modification',)
    fields = ('type_mot_de_passe', 'mot_de_passe_defaut', 'date_modification')

    def has_add_permission(self, request):
        # Singleton : pas d'ajout si une ligne existe déjà
        return not ConfigSecurite.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


