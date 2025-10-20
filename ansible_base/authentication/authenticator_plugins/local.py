import logging

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework.serializers import ValidationError

from ansible_base.authentication.authenticator_plugins.base import AbstractAuthenticatorPlugin, BaseAuthenticatorConfiguration
from ansible_base.authentication.utils.authentication import get_or_create_authenticator_user
from ansible_base.authentication.utils.claims import update_user_claims
from ansible_base.lib.serializers.fields import ListField
from ansible_base.lib.utils.imports import MODULE_PATH_PATTERN, import_object

logger = logging.getLogger('ansible_base.authentication.authenticator_plugins.local')


# TODO: Change the validator to not allow it to be deleted or a second one added

UserModel = get_user_model()


class LocalConfiguration(BaseAuthenticatorConfiguration):
    documentation_url = "https://docs.djangoproject.com/en/4.2/ref/contrib/auth/#django.contrib.auth.backends.ModelBackend"

    fallback_authentication = ListField(
        help_text=_(
            'List of fallback authentication handler modules to attempt when primary authentication fails. '
            'Each item should be a Python module path containing a FallbackAuthenticator class '
            '(e.g., "my_app.authentication.fallbacks.my_fallback_service"). '
            'The module must contain a class named "FallbackAuthenticator". '
            'Fallbacks are attempted in the order specified.'
        ),
        allow_null=True,
        required=False,
        default=[],
        ui_field_label=_('Fallback Authentication Handlers'),
        child=serializers.CharField(),
    )

    def validate(self, attrs):
        """
        Validate the configuration and ensure fallback authenticators are valid module paths.
        """
        # Call parent validation
        attrs = super().validate(attrs)

        # Validate fallback_authentication module paths
        fallback_paths = attrs.get('fallback_authentication', [])
        if fallback_paths:
            errors = {}
            for index, path in enumerate(fallback_paths):
                if not isinstance(path, str):
                    errors[index] = _('Must be a string representing a Python module path')
                elif not MODULE_PATH_PATTERN.match(path):
                    errors[index] = _('Invalid module path format. Must be a valid Python module path with at least one dot (e.g., "myapp.fallbacks.handler")')

            if errors:
                raise ValidationError({'fallback_authentication': errors})

        return attrs


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

        # Try standard ModelBackend authentication first
        user = super().authenticate(request, username, password, **kwargs)

        # If authentication failed, try fallback authenticators
        if not user:
            user = self._try_fallback_authenticators(request, username, password, **kwargs)

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

    def _try_fallback_authenticators(self, request, username, password, **kwargs):
        """
        Try each configured fallback authenticator in order.

        Fallback authenticators are loaded as plugins from the 'fallback_authentication' configuration
        field, which should be a list of module paths. Each module must contain a class named
        'FallbackAuthenticator'.

        Example:
            Configuration: ['my_service.authentication.fallbacks.my_fallback_service']
            Loads: my_service.authentication.fallbacks.my_fallback_service.FallbackAuthenticator

        Each fallback authenticator is instantiated and checked to see if it should be attempted
        using its should_attempt() method. If so, its authenticate() method is called.

        If a fallback authenticator returns a user, we use that user. Otherwise, we continue
        to the next fallback authenticator.

        Args:
            request: The HTTP request object
            username: The username to authenticate
            password: The password to authenticate
            **kwargs: Additional authentication parameters

        Returns:
            The authenticated user object if successful, None otherwise
        """
        configuration = self.database_instance.configuration if self.database_instance else {}
        fallback_paths = configuration.get('fallback_authentication', [])

        for module_path in fallback_paths:
            try:
                # Load the fallback plugin (must contain a class named 'FallbackAuthenticator')
                fallback_class = import_object(module_path, 'FallbackAuthenticator')

                # Instantiate the fallback authenticator
                fallback_authenticator = fallback_class()

                logger.info(f"Attempting fallback authenticator: {module_path}")

                # Try the fallback authentication
                user = fallback_authenticator.authenticate(request, username, password, **kwargs)

                # If fallback returned a user, use it
                if user:
                    logger.info(f"Fallback authenticator {module_path} returned user {user.username}")
                    return user

            except (ImportError, AttributeError, ValueError) as e:
                logger.error(f"Failed to load fallback authenticator plugin from {module_path}: {e}")
                continue
            except Exception as e:
                logger.error(f"Error in fallback authenticator {module_path}: {e}")
                continue

        if not fallback_paths:
            logger.debug("No fallback authenticators configured")
        else:
            logger.debug("All fallback authenticators exhausted, authentication failed")
        return None
