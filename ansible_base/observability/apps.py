from django.apps import AppConfig

from .instrument import setup_observability


class ObservabilityConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ansible_base.observability'
    label = 'dao_opentelemetry'
    verbose_name = 'Auto-Instrumented OpenTelemetry'

    def ready(self):
        setup_observability()
        super().ready()
