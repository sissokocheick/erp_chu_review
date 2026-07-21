# stock/urls_pdf_config.py
# Inclure dans stock/urls.py via : path('', include('stock.urls_pdf_config'))

from django.urls import path
from .pdf_config_views import ModelePDFConfigView

urlpatterns = [
    path('magasin/<int:magasin_id>/modele-pdf/<str:type_doc>/', ModelePDFConfigView.as_view(), name='modele_pdf_config'),
    path('magasin/<int:magasin_id>/modele-pdf/', ModelePDFConfigView.as_view(), name='modele_pdf_config_default'),
]
