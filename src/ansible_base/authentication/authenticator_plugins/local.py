import logging

from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import ValidationError

from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration
from ansible_base.authentication.models import AuthenticatorUser

logger = logging.getLogger('ansible_base.authentication.authenticator_plugins.local')

# TODO: Change the validator to not allow it to be deleted or a second one added


class LocalConfiguration(BaseAuthenticatorConfiguration):
    documentation_url = "https://docs.djangoproject.com/en/4.2/ref/contrib/auth/#django.contrib.auth.backends.ModelBackend"

    def validate(self, data):
        if data != {}:
            raise ValidationError({"configuration": "Can only be {} for local authenticators"})
        return data


class AuthenticatorPlugin(ModelBackend, AbstractAuthenticatorPlugin):
    configuration_class = LocalConfiguration
    logger = logger
    type = "local"
    category = "password"

    def __init__(self, database_instance=None, *args, **kwargs):
        super().__init__(database_instance, *args, **kwargs)

    def authenticate(self, request, username=None, password=None, **kwargs):
        if not username or not password:
            return None
        user = super().authenticate(request, username, password, **kwargs)

        # This auth class doesn't create any new local users, so we just need to make sure
        # it has an AuthenticatorUser associated with it.
        if user:
            AuthenticatorUser.objects.get_or_create(uid=username, user=user, provider=self.database_instance)

        # TODO, we will need to return attributes and claims eventually
        return user
