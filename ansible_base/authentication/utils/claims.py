import logging
import re

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils.timezone import now
from social_core.pipeline.user import get_username

from ansible_base.authentication.models import Authenticator, AuthenticatorMap, AuthenticatorUser
from ansible_base.authentication.social_auth import AuthenticatorStorage, AuthenticatorStrategy

from .trigger_definition import TRIGGER_DEFINITION

logger = logging.getLogger('ansible_base.authentication.utils.claims')


def create_claims(authenticator: Authenticator, username: str, attrs: dict, groups: list) -> (bool, bool, dict, list):
    '''
    Given an authenticator and a username, attrs and groups determine what the user has access to
    '''

    # Assume we are not going to change our flags
    is_superuser = None
    is_system_auditor = None
    # Assume we start with no mappings
    org_team_mapping = {}
    # Assume we are not members of any orgs (direct members)
    organization_membership = {}
    # Start with an empty rule responses
    rule_responses = []
    # Assume we will have access
    access_allowed = True
    logger.info(f"Creating mapping for user {username} through authenticator {authenticator.name}")
    logger.debug(f"{username}'s groups: {groups}")
    logger.debug(f"{username}'s attrs: {attrs}")

    # load the maps
    maps = AuthenticatorMap.objects.filter(authenticator=authenticator.id).order_by("order")
    for auth_map in maps:
        has_permission = None
        allowed_keys = TRIGGER_DEFINITION.keys()
        invalid_keys = set(auth_map.triggers.keys()) - set(allowed_keys)
        if invalid_keys:
            logger.warning(f"In AuthenticatorMap {auth_map.id} the following trigger keys are invalid: {', '.join(invalid_keys)}, rule will be ignored")
            rule_responses.append({auth_map.id: 'invalid'})
            continue

        for trigger_type, trigger in auth_map.triggers.items():
            if trigger_type == 'groups':
                has_permission = process_groups(trigger, groups, authenticator.name)
            if trigger_type == 'attributes':
                has_permission = process_user_attributes(trigger, attrs, authenticator.name)
            if trigger_type == 'always':
                has_permission = True
            if trigger_type == 'never':
                has_permission = False

        # If we didn't get permission and we are set to revoke permission we can set has_permission to False
        if auth_map.revoke and not has_permission:
            has_permission = False

        if has_permission is None:
            rule_responses.append({auth_map.id: 'skipped'})
            continue

        rule_responses.append({auth_map.id: has_permission})

        if auth_map.map_type == 'allow' and not has_permission:
            # If any rule does not allow we don't want to return this to true
            access_allowed = False
        elif auth_map.map_type == 'is_superuser':
            is_superuser = has_permission
        elif auth_map.map_type == 'is_system_auditor':
            is_system_auditor = has_permission
        elif auth_map.map_type == 'team':
            if auth_map.organization not in org_team_mapping:
                org_team_mapping[auth_map.organization] = {}
            org_team_mapping[auth_map.organization][auth_map.team] = has_permission
        elif auth_map.map_type == 'organization':
            organization_membership[auth_map.organization] = has_permission
        else:
            logger.error(f"Map type {auth_map.map_type} of rule {auth_map.name} does not know how to be processed")

    return {
        "access_allowed": access_allowed,
        "is_superuser": is_superuser,
        "is_system_auditor": is_system_auditor,
        "claims": {
            "team_membership": org_team_mapping,
            "organization_membership": organization_membership,
        },
        "last_login_map_results": rule_responses,
    }


def process_groups(trigger_condition: dict, groups: list, authenticator_id: int) -> bool:
    '''
    Looks at a maps trigger for a group and users groups and determines if the trigger True or False
    '''

    invalid_conditions = set(trigger_condition.keys()) - set(TRIGGER_DEFINITION['groups']['keys'].keys())
    if invalid_conditions:
        logger.warning(f"The conditions {', '.join(invalid_conditions)} for groups in mapping {authenticator_id} are invalid and won't be processed")

    has_access = None
    set_of_user_groups = set(groups)

    if "has_or" in trigger_condition:
        if set_of_user_groups.intersection(set(trigger_condition["has_or"])):
            has_access = True
        else:
            has_access = False

    elif "has_and" in trigger_condition:
        if set(trigger_condition["has_and"]).issubset(set_of_user_groups):
            has_access = True
        else:
            has_access = False

    elif "has_not" in trigger_condition:
        if set(trigger_condition["has_not"]).intersection(set_of_user_groups):
            has_access = False
        else:
            has_access = True

    return has_access


def has_access_with_join(current_access: bool, new_access: bool, condition: str = 'or') -> bool:
    '''
    Handle join of authenticator_maps
    '''
    if current_access is None:
        return new_access

    if condition == 'or':
        return current_access or new_access

    if condition == 'and':
        return current_access and new_access


def process_user_attributes(trigger_condition: dict, attributes: dict, authenticator_id: int) -> bool:
    '''
    Looks at a maps trigger for an attribute and the users attributes and determines if the trigger is True, False or None
    '''

    has_access = None
    join_condition = trigger_condition.get('join_condition', 'or')
    if join_condition not in TRIGGER_DEFINITION['attributes']['keys']['join_condition']['choices']:
        logger.warning("Trigger join_condition {join_condition} on authenticator map {authenticator_id} is invalid and will be set to 'or'")
        join_condition = 'or'

    for attribute in trigger_condition.keys():
        if has_access and join_condition == 'or':
            # If we are an or condition and we already have a positive we can break out and return
            break
        elif has_access is False and join_condition == 'and':
            # If we are an and and already have a False we can give up
            break

        # We can skip the join_condition since we already processed that.
        if attribute == 'join_condition':
            continue

        # Warn if there are any invalid conditions, we are just going to ignore them
        invalid_conditions = set(trigger_condition[attribute].keys()) - set(TRIGGER_DEFINITION['attributes']['keys']['*']['keys'].keys())
        if invalid_conditions:
            logger.warning(
                f"The conditions {', '.join(invalid_conditions)} for attribute {attribute} "
                "in authenticator map {authenticator_id} are invalid and won't be processed"
            )

        # The attribute is an empty dict we just need to see if the user has the attribute or not
        if trigger_condition[attribute] == {}:
            has_access = has_access_with_join(has_access, attribute in attributes, join_condition)
            continue

        user_value = attributes.get(attribute, None)
        # If the user does not contain the attribute then we can't check any further, don't set has_access and just continue
        if user_value is None:
            continue

        if type(user_value) is not list:
            # If the value is a string then convert it to a list
            user_value = [user_value]

        for a_user_value in user_value:
            # We are going to do mostly string comparisons, so convert the attribute to a
            #  string just in case it came back as an int or something funky
            a_user_value = f"{a_user_value}"

            # Check for any of the valid conditions
            if "equals" in trigger_condition[attribute]:
                has_access = has_access_with_join(has_access, a_user_value == trigger_condition[attribute]["equals"], join_condition)

            elif "matches" in trigger_condition[attribute]:
                has_access = has_access_with_join(
                    has_access, re.match(trigger_condition[attribute]["matches"], a_user_value, re.IGNORECASE) is not None, join_condition
                )

            elif "contains" in trigger_condition[attribute]:
                has_access = has_access_with_join(has_access, trigger_condition[attribute]['contains'] in a_user_value, join_condition)

            elif "ends_with" in trigger_condition[attribute]:
                has_access = has_access_with_join(has_access, a_user_value.endswith(trigger_condition[attribute]['ends_with']), join_condition)

            elif "in" in trigger_condition[attribute]:
                has_access = has_access_with_join(has_access, a_user_value in trigger_condition[attribute]['in'], join_condition)

    return has_access


def get_local_username(user_details, authenticator):
    """
    Converts the username provided by the backend to one that doesn't conflict with users
    from other auth backends.
    """

    class FakeBackend:
        def setting(self, *args, **kwargs):
            return ["username", "email"]

    username = get_username(strategy=AuthenticatorStrategy(AuthenticatorStorage()), details=user_details, backend=FakeBackend())

    if username:
        return username["username"]
    else:
        return user_details["username"]


def get_or_create_authenticator_user(user_id, user_details, authenticator, extra_data):
    """
    Create the user object in the database along with it's associated AuthenticatorUser class.
    """

    extra = {**extra_data, "auth_time": now().isoformat()}

    try:
        auth_user = AuthenticatorUser.objects.get(uid=user_id, provider=authenticator)
        auth_user.extra_data = extra
        auth_user.save()
        return (auth_user, False)
    except AuthenticatorUser.DoesNotExist:
        username = get_local_username(user_details, authenticator)

        # ensure the authenticator isn't trying to pass along a cheeky is_superuser in user_details
        allowed_keys = ["first_name", "last_name", "email"]
        details = {k: user_details.get(k, "") for k in allowed_keys if k}

        local_user, created = get_user_model().objects.get_or_create(username=username, defaults=details)

        return (AuthenticatorUser.objects.create(user=local_user, uid=user_id, extra_data=extra, provider=authenticator), True)


def update_user_claims(user, database_authenticator, groups):
    if not user:
        return None

    results = create_claims(database_authenticator, user.username, user.authenticator_user.extra, groups)

    needs_save = False
    authenticator_user, _ = AuthenticatorUser.objects.get_or_create(provider=database_authenticator, user=user)
    for attribute, attr_value in results.items():
        if attr_value is None:
            continue
        logger.debug(f"{attribute}: {attr_value}")
        if hasattr(user, attribute):
            object = user
        elif hasattr(authenticator_user, attribute):
            object = authenticator_user
        else:
            logger.error(f"Neither user nor authenticator user has attribute {attribute}")
            continue

        if getattr(object, attribute, None) != attr_value:
            logger.debug(f"Setting new attribute {attribute} for {user.username}")
            setattr(object, attribute, attr_value)
            needs_save = True

    if needs_save:
        authenticator_user.save()
        user.save()

    if results['access_allowed'] is not True:
        logger.warning(f"User {user.username} failed an allow map and was denied access")
        return None

    # We have allowed access so now we need to make the user within the system
    reconcile_class = getattr(settings, 'ANSIBLE_BASE_AUTHENTICATOR_RECONCILE_MODULE', 'ansible_base.authentication.utils.claims')
    try:
        module = __import__(reconcile_class, fromlist=['ReconcileUser'])
        klass = getattr(module, 'ReconcileUser')
        klass.reconcile_user_claims(user, authenticator_user)
    except Exception as e:
        logger.error(f"Failed to reconcile user attributes! {e}")

    return user


class ReconcileUser:
    def reconcile_user_claims(user, authenticator_user):
        logger.error("TODO: Fix reconciliation of user claims")
        claims = getattr(user, 'claims', getattr(authenticator_user, 'claims'))
        logger.error(claims)
