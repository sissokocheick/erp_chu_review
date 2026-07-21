from django.urls import path
from django.contrib.auth.views import LogoutView
from . import views
from . import config_documents_views as config_docs_views
from . import views_fonctions


app_name = 'accounts'


urlpatterns = [
    # 🔐 Authentification
    path('login/', views.custom_login, name='custom_login'),
    path('logout/', views.custom_logout, name='logout'),

    path('forcer-mdp/', views.changer_mdp_obligatoire, name='changer_mdp_obligatoire'),
    path('utilisateurs/', views.page_utilisateurs, name='page_utilisateurs'),
    path('roles/', views.page_roles, name='page_roles'),
    path('profil/', views.profil_utilisateur, name='profil_utilisateur'),
    path('entreprises/', views.page_entreprises, name='page_entreprises'),
    path('entreprises/changer/', views.changer_entreprise_session, name='changer_entreprise_session'),
    path('securite/mots-de-passe/', views.parametres_securite, name='parametres_securite'),
    path('accueil/', views.accueil_personnalise, name='accueil_personnalise'),
    path('api/save-theme/', views.save_theme_preference, name='save_theme'),
    path('parametres/entreprise/', views.parametres_entreprise, name='parametres_entreprise'),
    path('utilisateurs/<int:user_id>/reinitialiser-mdp/', views.reinitialiser_mdp, name='reinitialiser_mdp'),

    # 📄 Configuration globale documents PDF
    path('config-documents/', config_docs_views.config_documents_globaux, name='config_documents_globaux'),

    # 🏷️ Fonctions (titres professionnels)
    path('fonctions/', views_fonctions.page_fonctions, name='page_fonctions'),
    path('fonctions/<int:fonction_id>/modifier/', views_fonctions.modifier_fonction, name='modifier_fonction'),
    path('fonctions/<int:fonction_id>/supprimer/', views_fonctions.supprimer_fonction, name='supprimer_fonction'),
    path('api/fonctions/creer/', views_fonctions.api_creer_fonction, name='api_creer_fonction'),
    path('api/fonctions/liste/', views_fonctions.api_liste_fonctions, name='api_liste_fonctions'),

    # 📝 Journal d'audit
    path('journal-audit/', views.journal_audit, name='journal_audit'),
]