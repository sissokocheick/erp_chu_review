from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import render, redirect
from django.contrib import messages


class MagasinRequiredMixin(LoginRequiredMixin):
    """
    Mixin pour vues basées sur des classes (ListView, DetailView...).
    """
    def dispatch(self, request, *args, **kwargs):
        if request.session.get('magasin_actif_id'):
            return super().dispatch(request, *args, **kwargs)

        from .models import Magasin
        entreprise = getattr(request, 'entreprise', None)
        if not entreprise:
            messages.error(request, "⛔ Aucune entreprise active.")
            return redirect('/')

        user = request.user
        if user.is_superuser:
            magasins = Magasin.objects.filter(entreprise=entreprise)
        else:
            magasins = user.profil.magasins_autorises.filter(entreprise=entreprise)

        if magasins.count() == 1:
            request.session['magasin_actif_id'] = str(magasins.first().id)
            return super().dispatch(request, *args, **kwargs)

        return render(request, 'stock/choix_magasin_obligatoire.html', {'url_voulue': request.path})