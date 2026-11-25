import logging

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import IntegrityError, transaction
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework.fields import empty
from rest_framework.serializers import ValidationError

from ansible_base.authentication.jwk_client import (
    DEFAULT_JWKS_CACHE_TIMEOUT,
    DEFAULT_JWKS_URL_TIMEOUT,
    MAX_JWKS_URL_TIMEOUT,
    MIN_JWKS_URL_TIMEOUT,
)
from ansible_base.authentication.models import Authenticator
from ansible_base.lib.serializers.fields import IntegerField, JSONField
from ansible_base.lib.utils.response import get_relative_url

logger = logging.getLogger('ansible_base.authentication.authenticator_plugins.base')


def jwks_url_timeout_field():
    """Build the shared JWKS request timeout field so token-verifying plugins stay in sync."""
    return IntegerField(
        help_text=_("Timeout for JWKS URL requests in seconds."),
        default=DEFAULT_JWKS_URL_TIMEOUT,
        allow_null=False,
        validators=[MinValueValidator(MIN_JWKS_URL_TIMEOUT), MaxValueValidator(MAX_JWKS_URL_TIMEOUT)],
        ui_field_label=_("JWKS URL Timeout"),
    )


def jwks_cache_timeout_field():
    """Build the shared JWKS cache lifetime field used by token-verifying plugins."""
    return IntegerField(
        help_text=_(
            "How long to cache JWKS keys, in seconds. Minimum 0 (cache disabled); this makes a JWKS call for every request. "
            "No maximum — longer TTLs are fine for stable IdPs; token validation refreshes keys on signature failure so rotation still works."
        ),
        default=DEFAULT_JWKS_CACHE_TIMEOUT,
        allow_null=False,
        validators=[MinValueValidator(0)],
        ui_field_label=_("JWKS Cache Timeout (seconds)"),
    )


def _field_required(field):
    if hasattr(field, 'required'):
        return field.required
    elif hasattr(field, 'allow_null'):
        return not field.allow_null
    return True


class BaseAuthenticatorConfiguration(serializers.Serializer):
    documentation_url = None
    ADDITIONAL_UNVERIFIED_ARGS = JSONField(
        help_text=_("Any additional fields that this authenticator can take. They are not validated and passed directly back to the authenticator."),
        required=False,
        allow_null=True,
        ui_field_label=_('Additional Authenticator Fields'),
    )

    def get_configuration_schema(self):
        fields = self.get_fields()

        schema = []

        for f in fields:
            field = fields[f]
            default = None
            if field.default is not empty:
                default = field.default

            schema_data = {
                "name": f,
                "help_text": field.help_text,
                "required": _field_required(field),
                "default": default,
                "type": field.__class__.__name__,
                "ui_field_label": getattr(field, 'ui_field_label', _('Undefined')),
            }
            if getattr(field, 'choices', None):
                schema_data["choices"] = getattr(field, 'choices')

            schema.append(schema_data)
        return schema


class AbstractAuthenticatorPlugin:
    """
    Base class for non social auth backends
    """

    configuration_class = BaseAuthenticatorConfiguration
    configuration_encrypted_fields = []
    # Optional human-readable label for UIs (exposed by AuthenticatorPluginView).
    # Prefer gettext_lazy so Gateway can translate via Accept-Language.
    # Empty falls back to a title-cased short type in AuthenticatorPluginView.
    display_name = ""

    def __init__(self, database_instance=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.database_instance = database_instance

    def set_logger(self, logger) -> None:
        if not logger:
            self.logger = logging.getLogger('ansible_base.authentication.models.abstract_authenticator')
        else:
            self.logger = logger

    def validate_configuration(self, data: dict, instance: object) -> dict:
        if not issubclass(self.configuration_class, BaseAuthenticatorConfiguration):
            raise TypeError(_("self.configuration_class must subclass BaseAuthenticatorConfiguration."))

        serializer = self.configuration_class(data=data, instance=instance)
        serializer.is_valid(raise_exception=True)

        allowed_fields = serializer.get_fields()
        errors = {}
        for k in data:
            if k not in allowed_fields:
                errors[k] = _(f"{k} is not a supported configuration option.")

        if errors:
            raise ValidationError(errors)

        return serializer.validated_data

    def to_representation(self, instance: object):
        if not issubclass(self.configuration_class, BaseAuthenticatorConfiguration):
            raise TypeError("self.configuration_class must subclass BaseAuthenticatorConfiguration.")
        serializer = self.configuration_class(data=instance.configuration, instance=instance)
        response = serializer.to_representation(instance.configuration)
        return response

    def update_settings(self, database_authenticator: Authenticator) -> None:
        self.settings = database_authenticator.configuration

    def configuration_updated(
        self,
        *,
        authenticator_id: int,
        previous_configuration: dict,
        previous_modified: object,
        configuration: dict,
        modified: object,
    ) -> None:
        """React to a committed authenticator configuration change.

        Subclasses may invalidate configuration-dependent shared state here.
        The model invokes this hook only after the surrounding transaction
        commits, so callbacks never observe rolled-back configuration.
        """

    def update_if_needed(self, database_authenticator: Authenticator) -> None:
        if not self.database_instance or self.database_instance.modified != database_authenticator.modified:
            if self.database_instance:
                self.logger.info(f"Updating {self.type} adapter {database_authenticator.name}")
            else:
                self.logger.info(f"Creating an {self.type} adapter from {database_authenticator.name}")
            self.database_instance = database_authenticator
            self.update_settings(database_authenticator)
        else:
            self.logger.info(f"No updated needed for {self.type} adapter {database_authenticator.name}")

    def get_default_attributes(self):
        """
        Each backend must return a list of common attributes that are available for the authenticator map.
        These values will  be queryable by the API so that the UI can help the user configure authenticator maps.

        This list won't be comprehensive since we may not know what's available until a user logs in.

        Users will be able to configure attributes which they know exist in the Authenticator model. Additionally,
        the list of available attributes returned to the api should include fields in AuthenticatorUser.extra
        once user's have started logging in with the authenticator.
        """
        raise NotImplementedError("Implement in subclass.")

    def get_login_url(self, authenticator):
        if authenticator.category == 'sso':
            return get_relative_url('social:begin', kwargs={'backend': authenticator.slug})

    def add_related_fields(self, request, authenticator):
        return {}

    def validate(self, serializer, data):
        return data

    def move_authenticator_user_to(self, new_user, old_authenticator_user):
        """
        new_user: django User instance. User that we're moving this account to.
        old_authenticator_user: AuthenticatorUser instance from this authenticator that is being removed.
        """
        exclude_fields = (
            "social_auth",
            "authenticator_users",
            "groups",
            "has_roles",
            # We're ignoring role assignments for two reasons: 1. this isn't safe to copy right now, as it
            # could break the caching layer, 2. roles are intented to come from the authenticator via an
            # authenticator map, so when a user is move to a new authenticator, they're old roles should
            # be removed.
            "role_assignments",
            "logentry",
        )

        old_user = old_authenticator_user.user

        # Delete the old authenticator user
        old_authenticator_user.delete()

        if new_user.pk == old_user.pk:
            return

        # Copy all of the relationships from the old user to the new one
        for field in new_user._meta.get_fields():
            if field.many_to_many is True or field.one_to_many is True:
                name = field.name
                if name in exclude_fields:
                    continue
                if not hasattr(old_user, name) or not hasattr(new_user, name):
                    continue
                for x in getattr(old_user, name).all():
                    # The only case where this might fail is if the relationship has a uniqueness
                    # contraint on the user. In this case, all we can do is skip.
                    try:
                        # This atomic block is here to prevent a failure that is best described by
                        # this stack overflow: https://stackoverflow.com/questions/21458387
                        with transaction.atomic():
                            getattr(new_user, name).add(x)
                    except IntegrityError as e:
                        logger.warning(f"Could not add {name} to {new_user.username}. Error: {e}")
                        continue

        return old_user

    def get_alternative_uid(self, **kwargs):
        """
        This method can be used to provide an alternative UID for the user in case we need to match
        UIDs across different authenticators (as is the case for auto_migrate_users_to). It receives
        the kwargs from the social auth pipeline (https://python-social-auth.readthedocs.io/en/latest/pipeline.html).

        For a good example of this method in action, check out the keycloak authenticator.
        """
        return None
