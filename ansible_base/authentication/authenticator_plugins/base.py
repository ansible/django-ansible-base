import logging

from django.db import IntegrityError, transaction
from django.utils.translation import gettext_lazy as _
from rest_framework import serializers
from rest_framework.fields import empty
from rest_framework.serializers import ValidationError

from ansible_base.authentication.models import Authenticator
from ansible_base.lib.serializers.fields import JSONField
from ansible_base.lib.utils.response import get_relative_url

logger = logging.getLogger('ansible_base.authentication.authenticator_plugins.base')


def _field_required(field):
    if hasattr(field, 'required'):
        return field.required
    elif hasattr(field, 'allow_null'):
        return not field.allow_null
    return True


class BaseAuthenticatorConfiguration(serializers.Serializer):
    documentation_url = None
    ADDITIONAL_UNVERIFIED_ARGS = JSONField(
        help_text=_("Any additional fields that this authenticator can take, they are not validated and passed directly back to the authenticator"),
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
            "role_assignments",
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
                    except IntegrityError:
                        continue

        return old_user
