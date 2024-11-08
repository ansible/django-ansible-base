from django.apps import AppConfig
from django.db.models import signals


def _initialize_data(sender, **kwargs):
    from ansible_base.django_template.signals.preloaded_data import create_preload_data

    create_preload_data(**kwargs)


class DjangoTemplateConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ansible_base.django_template'
    label = 'dab_django_template'
    verbose_name = 'Django AAP Template'

    def ready(self):
        signals.post_migrate.connect(_initialize_data, sender=self, weak=False)

        # Load the signals
        import ansible_base.django_template.signals  # noqa 401
