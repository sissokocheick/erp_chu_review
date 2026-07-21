from django.apps import AppConfig


class PatrimoineConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name               = 'patrimoine'
    verbose_name       = 'Gestion du Patrimoine'

    def ready(self):
        import patrimoine.signals  # noqa — déclenche l'enregistrement des signals