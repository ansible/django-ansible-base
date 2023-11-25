import logging

from django.contrib.auth import get_user_model

from ansible_base.authenticator_plugins.base import AbstractAuthenticatorPlugin

logger = logging.getLogger('ansible_base.tests.fixtures.authenticator_plugins')


class AuthenticatorPlugin(AbstractAuthenticatorPlugin):
    def __init__(self, database_instance=None, *args, **kwargs):
        super().__init__(database_instance, *args, **kwargs)
        self.configuration_encrypted_fields = []
        self.type = "custom"
        self.set_logger(logger)
        self.category = "password"

    def authenticate(self, request, username=None, password=None, **kwargs):
        if username == "admin" and password == "hello123":
            user = get_user_model().objects.get(username=username)
            return user

        return None
