from django.urls import path
from . import views

app_name = 'projets'

urlpatterns = [
    path('', views.liste_projets, name='liste'),
    path('creer/', views.creer_projet, name='creer'),
    path('<int:projet_id>/', views.detail_projet, name='detail'),
    path('<int:projet_id>/modifier/', views.modifier_projet, name='modifier'),
    path('<int:projet_id>/statut/', views.changer_statut, name='changer_statut'),
    path('api/articles/', views.api_recherche_articles, name='api_articles'),
    path('api/projets/', views.api_recherche_projets, name='api_projets'),
    # Proformas
    path('<int:projet_id>/proformas/creer/', views.creer_proforma, name='creer_proforma'),
    path('<int:projet_id>/proformas/<int:proforma_id>/modifier/', views.modifier_proforma, name='modifier_proforma'),
    path('api/proformas/<int:proforma_id>/', views.api_detail_proforma, name='api_detail_proforma'),
    path('<int:projet_id>/proformas/<int:proforma_id>/annuler/', views.annuler_proforma, name='annuler_proforma'),
    path('<int:projet_id>/proformas/<int:proforma_id>/imprimer/', views.imprimer_proforma, name='imprimer_proforma'),
]
