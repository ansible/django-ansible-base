import logging

from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import ValidationError

from ansible_base.authenticator_plugins.base import AbstractAuthenticatorPlugin
from ansible_base.models import AuthenticatorUser

logger = logging.getLogger('aap.gateway.authentication.local')

# TODO: Figure out how to move this plugin into ansible_base itself
#       Change the validator to not allow it to be deleted or a second one added


class AuthenticatorPlugin(ModelBackend, AbstractAuthenticatorPlugin):
    def __init__(self, database_instance=None, *args, **kwargs):
        super().__init__(database_instance, *args, **kwargs)
        self.configuration_encrypted_fields = []
        self.type = "local"
        self.set_logger(logger)
        self.category = "password"

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

    def validate_configuration(self, data: dict, instance: object) -> None:
        if data != {}:
            raise ValidationError({"configuration": "Can only be {} for local authenticators"})
