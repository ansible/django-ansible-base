import logging
from typing import Optional

from django.utils.translation import gettext_lazy as _
from rest_framework.serializers import ValidationError

from ansible_base.authentication.models import AuthenticatorMap
from ansible_base.authentication.utils.authenticator_map import _EXPANSION_FIELDS, check_expansion_syntax, check_role_type, has_expansion
from ansible_base.authentication.utils.trigger_definition import TRIGGER_DEFINITION
from ansible_base.lib.serializers.common import NamedCommonModelSerializer
from ansible_base.lib.utils.string import is_empty
from ansible_base.lib.utils.typing import TranslatedString

logger = logging.getLogger('ansible_base.authentication.serializers.authenticator_map')


class AuthenticatorMapSerializer(NamedCommonModelSerializer):
    class Meta:
        model = AuthenticatorMap
        fields = NamedCommonModelSerializer.Meta.fields + ['authenticator', 'map_type', 'role', 'organization', 'team', 'revoke', 'triggers', 'order']

    def validate(self, data) -> dict:
        errors = {}
        errors.update(self.validate_trigger_data(data))

        map_type = data.get('map_type', None)
        team = data.get('team', None)
        org = data.get('organization', None)
        role = data.get('role', None)

        if map_type == 'team' and is_empty(team):
            errors["team"] = _("You must specify a team with the selected map type")
        if map_type in ['team', 'organization'] and is_empty(org):
            errors["organization"] = _("You must specify an organization with the selected map type")
        if map_type in ['team', 'organization', 'role'] and is_empty(role):
            errors["role"] = _("You must specify a role with the selected map type")
        if map_type in ['allow', 'is_superuser'] and not is_empty(role):
            errors["role"] = _("You cannot specify role with the selected map type")

        if role:
            errors.update(self.validate_role_data(map_type, role, org, team))

        for field in _EXPANSION_FIELDS:
            if error_message := check_expansion_syntax(data.get(field, None)):
                # Its really not possible to have two errors on the same time.
                # Other errors indicate that things are missing so they would never get into here
                errors[field] = error_message

        if errors:
            raise ValidationError(errors)
        return data

    def validate_role_data(self, map_type: Optional[str], role: Optional[str], org: Optional[str], team: Optional[str]) -> dict[str, TranslatedString]:
        # If the role field has an expansion in it we can only check this role at runtime
        if has_expansion(role):
            return {}

        return check_role_type(map_type, role, org, team)

    def validate_trigger_data(self, data):
        errors = {}
        request = self.context.get('request', None)
        if 'triggers' not in data or not data['triggers']:
            if not request or (request.method != 'PATCH'):
                errors["triggers"] = "Triggers must be a valid dict"
        else:
            errors.update(self._validate_trigger_data(data['triggers'], TRIGGER_DEFINITION, 'triggers'))
        return errors

    def _validate_trigger_data(self, triggers: dict, definition, error_prefix: str) -> dict:
        """
        Examples of valid data:
        - {triggers: {'groups': {'has_or': ['aaa', 'bbb'], 'has_and': ['ccc']}}}
        - {triggers: {'always': {}}}
        - {triggers: {'never': {}}}
        - {triggers: {'attributes': {'join_condition': "and",
                                   'some_attr1': {'contains': "some_str"},
                                   'some_attr2': {'ends_with': "some_str"}}}}
        """
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
                errors.update(self._validate_trigger_data(triggers[trigger_type], type_definition['keys'], f'{error_prefix}.{trigger_type}'))
            elif isinstance(triggers[trigger_type], str):
                if 'choices' in type_definition:
                    if triggers[trigger_type] not in type_definition['choices']:
                        errors[f'{error_prefix}.{trigger_type}'] = f"Invalid, choices can only be one of: {', '.join(type_definition['choices'])}"
            elif isinstance(triggers[trigger_type], list):
                if 'contents' in type_definition:
                    for item in triggers[trigger_type]:
                        if not isinstance(item, type(type_definition['contents'])):
                            errors[f'{error_prefix}.{trigger_type}.{item}'] = (
                                f"Invalid, must be of type {type(type_definition['contents']).__name__}, got {type(item)}"
                            )

        return errors
