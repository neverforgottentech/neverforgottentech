from django.apps import AppConfig


class MemorialConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'memorial'

    def ready(self):
        import memorial.signals  # This loads the signals