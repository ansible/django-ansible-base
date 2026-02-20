import logging

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration
from ansible_base.authentication.utils.authentication import get_or_create_authenticator_user
from ansible_base.authentication.utils.claims import update_user_claims

logger = logging.getLogger('ansible_base.authentication.authenticator_plugins.local')


# TODO: Change the validator to not allow it to be deleted or a second one added

UserModel = get_user_model()


class LocalConfiguration(BaseAuthenticatorConfiguration):
    documentation_url = "https://docs.djangoproject.com/en/4.2/ref/contrib/auth/#django.contrib.auth.backends.ModelBackend"


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

        if not self.database_instance:
            return None

        if not self.database_instance.enabled:
            logger.info(f"Local authenticator {self.database_instance.name} is disabled, skipping")
            return None

        user = super().authenticate(request, username, password, **kwargs)

        # This auth class doesn't create any new local users, but we still need to make sure
        # it has an AuthenticatorUser associated with it.
        if user:
            get_or_create_authenticator_user(
                uid=username,
                email=user.email,
                authenticator=self.database_instance,
                user_details={},
                extra_data={
                    "username": username,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "email": user.email,
                    "is_superuser": user.is_superuser,
                },
            )
        return update_user_claims(user, self.database_instance, [])
