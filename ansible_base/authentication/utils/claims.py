import importlib
import logging
import re
from typing import Iterator, Optional, Tuple, Union

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AbstractUser
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ObjectDoesNotExist
from django.db import models
from django.utils.timezone import now
from django.utils.translation import gettext_lazy as _
from rest_framework.serializers import DateTimeField

from ansible_base.authentication.models import Authenticator, AuthenticatorMap, AuthenticatorUser
from ansible_base.lib.abstract_models import AbstractOrganization, AbstractTeam, CommonModel
from ansible_base.lib.utils.auth import get_organization_model, get_team_model
from ansible_base.lib.utils.string import is_empty

from .trigger_definition import TRIGGER_DEFINITION

logger = logging.getLogger('ansible_base.authentication.utils.claims')
Organization = get_organization_model()
Team = get_team_model()
User = get_user_model()


def create_claims(authenticator: Authenticator, username: str, attrs: dict, groups: list[str]) -> dict:
    """
    Given an authenticator and a username, attrs and groups determine what the user has access to
    """

    # Assume we are not going to change our flags
    is_superuser = None

    rbac_role_mapping = {'system': {'roles': {}}, 'organizations': {}}
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
        elif auth_map.map_type in ['team', 'role'] and not is_empty(auth_map.organization) and not is_empty(auth_map.team) and not is_empty(auth_map.role):
            if auth_map.organization not in org_team_mapping:
                org_team_mapping[auth_map.organization] = {}
            org_team_mapping[auth_map.organization][auth_map.team] = has_permission
            _add_rbac_role_mapping(has_permission, rbac_role_mapping, auth_map.role, auth_map.organization, auth_map.team)
        elif auth_map.map_type in ['organization', 'role'] and not is_empty(auth_map.organization) and not is_empty(auth_map.role):
            organization_membership[auth_map.organization] = has_permission
            _add_rbac_role_mapping(has_permission, rbac_role_mapping, auth_map.role, auth_map.organization)
        elif auth_map.map_type == 'role' and not is_empty(auth_map.role) and is_empty(auth_map.organization) and is_empty(auth_map.team):
            _add_rbac_role_mapping(has_permission, rbac_role_mapping, auth_map.role)

        else:
            logger.error(f"Map type {auth_map.map_type} of rule {auth_map.name} does not know how to be processed")

    return {
        "access_allowed": access_allowed,
        "is_superuser": is_superuser,
        "claims": {
            "team_membership": org_team_mapping,
            "organization_membership": organization_membership,
            "rbac_roles": rbac_role_mapping,
        },
        "last_login_map_results": rule_responses,
    }


def _add_rbac_role_mapping(has_permission, role_mapping, role, organization=None, team=None):
    """
    Example of RBAC roles mapping dict:
    {
      'system': {'roles': {'System Auditor': true}},
      'organizations': {
        'Organization 1': {
            'roles': {'Organization Member': true, 'Organization Admin': false},
            'teams': {}
         },
        'Organization 2': {
            'roles': {'Organization Admin': true},
            'teams': {
                'Team 1': {
                    'roles': {'Team Member': true},
                },
                'Team 2': {
                    'roles': {'Team Admin': false},
                }
            }
        }
    """
    # System role
    if organization is None and team is None:
        role_mapping['system']['roles'][role] = has_permission
    else:
        if organization not in role_mapping['organizations']:
            role_mapping['organizations'][organization] = {'roles': {}, 'teams': {}}
        # Organization role
        if organization and not team:
            role_mapping['organizations'][organization]['roles'][role] = has_permission
        # Team role
        elif organization and team:
            if team not in role_mapping['organizations'][organization]['teams']:
                role_mapping['organizations'][organization]['teams'][team] = {'roles': {}}
            role_mapping['organizations'][organization]['teams'][team]['roles'][role] = has_permission
        else:
            logger.warning(f"Role mapping is not possible, organization for team '{team}' is missing")


def process_groups(trigger_condition: dict, groups: list, authenticator_id: int) -> Optional[bool]:
    """
    Looks at a maps trigger for a group and users groups and determines if the trigger True or False
    """

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
    """
    Handle join of authenticator_maps
    """
    if current_access is None:
        return new_access

    if condition == 'or':
        return current_access or new_access

    if condition == 'and':
        return current_access and new_access


def process_user_attributes(trigger_condition: dict, attributes: dict, authenticator_id: int) -> Optional[bool]:
    """
    Looks at a maps trigger for an attribute and the users attributes and determines if the trigger is True, False or None
    """

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
    It will look up the AuthenticatorUser (it must exist already) and update that User and their permissions in the system.
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
    if database_authenticator.create_objects:
        create_organizations_and_teams(results)

    if reconcile_user_class := load_reconcile_user_class():
        try:
            # We have allowed access, so now we need to make the user within the system
            reconcile_user_class.reconcile_user_claims(user, authenticator_user)
        except Exception as e:
            logger.exception("Failed to reconcile user claims: %s", e)

    return user


# TODO(cutwater): Implement a generic version of this function and move it to lib/utils.
def load_reconcile_user_class():
    module_path = getattr(settings, 'ANSIBLE_BASE_AUTHENTICATOR_RECONCILE_MODULE', 'ansible_base.authentication.utils.claims')
    try:
        module = importlib.import_module(module_path)
    except ImportError:
        logger.warning("Failed to load module '%s'.", module_path)
        return None

    try:
        return getattr(module, 'ReconcileUser')
    except AttributeError:
        logger.warning("Failed to load ReconcileUser class in module '%s'.", module_path)
        return None


def create_organizations_and_teams(results) -> None:
    """
    Use the results data from 'create_claims' to make the Organization
    and Team objects necessary for the user if they do not exist.
    """

    # a flat list of relevant org names
    org_list = set()
    # a flat list of relevant org:team names
    team_list = set()

    # a structure for caching org+team,member info
    membership_map = {}

    # fill in the top level org membership data ...
    for org_name, is_member in results['claims']['organization_membership'].items():
        if is_member:
            org_list.add(org_name)
            membership_map[org_name] = {'id': None, 'teams': {}}

    # fill in the team membership data ...
    for org_name, teams in results['claims']['team_membership'].items():
        for team_name, is_member in teams.items():
            if is_member:
                org_list.add(org_name)
                team_list.add((org_name, team_name))
                if org_name not in membership_map:
                    membership_map[org_name] = {'id': None, 'teams': {}}
                membership_map[org_name]['teams'][team_name] = True

    # make a map or org name to org id to reduce calls and data sent over the wire
    existing_orgs = {org.name: org.id for org in Organization.objects.filter(name__in=org_list)}

    # make each org as necessary or simply store the id
    for org_name in org_list:
        if org_name not in existing_orgs:
            new_org, _ = Organization.objects.get_or_create(name=org_name)
            membership_map[org_name]['id'] = new_org.id
        else:
            membership_map[org_name]['id'] = existing_orgs[org_name]

    # make a map or org id, team name to reduce calls and data sent over the wire
    # NOTE(cutwater): This doesn't seem to work
    existing_teams = [x for x in Team.objects.filter(name__in=team_list).values_list('organization', 'name')]

    # make each team as necessary
    for org_name, org_data in membership_map.items():
        org_id = org_data['id']
        for team_name, is_member in org_data['teams'].items():
            if (org_id, team_name) not in existing_teams:
                new_team, _ = Team.objects.get_or_create(name=team_name, organization_id=org_id)


# NOTE(cutwater): Current class is sub-optimal, since it loads the data that has been already loaded
#  at the teams and organizations creation. Next step will be combining teams and organizations creation with
#  this class and transforming it into a reconciliation use case class. This implies either
#  removal or update of a pluggable interface.
class ReconcileUser:
    @classmethod
    def reconcile_user_claims(cls, user: AbstractUser, authenticator_user: AuthenticatorUser) -> None:
        logger.info("Reconciling user claims")

        claims = getattr(user, 'claims', authenticator_user.claims)

        if 'ansible_base.rbac' in settings.INSTALLED_APPS:
            cls(claims, user, authenticator_user).manage_permissions()
        else:
            logger.info(_("Skipping user claims with RBAC roles, because RBAC app is not installed"))

    def __init__(self, claims: dict, user: AbstractUser, authenticator_user: AuthenticatorUser):
        """
        :param claims: initialized by method create_claims()
        """
        self.authenticator_user = authenticator_user
        self.claims = claims
        self.permissions_cache = RoleUserAssignmentsCache()
        self.rebuild_user_permissions = self.authenticator_user.provider.remove_users
        self.user = user

    def manage_permissions(self) -> None:
        """Processes the user claims (key `rbac_roles`)
        and adds/removes RBAC permissions (a.k.a. role_user_assignments)
        """
        # NOTE(cutwater): Here `prefetch_related` is used to prevent N+1 problem when accessing `content_object`
        #  attribute in `RoleUserAssignmentsCache.cache_existing` method.
        self.permissions_cache.cache_existing(self.user.role_assignments.prefetch_related('content_object').all())

        # System roles
        self._compute_system_permissions()

        # Organization roles
        for org, org_teams_dict in self._compute_organization_permissions():
            # Team roles
            self._compute_team_permissions(org, org_teams_dict)

        self.apply_permissions()

    def _compute_system_permissions(self) -> None:
        for role_name, has_permission in self.claims['rbac_roles'].get('system', {}).get('roles', {}).items():
            self.permissions_cache.add_or_remove(role_name, has_permission, organization=None, team=None)

    def _compute_organization_permissions(self) -> Iterator[Tuple[AbstractOrganization, dict]]:
        orgs_by_name = self._get_orgs_by_name(self.claims['rbac_roles'].get('organizations', {}).keys())

        for org_name, org_details in self.claims['rbac_roles'].get('organizations', {}).items():
            if (org := orgs_by_name.get(org_name)) is None:
                logger.error(
                    _("Skipping organization '{organization}', because the organization does not exist but it should already have been created").format(
                        organization=org_name
                    )
                )
                continue

            for role_name, has_permission in org_details['roles'].items():
                self.permissions_cache.add_or_remove(role_name, has_permission, organization=org)
            yield org, org_details['teams']

    def _compute_team_permissions(self, org: AbstractOrganization, teams_dict: dict[str, dict]) -> None:
        teams_by_name = self._get_teams_by_name(org.id, teams_dict.keys())

        for team_name, team_details in teams_dict.items():
            if (team := teams_by_name.get(team_name)) is None:
                logger.error(
                    _(
                        "Skipping team '{team}' in organization '{organization}', because the team does not exist but it should already have been created"
                    ).format(team=team_name, organization=org.name)
                )
                continue

            for role_name, has_permission in team_details['roles'].items():
                self.permissions_cache.add_or_remove(role_name, has_permission, team=team)

    def apply_permissions(self) -> None:
        """See RoleUserAssignmentsCache for more details."""
        for role_name, role_permissions in self.permissions_cache.items():
            if not self.permissions_cache.rd_by_name(role_name):
                # If we failed to load this role for some reason
                # we can't continue setting the permissions, log message was already emitted
                continue

            for content_type_id, content_type_permissions in role_permissions.items():
                for _object_id, object_with_status in content_type_permissions.items():
                    self._apply_permission(object_with_status, role_name)

    def _apply_permission(self, object_with_status, role_name):
        status = object_with_status['status']
        obj = object_with_status['object']

        if status == self.permissions_cache.STATUS_ADD:
            self._give_permission(self.permissions_cache.rd_by_name(role_name), obj)
        elif status == self.permissions_cache.STATUS_REMOVE:
            self._remove_permission(self.permissions_cache.rd_by_name(role_name), obj)
        elif status == self.permissions_cache.STATUS_EXISTING and self.rebuild_user_permissions:
            self._remove_permission(self.permissions_cache.rd_by_name(role_name), obj)

    @staticmethod
    def _get_orgs_by_name(org_names) -> dict[str, AbstractOrganization]:
        if not org_names:
            return {}
        orgs_by_name = {org.name: org for org in Organization.objects.filter(name__in=org_names)}
        return orgs_by_name

    @staticmethod
    def _get_teams_by_name(org_id, team_names) -> dict[str, AbstractTeam]:
        if not team_names:
            return {}
        # FIXME(cutwater): Load all teams in all organizations at once.
        #       This will require raw query to filter by tuples of (org id, team name).
        teams_by_name = {team.name: team for team in Team.objects.filter(organization__pk=org_id, name__in=team_names)}
        return teams_by_name

    def _give_permission(self, role_definition: CommonModel, obj: Union[AbstractOrganization, AbstractTeam, None] = None) -> None:
        if obj:
            logger.info(
                _("Assigning role '{rd}' to user '{username}' in '{object}").format(
                    rd=role_definition.name, username=self.user.username, object=obj.__class__.__name__
                )
            )
        else:
            logger.info(_("Assigning role '{rd}' to user '{username}'").format(rd=role_definition.name, username=self.user.username))

        if obj:
            role_definition.give_permission(self.user, obj)
        else:
            role_definition.give_global_permission(self.user)

    def _remove_permission(self, role_definition: CommonModel, obj: Union[AbstractOrganization, AbstractTeam, None] = None) -> None:
        if obj:
            logger.info(
                _("Removing role '{rd}' from user '{username}' in '{object}").format(
                    rd=role_definition.name, username=self.user.username, object=obj.__class__.__name__
                )
            )
        else:
            logger.info(_("Removing role '{rd}' from user '{username}'").format(rd=role_definition.name, username=self.user.username))

        if obj:
            role_definition.remove_permission(self.user, obj)
        else:
            role_definition.remove_global_permission(self.user)


class RoleUserAssignmentsCache:
    STATUS_NOOP = 'noop'
    STATUS_EXISTING = 'existing'
    STATUS_ADD = 'add'
    STATUS_REMOVE = 'remove'

    def __init__(self):
        self.cache = {}
        self.content_types = {
            content_type.model: content_type for content_type in ContentType.objects.get_for_models(get_organization_model(), get_team_model()).values()
        }
        self.role_definitions = {}

    def items(self):
        """
        Caches role_user_assignments in form of parameters:
        - role_name: role_user_assignment.role_definition.name
        - content_type_id: role_user_assignment.content_type_id
        - object_id: role_user_assignment.object_id

        When content_type_id is None, it means it's a system role (i.e. System Auditor)
        When content_type_id is None, then object_id is None.

        Structure:
        {
          <role_name:str>: {
              <content_type_id:Optional[int]>: {
                  <object_id:Optional[int]>: {
                      {'object': Union[Organization,Team,None],
                       'status': Union[STATUS_NOOP,STATUS_EXISTING,STATUS_ADD,STATUS_REMOVE]
                      }
                  }
              }
          }
        """
        return self.cache.items()

    def cache_existing(self, role_assignments):
        """Caches given role_assignments associated with one user in form of dict (see method `items()`)"""
        for role_assignment in role_assignments:
            # Cache role definition
            if (role_definition := self._rd_by_id(role_assignment)) is None:
                role_definition = role_assignment.role_definition
                self.role_definitions[role_definition.name] = role_definition

            # Cache Role User Assignment
            self._init_cache_key(role_definition.name, content_type_id=role_assignment.content_type_id)

            # object_id is TEXT db type
            object_id = int(role_assignment.object_id) if role_assignment.object_id is not None else None
            obj = role_assignment.content_object if object_id else None

            self.cache[role_definition.name][role_assignment.content_type_id][object_id] = {'object': obj, 'status': self.STATUS_EXISTING}

    def rd_by_name(self, role_name: str) -> Optional[CommonModel]:
        """Returns RoleDefinition by its name. Caches it if requested for first time"""
        from ansible_base.rbac.models import RoleDefinition

        try:
            if self.role_definitions.get(role_name) is None:
                self.role_definitions[role_name] = RoleDefinition.objects.get(name=role_name)
        except ObjectDoesNotExist:
            logger.warning(_("Skipping role '{role_name}', because the role does not exist").format(role_name=role_name))
            self.role_definitions[role_name] = False  # skips multiple db queries

        return self.role_definitions.get(role_name)

    def _rd_by_id(self, role_assignment: models.Model) -> Optional[CommonModel]:
        """Tries to find cached role definition by id, saving SQL queries"""
        for rd in self.role_definitions.values():
            if rd.id == role_assignment.role_definition_id:
                return rd
        return None

    def add_or_remove(
        self, role_name: str, has_permission: bool, organization: Optional[AbstractOrganization] = None, team: Optional[AbstractTeam] = None
    ) -> None:
        """
        Marks role assignment's params and (optionally) associated object in the cache.
        Either marks it as STATUS_ADD, STATUS_REMOVE or STATUS_NOOP.
        """
        content_type_id = self._get_content_type_id(organization, team)
        self._init_cache_key(role_name, content_type_id=content_type_id)

        object_id = self._get_object_id(organization, team)
        current_status = self.cache[role_name][content_type_id].get(object_id, {}).get('status')

        if has_permission:
            self._add(role_name, content_type_id, object_id, current_status, organization, team)
        else:
            self._remove(role_name, content_type_id, object_id, current_status, organization, team)

    def _add(
        self,
        role_name: str,
        content_type_id: Optional[int],
        object_id: Optional[int],
        current_status: Optional[str],
        organization: Optional[AbstractOrganization] = None,
        team: Optional[AbstractTeam] = None,
    ) -> None:
        """Marks role assignment's params and (optionally) associated object in the cache.
        If role_user_assignment (a.k.a. permission) existed before, marks it to do nothing
        """
        if current_status in [self.STATUS_EXISTING, self.STATUS_NOOP]:
            self.cache[role_name][content_type_id][object_id] = {'object': organization or team, 'status': self.STATUS_NOOP}
        elif current_status is None:
            self.cache[role_name][content_type_id][object_id] = {'object': organization or team, 'status': self.STATUS_ADD}

    def _remove(
        self,
        role_name: str,
        content_type_id: Optional[int],
        object_id: Optional[int],
        current_status: Optional[str],
        organization: Optional[AbstractOrganization] = None,
        team: Optional[AbstractTeam] = None,
    ) -> None:
        """Marks role assignment's params and (optionally) associated object in the cache.
        If role_user_assignment (a.k.a. permission) didn't exist before, marks it to do nothing
        """
        if current_status is None or current_status == self.STATUS_NOOP:
            self.cache[role_name][content_type_id][object_id] = {'object': organization or team, 'status': self.STATUS_NOOP}
        elif current_status == self.STATUS_EXISTING:
            self.cache[role_name][content_type_id][object_id] = {'object': organization or team, 'status': self.STATUS_REMOVE}

    def _get_content_type_id(self, organization, team) -> Optional[int]:
        content_type = None
        if organization:
            content_type = self.content_types['organization']
        elif team:
            content_type = self.content_types['team']

        return content_type.id if content_type is not None else None

    def _get_object_id(self, organization: Optional[AbstractOrganization], team: Optional[AbstractTeam]) -> Optional[int]:
        """
        Returns an object id of either organization or team.
        If both items are set organization will take priority over a team id.
        """
        if organization:
            return organization.id
        elif team:
            return team.id
        else:
            return None

    def _init_cache_key(self, role_name: str, content_type_id: Optional[int]) -> None:
        """
        Initialize a key in the cache for later use
        """
        self.cache[role_name] = self.cache.get(role_name, {})
        self.cache[role_name][content_type_id] = self.cache[role_name].get(content_type_id, {})
