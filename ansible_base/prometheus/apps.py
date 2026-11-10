from django.apps import AppConfig


class PrometheusConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ansible_base.prometheus'
    label = 'dao_prometheus'
    verbose_name = 'Prometheus Metrics'

    def ready(self):
        from .instrument import setup_prometheus

        setup_prometheus()
        super().ready()
