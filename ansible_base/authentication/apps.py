from django.apps import AppConfig

import ansible_base.lib.checks  # noqa: F401 - register checks
from ansible_base.lib.utils.models import decorate_user_model


class AuthenticationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ansible_base.authentication'
    label = 'dab_authentication'
    verbose_name = 'Pluggable Authentication'

    def ready(self):
        """
        This app offers an API and has relational links to the user model
        so we must call this so that the User model has needed utility methods
        expected by the common serializers.
        """
        decorate_user_model()
