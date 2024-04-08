import logging

from django.contrib.auth.backends import ModelBackend
from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration
from ansible_base.authentication.utils.authentication import determine_username_from_uid, get_or_create_authenticator_user
from ansible_base.authentication.utils.claims import update_user_claims

logger = logging.getLogger('ansible_base.authentication.authenticator_plugins.local')

# TODO: Change the validator to not allow it to be deleted or a second one added


class LocalConfiguration(BaseAuthenticatorConfiguration):
    documentation_url = "https://docs.djangoproject.com/en/4.2/ref/contrib/auth/#django.contrib.auth.backends.ModelBackend"

    def validate(self, data):
        if data != {}:
            raise ValidationError(_({"configuration": "Can only be {} for local authenticators"}))
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

        if not self.database_instance:
            return None

        if not self.database_instance.enabled:
            logger.info(f"Local authenticator {self.database_instance.name} is disabled, skipping")
            return None

        # Determine the user name for this authenticator, we have to call this so that we can "attach" to a pre-created user
        new_username = determine_username_from_uid(username, self.database_instance)
        # However we can't really accept a different username because we are the local authenticator imageine if:
        #    User "a" is from another authenticator and has an AuthenticatorUser
        #    User "a" tried to login from local authenticator
        #    The above function will return a username of "a<hash>"
        #    We then try to do local authentication with the database from a different username that will not exist in the database, so it would never work
        if new_username != username:
            return None

        user = super().authenticate(request, username, password, **kwargs)

        # This auth class doesn't create any new local users, but we still need to make sure
        # it has an AuthenticatorUser associated with it.
        if user:
            get_or_create_authenticator_user(
                username,
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
