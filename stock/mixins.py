from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render, redirect
from django.contrib import messages


class MagasinRequiredMixin(LoginRequiredMixin):
    """
    Mixin pour vues basées sur des classes.
    Version mono-tenant.
    """
    def dispatch(self, request, *args, **kwargs):
        if request.session.get('magasin_actif_id'):
            return super().dispatch(request, *args, **kwargs)

        from .models import Magasin

        user = request.user
        if user.is_superuser:
            magasins = Magasin.objects.all()
        else:
            try:
                magasins = user.profil.magasins_autorises.all()
            except Exception:
                magasins = Magasin.objects.none()

        if magasins.count() == 1:
            request.session['magasin_actif_id'] = str(magasins.first().id)
            return super().dispatch(request, *args, **kwargs)

        if magasins.count() == 0:
            messages.error(request, "⛔ Vous n'avez accès à aucun magasin.")
            return redirect('/')

        return render(request, 'stock/choix_magasin_obligatoire.html', {'url_voulue': request.path})