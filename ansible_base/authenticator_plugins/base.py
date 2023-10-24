import logging

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework.fields import empty
from rest_framework.serializers import JSONField, ValidationError

from ansible_base.models import Authenticator

logger = logging.getLogger('ansible_base.authentication.authenticator_lib')


class BaseAuthenticatorConfiguration(serializers.Serializer):
    documentation_url = None
    ADDITIONAL_UNVERIFIED_ARGS = JSONField(
        help_text="Any additional fields that this authenticator can take, they are not validated and passed directly back to the authenticator",
        required=False,
        allow_null=True,
    )

    def get_configuration_schema(self):
        fields = self.get_fields()

        schema = []

        for f in fields:
            field = fields[f]
            default = None
            print(empty)
            if field.default is not empty:
                default = field.default

            schema.append({"name": f, "help_text": field.help_text, "required": not field.allow_null, "default": default, "type": field.__class__.__name__})
        return schema


class AbstractAuthenticatorPlugin:
    """
    Base class for non social auth backends
    """

    configuration_class = BaseAuthenticatorConfiguration

    def __init__(self, database_instance=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.database_instance = database_instance

    def set_logger(self, logger) -> None:
        if not logger:
            self.logger = logging.getLogger('ansible_base.models.abstract_authenticator')
        else:
            self.logger = logger

    def validate_configuration(self, data: dict, instance: object) -> None:
        if not issubclass(self.configuration_class, BaseAuthenticatorConfiguration):
            raise TypeError("self.configuration_class must subclass BaseAuthenticatorConfiguration.")

        serializer = self.configuration_class(data=data)
        serializer.is_valid(raise_exception=True)

        allowed_fields = serializer.get_fields()
        errors = {}
        for k in data:
            if k not in allowed_fields:
                errors[k] = _(f"{k} is not a supported configuration option.")

        if errors:
            raise ValidationError(errors)

    def update_settings(self, database_authenticator: Authenticator) -> None:
        self.settings = database_authenticator.configuration

    def update_if_needed(self, database_authenticator: Authenticator) -> None:
        if not self.database_instance or self.database_instance.modified_on != database_authenticator.modified_on:
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
