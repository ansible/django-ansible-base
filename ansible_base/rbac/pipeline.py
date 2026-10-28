from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from typing import NamedTuple, Union, cast

from django.apps import apps as django_apps
from django.conf import settings
from django.db import connection, models
from django.db.models import Q
from django.db.models.signals import post_save

from ansible_base.lib.utils.db import bulk_create_db_safe
from ansible_base.lib.utils.models import current_user_or_system_user
from ansible_base.rbac.caching import (
    bulk_ancestor_roles,
    compute_team_member_roles,
    delete_object_roles,
    defer_rbac_state,
    recompute_role_evaluations,
    team_ids_from_role_target,
)
from ansible_base.rbac.models.content_type import DABContentType
from ansible_base.rbac.models.role import AssignmentBase, ObjectRole, RoleDefinition, RoleTeamAssignment, RoleUserAssignment
from ansible_base.rbac.permission_registry import permission_registry
from ansible_base.rbac.remote import RemoteObject
from ansible_base.rbac.resource_queries import resolve_resource_ids
from ansible_base.rbac.validators import validate_assignment, validate_team_assignment_enabled

logger = logging.getLogger(__name__)


class ResolvedAssignment(NamedTuple):
    role_definition: RoleDefinition
    actor: models.Model
    content_type: DABContentType
    object_id: str
    parent_reference: str


ContentObject = Union[models.Model, RemoteObject]
PermissionTriple = tuple[RoleDefinition, models.Model, ContentObject]
ObjectRoleLookup = dict[tuple[int, str], ObjectRole]

SQL_SERVER_MAX_QUERY_PARAMETERS = 2100
PARAMETERS_PER_PAIR_FILTER = 2
SQL_SERVER_QUERY_PARAMETER_HEADROOM = 100
SQL_SERVER_PAIR_FILTER_BATCH_SIZE = (SQL_SERVER_MAX_QUERY_PARAMETERS - SQL_SERVER_QUERY_PARAMETER_HEADROOM) // PARAMETERS_PER_PAIR_FILTER


def _resolve_content_object(obj: models.Model | RemoteObject) -> tuple[DABContentType, str, str]:
    """Resolve content_type, object_id, and parent_reference from a content object.

    For RemoteObject: uses its own attributes directly.
    For local Django models: resolves parent_reference from the registered parent FK.
    """
    if isinstance(obj, RemoteObject):
        return cast(DABContentType, obj.content_type), str(obj.object_id), str(obj.parent_reference) if obj.parent_reference else ''
    ct = cast(DABContentType, DABContentType.objects.get_for_model(obj))
    object_id = str(obj._meta.pk.get_db_prep_value(obj.pk, connection))
    parent_field_name = permission_registry.get_parent_fd_name(type(obj))
    if parent_field_name:
        parent_id = getattr(obj, f'{parent_field_name}_id', None)
        if parent_id is not None:
            return ct, object_id, str(parent_id)
    return ct, object_id, ''


def _resolve_triples(triples: Iterable[PermissionTriple]) -> list[ResolvedAssignment]:
    """Convert permission triples to ResolvedAssignments (no validation, no DB queries beyond content type lookup)."""
    return [ResolvedAssignment(rd, actor, *_resolve_content_object(obj)) for rd, actor, obj in triples]


def _resolve_assignments(
    user_permissions: Sequence[PermissionTriple],
    team_permissions: Sequence[PermissionTriple],
) -> tuple[list[ResolvedAssignment], list[ResolvedAssignment]]:
    """Validate permissions and build the resolved assignment lists."""
    validated_pairs: set[tuple[int, int]] = set()

    user_resolved: list[ResolvedAssignment] = []
    for rd, actor, obj in user_permissions:
        obj_ct, object_id, parent_ref = _resolve_content_object(obj)
        key = (rd.pk, obj_ct.id)
        if key not in validated_pairs:
            validate_assignment(rd, actor, obj)
            validated_pairs.add(key)
        user_resolved.append(ResolvedAssignment(rd, actor, obj_ct, object_id, parent_ref))

    team_validated_pairs: set[tuple[int, int]] = set()
    team_resolved: list[ResolvedAssignment] = []
    for rd, actor, obj in team_permissions:
        obj_ct, object_id, parent_ref = _resolve_content_object(obj)
        key = (rd.pk, obj_ct.id)
        if key not in validated_pairs:
            validate_assignment(rd, actor, obj)
            validated_pairs.add(key)
        if key not in team_validated_pairs:
            has_team_perm = rd.permissions.filter(codename=permission_registry.team_permission).exists()
            has_org_member = rd.permissions.filter(codename='member_organization').exists()
            validate_team_assignment_enabled(obj_ct, has_team_perm=has_team_perm, has_org_member=has_org_member)
            team_validated_pairs.add(key)
        team_resolved.append(ResolvedAssignment(rd, actor, obj_ct, object_id, parent_ref))

    return user_resolved, team_resolved


def _batch_resolve_object_ansible_ids(resolved: Sequence[ResolvedAssignment]) -> dict[tuple[str, str, str], str]:
    """Resolve local assignment resources in one query for the whole batch."""
    if not resolved or not django_apps.is_installed('ansible_base.resource_registry'):
        return {}

    object_ids_by_type: dict[tuple[str, str], set[str]] = {}
    services_by_type: dict[tuple[str, str], set[str]] = {}
    for assignment in resolved:
        content_type = assignment.content_type
        content_type_key = (content_type.app_label, content_type.model)
        object_ids_by_type.setdefault(content_type_key, set()).add(assignment.object_id)
        services_by_type.setdefault(content_type_key, set()).add(content_type.service)

    return resolve_resource_ids(object_ids_by_type, services_by_type)


def _lookup_object_roles(resolved: list[ResolvedAssignment]) -> ObjectRoleLookup:
    """Look up existing ObjectRoles for resolved assignments."""
    object_ids_by_rd: dict[int, tuple[int, set[str]]] = {}
    for ra in resolved:
        rd_id = ra.role_definition.pk
        if rd_id not in object_ids_by_rd:
            object_ids_by_rd[rd_id] = (ra.content_type.id, set())
        object_ids_by_rd[rd_id][1].add(ra.object_id)

    lookup: ObjectRoleLookup = {}
    for rd_id, (ct_id, object_ids) in object_ids_by_rd.items():
        for obj_role in ObjectRole.objects.filter(role_definition_id=rd_id, content_type_id=ct_id, object_id__in=object_ids):
            lookup[(rd_id, obj_role.object_id)] = obj_role

    return lookup


def _ensure_object_roles(requested_assignments: list[ResolvedAssignment]) -> ObjectRoleLookup:
    """Look up existing ObjectRoles, create any that are missing, and return the full lookup."""
    object_ids_by_rd: dict[int, tuple[int, set[str]]] = {}
    # Key by (rd_id, object_id) so batches with the same object_id across different
    # role definitions / content types do not overwrite each other's parent_reference.
    parent_refs: dict[tuple[int, str], str] = {}
    for ra in requested_assignments:
        rd_id = ra.role_definition.pk
        if rd_id not in object_ids_by_rd:
            object_ids_by_rd[rd_id] = (ra.content_type.id, set())
        object_ids_by_rd[rd_id][1].add(ra.object_id)
        if ra.parent_reference:
            parent_refs[(rd_id, ra.object_id)] = ra.parent_reference

    lookup: ObjectRoleLookup = {}
    for rd_id, (ct_id, object_ids) in object_ids_by_rd.items():
        for obj_role in ObjectRole.objects.filter(role_definition_id=rd_id, content_type_id=ct_id, object_id__in=object_ids):
            lookup[(rd_id, obj_role.object_id)] = obj_role
        missing = [oid for oid in object_ids if (rd_id, oid) not in lookup]
        if missing:
            bulk_create_db_safe(
                ObjectRole,
                [
                    ObjectRole(
                        role_definition_id=rd_id,
                        content_type_id=ct_id,
                        object_id=oid,
                        parent_reference=parent_refs.get((rd_id, oid), ''),
                    )
                    for oid in missing
                ],
                ignore_conflicts=True,
            )
            # Re-fetch to get PKs — bulk_create(ignore_conflicts=True) doesn't populate them.
            # unique_together on (role_definition, content_type, object_id) guarantees one row per oid.
            for obj_role in ObjectRole.objects.filter(role_definition_id=rd_id, content_type_id=ct_id, object_id__in=missing):
                lookup[(rd_id, obj_role.object_id)] = obj_role

    return lookup


def _audit_log_created(db_assignments: list[AssignmentBase], existing_pks: set[int]) -> None:
    """Emit audit logs for newly-created assignments (not idempotent re-assignments)."""
    if not db_assignments or 'ansible_base.activitystream' not in settings.INSTALLED_APPS:
        return

    from ansible_base.activitystream.signals import _store_activitystream_entry

    for assignment in db_assignments:
        if assignment.pk not in existing_pks:
            _store_activitystream_entry(None, assignment, 'create')


def _pair_filter_chunks(pairs: Sequence[tuple[object, object]], first_field: str, second_field: str):
    """Build OR filters for exact pairs, respecting SQL Server's parameter limit."""
    chunk_size = SQL_SERVER_PAIR_FILTER_BATCH_SIZE if connection.vendor == 'microsoft' else max(len(pairs), 1)
    for start in range(0, len(pairs), chunk_size):
        query_filter = Q()
        for first_value, second_value in pairs[start : start + chunk_size]:
            query_filter |= Q(**{first_field: first_value, second_field: second_value})
        yield query_filter


def _fire_post_save(db_assignments: list[AssignmentBase], existing_pks: set[int]) -> None:
    """Fire post_save signals for newly-created assignments (skipped by bulk_create)."""
    for assignment in db_assignments:
        if assignment.pk not in existing_pks:
            post_save.send(sender=type(assignment), instance=assignment, created=True, raw=False, using='default', update_fields=None)


def _build_assignment_objects(
    resolved: list[ResolvedAssignment],
    assignment_model,
    actor_field: str,
    lookup: ObjectRoleLookup,
    object_ansible_ids: dict[tuple[str, str, str], str],
    created_by,
) -> list[AssignmentBase]:
    assignments = []
    for item in resolved:
        object_role = lookup[(item.role_definition.pk, item.object_id)]
        assignments.append(
            assignment_model(
                **{
                    actor_field: item.actor,
                    'object_role': object_role,
                    'role_definition': item.role_definition,
                    'content_type': item.content_type,
                    'object_id': item.object_id,
                    'object_ansible_id': object_ansible_ids.get((item.content_type.app_label, item.content_type.model, item.object_id)),
                    'created_by': created_by,
                }
            )
        )
    return assignments


def _assignment_query_filters(assignments: list[AssignmentBase], actor_field: str) -> list[Q]:
    pairs = [(getattr(assignment, actor_field), assignment.object_role) for assignment in assignments]
    return list(_pair_filter_chunks(pairs, actor_field, 'object_role'))


def _create_assignment_batch(
    assignment_model,
    assignments: list[AssignmentBase],
    actor_field: str,
    fire_signals_on_create: bool,
    ignore_conflicts: bool,
) -> list[AssignmentBase]:
    if not assignments:
        return []

    query_filters = _assignment_query_filters(assignments, actor_field)
    existing_pks = set()
    for query_filter in query_filters:
        existing_pks.update(assignment_model.objects.filter(query_filter).values_list('pk', flat=True))

    bulk_create_db_safe(assignment_model, assignments, ignore_conflicts=ignore_conflicts)

    created = []
    for query_filter in query_filters:
        created.extend(assignment_model.objects.filter(query_filter))
    if fire_signals_on_create:
        _fire_post_save(created, existing_pks)
    else:
        _audit_log_created(created, existing_pks)
    return created


def _create_assignments(
    user_resolved: list[ResolvedAssignment],
    team_resolved: list[ResolvedAssignment],
    lookup: ObjectRoleLookup,
    object_ansible_ids: dict[tuple[str, str, str], str],
    fire_signals_on_create: bool = True,
    ignore_conflicts: bool = True,
) -> list[AssignmentBase]:
    """Bulk-create user and team assignment objects, return all resulting assignments."""
    created_by = current_user_or_system_user()
    all_assignments: list[AssignmentBase] = []

    for resolved, assignment_model, actor_field in (
        (user_resolved, RoleUserAssignment, 'user'),
        (team_resolved, RoleTeamAssignment, 'team'),
    ):
        objects = _build_assignment_objects(resolved, assignment_model, actor_field, lookup, object_ansible_ids, created_by)
        all_assignments.extend(_create_assignment_batch(assignment_model, objects, actor_field, fire_signals_on_create, ignore_conflicts))

    return all_assignments


def _collect_recompute_team_ids(object_roles: Iterable[ObjectRole]) -> set[int]:
    """Identify team IDs that need member-role recomputation."""
    rd_has_team_perm: dict[int, bool] = {}
    recompute_team_ids: set[int] = set()
    for obj_role in object_roles:
        rd_id = obj_role.role_definition_id
        if rd_id not in rd_has_team_perm:
            rd_has_team_perm[rd_id] = RoleDefinition.objects.filter(pk=rd_id, permissions__codename=permission_registry.team_permission).exists()
        if rd_has_team_perm[rd_id]:
            recompute_team_ids.update(team_ids_from_role_target(obj_role))
    return recompute_team_ids


def _check_defer_guard() -> None:
    if defer_rbac_state.active and defer_rbac_state.has_deferred_data:
        raise RuntimeError(
            "Permission assignment/removal cannot be called inside defer_rbac_computations "
            "after resources have been created or deleted. RoleEvaluation data is stale."
        )


def _recompute_after_give(
    lookup: ObjectRoleLookup,
    assignments: list[AssignmentBase],
) -> None:
    """Run recomputation pass after bulk permission assignment."""
    _check_defer_guard()
    recompute_team_ids = _collect_recompute_team_ids(lookup.values())
    object_roles_to_update: set[ObjectRole] = set(lookup.values())

    unique_teams = {a.team for a in assignments if isinstance(a, RoleTeamAssignment)}
    if unique_teams:
        direct_roles = ObjectRole.objects.filter(pk__in=[obj_role.pk for obj_role in object_roles_to_update]).prefetch_related('provides_teams__has_roles')
        for obj_role in direct_roles:
            object_roles_to_update.update(obj_role.descendent_roles())
        object_roles_to_update.update(bulk_ancestor_roles({team.pk for team in unique_teams}))

    if recompute_team_ids:
        compute_team_member_roles(team_ids=recompute_team_ids)
    if object_roles_to_update:
        roles_to_recompute = ObjectRole.objects.filter(pk__in=[obj_role.pk for obj_role in object_roles_to_update]).prefetch_related(
            'provides_teams__has_roles'
        )
        recompute_role_evaluations(roles_to_recompute)


def _find_assignments(
    resolved: Sequence[ResolvedAssignment],
    lookup: ObjectRoleLookup,
    model: type[AssignmentBase],
    actor_field: str,
) -> list[AssignmentBase]:
    """Find existing assignments matching resolved triples via the ObjectRole lookup."""
    # Build list of (object_role_id, actor_pk) pairs
    pairs = []
    for ra in resolved:
        obj_role = lookup.get((ra.role_definition.pk, ra.object_id))
        if obj_role is not None:
            pairs.append((obj_role.pk, ra.actor.pk))

    if not pairs:
        return []

    results = []
    for query_filter in _pair_filter_chunks(pairs, 'object_role_id', actor_field):
        results.extend(model.objects.filter(query_filter))
    return results


def _recompute_after_remove(
    object_role_ids: set[int],
    actor_team_ids: set[int] = frozenset(),
) -> None:
    """Recompute permissions, expand team ancestors, and clean up orphaned ObjectRoles."""
    _check_defer_guard()
    object_roles = set(ObjectRole.objects.filter(pk__in=object_role_ids))
    recompute_team_ids = _collect_recompute_team_ids(object_roles)
    object_roles_to_update: set[ObjectRole] = set(object_roles)

    if actor_team_ids:
        snapshot = list(object_roles_to_update)  # snapshot: set is mutated in the loop
        for obj_role in snapshot:
            object_roles_to_update.update(obj_role.descendent_roles())
        object_roles_to_update.update(bulk_ancestor_roles(actor_team_ids))

    if recompute_team_ids:
        compute_team_member_roles(team_ids=recompute_team_ids)
    if object_roles_to_update:
        surviving_object_roles = ObjectRole.objects.filter(pk__in=[o.pk for o in object_roles_to_update])
        recompute_role_evaluations(surviving_object_roles)

    delete_object_roles(ObjectRole.objects.filter(id__in=object_role_ids, users__isnull=True, teams__isnull=True))


def remove_assignments(
    user_assignments: Sequence[RoleUserAssignment] = (),
    team_assignments: Sequence[RoleTeamAssignment] = (),
) -> None:
    """Remove assignments by reference and recompute affected permissions.

    Lower-level alternative to bulk_remove_permissions — accepts assignment objects
    directly, avoiding the triple resolution and GFK lookups that the bulk API requires.
    """
    if not user_assignments and not team_assignments:
        return

    object_role_ids: set[int] = set()
    actor_team_ids: set[int] = set()
    for a in user_assignments:
        object_role_ids.add(a.object_role_id)
    for a in team_assignments:
        object_role_ids.add(a.object_role_id)
        actor_team_ids.add(a.team_id)

    if user_assignments:
        RoleUserAssignment.objects.filter(pk__in=[a.pk for a in user_assignments]).delete()
    if team_assignments:
        RoleTeamAssignment.objects.filter(pk__in=[a.pk for a in team_assignments]).delete()

    _recompute_after_remove(object_role_ids, actor_team_ids)


def give_assignments(
    user_resolved: Sequence[ResolvedAssignment] = (),
    team_resolved: Sequence[ResolvedAssignment] = (),
    fire_signals_on_create: bool = True,
    ignore_conflicts: bool = True,
) -> list[AssignmentBase]:
    """Assign already-resolved roles and return the persisted assignments.

    Validation is skipped. ``ignore_conflicts`` controls whether database insert
    conflicts are ignored or surfaced to the caller.
    """
    if not user_resolved and not team_resolved:
        return []

    user_resolved = list(user_resolved)
    team_resolved = list(team_resolved)
    object_ansible_ids = _batch_resolve_object_ansible_ids(user_resolved + team_resolved)
    lookup = _ensure_object_roles(user_resolved + team_resolved)
    assignments = _create_assignments(
        user_resolved,
        team_resolved,
        lookup,
        object_ansible_ids,
        fire_signals_on_create=fire_signals_on_create,
        ignore_conflicts=ignore_conflicts,
    )
    _recompute_after_give(lookup, assignments)
    return assignments


def bulk_give_permissions(
    user_permissions: Sequence[PermissionTriple] = (),
    team_permissions: Sequence[PermissionTriple] = (),
    fire_signals_on_create: bool = True,
    ignore_conflicts: bool = True,
) -> list[AssignmentBase]:
    """Validate permission triples, create their assignments, and return persisted rows.

    ``ignore_conflicts`` defaults to ignoring insert conflicts; callers that need to
    distinguish their writes can disable it and handle integrity conflicts.
    """
    if not user_permissions and not team_permissions:
        return []

    user_resolved, team_resolved = _resolve_assignments(user_permissions, team_permissions)
    return give_assignments(
        user_resolved,
        team_resolved,
        fire_signals_on_create=fire_signals_on_create,
        ignore_conflicts=ignore_conflicts,
    )


def bulk_remove_permissions(
    user_permissions: Sequence[PermissionTriple] = (),
    team_permissions: Sequence[PermissionTriple] = (),
) -> None:
    """Bulk-remove multiple role assignments.

    user_permissions: sequence of (role_definition, user, content_object) triples
    team_permissions: sequence of (role_definition, team, content_object) triples

    This is the bulk replacement for remove_permission. Deletes assignments,
    cleans up orphaned ObjectRoles, and runs a single recomputation pass.
    """
    if not user_permissions and not team_permissions:
        return

    user_resolved = _resolve_triples(user_permissions)
    team_resolved = _resolve_triples(team_permissions)
    lookup = _lookup_object_roles(user_resolved + team_resolved)
    if not lookup:
        return

    user_found = _find_assignments(user_resolved, lookup, RoleUserAssignment, 'user_id')
    team_found = _find_assignments(team_resolved, lookup, RoleTeamAssignment, 'team_id')
    remove_assignments(user_assignments=user_found, team_assignments=team_found)
