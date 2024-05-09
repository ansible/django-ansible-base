import logging
import re
from typing import Optional

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.utils.timezone import now
from rest_framework.serializers import DateTimeField

from ansible_base.authentication.models import Authenticator, AuthenticatorMap
from ansible_base.lib.utils.auth import get_organization_model, get_team_model

from .trigger_definition import TRIGGER_DEFINITION

logger = logging.getLogger('ansible_base.authentication.utils.claims')


def create_claims(authenticator: Authenticator, username: str, attrs: dict, groups: list[str]) -> dict:
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
                has_permission = process_groups(trigger, groups, authenticator.pk)
            if trigger_type == 'attributes':
                has_permission = process_user_attributes(trigger, attrs, authenticator.pk)
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


def process_groups(trigger_condition: dict, groups: list, authenticator_id: int) -> Optional[bool]:
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


def has_access_with_join(current_access: Optional[bool], new_access: bool, condition: str = 'or') -> Optional[bool]:
    '''
    Handle join of authenticator_maps
    '''
    if current_access is None:
        return new_access

    if condition == 'or':
        return current_access or new_access

    if condition == 'and':
        return current_access and new_access


def process_user_attributes(trigger_condition: dict, attributes: dict, authenticator_id: int) -> Optional[bool]:
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


def update_user_claims(user: Optional[AbstractUser], database_authenticator: Authenticator, groups: list[str]) -> Optional[AbstractUser]:
    """
    This method takes a user, an authenticator and a list of the users associated groups.
    It will lookup the AuthenticatorUser (it must exist already) and update that User and their permissions in the system.
    """
    if not user:
        return None

    authenticator_user = user.authenticator_users.filter(provider=database_authenticator).first()
    # update the auth_time field to align with the general format used for other authenticators
    authenticator_user.extra_data = {**authenticator_user.extra_data, "auth_time": DateTimeField().to_representation(now())}
    authenticator_user.save(update_fields=["extra_data"])

    results = create_claims(database_authenticator, user.username, authenticator_user.extra_data, groups)

    needs_save = False

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
    else:
        # If we don't have to save because of a change we at least need to save the extra data with the login timestamp
        authenticator_user.save(update_fields=["extra_data"])

    if results['access_allowed'] is not True:
        logger.warning(f"User {user.username} failed an allow map and was denied access")
        return None

    # Make the orgs and the teams as necessary ...
    process_organization_and_team_memberships(results)

    # We have allowed access so now we need to make the user within the system
    reconcile_class = getattr(settings, 'ANSIBLE_BASE_AUTHENTICATOR_RECONCILE_MODULE', 'ansible_base.authentication.utils.claims')
    try:
        module = __import__(reconcile_class, fromlist=['ReconcileUser'])
        klass = getattr(module, 'ReconcileUser')
        klass.reconcile_user_claims(user, authenticator_user)
    except Exception as e:
        logger.error(f"Failed to reconcile user attributes! {e}")

    return user


def process_organization_and_team_memberships(results):
    # Extract organizations where the user is a member
    org_list = [org_name for org_name, is_member in results['claims']['organization_membership'].items() if is_member]

    # Build a mapping of teams to their respective organizations, filtering out non-members
    team_map = {
        team_name: org_name
        for org_name, teams in results['claims']['team_membership'].items()
        for team_name, is_member in teams.items() if is_member
    }

    # Create organizations and teams based on the membership data
    create_orgs_and_teams(org_list, team_map)


def create_orgs_and_teams(org_list, team_map, adapter=None, can_create=True):
    # Early exit if creation is not allowed
    if not can_create:
        logger.debug(f"Adapter {adapter} is not allowed to create orgs/teams")
        return

    # Ensure unique organization names and gather all team names
    all_orgs = set(org_list) | set(team_map.values())
    all_teams = list(team_map.keys())

    # Load existing organizations
    existing_orgs = load_existing_orgs(all_orgs)

    # Create missing organizations
    create_missing_orgs(all_orgs, existing_orgs, adapter)

    # Load existing teams
    existing_teams = load_existing_teams(all_teams)

    # Create missing teams
    create_missing_teams(all_teams, team_map, existing_orgs, existing_teams, adapter)


def load_existing_orgs(org_names):
    Organization = get_organization_model()
    existing_orgs = {org.name: org.id for org in Organization.objects.filter(name__in=org_names)}
    return existing_orgs


def create_missing_orgs(org_names, existing_orgs, adapter):
    Organization = get_organization_model()
    for org_name in org_names:
        if org_name not in existing_orgs:
            logger.info(f"{adapter} adapter is creating org {org_name}")
            new_org, _ = Organization.objects.get_or_create(name=org_name)
            existing_orgs[org_name] = new_org.id


def load_existing_teams(team_names):
    Team = get_team_model()
    existing_teams = set(Team.objects.filter(name__in=team_names).values_list('name', flat=True))
    return existing_teams


def create_missing_teams(team_names, team_map, existing_orgs, existing_teams, adapter):
    Team = get_team_model()
    for team_name in team_names:
        if team_name not in existing_teams:
            org_name = team_map[team_name]
            if org_name in existing_orgs:
                logger.info(f"{adapter} adapter is creating team {team_name} in org {org_name}")
                Team.objects.get_or_create(name=team_name, organization_id=existing_orgs[org_name])
            else:
                logger.error(f"{adapter} adapter is attempting to create team {team_name} but its organization does not exist")


class ReconcileUser:
    def reconcile_user_claims(user, authenticator_user):
        logger.error("TODO: Fix reconciliation of user claims")
        claims = getattr(user, 'claims', getattr(authenticator_user, 'claims'))
        logger.error(claims)
