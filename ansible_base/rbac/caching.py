import logging
from collections import defaultdict
from collections.abc import Iterable
from typing import Optional
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.db.utils import IntegrityError

from ansible_base.rbac.models import ObjectRole, RoleDefinition, RoleEvaluation, RoleEvaluationUUID, get_evaluation_model
from ansible_base.rbac.permission_registry import permission_registry
from ansible_base.rbac.prefetch import TypesPrefetch

logger = logging.getLogger('ansible_base.rbac.caching')


"""
This module has callable methods to fill in things marked with COMPUTED DATA in the models
from the user-specifications in other fields.
These need to be called in specific hooks to assure that evaluations remain correct,
logic for triggers are in the triggers module.

NOTE:
This is highly dependent on the model methods ObjectRole.needed_cache_updates and expected_direct_permissions
Those methods are what truly dictate the object-role to object-permission translation
"""


def bulk_ancestor_roles(team_pks: Iterable[int]) -> set['ObjectRole']:
    """Return ObjectRoles that grant any permission to the given teams (via RoleEvaluation)."""
    ancestor_evals = RoleEvaluation.objects.filter(
        codename=permission_registry.team_permission,
        object_id__in=team_pks,
        content_type_id=permission_registry.team_ct_id,
    )
    return set(ObjectRole.objects.filter(permission_partials__in=ancestor_evals))


def cleanup_deleted_team_roles(team_pks: set[int]) -> tuple[set['ObjectRole'], set[int]]:
    """Remove ObjectRoles and evaluations for deleted teams. Called by defer_rbac_computations flush."""
    ancestor_roles = bulk_ancestor_roles(team_pks)
    team_ct_id = permission_registry.team_ct_id
    RoleEvaluation.objects.filter(content_type_id=team_ct_id, object_id__in=team_pks).delete()
    deleted_or_ids = set(ObjectRole.objects.filter(content_type_id=team_ct_id, object_id__in=team_pks).values_list('id', flat=True))
    ObjectRole.objects.filter(id__in=deleted_or_ids).delete()
    eval_model = get_evaluation_model(permission_registry.team_model)
    eval_model.objects.filter(content_type_id=team_ct_id, object_id__in=team_pks).delete()
    return ancestor_roles, deleted_or_ids


def cleanup_deleted_object_roles(object_pks: list[tuple[int, int | UUID]]) -> set[int]:
    """Remove ObjectRoles and evaluations for deleted objects. Called by defer_rbac_computations flush."""
    by_ct: dict[int, set[int | UUID]] = defaultdict(set)
    for ct_id, obj_id in object_pks:
        by_ct[ct_id].add(obj_id)
    deleted_or_ids: set[int] = set()
    for ct_id, obj_ids in by_ct.items():
        batch_ids = set(ObjectRole.objects.filter(content_type_id=ct_id, object_id__in=obj_ids).values_list('id', flat=True))
        ObjectRole.objects.filter(id__in=batch_ids).delete()
        deleted_or_ids.update(batch_ids)
        uuid_ids = {oid for oid in obj_ids if isinstance(oid, UUID)}
        int_ids = obj_ids - uuid_ids
        if int_ids:
            RoleEvaluation.objects.filter(content_type_id=ct_id, object_id__in=int_ids).delete()
        if uuid_ids:
            RoleEvaluationUUID.objects.filter(content_type_id=ct_id, object_id__in=uuid_ids).delete()
    return deleted_or_ids


def object_roles_for_parents(parent_gfks: set[tuple]) -> set['ObjectRole']:
    """Return ObjectRoles affected by created objects via their parent chain. Called by defer_rbac_computations flush."""
    q_exprs = [Q(content_type=parent_ct, object_id=parent_id) for parent_ct, parent_id in parent_gfks]
    q_filter = q_exprs[0]
    for next_q in q_exprs[1:]:
        q_filter |= next_q
    to_update = set(ObjectRole.objects.filter(q_filter))
    ancestors = set(ObjectRole.objects.filter(provides_teams__has_roles__in=to_update))
    to_update.update(ancestors)
    return to_update


def all_team_parents(team_id: int, team_team_parents: dict, seen: Optional[set] = None) -> set[int]:
    """
    Returns parent teams, and parent teams of parent teams, until we have them all
        {parent_team_id, parent_team_id, ...}

    team_id: id of the team we want to get the direct and indirect parents of
    team_team_parents: mapping of team id to ids of its parents, this is not modified by this method
    seen: mutable set that will be added to by each call so that we can not recurse infinitely
    """
    parent_team_ids = set()
    if seen is None:
        seen = set()
    for parent_id in team_team_parents.get(team_id, []):
        if parent_id in seen:
            # will be combined in a lower level of the call stack
            # this condition prevents infinite recursion in the event of loops in the graph
            continue
        parent_team_ids.add(parent_id)
        seen.add(parent_id)
        parent_team_ids.update(all_team_parents(parent_id, team_team_parents, seen=seen))
    return parent_team_ids


def all_team_children(team_id: int, team_team_children: dict, seen: Optional[set] = None) -> set[int]:
    """
    Returns child teams, and child teams of child teams, until we have them all.
    Mirror of all_team_parents but traversing the reverse direction.

    team_id: id of the team we want to get the direct and indirect children of
    team_team_children: mapping of team id to ids of its children (reverse of team_team_parents)
    seen: mutable set to prevent infinite recursion in the event of loops
    """
    child_team_ids = set()
    if seen is None:
        seen = set()
    for child_id in team_team_children.get(team_id, []):
        if child_id in seen:
            continue
        child_team_ids.add(child_id)
        seen.add(child_id)
        child_team_ids.update(all_team_children(child_id, team_team_children, seen=seen))
    return child_team_ids


def get_org_team_mapping() -> dict[int, list[int]]:
    """
    Returns the teams in all organization as a dictionary.
        {
            organization_id: [team_id, team_id, ...],
            organization_id: [team_id, ...]
        }
    """
    org_team_mapping = defaultdict(list)
    team_fields = ['id']
    team_parent_fd = permission_registry.get_parent_fd_name(permission_registry.team_model)
    if team_parent_fd:
        team_fields.append(f'{team_parent_fd}_id')
        for team in permission_registry.team_model.objects.only(*team_fields):
            team_parent_id = getattr(team, f'{team_parent_fd}_id')
            org_team_mapping[team_parent_id].append(team.id)
    return org_team_mapping


def get_direct_team_member_roles(org_team_mapping: dict) -> dict[int, list[int]]:
    """
    If an organization-level role lists "member_team" permission, that confers
    several team's permissions to users who holds an org role of that type.
    If a team-level role lists "member_team" then that also convers
    the member permissions to the user.
    These do not yet consider teams-of-teams, so these are "direct" membership roles to a team.
    Returns a dictionary with teams as keys and the object role ids that give membership as values.
        {
            team_id: [role_id, role_id, ...],
            team_id: [role_id, ...]
        }
    """
    direct_member_roles = defaultdict(list)
    for object_role in ObjectRole.objects.filter(role_definition__permissions__codename=permission_registry.team_permission).iterator():
        if object_role.content_type_id == permission_registry.team_ct_id:
            direct_member_roles[int(object_role.object_id)].append(object_role.id)
        elif object_role.content_type_id == permission_registry.org_ct_id:
            object_id = int(object_role.object_id)
            if object_id not in org_team_mapping:
                continue  # this means the organization has no team but has member_team as a listed permission
            for team_id in org_team_mapping[object_id]:
                direct_member_roles[team_id].append(object_role.id)
        else:
            logger.warning(f'{object_role} gives {permission_registry.team_permission} to an invalid type')
    return direct_member_roles


def get_parent_teams_of_teams(org_team_mapping: dict) -> dict[int, list[int]]:
    """
    Returns a dictionary showing the teams-of-teams relationships in the system
    this happens when a member_team role confers membership to another team.
        {
            team_id: [parent_team_id, parent_team_id, ...],
            team_id: []
        }
    The queryset and logic is similar to get_direct_team_member_roles but
    optimizations are different.
    """
    team_team_parents = defaultdict(list)
    for object_role in ObjectRole.objects.filter(
        role_definition__permissions__codename=permission_registry.team_permission, teams__isnull=False
    ).prefetch_related('teams'):
        for actor_team in object_role.teams.all():
            if object_role.content_type_id == permission_registry.team_ct_id:
                team_team_parents[int(object_role.object_id)].append(actor_team.id)
            elif object_role.content_type_id == permission_registry.org_ct_id:
                object_id = int(object_role.object_id)
                if object_id not in org_team_mapping:
                    continue  # again, means the organization has no team but has member_team as a listed permission
                for team_id in org_team_mapping[object_id]:
                    team_team_parents[team_id].append(actor_team.id)
    return team_team_parents


def _is_stale_objectrole_fk(exc):
    """Return True if *exc* is specifically an FK violation from a stale ObjectRole reference.

    PostgreSQL (psycopg2/psycopg3): checks SQLSTATE 23503 (foreign_key_violation)
    and that the referenced table is ``dab_rbac_objectrole``.  Other
    IntegrityError sub-types (unique-constraint, check-constraint, etc.) or FK
    violations referencing a different table return False so they propagate
    normally.

    Other backends (SQLite): returns False.  The TOCTOU race requires truly
    concurrent committed transactions, which SQLite's global write lock
    prevents, so FK errors there indicate a real bug.
    """
    cause = exc.__cause__
    if cause is None:
        return False
    # psycopg3 exposes .sqlstate, psycopg2 exposes .pgcode
    sqlstate = getattr(cause, 'sqlstate', None) or getattr(cause, 'pgcode', None)
    if sqlstate != '23503':
        return False
    return 'dab_rbac_objectrole' in str(cause)


def _safe_m2m_add(team, to_add):
    """Add ObjectRole IDs to team.member_roles, handling concurrent deletions.

    A TOCTOU race exists: ObjectRole IDs collected during the read phase of
    compute_team_member_roles() may be deleted by a concurrent transaction
    (e.g. org deletion cascading through rbac_post_delete_remove_object_roles)
    before this write.  The savepoint allows us to catch the FK violation
    without aborting the outer transaction, then retry with only IDs that
    still exist.
    """
    try:
        with transaction.atomic():
            team.member_roles.add(*to_add)
    except IntegrityError as exc:
        if not _is_stale_objectrole_fk(exc):
            raise
        to_add = set(ObjectRole.objects.filter(id__in=to_add).values_list('id', flat=True))
        if to_add:
            try:
                with transaction.atomic():
                    team.member_roles.add(*to_add)
            except IntegrityError as exc:
                if not _is_stale_objectrole_fk(exc):
                    raise
                logger.warning('Persistent IntegrityError adding member_roles for team %s, will be corrected on next recompute', team.id)


def compute_team_member_roles(team_ids=None):
    """
    Fills in the ObjectRole.provides_teams relationship for teams.
    This relationship is a list of teams that the role grants membership for.

    Args:
        team_ids: Optional iterable of team IDs to scope the write phase.
            When provided, only those teams (plus their descendants in the
            team-of-team graph) have their member_roles updated.
            When None, all teams are updated (global recompute).
    """
    # Manually prefetch the team to org memberships
    org_team_mapping = get_org_team_mapping()

    # Build out the direct member roles for teams
    direct_member_roles = get_direct_team_member_roles(org_team_mapping)

    # Build a team-to-team child-to-parents mapping for teams that have permission to other teams
    team_team_parents = get_parent_teams_of_teams(org_team_mapping)

    # Now we need to crawl the team-team graph to get the full list of roles that grants access to each team
    # for each parent team that grants membership to a team, we need to add the roles that grant
    # membership to that parent team
    all_member_roles = {}
    for team_id, member_roles in direct_member_roles.items():
        all_member_roles[team_id] = set(member_roles)  # will also avoid mutating original data structure later
        for parent_team_id in all_team_parents(team_id, team_team_parents):
            all_member_roles[team_id].update(set(direct_member_roles.get(parent_team_id, [])))

    # Great! we should be done building all_member_roles which tells what roles gives team membership for all teams
    # now at this point we save that data, optionally scoped to specific teams
    if team_ids is not None:
        team_ids = set(team_ids)
        # Expand to include descendants in the team-of-team graph
        team_team_children = defaultdict(set)
        for child, parents in team_team_parents.items():
            for parent in parents:
                team_team_children[parent].add(child)
        expanded = set(team_ids)
        for tid in team_ids:
            expanded.update(all_team_children(tid, team_team_children))
        teams_qs = permission_registry.team_model.objects.filter(id__in=expanded)
    else:
        teams_qs = permission_registry.team_model.objects.all()

    for team in teams_qs.prefetch_related('member_roles'):
        # NOTE: the .set method will not use the prefetched data, thus the messy implementation here
        existing_ids = set(r.id for r in team.member_roles.all())
        expected_ids = set(all_member_roles.get(team.id, []))
        to_add = expected_ids - existing_ids
        to_remove = existing_ids - expected_ids
        if to_add:
            _safe_m2m_add(team, to_add)
        if to_remove:
            team.member_roles.remove(*to_remove)


def _safe_bulk_create_evaluations(model, evaluations, ignore_conflicts):
    """bulk_create RoleEvaluation rows, handling concurrent ObjectRole deletions.

    ignore_conflicts (ON CONFLICT DO NOTHING) only suppresses unique-constraint
    violations.  A concurrent ObjectRole deletion causes an FK violation on
    the role_id column which is a different IntegrityError.  We use a savepoint
    so the outer transaction stays healthy, then retry without the stale rows.
    """
    if not evaluations:
        return
    try:
        with transaction.atomic():
            model.objects.bulk_create(evaluations, ignore_conflicts=ignore_conflicts)
    except IntegrityError as exc:
        if not _is_stale_objectrole_fk(exc):
            raise
        existing_role_ids = set(ObjectRole.objects.filter(id__in={e.role_id for e in evaluations}).values_list('id', flat=True))
        evaluations = [e for e in evaluations if e.role_id in existing_role_ids]
        if evaluations:
            try:
                with transaction.atomic():
                    model.objects.bulk_create(evaluations, ignore_conflicts=ignore_conflicts)
            except IntegrityError as exc:
                if not _is_stale_objectrole_fk(exc):
                    raise
                logger.warning('Persistent IntegrityError in bulk_create for %s, will be corrected on next recompute', model.__name__)


def compute_object_role_permissions(object_roles=None, types_prefetch=None, object_pk=None, object_ct_id=None):
    """
    Assumes the ObjectRole.provides_teams relationship is correct.
    Makes the RoleEvaluation table correct for all specified object_roles
    """
    to_delete = set()
    to_add = []

    if types_prefetch is None:
        types_prefetch = TypesPrefetch.from_database(RoleDefinition)
    if object_roles is None:
        object_roles = ObjectRole.objects.iterator()

    for object_role in object_roles:
        role_to_delete, role_to_add = object_role.needed_cache_updates(types_prefetch=types_prefetch, object_pk=object_pk, object_ct_id=object_ct_id)

        if role_to_delete:
            logger.debug(f'Removing {len(role_to_delete)} object-permissions from {object_role}')
            to_delete.update(role_to_delete)

        if role_to_add:
            logger.debug(f'Adding {len(role_to_add)} object-permissions to {object_role}')
            to_add.extend(role_to_add)

    if to_add:
        logger.info(f'Adding {len(to_add)} object-permission records')
        to_add_int = []
        to_add_uuid = []
        for evaluation in to_add:
            if isinstance(evaluation.object_id, int):
                to_add_int.append(evaluation)
            elif isinstance(evaluation.object_id, UUID):
                to_add_uuid.append(evaluation)
            else:
                raise RuntimeError(f'Could not find a place in cache for {evaluation}')
        _safe_bulk_create_evaluations(RoleEvaluation, to_add_int, settings.ANSIBLE_BASE_EVALUATIONS_IGNORE_CONFLICTS)
        _safe_bulk_create_evaluations(RoleEvaluationUUID, to_add_uuid, settings.ANSIBLE_BASE_EVALUATIONS_IGNORE_CONFLICTS)

    if to_delete:
        logger.info(f'Deleting {len(to_delete)} object-permission records')
        to_delete_int = []
        to_delete_uuid = []
        for evaluation_id, evaluation_type in to_delete:
            if evaluation_type is int:
                to_delete_int.append(evaluation_id)
            elif evaluation_type is UUID:
                to_delete_uuid.append(evaluation_id)
            else:
                raise RuntimeError(f'Unexpected type to delete {evaluation_id}-{evaluation_type}')
        if to_delete_int:
            RoleEvaluation.objects.filter(id__in=to_delete_int).delete()
        if to_delete_uuid:
            RoleEvaluationUUID.objects.filter(id__in=to_delete_uuid).delete()
