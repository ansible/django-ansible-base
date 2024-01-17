from rest_framework.serializers import ValidationError

from ansible_base.authentication.models import AuthenticatorMap
from ansible_base.authentication.utils.trigger_definition import TRIGGER_DEFINITION
from ansible_base.common.serializers.common import NamedCommonModelSerializer


class AuthenticatorMapSerializer(NamedCommonModelSerializer):
    reverse_url_name = 'authenticator_map-detail'

    class Meta:
        model = AuthenticatorMap
        fields = NamedCommonModelSerializer.Meta.fields + ['authenticator', 'order', 'organization', 'revoke', 'team', 'triggers', 'map_type']

    def validate(self, data) -> dict:
        errors = {}
        if 'triggers' not in data or not data['triggers']:
            errors["triggers"] = "Triggers must be a valid dict"
        else:
            errors.update(self.validate_trigger_data(data['triggers'], TRIGGER_DEFINITION, 'triggers'))

        map_type = data.get('map_type', None)
        team = data.get('team', None)
        org = data.get('organization', None)
        if map_type == 'team' and not team:
            errors["team"] = "You must specify a team with the selected map type"
        if map_type == 'team' and not org:
            errors["organization"] = "You must specify an organization with the selected map type"
        if map_type == 'organization' and not org:
            errors["organization"] = "You must specify an organization with the selected map type"

        if not data.get('order', None):
            errors['order'] = "Must be a valid integer"

        if errors:
            raise ValidationError(errors)
        return data

    def validate_trigger_data(self, triggers: dict, definition, error_prefix: str) -> dict:
        errors = {}

        # Validate only valid items
        for trigger_type in triggers.keys():
            type_definition = definition.get(trigger_type, definition.get('*', None))
            if not type_definition:
                errors[f'{error_prefix}.{trigger_type}'] = f"Invalid, can only be one of: {', '.join(definition.keys())}"
                continue

            # Validate the type we got is what we expect
            if not isinstance(triggers[trigger_type], type(type_definition['type'])):
                errors[f'{error_prefix}.{trigger_type}'] = f"Expected {type(type_definition['type']).__name__} but got {type(triggers[trigger_type]).__name__}"
                continue

            if isinstance(triggers[trigger_type], dict):
                errors.update(self.validate_trigger_data(triggers[trigger_type], type_definition['keys'], f'{error_prefix}.{trigger_type}'))
            elif isinstance(triggers[trigger_type], str):
                if 'choices' in type_definition:
                    if triggers[trigger_type] not in type_definition['choices']:
                        errors[f'{error_prefix}.{trigger_type}'] = f"Invalid, choices can only be one of: {', '.join(type_definition['choices'])}"
            elif isinstance(triggers[trigger_type], list):
                if 'contents' in type_definition:
                    for item in triggers[trigger_type]:
                        if not isinstance(item, type(type_definition['contents'])):
                            errors[
                                f'{error_prefix}.{trigger_type}.{item}'
                            ] = f"Invalid, must be of type {type(type_definition['contents']).__name__}, got {type(item)}"

        return errors
