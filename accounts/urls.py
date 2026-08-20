from django.urls import path
from . import views
from . import views_fonctions
from . import views_reset

app_name = 'accounts'

urlpatterns = [
    # Auth
    path('login/', views.custom_login, name='custom_login'),
    path('logout/', views.custom_logout, name='custom_logout'),
    path('forcer-mdp/', views.changer_mdp_obligatoire, name='changer_mdp_obligatoire'),

    # Réinitialisation du mot de passe par l'utilisateur (mot de passe oublié)
    path('mot-de-passe-oublie/', views_reset.mot_de_passe_oublie, name='mot_de_passe_oublie'),
    # Étape 2 sans token : saisie du code reçu par SMS
    path('reinitialisation/', views_reset.reinitialiser_mot_de_passe, name='reinitialiser_mot_de_passe'),
    # Étape 2 via le lien envoyé par email (token dans l'URL)
    path('reinitialisation/<str:token>/', views_reset.reinitialiser_mot_de_passe, name='reinitialiser_mot_de_passe_lien'),

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

    # Notifications : gérées côté stock (cloche topbar → liste_notifications)

    # Journal
    path('journal-audit/', views.journal_audit, name='journal_audit'),

    # Thème
    path('api/save-theme/', views.save_theme_preference, name='save_theme'),

    # Fonctions
    # NB: la page Fonctions est gérée dans Paramètres → Administratifs (section Fonctions)
    # NB: routes modifier_fonction / supprimer_fonction desactivees (15/08/2026) : CRUD vivant dans Parametres -> Administratifs (stock)
    path('api/fonctions/creer/', views_fonctions.api_creer_fonction, name='api_creer_fonction'),
    path('api/fonctions/liste/', views_fonctions.api_liste_fonctions, name='api_liste_fonctions'),

    path('securite/mots-de-passe/', views.parametres_securite, name='parametres_securite'),


    # Signature
    path('profil/signature/', views.enregistrer_signature, name='enregistrer_signature'),

    # Circuits de validation
    path('circuits-validation/', views.circuits_validation, name='circuits_validation'),
    path('circuits-validation/creer/', views.creer_circuit, name='creer_circuit'),
    path('circuits-validation/<int:circuit_id>/modifier/', views.modifier_circuit, name='modifier_circuit'),

    # Configuration des documents PDF
]
