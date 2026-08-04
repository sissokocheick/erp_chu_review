from django.urls import path
from . import views
from . import views_fonctions

app_name = 'accounts'

urlpatterns = [
    # Auth
    path('login/', views.custom_login, name='custom_login'),
    path('logout/', views.custom_logout, name='custom_logout'),
    path('forcer-mdp/', views.changer_mdp_obligatoire, name='changer_mdp_obligatoire'),

    # Accueil
    path('', views.accueil_personnalise, name='accueil_personnalise'),
    path('accueil/', views.accueil_personnalise, name='accueil'),

    # Utilisateurs
    path('utilisateurs/', views.page_utilisateurs, name='page_utilisateurs'),
    path('utilisateurs/<int:user_id>/reinitialiser-mdp/', views.reinitialiser_mdp, name='reinitialiser_mdp'),
    path('api/utilisateurs/verifier/', views.api_verifier_champ_utilisateur, name='api_verifier_champ_utilisateur'),

    # Rôles
    path('roles/', views.page_roles, name='page_roles'),

    # Profil
    path('profil/', views.profil_utilisateur, name='profil_utilisateur'),

    # Notifications
    path('notifications/', views.mes_notifications, name='mes_notifications'),
    path('notifications/<int:notif_id>/lue/', views.marquer_notification_lue, name='marquer_notification_lue'),

    # Journal
    path('journal-audit/', views.journal_audit, name='journal_audit'),

    # Thème
    path('api/save-theme/', views.save_theme_preference, name='save_theme'),

    # Fonctions
    path('fonctions/', views_fonctions.page_fonctions, name='page_fonctions'),
    path('fonctions/<int:fonction_id>/modifier/', views_fonctions.modifier_fonction, name='modifier_fonction'),
    path('fonctions/<int:fonction_id>/supprimer/', views_fonctions.supprimer_fonction, name='supprimer_fonction'),
    path('api/fonctions/creer/', views_fonctions.api_creer_fonction, name='api_creer_fonction'),
    path('api/fonctions/liste/', views_fonctions.api_liste_fonctions, name='api_liste_fonctions'),

    # Stubs (anciennes pages multi-tenant)
    path('entreprises/', views.page_entreprises, name='page_entreprises'),
    path('entreprises/changer/', views.changer_entreprise_session, name='changer_entreprise_session'),
    path('parametres/entreprise/', views.parametres_entreprise, name='parametres_entreprise'),
    path('securite/mots-de-passe/', views.parametres_securite, name='parametres_securite'),


    # Signature
    path('profil/signature/', views.enregistrer_signature, name='enregistrer_signature'),

    # Circuits de validation
    path('circuits-validation/', views.circuits_validation, name='circuits_validation'),
    path('circuits-validation/creer/', views.creer_circuit, name='creer_circuit'),
    path('circuits-validation/<int:circuit_id>/modifier/', views.modifier_circuit, name='modifier_circuit'),
]