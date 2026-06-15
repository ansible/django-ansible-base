from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Protocol

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q

from ansible_base.lib.utils.apps import is_rbac_installed
from ansible_base.resource_registry.models import Resource

logger = logging.getLogger('ansible_base.rbac.assignment_utils')

DEFAULT_SYNC_PAGE_SIZE = 50

__all__ = [
    'AssignmentClient',
    'AssignmentTuple',
    'RemoteAssignmentFetcher',
    'RemoteAssignmentResult',
    'create_local_assignment',
    'delete_local_assignment',
    'get_ansible_id_or_pk',
    'get_content_object',
    'get_local_assignments',
    'get_remote_assignments',
]


@dataclass
class AssignmentTuple:
    """Represents an assignment as a 4-tuple for set comparison."""

    actor_ansible_id: str  # user_ansible_id or team_ansible_id
    ansible_id_or_pk: str | None  # object_id or object_ansible_id (None for global)
    role_definition_name: str
    assignment_type: str  # 'user' or 'team'

    def __hash__(self):
        return hash((self.actor_ansible_id, self.ansible_id_or_pk, self.role_definition_name, self.assignment_type))

    def __eq__(self, other):
        if not isinstance(other, AssignmentTuple):
            return False
        return (
            self.actor_ansible_id == other.actor_ansible_id
            and self.ansible_id_or_pk == other.ansible_id_or_pk
            and self.role_definition_name == other.role_definition_name
            and self.assignment_type == other.assignment_type
        )


@dataclass
class RemoteAssignmentResult:
    """Result of fetching remote assignments, including completeness status.

    When ``is_complete`` is False the caller must not use the partial
    ``assignments`` set for deletion decisions — doing so would remove
    local assignments that simply weren't fetched.
    """

    assignments: set[AssignmentTuple] = field(default_factory=set)
    is_complete: bool = False


class AssignmentClient(Protocol):
    """Protocol for clients that can list role assignments.

    ``ResourceAPIClient`` already satisfies this protocol.  Gateway or
    other consumers can provide their own adapter implementing these
    two methods.  Each must accept a ``filters`` keyword argument (a
    dict passed as query parameters) and return a response object with
    ``.status_code`` and ``.json()`` attributes.
    """

    def list_user_assignments(self, filters: dict | None = None, **kwargs) -> Any: ...
    def list_team_assignments(self, filters: dict | None = None, **kwargs) -> Any: ...


class RemoteAssignmentFetcher:
    """Fetches role assignments from a remote resource server with pagination.

    Collects user and team assignments into a single set.  If any page
    request fails the fetcher stops early and marks the result as
    incomplete so the caller can skip deletions safely.
    """

    def __init__(self, api_client: AssignmentClient, page_size: int | None = None):
        self.api_client = api_client
        self.assignments: set[AssignmentTuple] = set()
        self.page_size = page_size if page_size is not None else getattr(settings, 'RESOURCE_SYNC_PAGE_SIZE', DEFAULT_SYNC_PAGE_SIZE)

    def fetch(self) -> RemoteAssignmentResult:
        """Paginate user then team assignments and return the result.

        If user pagination fails, team pagination is skipped entirely
        because the result will be incomplete regardless.
        """
        from ansible_base.rbac.models.role import RoleDefinition

        self.local_role_names: set[str] = set(RoleDefinition.objects.values_list('name', flat=True))

        users_ok = self._paginate(self.api_client.list_user_assignments, 'user_ansible_id', 'user')
        if not users_ok:
            return RemoteAssignmentResult(assignments=self.assignments, is_complete=False)

        teams_ok = self._paginate(self.api_client.list_team_assignments, 'team_ansible_id', 'team')
        return RemoteAssignmentResult(assignments=self.assignments, is_complete=teams_ok)

    def _paginate(self, list_fn, actor_id_key: str, assignment_type: str) -> bool:
        """Paginate a single assignment endpoint, adding results to ``self.assignments``.

        Returns True if all pages were fetched successfully, False on any error.
        """
        page = 1
        try:
            while True:
                resp = list_fn(filters={'page': page, 'page_size': self.page_size})
                if resp.status_code != 200:
                    logger.warning(f"Failed to fetch {assignment_type} assignments page {page}: HTTP {resp.status_code}")
                    return False

                data = resp.json()
                for assignment in data.get('results') or []:
                    role_name = assignment['role_definition']
                    if role_name not in self.local_role_names:
                        logger.debug(f"Skipping remote {assignment_type} assignment with unknown local role: {role_name}")
                        continue
                    ansible_id_or_pk = assignment.get('object_ansible_id') or assignment.get('object_id')
                    self.assignments.add(
                        AssignmentTuple(
                            actor_ansible_id=assignment[actor_id_key],
                            ansible_id_or_pk=ansible_id_or_pk,
                            role_definition_name=role_name,
                            assignment_type=assignment_type,
                        )
                    )

                if not data.get('next'):
                    return True

                page += 1
                logger.debug(f"Fetching next page {page} of {assignment_type} assignments")
        except Exception:
            logger.exception(f"Failed to fetch remote {assignment_type} assignments")
            return False


def get_remote_assignments(api_client: AssignmentClient, page_size: int | None = None) -> RemoteAssignmentResult:
    """Fetch remote assignments from the resource server and convert to tuples.

    Returns a ``RemoteAssignmentResult`` so the caller can distinguish a
    complete fetch from a partial one (e.g. due to HTTP errors or
    timeouts mid-pagination).
    """
    return RemoteAssignmentFetcher(api_client, page_size=page_size).fetch()


def get_ansible_id_or_pk(assignment) -> str:
    """Resolve the ansible_id or raw PK for an assignment's target object.

    For organization/team content types the object's ``ansible_id`` is
    looked up via the Resource table.  For all other types the raw
    ``object_id`` is returned directly.
    """
    if not is_rbac_installed():
        raise RuntimeError("get_ansible_id_or_pk requires ansible_base.rbac to be installed")
    if assignment.content_type.model in ('organization', 'team'):
        object_resource = Resource.objects.filter(object_id=assignment.object_id, content_type__model=assignment.content_type.model).first()
        if object_resource:
            ansible_id_or_pk = object_resource.ansible_id
        else:
            raise RuntimeError(f"Error: {assignment.content_type.model} {assignment.object_id} was found without an associated Resource.")
    else:
        ansible_id_or_pk = assignment.object_id

    return str(ansible_id_or_pk)


def get_content_object(role_definition, assignment_tuple: AssignmentTuple) -> Any:
    """Resolve the Django model instance for an assignment tuple's target object."""
    if not is_rbac_installed():
        raise RuntimeError("get_content_object requires ansible_base.rbac to be installed")
    content_object = None
    if role_definition.content_type.model in ('organization', 'team'):
        object_resource = Resource.objects.get(ansible_id=assignment_tuple.ansible_id_or_pk)
        content_object = object_resource.content_object
    else:
        model = role_definition.content_type.model_class()
        content_object = model.objects.get(pk=assignment_tuple.ansible_id_or_pk)

    return content_object


def _bulk_resolve_actor_ansible_ids(assignments: list, actor_attr: str) -> dict[str, str]:
    """Build a ``{str(pk): str(ansible_id)}`` map for all actors in a single query.

    *actor_attr* is ``'user'`` or ``'team'`` — the FK attribute name on the
    assignment model.
    """
    if not assignments:
        return {}

    actor_pks = {str(getattr(a, f'{actor_attr}_id')) for a in assignments}
    first_actor = getattr(assignments[0], actor_attr)
    actor_ct_id = ContentType.objects.get_for_model(first_actor).pk

    return {
        str(obj_id): str(ansible_id)
        for obj_id, ansible_id in Resource.objects.filter(
            object_id__in=actor_pks,
            content_type_id=actor_ct_id,
        ).values_list('object_id', 'ansible_id')
    }


def _bulk_resolve_object_ansible_ids(assignments: list) -> dict[tuple[str, str], str]:
    """Build a ``{(str(object_id), model_name): str(ansible_id)}`` map for org/team objects.

    Only organization and team content types need Resource lookups — all
    other types use the raw ``object_id`` directly.
    """
    org_team_ids = set()
    for a in assignments:
        if a.object_id and a.content_type and a.content_type.model in ('organization', 'team'):
            org_team_ids.add(str(a.object_id))

    if not org_team_ids:
        return {}

    return {
        (str(obj_id), model): str(ansible_id)
        for obj_id, model, ansible_id in Resource.objects.filter(
            object_id__in=org_team_ids,
            content_type__model__in=['organization', 'team'],
        ).values_list('object_id', 'content_type__model', 'ansible_id')
    }


def get_local_assignments(service: str | None = None) -> set[AssignmentTuple]:
    """Get local role assignments as a set of tuples for set-diff comparison.

    Args:
        service: Optional service name (e.g. ``"controller"``, ``"hub"``,
            ``"eda"``) to filter assignments by ``content_type__service``.
            Global assignments (``content_type=None``) are always included.
            When ``None`` (default), all assignments are returned.

    Returns:
        A set of ``AssignmentTuple`` instances representing the local
        role assignments.  Assignments whose actor (user/team) lacks a
        corresponding ``Resource`` entry are silently skipped.
    """
    if not is_rbac_installed():
        raise RuntimeError("get_local_assignments requires ansible_base.rbac to be installed")
    from ansible_base.rbac.models.role import RoleTeamAssignment, RoleUserAssignment

    assignments: set[AssignmentTuple] = set()
    service_filter = Q()
    if service:
        service_filter = Q(content_type__service=service) | Q(content_type__isnull=True)

    # --- User assignments ---
    user_qs = RoleUserAssignment.objects.select_related('user', 'role_definition', 'content_type')
    if service:
        user_qs = user_qs.filter(service_filter)
    user_assignment_list = list(user_qs)

    actor_map = _bulk_resolve_actor_ansible_ids(user_assignment_list, 'user')
    object_map = _bulk_resolve_object_ansible_ids(user_assignment_list)

    for a in user_assignment_list:
        user_pk = str(a.user_id)
        if user_pk not in actor_map:
            continue

        ansible_id_or_pk = None
        if a.object_id and a.content_type:
            model_name = a.content_type.model
            if model_name in ('organization', 'team'):
                key = (str(a.object_id), model_name)
                if key not in object_map:
                    logger.warning(f"{model_name} {a.object_id} found without an associated Resource, skipping assignment.")
                    continue
                ansible_id_or_pk = object_map[key]
            else:
                ansible_id_or_pk = str(a.object_id)

        assignments.add(
            AssignmentTuple(
                actor_ansible_id=actor_map[user_pk],
                ansible_id_or_pk=ansible_id_or_pk if ansible_id_or_pk else None,
                role_definition_name=a.role_definition.name,
                assignment_type='user',
            )
        )

    # --- Team assignments ---
    team_qs = RoleTeamAssignment.objects.select_related('team', 'role_definition', 'content_type')
    if service:
        team_qs = team_qs.filter(service_filter)
    team_assignment_list = list(team_qs)

    actor_map = _bulk_resolve_actor_ansible_ids(team_assignment_list, 'team')
    object_map = _bulk_resolve_object_ansible_ids(team_assignment_list)

    for a in team_assignment_list:
        team_pk = str(a.team_id)
        if team_pk not in actor_map:
            continue

        ansible_id_or_pk = None
        if a.object_id and a.content_type:
            model_name = a.content_type.model
            if model_name in ('organization', 'team'):
                key = (str(a.object_id), model_name)
                if key not in object_map:
                    logger.warning(f"{model_name} {a.object_id} found without an associated Resource, skipping assignment.")
                    continue
                ansible_id_or_pk = object_map[key]
            else:
                ansible_id_or_pk = str(a.object_id)

        assignments.add(
            AssignmentTuple(
                actor_ansible_id=actor_map[team_pk],
                ansible_id_or_pk=ansible_id_or_pk if ansible_id_or_pk else None,
                role_definition_name=a.role_definition.name,
                assignment_type='team',
            )
        )

    return assignments


def delete_local_assignment(assignment_tuple: AssignmentTuple) -> bool:
    """Delete a local assignment based on the tuple."""
    if not is_rbac_installed():
        raise RuntimeError("delete_local_assignment requires ansible_base.rbac to be installed")
    from ansible_base.rbac.models.role import RoleDefinition

    try:
        role_definition = RoleDefinition.objects.get(name=assignment_tuple.role_definition_name)

        resource = Resource.objects.get(ansible_id=assignment_tuple.actor_ansible_id)
        actor = resource.content_object

        content_object = None
        if assignment_tuple.ansible_id_or_pk:
            content_object = get_content_object(role_definition, assignment_tuple)
        if content_object:
            role_definition.remove_permission(actor, content_object)
        else:
            role_definition.remove_global_permission(actor)

        return True

    except Exception:
        logger.exception(f"Failed to delete assignment {assignment_tuple}")
        return False


def create_local_assignment(assignment_tuple: AssignmentTuple) -> bool:
    """Create a local assignment based on the tuple."""
    if not is_rbac_installed():
        raise RuntimeError("create_local_assignment requires ansible_base.rbac to be installed")
    from ansible_base.rbac.models.role import RoleDefinition

    try:
        role_definition = RoleDefinition.objects.get(name=assignment_tuple.role_definition_name)

        resource = Resource.objects.get(ansible_id=assignment_tuple.actor_ansible_id)
        actor = resource.content_object

        content_object = None
        if assignment_tuple.ansible_id_or_pk:
            content_object = get_content_object(role_definition, assignment_tuple)
        if content_object:
            role_definition.give_permission(actor, content_object)
        else:
            role_definition.give_global_permission(actor)

        return True

    except Exception:
        logger.exception(f"Failed to create assignment {assignment_tuple}")
        return False
