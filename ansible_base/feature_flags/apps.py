from django.apps import AppConfig


class FeatureFlagsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ansible_base.feature_flags'
    label = 'dab_feature_flags'
    verbose_name = 'Feature Flags'
