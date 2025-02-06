from collections import OrderedDict

from django.utils.translation import gettext_lazy as _
from rest_framework.serializers import ChoiceField, ValidationError

from ansible_base.authentication.authenticator_plugins.utils import generate_authenticator_slug, get_authenticator_plugin, get_authenticator_plugins
from ansible_base.authentication.models import Authenticator
from ansible_base.lib.serializers.common import NamedCommonModelSerializer
from ansible_base.lib.serializers.mixins import ImmutableFieldsMixin
from ansible_base.lib.utils.encryption import ENCRYPTED_STRING
from ansible_base.lib.utils.response import get_relative_url


class AuthenticatorSerializer(NamedCommonModelSerializer, ImmutableFieldsMixin):
    type = ChoiceField(get_authenticator_plugins())

    def validate_type(self, value):
        if self.instance and self.instance.type != value:
            raise ValidationError(_("Cannot change authenticator type after it has been created."))
        return value

    def validate_slug(self, value):
        # Only need to perform creation validation for immutable fields;
        # read_only fields do not include the value in input to the serializer.
        value = generate_authenticator_slug(value)

        return value

    class Meta:
        model = Authenticator
        fields = NamedCommonModelSerializer.Meta.fields + [x.name for x in Authenticator._meta.concrete_fields]
        fields.remove("category")
        immutable_fields = ["slug"]
        extra_kwargs = {
            "slug": {
                "allow_blank": True,
                "required": False,
            }
        }

    # TODO: Do we need/want to delve into dicts and search their keys?
    def to_representation(self, authenticator):
        ret = super().to_representation(authenticator)
        configuration = authenticator.configuration
        masked_configuration = OrderedDict()

        try:
            authenticator_plugin = get_authenticator_plugin(authenticator.type)
            encrypted_keys = authenticator_plugin.configuration_encrypted_fields

            # If the authenticator configuration has a to_representation we need to respect it
            ret['configuration'] = authenticator_plugin.to_representation(authenticator)

            keys = list(configuration.keys())
            keys.sort()
            # Mask any keys in the encryption that should be masked
            for key in keys:
                if key in encrypted_keys:
                    masked_configuration[key] = ENCRYPTED_STRING
                else:
                    masked_configuration[key] = configuration[key]
            ret['configuration'] = masked_configuration
        except ImportError:
            # A log message will already be displayed if we can't load this
            ret['configuration'] = {}
            ret['error'] = _('Failed to load the plugin behind this authenticator, configuration hidden to protect secrets')
            return ret

        # Generate a sso login URL if this is an sso category
        login_url = authenticator.get_login_url()
        if login_url:
            ret['sso_login_url'] = login_url

        return ret

    def to_internal_value(self, data):
        parsed_data = super().to_internal_value(data)

        # Incase type was not passed in the data (like from a patch) we need to take it from the existing instance
        type = parsed_data.get('type', getattr(self.instance, 'type', None))

        # Here we will let a stack trace propagate because we can't convert this thing to an internal value and we likely don't want to save
        authenticator_plugin = get_authenticator_plugin(type)

        encrypted_keys = authenticator_plugin.configuration_encrypted_fields

        configuration = parsed_data.get('configuration', {})

        for key in encrypted_keys:
            if configuration.get(key, None) and self.instance and configuration.get(key, None) == ENCRYPTED_STRING:
                configuration[key] = self.instance.configuration.get(key)

        return parsed_data

    def validate(self, data) -> dict:
        # prevent disabling the last enabled authenticator
        if data.get('enabled') is False:
            if self.instance and self.instance.is_last_enabled:
                raise ValidationError(_("At least one authenticator must be enabled"))

        validator_type = data.get('type', None)
        # if we didn't have a type, try to get the type of the existing object (if we have one)
        if not validator_type and self.instance:
            validator_type = self.instance.type

        configuration = data.get('configuration', None)
        # Not having configuration is only valid for a PATCH
        request = self.context.get('request', None)
        if not request or (request.method != 'PATCH' and configuration is None):
            raise ValidationError(_("You must specify configuration for the authenticator"))

        if auto_migrate := data.get('auto_migrate_users_to'):
            if auto_migrate.auto_migrate_users_to is not None:
                raise ValidationError(
                    {
                        "auto_migrate_users_to": _(
                            "The authenticator you have picked is already configured to auto migrate users from a different authenticator."
                        )
                    }
                )

        try:
            invalid_encrypted_keys = {}
            authenticator = get_authenticator_plugin(validator_type)
            data = authenticator.validate(self, data)

            if configuration or configuration == {}:
                for key in authenticator.configuration_encrypted_fields:
                    if not self.instance and configuration.get(key, None) == ENCRYPTED_STRING:
                        invalid_encrypted_keys[key] = _("Can not be set to %(ENCRYPTED_STRING)s") % {"ENCRYPTED_STRING": ENCRYPTED_STRING}
                if invalid_encrypted_keys:
                    raise ValidationError(invalid_encrypted_keys)
                data['configuration'] = authenticator.validate_configuration(configuration, self.instance)
            return data
        except ImportError as e:
            raise ValidationError({'type': _('Failed to import %(e)s') % {'e': e}})

    def _get_related(self, obj) -> dict[str, str]:
        related = super()._get_related(obj)
        from ansible_base.authentication.views.authenticator_users import get_authenticator_user_view

        if get_authenticator_user_view():
            related['users'] = get_relative_url('authenticator-users-list', kwargs={'pk': obj.pk})

        return related
