import logging
from typing import Any, Optional

from django.utils.translation import gettext_lazy as _
from rest_framework.serializers import ValidationError

from ansible_base.authentication.models import AuthenticatorMap
from ansible_base.authentication.utils.authenticator_map import _EXPANSION_FIELDS, check_expansion_syntax, check_role_type, has_expansion
from ansible_base.authentication.utils.trigger_definition import TRIGGER_DEFINITION
from ansible_base.lib.serializers.common import NamedCommonModelSerializer
from ansible_base.lib.serializers.fields import JSONField
from ansible_base.lib.serializers.mixins import _INCOMPLETE_VALIDATION_MSG, CleanTextMixin
from ansible_base.lib.utils.settings import get_setting
from ansible_base.lib.utils.string import is_empty
from ansible_base.lib.utils.typing import TranslatedString
from ansible_base.lib.utils.validation import validate_free_text

logger = logging.getLogger('ansible_base.authentication.serializers.authenticator_map')


class AuthenticatorMapSerializer(CleanTextMixin, NamedCommonModelSerializer):
    triggers = JSONField(
        required=True,
        allow_null=False,
        error_messages={'required': 'Triggers must be a valid dict'},
        help_text="Required. Trigger conditions dictionary that determines when this map applies. "
        "See /trigger_definition/ for structure details. Only one top-level key per request.",
    )

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
        return super().validate(data)

    def _run_text_validator(self, field_name, value, errors):
        # organization/role/team accept {% for_attr_value() %} template expansion syntax;
        # check_expansion_syntax() above already validates the format of such values. Skip
        # CleanTextMixin's Tier 1/Tier 2 validation only for values that actually use
        # expansion syntax — literal content still runs through the normal free-text check.
        # See docs/lib/validation.md "AuthenticatorMap field exclusions" for details.
        if field_name in _EXPANSION_FIELDS and has_expansion(value):
            return
        super()._run_text_validator(field_name, value, errors)

    def _validate_json_fields(self, field_names, attrs, errors):
        """Run CleanText JSON validation, then Tier 2 checks on attribute trigger names."""
        super()._validate_json_fields(field_names, attrs, errors)
        if 'triggers' not in field_names:
            return
        triggers = attrs.get('triggers')
        if triggers is None:
            return
        attr_key_errors = self._validate_trigger_attribute_name_keys(triggers)
        if attr_key_errors:
            self._merge_trigger_attribute_key_errors(errors, attr_key_errors)

    @staticmethod
    def _merge_trigger_attribute_key_errors(errors: dict, attr_key_errors: dict[str, Any]) -> None:
        """Combine attribute-name validation errors with existing ``triggers`` errors."""
        triggers_errors = errors.get('triggers')
        if triggers_errors is None:
            errors['triggers'] = attr_key_errors
        elif isinstance(triggers_errors, dict):
            triggers_errors.update(attr_key_errors)
        else:
            errors['triggers'] = attr_key_errors

    def _stored_trigger_attributes(self) -> dict[str, Any]:
        """Return stored ``triggers.attributes`` for grandfathering attribute names on update."""
        if not self.instance or not isinstance(self.instance.triggers, dict):
            return {}
        stored = self.instance.triggers.get('attributes')
        return stored if isinstance(stored, dict) else {}

    def _validate_trigger_attribute_name_keys(self, triggers: dict) -> dict[str, Any]:
        """Tier 2 validation for user-defined attribute names under triggers.attributes.

        CleanTextMixin's JSON walk validates string values only; attribute names are
        stored as dict keys. Grandfather unchanged key names on update.
        """
        if not isinstance(triggers, dict):
            return {}
        attributes = triggers.get('attributes')
        if not isinstance(attributes, dict):
            return {}

        stored_attributes = self._stored_trigger_attributes()
        key_errors: dict[str, Any] = {}
        for attr_name in attributes:
            self._validate_one_trigger_attribute_name_key(attr_name, stored_attributes, key_errors)
        return key_errors

    def _validate_one_trigger_attribute_name_key(self, attr_name, stored_attributes: dict[str, Any], key_errors: dict[str, Any]) -> None:
        """Apply Tier 2 to one attribute name unless it is ``join_condition`` or already stored."""
        if attr_name == 'join_condition' or not isinstance(attr_name, str):
            return
        if attr_name in stored_attributes:
            return
        error_key = f'attributes.{attr_name}'
        try:
            validate_free_text(attr_name)
        except ValidationError as exc:
            key_errors[error_key] = exc.detail
            self._log_validation_failure('triggers.attributes', exc.detail)
        except Exception:
            logger.exception("Unexpected error validating trigger attribute name under triggers.attributes")
            if get_setting('ENHANCED_INPUT_VALIDATION_ENABLED', False):
                key_errors[error_key] = [_INCOMPLETE_VALIDATION_MSG]

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
