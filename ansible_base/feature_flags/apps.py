from django.apps import AppConfig
from django.db.models.signals import post_migrate

from ansible_base.feature_flags.utils import create_initial_data


class FeatureFlagsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ansible_base.feature_flags'
    label = 'dab_feature_flags'
    verbose_name = 'Feature Flags'

    def ready(self):
        post_migrate.connect(create_initial_data, sender=self)
