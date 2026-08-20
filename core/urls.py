from django.urls import path
from . import config_documents_views

app_name = 'core'

urlpatterns = [
    path('parametres/documents-pdf/', config_documents_views.config_documents_globaux, name='config_documents_globaux'),
]
