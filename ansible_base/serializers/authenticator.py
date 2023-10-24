from collections import OrderedDict

from rest_framework.reverse import reverse
from rest_framework.serializers import ValidationError

from ansible_base.authenticator_plugins.utils import get_authenticator_plugin
from ansible_base.models import Authenticator
from ansible_base.utils.encryption import ENCRYPTED_STRING

from .common import NamedCommonModelSerializer


class AuthenticatorSerializer(NamedCommonModelSerializer):
    reverse_url_name = 'authenticator-detail'

    class Meta:
        model = Authenticator
        fields = NamedCommonModelSerializer.Meta.fields + [x.name for x in Authenticator._meta.concrete_fields]

    # TODO: Do we need/want to delve into dicts and search their keys?
    def to_representation(self, authenticator):
        ret = super().to_representation(authenticator)
        configuration = authenticator.configuration
        masked_configuration = OrderedDict()
        keys = list(configuration.keys())
        encrypted_keys = []

        authenticator_plugin = get_authenticator_plugin(authenticator.type)
        encrypted_keys = authenticator_plugin.configuration_encrypted_fields

        keys.sort()
        # Mask any keys in the encryption that should be masked
        for key in keys:
            if key in encrypted_keys:
                masked_configuration[key] = ENCRYPTED_STRING
            else:
                masked_configuration[key] = configuration[key]
        ret['configuration'] = masked_configuration

        # Generate a sso login URL if this is an sso category
        if authenticator.category == 'sso':
            ret['sso_login_url'] = reverse('social:begin', kwargs={'backend': authenticator.slug})

        return ret

    def validate(self, data) -> dict:
        validator_type = data.get('type', None)
        # if we didn't have a type, try to get the type of the existing object (if we have one)
        if not validator_type and self.instance:
            validator_type = self.instance.type

        try:
            authenticator = get_authenticator_plugin(validator_type)
            authenticator.validate_configuration(data['configuration'], self.instance)
        except ImportError as e:
            raise ValidationError({'type': e})
        return data
