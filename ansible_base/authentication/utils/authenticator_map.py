import logging
import re
from typing import Any, Dict, Optional

from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.utils.translation import gettext_lazy as _

from ansible_base.authentication.models import AuthenticatorMap
from ansible_base.lib.utils.auth import get_organization_model, get_team_model
from ansible_base.lib.utils.collection import dict_cartesian_product
from ansible_base.lib.utils.string import is_empty
from ansible_base.lib.utils.typing import TranslatedString

logger = logging.getLogger('ansible_base.authentication.utils.authenticator_map')

_EXPANSION_FIELDS = ['organization', 'role', 'team']
_EXPANSION_RE = re.compile(r'{%\s*for_attr_value\(([^(%})]+)\)\s*%}')


def has_expansion(value: Optional[str]) -> bool:
    """
    Checks the given value to see if it has the expansion syntax
    """
    if not value:
        return False
    if re.search(r'{%.*%}', value):
        return True
    else:
        return False


def check_expansion_syntax(value: Optional[str]) -> Optional[TranslatedString]:
    """
    Check a given field to see if it contains the proper syntax for {% for_attr_value(user_orgs) %}
    """

    if has_expansion(value) and not _EXPANSION_RE.search(value):
        return _("Expansion only supports the format {% for_attr_value(attribute) %}")


def expand_syntax(attributes: dict, auth_map: AuthenticatorMap) -> list[Dict[str, str]]:
    """
    Given attributes and a map, look for the fields that can be expanded and do the expansion
    If no fields require expansion, do nothing

    returns:
    list of named tuples of expanded value
    """
    expanded_strings = {}
    for field in _EXPANSION_FIELDS:
        field_value = getattr(auth_map, field, None)

        if field_value is None:
            # If this particular field is None we can move on.
            # This might be true for the team value of an authenticator map type of organization for example.
            continue

        # Get a list of all of the attributes specified in {% for_attr_value(something) %}
        # In the above example, we would get a list like ['something'].
        # If there were more than one in a given string we would have an array like ['something', 'else']
        attrs_used = _EXPANSION_RE.findall(field_value)

        if has_expansion(field_value) and attrs_used == []:
            # This field had an invalid expansion so we can't expand anything, just return []
            logger.info(
                f"Authenticator Map {auth_map.name} on {auth_map.authenticator.name} has a bad expansion in {field} unable to process map ({field_value})"
            )
            continue

        # Make sure that the attributes we got contain all the ones we want to expand
        if missing_attributes := set(attrs_used).difference(set(attributes.keys())):
            logger.info(
                f"Authenticator Map {auth_map.name} on {auth_map.authenticator.name} tried to expand attribute(s) "
                f"{', '.join(missing_attributes)} but they were not in the users attributes!"
            )
            continue

        # Normalize and check the attribute values we are going to use
        try:
            normalized_attributes = _normalize_attributes(auth_map, attrs_used, attributes)
        except ValueError:
            # If we had issues normalizing the data we can just move on because if can't replace
            # even one of the items in the string there is no point in trying at all
            continue

        # Create an entry in our expanded_string dictionary with the initial value of the field
        expanded_strings[field] = [field_value]

        # For each value in the attribute, expand the strings
        # Lets say we have a field like "Organization {% for_attr_value(org) %} - Department {% for attr_value(dept) %}"
        # And in our attributes we had:
        #    org = ["a", "b"]
        #    dept = ['Z', 'Y']
        # First our string list will be:
        #     ['Organization {% for_attr_value(org) %} - Department {% for attr_value(dept) %}']
        # After the first pass of this loop, our string list will be:
        #     ['Organization a - Department {% for attr_value(dept) %}', 'Organization b Department {% for attr_value(dept) %}']
        # After the second pass the string list will be:
        #     [
        #         ['Organization a - Department Z'
        #         ['Organization a - Department Y'
        #         ['Organization b - Department Z'
        #         ['Organization b - Department Y'
        #     ]
        expanded_strings[field] = _expand_strings(attrs_used, normalized_attributes, expanded_strings[field])

    # Return the cartesian product of the expanded strings
    return dict_cartesian_product(expanded_strings)


def _expand_strings(attrs_used: list[str], normalized_attributes: dict[str, list[str]], expanded_strings: list[str]) -> list[str]:
    for attr_name in attrs_used:
        # Make a list of new strings.
        new_strings = []

        for value in normalized_attributes[attr_name]:
            for string in expanded_strings:
                new_strings.append(_EXPANSION_RE.sub(value, string, 1))

        expanded_strings = new_strings

    return expanded_strings


def _normalize_attributes(auth_map: AuthenticatorMap, attrs_used: list[str], attributes: dict) -> dict[str, list[str]]:
    """
    Normalize the attributes we are going to use

    Given a list of attributes that are used (i.e. ["first_name", "last_name"]) create and return a dictionary of attributes lke:
        {
            "first_name": ["all", "values", "of", "first_name"],
            "last_name": ["value"],
        }

    If the list contains non-strings we will raise errors

    Raises ValueError if we got one or more issues when normalizing values
    """
    normalized_attributes = {}
    errors = []
    for attr_name in attrs_used:
        attr_errors = []
        # Make sure the attribute is in the list of attributes we have.
        attr_value = _make_list(attributes.get(attr_name, []))

        if len(attr_value) == 0:
            attr_errors.append(
                f"Authenticator Map {auth_map.name} on {auth_map.authenticator.name} tried to expand attribute {attr_name} "
                f"but there were not values in that attribute, ignoring"
            )

        # If any of the values are not a string then we can't expand it
        for value in attr_value:
            if type(value) is not str:
                attr_errors.append(
                    f"Authenticator Map {auth_map.name} on {auth_map.authenticator.name} tried to expand attribute {attr_name} "
                    f"but that was not a list of string, instead got {value}, ignoring"
                )

        if attr_errors == []:
            normalized_attributes[attr_name] = attr_value
        else:
            # If we got errors for this item add them to the overall errors for logging
            errors.extend(attr_errors)
            for error in attr_errors:
                logger.info(error)

    if errors:
        raise ValueError()

    return normalized_attributes


def _make_list(value: Any) -> list[Any]:
    if type(value) is list:
        return value
    return [value]


def _is_rbac_installed():
    """
    Determine if RBAC is installed.
    Separated out for easy mocking.
    """
    return 'ansible_base.rbac' in settings.INSTALLED_APPS


def check_role_type(map_type: Optional[str], role: Optional[str], org: Optional[str], team: Optional[str]) -> dict[str, TranslatedString]:
    errors = {}

    if not _is_rbac_installed():
        errors['role'] = _("You specified a role without RBAC installed ")
        return errors

    from ansible_base.rbac.models import RoleDefinition

    try:
        rbac_role = RoleDefinition.objects.get(name=role)
        is_system_role = rbac_role.content_type is None

        # system role is allowed for map type == role without further conditions
        if is_system_role and map_type == 'role':
            return errors

        is_org_role, is_team_role = False, False
        if not is_system_role:
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
