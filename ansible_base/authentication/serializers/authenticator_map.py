import logging

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.utils.translation import gettext_lazy as _
from rest_framework.serializers import ValidationError

from ansible_base.authentication.models import AuthenticatorMap
from ansible_base.authentication.utils.trigger_definition import TRIGGER_DEFINITION
from ansible_base.lib.serializers.common import NamedCommonModelSerializer
from ansible_base.lib.utils.auth import get_organization_model, get_team_model
from ansible_base.lib.utils.string import is_empty

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

        if errors:
            raise ValidationError(errors)
        return data

    @staticmethod
    def _is_rbac_installed():
        return 'ansible_base.rbac' in settings.INSTALLED_APPS

    def validate_role_data(self, map_type, role, org, team):
        errors = {}

        # Validation is possible only if RBAC is installed
        if not self._is_rbac_installed():
            logger.warning(_("You specified a role without RBAC installed "))
            return errors

        from ansible_base.rbac.models import RoleDefinition

        try:
            rbac_role = RoleDefinition.objects.get(name=role)
            is_system_role = rbac_role.content_type is None

            # system role is allowed for map type == role without further conditions
            if is_system_role and map_type == 'role':
                return errors

            if is_system_role:
                is_org_role, is_team_role = False, False
            else:
                model_class = rbac_role.content_type.model_class()
                is_org_role = issubclass(model_class, get_organization_model())
                is_team_role = issubclass(model_class, get_team_model())

            # role type and map type must correspond
            if map_type == 'organization' and not is_org_role:
                errors['role'] = _("For an organization map type you must specify an organization based role")

            if map_type == 'team' and not is_team_role:
                errors['role'] = _("For a team map type you must specify a team based role")

            # org/team role needs organization field
            if (is_org_role or is_team_role) and is_empty(org):
                errors["organization"] = _("You must specify an organization with the selected role")

            # team role needs team field
            if is_team_role and is_empty(team):
                errors["team"] = _("You must specify a team with the selected role")

        except ObjectDoesNotExist:
            errors['role'] = _("RoleDefinition {role} doesn't exist").format(role=role)

        return errors

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
