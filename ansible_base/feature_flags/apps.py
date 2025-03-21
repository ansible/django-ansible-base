from django.apps import AppConfig
from django.db.models.signals import post_migrate
from django.db.utils import OperationalError, ProgrammingError

from .utils import create_initial_data


class FeatureFlagsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ansible_base.feature_flags'
    label = 'dab_feature_flags'
    verbose_name = 'Feature Flags'

    def ready(self):
        from django.conf import settings

        if 'ansible_base.feature_flags' in settings.INSTALLED_APPS:
            # TODO: Is there a better way to handle this logic?

            # If migrations are complete, attempt to load in feature flags again.
            # This can help capture any updates to the platform flags loaded in to ensure that new values
            # are added and updated.
            # Otherwise wait for migrations to be complete before loading in feature flags.
            try:
                create_initial_data()
            except (ProgrammingError, OperationalError):
                post_migrate.connect(create_initial_data)
