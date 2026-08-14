from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from core import views as core_views

urlpatterns = [
    # 🩺 Supervision (LB, systemd HealthCheck, uptime checkers) — sans authentification
    path('health/', core_views.health_check, name='health_check'),
    path('admin/', admin.site.urls),
    # 🔐 URLs accounts (auth + profil + gestion) — namespace géré par app_name dans accounts/urls.py
    path('auth/', include('accounts.urls')),

    path('', include('stock.urls')), 

    path('patrimoine/', include('patrimoine.urls')),
]

# En production, WhiteNoise (middleware) sert /static/ depuis STATIC_ROOT avec
# compression et cache — le helper static() n'est utile qu'en développement.
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
    # Permet d'afficher les fichiers envoyés (images/PDF) en mode développement
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)