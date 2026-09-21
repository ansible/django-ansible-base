from django.apps import AppConfig

from .instrument import setup_observability


class ObservabilityConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ansible_base.observability'
    label = 'dao_opentelemetry'
    verbose_name = 'Auto-Instrumented OpenTelemetry'

    def ready(self):
        setup_observability()

        # Register validation bypass logging signal
        from ansible_base.lib.utils.validation_signals import register_validation_signals

        register_validation_signals()

        super().ready()
