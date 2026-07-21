from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path('admin/', admin.site.urls),
    # 🔐 URLs accounts (auth + profil + gestion) — namespace géré par app_name dans accounts/urls.py
    path('auth/', include('accounts.urls')),

    path('', include('stock.urls')), 

    path('patrimoine/', include('patrimoine.urls')),
] + static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)

# Permet d'afficher les fichiers envoyés (images/PDF) en mode développement
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)