from __future__ import annotations

import functools
import logging
import threading
from contextlib import contextmanager
from typing import TYPE_CHECKING, Any, Union
from uuid import UUID

from django.db.models import Model, Q
from django.db.models.signals import m2m_changed, post_delete, post_init, post_save, pre_delete, pre_save
from django.dispatch import Signal

if TYPE_CHECKING:
    from django.db.backends.base.base import BaseDatabaseWrapper

    from ansible_base.rbac.models import DABContentType

from ansible_base.lib.utils.db import build_safe_sql, migrations_are_complete
from ansible_base.rbac.caching import compute_object_role_permissions, compute_team_member_roles
from ansible_base.rbac.models import ObjectRole, RoleDefinition, RoleEvaluation, get_evaluation_model
from ansible_base.rbac.permission_registry import permission_registry
from ansible_base.rbac.validators import validate_team_assignment_enabled

logger = logging.getLogger('ansible_base.rbac.triggers')


_SENTINEL = object()


"""
As the caching module will fill in cached data,
this module shall manage the calling of the caching methods.
Sounds simple, but is actually more complicated that the caching logic itself.
"""


dab_post_migrate = Signal()


def team_ancestor_roles(team):
    """
    Return a queryset of all roles that directly or indirectly grant any form of permission to a team.
    This is generally used when invalidating a team membership for one reason or another.
    This assumes that teams and all team parent models have integer primary keys.
    """
    permission_kwargs = dict(codename=permission_registry.team_permission, object_id=team.id, content_type_id=permission_registry.team_ct_id)
    return set(ObjectRole.objects.filter(permission_partials__in=RoleEvaluation.objects.filter(**permission_kwargs)))


def _team_ids_from_role_target(object_role: 'ObjectRole') -> set[int]:
    """Derive which teams a member_team ObjectRole targets from its content type.

    Used only when the provides_teams relationship is not yet computed —
    i.e. for newly created ObjectRoles or when member_team permission was
    just added to a RoleDefinition. For existing roles where provides_teams
    is already populated, query provides_teams directly instead.
    """
    if object_role.content_type_id == permission_registry.team_ct_id:
        return {int(object_role.object_id)}
    if object_role.content_type_id == permission_registry.org_ct_id:
        parent_fd = permission_registry.get_parent_fd_name(permission_registry.team_model)
        if parent_fd:
            return set(permission_registry.team_model.objects.filter(**{f'{parent_fd}_id': int(object_role.object_id)}).values_list('id', flat=True))
    return set()


def needed_updates_on_assignment(role_definition, actor, object_role, created=False, giving=True):
    """
    If a user or a team is granted a role or has a role revoked,
    then this returns instructions for what needs to be updated
    returns tuple
        (set or None: team IDs needing provides_teams recomputation, set: object roles to update)
    """
    # we maintain a list of object roles that we need to update evaluations for
    to_update = set()
    if created:
        to_update.add(object_role)

    has_team_perm = role_definition.permissions.filter(codename=permission_registry.team_permission).exists()

    if actor._meta.model_name == permission_registry.team_model._meta.model_name:
        has_org_member = role_definition.permissions.filter(codename='member_organization').exists()

        # Raise exception if settings prohibits this assignment
        validate_team_assignment_enabled(object_role.content_type, has_team_perm=has_team_perm, has_org_member=has_org_member)

    # If permissions for team are changed. That tends to affect a lot.
    changes_team_owners = False
    if actor._meta.model_name != 'user':
        to_update.update(team_ancestor_roles(actor))
        if not giving:
            # this will delete some permission assignments that will be removed from this relationship
            to_update.update(object_role.descendent_roles())
        changes_team_owners = True

    deleted = False
    if (not giving) and (not (object_role.users.exists() or object_role.teams.exists())):
        # time to delete the object role because it is unused
        to_update.discard(object_role)
        deleted = True

    # giving or revoking team permissions may not change the parentage
    # but this will still change what downstream roles grant what permissions
    if (has_team_perm and created) or (giving and changes_team_owners):
        to_update.update(object_role.descendent_roles())

    # actions which can change the team parentage structure
    recompute_team_ids = None
    if has_team_perm and (created or deleted or changes_team_owners):
        if created:
            # provides_teams not yet computed for new ObjectRoles
            recompute_team_ids = _team_ids_from_role_target(object_role)
        else:
            # For existing roles, provides_teams already captures which
            # teams this role grants membership to
            recompute_team_ids = set(object_role.provides_teams.values_list('id', flat=True))

    return (recompute_team_ids, to_update)


# stores state for the defer_rbac_cache annotation so that it can be accessed by function in the call chain
# of the annotation
class _DeferRBACCache(threading.local):
    def __init__(self):
        self.active = False
        self.team_ids = set()
        self.object_roles = set()
        self.skip_post_delete_rbac = False


_defer_rbac_cache = _DeferRBACCache()


# allows deferring the rbac computation in cases where many object roles are updated in short order
@contextmanager
def defer_rbac_cache():
    if _defer_rbac_cache.active:
        # Re-entrant: the outermost caller owns the flush in its finally block.
        # yield is required by @contextmanager; return skips the finally block
        # intentionally so only the outermost exit triggers the flush.
        yield
        return
    _defer_rbac_cache.active = True
    try:
        yield
    except BaseException:
        _defer_rbac_cache.active = False
        _defer_rbac_cache.team_ids = set()
        _defer_rbac_cache.object_roles = set()
        _defer_rbac_cache.skip_post_delete_rbac = False
        raise
    else:
        team_ids = _defer_rbac_cache.team_ids
        object_roles = _defer_rbac_cache.object_roles
        _defer_rbac_cache.active = False
        _defer_rbac_cache.team_ids = set()
        _defer_rbac_cache.object_roles = set()
        _defer_rbac_cache.skip_post_delete_rbac = False

        if team_ids:
            compute_team_member_roles(team_ids=team_ids)

        if object_roles:
            surviving_ids = set(ObjectRole.objects.filter(id__in={r.id for r in object_roles}).values_list('id', flat=True))
            surviving_roles = {r for r in object_roles if r.id in surviving_ids}
            if surviving_roles:
                compute_object_role_permissions(object_roles=surviving_roles)

        ObjectRole.objects.filter(users__isnull=True, teams__isnull=True).delete()


def update_after_assignment(recompute_team_ids, to_update):
    "Call this with the output of needed_updates_on_assignment"
    if _defer_rbac_cache.active:
        if recompute_team_ids is not None:
            _defer_rbac_cache.team_ids.update(recompute_team_ids)
        if to_update is not None:
            _defer_rbac_cache.object_roles.update(to_update)
        return

    if recompute_team_ids is not None:
        compute_team_member_roles(team_ids=recompute_team_ids)

    compute_object_role_permissions(object_roles=to_update)


def permissions_changed(instance, action, model, pk_set, reverse, **kwargs):
    """Recompute object role permissions when a RoleDefinition's permissions m2m changes."""
    if action.startswith('pre_'):
        return
    to_recompute = set(ObjectRole.objects.filter(role_definition=instance).prefetch_related('teams__member_roles'))
    if not to_recompute:
        return
    if reverse:
        raise RuntimeError('Removal of permssions through reverse relationship not supported')

    if action in ('post_add', 'post_remove'):
        if permission_registry.permission_qs.filter(codename=permission_registry.team_permission, pk__in=pk_set).exists():
            for object_role in to_recompute.copy():
                to_recompute.update(object_role.descendent_roles())
            team_ids = set()
            for object_role in to_recompute:
                # provides_teams covers removal (member_team was present, teams are populated)
                team_ids.update(object_role.provides_teams.values_list('id', flat=True))
                if action == 'post_add':
                    # provides_teams is empty when member_team was just added,
                    # so derive affected teams from the role's content type
                    team_ids.update(_team_ids_from_role_target(object_role))
            compute_team_member_roles(team_ids=team_ids)
        # All team member roles that give this permission through this role need to be updated
        for role in to_recompute.copy():
            for team in role.teams.all():
                to_recompute.update(team.member_roles.all())
    elif action == 'post_clear':
        # unfortunately this does not give us a list of permissions to work with
        # provides_teams captures teams if member_team was among the cleared permissions;
        # content-type derivation covers the case where it wasn't yet computed
        team_ids = set()
        for object_role in to_recompute:
            team_ids.update(object_role.provides_teams.values_list('id', flat=True))
            team_ids.update(_team_ids_from_role_target(object_role))
        compute_team_member_roles(team_ids=team_ids)
        to_recompute = None  # all
    compute_object_role_permissions(object_roles=to_recompute)


m2m_changed.connect(permissions_changed, sender=RoleDefinition.permissions.through)


def rbac_post_init_set_original_parent(sender, instance, **kwargs):
    """
    connect to post_init signal
    Used to set the original, or
    pre-save parent id (usually organization), so we can later determine if
    the organization field has changed.
    """
    parent_field_name = permission_registry.get_parent_fd_name(instance)
    if parent_field_name is None:
        return
    parent_id_name = f'{parent_field_name}_id'
    if parent_id_name not in instance.__dict__:
        return  # we do not want to conflit with .only usage
    instance.__rbac_original_parent_id = getattr(instance, parent_id_name)


def get_parent_ids(instance) -> list[tuple[Model, Union[int, UUID]]]:
    parent_field_name = permission_registry.get_parent_fd_name(instance)
    if not parent_field_name:
        return []
    parent_cls = permission_registry.get_parent_model(instance)

    if permission_registry.get_parent_fd_name(parent_cls):
        # has another level of model
        parent_obj = getattr(instance, parent_field_name)
        if parent_obj:
            parent_ct = permission_registry.content_type_model.objects.get_for_model(parent_cls)
            return [(parent_ct, parent_obj.pk)] + get_parent_ids(parent_obj)
    else:
        parent_id = getattr(instance, f'{parent_field_name}_id')
        if parent_id:
            parent_ct = permission_registry.content_type_model.objects.get_for_model(parent_cls)
            return [(parent_ct, parent_id)]
    return []


def post_save_update_obj_permissions(instance, object_pk=None, object_ct_id=None):
    "Utility method shared by multiple signals"
    # Account for organization roles (and other parent objects), new and old
    parent_gfks = get_parent_ids(instance)

    if hasattr(instance, '__rbac_original_parent_id'):
        parent_cls = permission_registry.get_parent_model(instance)
        parent_ct = permission_registry.content_type_model.objects.get_for_model(parent_cls)
        parent_obj = parent_cls(pk=instance.__rbac_original_parent_id)
        parent_gfks += get_parent_ids(parent_obj)
        parent_gfks.append((parent_ct, instance.__rbac_original_parent_id))
        delattr(instance, '__rbac_original_parent_id')

    if parent_gfks:
        q_exprs = [Q(content_type=parent_ct, object_id=parent_id) for parent_ct, parent_id in parent_gfks]
        q_filter = q_exprs[0]
        for next_q in q_exprs[1:]:
            q_filter |= next_q
        to_update = set(ObjectRole.objects.filter(q_filter))
    else:
        to_update = set()

    # Account for parent team roles of those organization roles
    ancestors = set(ObjectRole.objects.filter(provides_teams__has_roles__in=to_update))
    to_update.update(ancestors)

    # If the actual object changed (created or modified) was a team, any org role
    # that has member_team needs to be updated, and any parent teams that have that role
    if instance._meta.model_name == permission_registry.team_model._meta.model_name:
        compute_team_member_roles(team_ids=[instance.id])

    if to_update:
        compute_object_role_permissions(object_roles=to_update, object_pk=object_pk, object_ct_id=object_ct_id)


def rbac_pre_save_identify_changes(instance, *args, **kwargs):
    # Exit right away if object does not have any parent objects
    parent_field_name = permission_registry.get_parent_fd_name(instance)
    if parent_field_name is None:
        return

    # The parent object can not have changed if update_fields was given and did not list that field
    update_fields = kwargs.get('update_fields', None)
    if update_fields and not (parent_field_name in update_fields or f'{parent_field_name}_id' in update_fields):
        return

    # If we HAVE to do a query to find out if the parent field has changed then we will here
    if not hasattr(instance, '__rbac_original_parent_id') and instance.pk:
        instance.__rbac_original_parent_id = getattr(type(instance).objects.only('pk').get(pk=instance.pk), f'{parent_field_name}_id')


def rbac_post_save_update_evaluations(instance, created, *args, **kwargs):
    """
    Connect to post_save signal for objects in the permission registry
    If the parent object changes, this rebuilds the cache
    """
    # Exit right away if object does not have any parent objects
    parent_field_name = permission_registry.get_parent_fd_name(instance)
    if parent_field_name is None:
        return

    # If child object is created and parent object has existing ObjectRoles
    # evaluations for the parent object roles need to be added
    if created:
        obj_ct_id = permission_registry.content_type_model.objects.get_for_model(instance).id
        post_save_update_obj_permissions(instance, object_pk=instance.pk, object_ct_id=obj_ct_id)
        return

    # The parent object can not have changed if update_fields was given and did not list that field
    update_fields = kwargs.get('update_fields', None)
    if update_fields and not (parent_field_name in update_fields or f'{parent_field_name}_id' in update_fields):
        return

    # Handle the unusual situation where the parent object changes
    current_parent_id = getattr(instance, f'{parent_field_name}_id')
    if hasattr(instance, '__rbac_original_parent_id') and instance.__rbac_original_parent_id != current_parent_id:
        logger.info(f'Object {instance} changed RBAC parent {instance.__rbac_original_parent_id}-->{current_parent_id}')
        post_save_update_obj_permissions(instance)


def team_pre_delete(instance, *args, **kwargs):
    instance.__rbac_stashed_member_roles = list(instance.member_roles.all())
    # Stash IDs of teams that have this team as a parent in the team-of-team graph.
    # After this team is deleted, those teams need their member_roles recomputed.
    # provides_teams tells us which teams these roles grant membership to.
    stashed_team_ids = set()
    for object_role in ObjectRole.objects.filter(teams=instance, role_definition__permissions__codename=permission_registry.team_permission):
        stashed_team_ids.update(object_role.provides_teams.values_list('id', flat=True))
    stashed_team_ids.discard(instance.id)  # the deleted team itself won't need recomputation
    instance.__rbac_stashed_recompute_team_ids = stashed_team_ids


def _collect_team_rbac_data(team_ids: set[int]) -> None:
    """Collect indirectly affected roles and recompute IDs for teams being deleted.

    Performs bulk lookups for ancestor roles, descendent roles, and provided
    teams for all ``team_ids`` at once, then stashes the results in the
    deferred RBAC cache.
    """
    team_ct_id = permission_registry.team_ct_id
    team_model = permission_registry.team_model

    # Bulk team_ancestor_roles for ALL teams at once
    ancestor_evals = RoleEvaluation.objects.filter(
        codename=permission_registry.team_permission,
        object_id__in=team_ids,
        content_type_id=team_ct_id,
    )
    indirectly_affected_roles = set(ObjectRole.objects.filter(permission_partials__in=ancestor_evals))

    # Bulk descendent_roles: get all member_roles for these teams,
    # then all provides_teams, then all has_roles
    team_object_roles = ObjectRole.objects.filter(
        teams__id__in=team_ids,
        role_definition__permissions__codename=permission_registry.team_permission,
    )
    # Get all teams provided by these roles
    provided_team_ids = set(team_model.objects.filter(member_roles__in=team_object_roles).values_list('id', flat=True))
    # Get descendent roles through provided teams
    if provided_team_ids:
        descendent_roles = set(ObjectRole.objects.filter(provides_teams__id__in=provided_team_ids))
        indirectly_affected_roles.update(descendent_roles)

    # Stash recompute team IDs (teams that had this team as parent)
    stashed_recompute_ids = provided_team_ids - team_ids  # exclude deleted teams
    if stashed_recompute_ids:
        _defer_rbac_cache.team_ids.update(stashed_recompute_ids)
    if indirectly_affected_roles:
        _defer_rbac_cache.object_roles.update(indirectly_affected_roles)


def _check_cascade_size(instance: Model, all_cts_and_pks: list[tuple[DABContentType, set[int | str | UUID]]], object_role_ids: list[int]) -> None:
    """Raise ValidationError if the total cascade footprint exceeds the configured limit.

    Counts the total number of objects that would be loaded into memory
    for audit logging during a cascade delete.  If the count exceeds
    ANSIBLE_BASE_RBAC_CASCADE_DELETE_CHILD_OBJECT_LIMIT, the delete is rejected with a clear
    error message telling the admin to reduce the org size first.
    """
    from django.conf import settings
    from django.db import connection

    from ansible_base.rbac.models import RoleTeamAssignment, RoleUserAssignment

    limit = getattr(settings, 'ANSIBLE_BASE_RBAC_CASCADE_DELETE_CHILD_OBJECT_LIMIT', 50_000)
    if limit <= 0:
        return  # unlimited

    # Single query to count both assignment types
    id_list = list(object_role_ids)
    count_sql = build_safe_sql(
        connection.vendor,
        "SELECT (SELECT COUNT(*) FROM {I} WHERE {I} IN ({P})) + (SELECT COUNT(*) FROM {I} WHERE {I} IN ({P}))",
        [RoleUserAssignment._meta.db_table, 'object_role_id', len(id_list), RoleTeamAssignment._meta.db_table, 'object_role_id', len(id_list)],
    )
    with connection.cursor() as cursor:
        cursor.execute(count_sql, id_list + id_list)
        total_assignments = cursor.fetchone()[0]

    # total_children:    child objects found by Django's collector (teams, inventories, etc.)
    # object_role_ids:   ObjectRoles that will be raw-SQL-deleted
    # total_assignments: RoleUserAssignment + RoleTeamAssignment rows captured for audit logging
    total_children = sum(len(primary_keys) for _, primary_keys in all_cts_and_pks)
    total_cascade = total_children + len(object_role_ids) + total_assignments

    if total_cascade > limit:
        from rest_framework.exceptions import ValidationError

        model_name = type(instance).__name__
        logger.error(
            'Deleting %s pk=%s would cascade-delete %d objects (limit: %d). Remove some child objects before deleting.',
            model_name,
            instance.pk,
            total_cascade,
            limit,
        )
        raise ValidationError(
            f'Deleting this {model_name} would cascade-delete {total_cascade} objects which exceeds the limit of {limit}. Remove some child objects first.'
        )


def _raw_sql_delete_object_roles(object_role_ids: list[int], connection: BaseDatabaseWrapper) -> None:
    """Delete ObjectRoles and all dependent rows via raw SQL in dependency order.

    Table/column names come from Django's ``_meta`` (not user input) and are
    validated by ``_safe_qn`` to reject anything that isn't a simple identifier.
    """
    if not object_role_ids:
        return

    from ansible_base.rbac.models import RoleEvaluationUUID, RoleTeamAssignment, RoleUserAssignment

    # Bottom-up delete order: children first, ObjectRole last.
    delete_steps = [
        # 1. RoleEvaluation (FK: role_id -> ObjectRole)
        (RoleEvaluation._meta.db_table, 'role_id'),
        # 2. RoleEvaluationUUID (FK: role_id -> ObjectRole)
        (RoleEvaluationUUID._meta.db_table, 'role_id'),
        # 3. RoleUserAssignment (FK: object_role_id -> ObjectRole)
        (RoleUserAssignment._meta.db_table, 'object_role_id'),
        # 4. RoleTeamAssignment (FK: object_role_id -> ObjectRole)
        (RoleTeamAssignment._meta.db_table, 'object_role_id'),
        # 5. provides_teams M2M through table (FK: objectrole_id -> ObjectRole)
        (ObjectRole.provides_teams.through._meta.db_table, 'objectrole_id'),
        # 6. ObjectRole itself (children already deleted above)
        (ObjectRole._meta.db_table, 'id'),
    ]
    vendor = connection.vendor
    with connection.cursor() as cursor:
        for table_name, fk_column in delete_steps:
            sql = build_safe_sql(vendor, "DELETE FROM {I} WHERE {I} IN ({P})", [table_name, fk_column, len(object_role_ids)])
            cursor.execute(sql, object_role_ids)


def _raw_sql_delete_parent_evaluations(all_cts_and_pks: list[tuple[DABContentType, set[int | str | UUID]]], connection: BaseDatabaseWrapper) -> None:
    """Delete RoleEvaluations for parent objects using the correct evaluation table per model."""
    with connection.cursor() as cursor:
        for content_type, primary_keys in all_cts_and_pks:
            str_pks = [str(pk) for pk in primary_keys]
            if not str_pks:
                continue
            model_cls = content_type.model_class()
            eval_table = get_evaluation_model(model_cls)._meta.db_table if model_cls else RoleEvaluation._meta.db_table
            delete_sql = build_safe_sql(
                connection.vendor,
                "DELETE FROM {I} WHERE {I} = {} AND {I} IN ({P})",
                [eval_table, 'content_type_id', 'object_id', len(str_pks)],
            )
            cursor.execute(delete_sql, [content_type.id] + str_pks)


def _emit_audit_for_deleted_assignments(user_assignment_rows: list[dict[str, Any]], team_assignment_rows: list[dict[str, Any]]) -> None:
    """Emit audit log entries for deleted role assignments.

    Reconstructs model instances from captured row data and calls
    ``_log_audit_entry`` to preserve per-row audit log entries.
    """
    from ansible_base.rbac.models import RoleTeamAssignment, RoleUserAssignment

    try:
        from ansible_base.activitystream.signals import _log_audit_entry

        for model_cls, rows in ((RoleUserAssignment, user_assignment_rows), (RoleTeamAssignment, team_assignment_rows)):
            for row in rows:
                changes = {'removed_fields': {k: str(v) for k, v in row.items()}}
                obj = model_cls.__new__(model_cls)
                obj.pk = row['id']
                obj.id = row['id']
                obj.audit_log_enabled = True
                row_id = row['id']
                cls_name = model_cls.__name__
                obj.__str__ = lambda _id=row_id, _cls=cls_name: f"{_cls}(id={_id})"
                _log_audit_entry(content_object=obj, operation='delete', changes=changes)
    except ImportError:
        pass  # activity stream not installed


def _bulk_delete_and_accumulate_sync(all_cts_and_pks: list[tuple[DABContentType, set[int | str | UUID]]], instance: Model) -> None:
    """Bulk-delete ObjectRoles and RoleEvaluations via raw SQL.

    Uses raw SQL DELETE instead of Django's ORM .delete() to bypass the
    collector overhead.  Django's ``on_delete=CASCADE`` is Python-only (no
    DB-level CASCADE), so child rows are deleted in explicit bottom-up order:
    RoleEvaluation -> RoleUserAssignment -> RoleTeamAssignment ->
    provides_teams M2M -> ObjectRole.

    Assignment data is captured before deletion and fed through the existing
    activity stream audit path via reconstructed model instances, preserving
    per-row audit log entries without per-row signal overhead.
    """
    from django.db import connection

    from ansible_base.rbac.models import RoleTeamAssignment, RoleUserAssignment

    # Build one Q filter for all children + the instance itself
    delete_filter = None
    for content_type, primary_keys in all_cts_and_pks:
        entry_q = Q(content_type=content_type, object_id__in=[str(pk) for pk in primary_keys])
        delete_filter = entry_q if delete_filter is None else (delete_filter | entry_q)

    if delete_filter is None:
        return

    object_role_ids = list(ObjectRole.objects.filter(delete_filter).values_list('id', flat=True))

    if not object_role_ids:
        return

    # Check cascade size before committing to memory-intensive operations
    _check_cascade_size(instance, all_cts_and_pks, object_role_ids)

    # Capture assignment data BEFORE delete for audit logging (single query, split by type)
    user_assignment_rows = []
    team_assignment_rows = []
    for model_cls, target_list in ((RoleUserAssignment, user_assignment_rows), (RoleTeamAssignment, team_assignment_rows)):
        target_list.extend(model_cls.objects.filter(object_role_id__in=object_role_ids).values())

    _raw_sql_delete_object_roles(object_role_ids, connection)
    _raw_sql_delete_parent_evaluations(all_cts_and_pks, connection)
    _emit_audit_for_deleted_assignments(user_assignment_rows, team_assignment_rows)


def _bulk_pre_cascade_rbac_cleanup(instance: Model) -> None:
    """Pre-cascade bulk RBAC cleanup.

    Collects all RBAC-registered children of ``instance`` and handles their
    ObjectRole / RoleEvaluation cleanup in bulk queries instead of firing the
    per-object ``post_delete`` signal handler for every cascaded child.
    After this runs, the signal handler becomes a no-op via the
    ``skip_post_delete_rbac`` flag.

    Only meaningful for models that have RBAC-registered children (e.g.
    Organization -> Team, Inventory).  Leaf models (no children) return
    early and let the signal handler run as normal.

    Only runs when defer_rbac_cache is active.  When defer is not active
    (e.g. patched with nullcontext in tests), the signal handler runs
    normally and no bulk state is accumulated.
    """
    if not _defer_rbac_cache.active:
        return

    child_models = permission_registry.get_child_models(type(instance))
    if not child_models:
        return  # leaf model, let the signal handle it

    ct_model = permission_registry.content_type_model

    # Collect all child object PKs by content type
    child_pks_by_ct = {}
    for parent_filter, child_model in child_models:
        child_ct = ct_model.objects.get_for_model(child_model)
        child_pks = set(child_model.objects.filter(**{parent_filter: instance}).values_list('pk', flat=True))
        if child_pks:
            child_pks_by_ct[child_ct] = child_pks

    if not child_pks_by_ct:
        return  # no children to clean up

    # Also include the instance itself
    instance_ct = ct_model.objects.get_for_model(instance)

    # --- Team-specific RBAC graph work (ancestor/descendent roles, provides_teams) ---
    # Teams require additional graph traversal; all other child types only need
    # their ObjectRoles and RoleEvaluations deleted, which happens below.
    team_ct_id = permission_registry.team_ct_id
    for content_type, primary_keys in child_pks_by_ct.items():
        if content_type.id == team_ct_id:
            _collect_team_rbac_data(primary_keys)
            break

    # --- Bulk ObjectRole and RoleEvaluation cleanup for ALL child types ---
    all_cts_and_pks = list(child_pks_by_ct.items())
    all_cts_and_pks.append((instance_ct, {instance.pk}))

    _bulk_delete_and_accumulate_sync(all_cts_and_pks, instance)

    # Clean provides_teams entries referencing teams that are about to be
    # cascade-deleted. _raw_sql_delete_object_roles already cleaned entries
    # by objectrole_id, but the through-table also has a team_id FK — any
    # entries from OTHER ObjectRoles that reference these teams would cause
    # an IntegrityError when Django's collector cascade-deletes the teams.
    team_ct_id = permission_registry.team_ct_id
    for content_type, primary_keys in child_pks_by_ct.items():
        if content_type.id == team_ct_id and primary_keys:
            from django.db import connection

            provides_table = ObjectRole.provides_teams.through._meta.db_table
            team_id_list = list(primary_keys)
            sql = build_safe_sql(
                connection.vendor,
                "DELETE FROM {I} WHERE {I} IN ({P})",
                [provides_table, 'team_id', len(team_id_list)],
            )
            with connection.cursor() as cursor:
                cursor.execute(sql, team_id_list)
            break

    # Set flag so post_delete signal handler skips RBAC work
    _defer_rbac_cache.skip_post_delete_rbac = True


def _handle_team_delete_signal(instance: Model) -> None:
    """Process RBAC side-effects specific to team deletion.

    Collects indirectly affected roles from ancestor and descendent
    relationships, then either stashes them in the deferred cache or
    recomputes immediately.
    """
    indirectly_affected_roles = set()
    indirectly_affected_roles.update(team_ancestor_roles(instance))
    for team_role in instance.__rbac_stashed_member_roles:
        indirectly_affected_roles.update(team_role.descendent_roles())

    if _defer_rbac_cache.active:
        _defer_rbac_cache.team_ids.update(instance.__rbac_stashed_recompute_team_ids)
        _defer_rbac_cache.object_roles.update(indirectly_affected_roles)
        return

    compute_team_member_roles(team_ids=instance.__rbac_stashed_recompute_team_ids)
    compute_object_role_permissions(object_roles=indirectly_affected_roles)

    # Similar to user deletion, clean up any orphaned object roles
    deleted_count, _ = ObjectRole.objects.filter(users__isnull=True, teams__isnull=True).delete()
    if deleted_count:
        logger.info('Removed %d orphaned object role(s) after team deletion', deleted_count)


def rbac_post_delete_remove_object_roles(instance, *args, **kwargs):
    """
    Call this when deleting an object to cascade delete its object roles
    Deleting a team can have consequences for the rest of the graph
    """
    if _defer_rbac_cache.active and _defer_rbac_cache.skip_post_delete_rbac:
        return

    if instance._meta.model_name == permission_registry.team_model._meta.model_name:
        _handle_team_delete_signal(instance)

    ct = permission_registry.content_type_model.objects.get_for_model(instance)

    ObjectRole.objects.filter(content_type=ct, object_id=instance.pk).delete()

    parent_field_name = permission_registry.get_parent_fd_name(instance)
    if parent_field_name:
        # Delete all evaluations from inherited permissions
        get_evaluation_model(instance).objects.filter(content_type_id=ct.id, object_id=instance.pk).delete()


def rbac_post_init_stash_email(instance, **kwargs):
    """Capture the email at load time so pre_save can detect changes
    without an extra query, following the same pattern as
    rbac_post_init_set_original_parent."""
    if 'email' in instance.__dict__:
        instance._rbac_original_email = instance.email
    else:
        instance._rbac_original_email = _SENTINEL


def rbac_pre_save_enforce_email_policy(instance, **kwargs):
    """Prevent non-privileged users from changing the email field.

    Superusers and org-admins (of ALL the target user's orgs) are
    allowed.  System operations with no request user (management
    commands, migrations, forward-sync) are always allowed.
    """
    from crum import get_current_user

    from ansible_base.rbac.policies import can_change_user

    if instance.pk is None:
        return

    # None when post_init signal was not connected (management commands, migrations, manual construction)
    original = getattr(instance, '_rbac_original_email', None)
    if original is _SENTINEL:
        try:
            original = type(instance).objects.values_list('email', flat=True).get(pk=instance.pk)
        except type(instance).DoesNotExist:
            return
    if original is None or original == instance.email:
        return

    update_fields = kwargs.get('update_fields')
    if update_fields and 'email' not in update_fields:
        return

    requesting_user = get_current_user()
    if requesting_user is None or not getattr(requesting_user, 'is_authenticated', False):
        return

    if not can_change_user(requesting_user, instance, can_self_edit=False):
        from rest_framework.exceptions import ValidationError

        instance.email = original
        raise ValidationError({'email': ["You do not have permission to change the email field."]})


def rbac_post_save_refresh_email_stash(instance, **kwargs):
    """Refresh the email stash after a successful save so subsequent
    saves on the same instance do not false-positive."""
    update_fields = kwargs.get('update_fields')
    if update_fields is not None and 'email' not in update_fields:
        return
    if 'email' in instance.__dict__:
        instance._rbac_original_email = instance.email


def rbac_post_user_delete(instance, *args, **kwargs):
    """
    After you delete a user, all their permissions should be removed as well
    """
    # Any RoleUserAssignment entries will already be cascade deleted
    # Just clean up any object roles that may be orphaned by this deletion
    ObjectRole.objects.filter(users__isnull=True, teams__isnull=True).delete()


def post_migration_rbac_setup(sender, *args, **kwargs):
    if not migrations_are_complete():
        logger.info('Not running DAB RBAC post_migrate logic because of incomplete migration')
        return

    dab_post_migrate.send(sender=sender)

    compute_team_member_roles()
    compute_object_role_permissions()


_DEFAULT_DEFERRED_CONTEXT_PATHS = [
    'django.db.transaction.atomic',
    'ansible_base.rbac.triggers.defer_rbac_cache',
    'awx.main.signals.deferred_activity_stream',
    'ansible_base.activitystream.signals.deferred_activity_stream',
]

_available_deferred_paths = None


def _resolve_import_path(path: str):
    """Resolve a dotted import path to the actual callable.

    Returns None if the module or attribute doesn't exist.
    """
    import importlib

    module_path, attr_name = path.rsplit('.', 1)
    try:
        mod = importlib.import_module(module_path)
        return getattr(mod, attr_name)
    except (ImportError, AttributeError):
        return None


def _get_available_paths() -> list[str]:
    """Return the subset of default paths that are actually importable.

    Cached after first check so we don't re-probe missing modules on
    every delete call.
    """
    global _available_deferred_paths
    if _available_deferred_paths is not None:
        return _available_deferred_paths

    _available_deferred_paths = [p for p in _DEFAULT_DEFERRED_CONTEXT_PATHS if _resolve_import_path(p) is not None]
    return _available_deferred_paths


def _get_deferred_context_managers(instance) -> tuple[list, list]:
    """Return two lists of context manager factories for a model delete.

    Returns ``(global_contexts, instance_contexts)`` where:

    - ``global_contexts`` are auto-discovered defaults from
      ``_DEFAULT_DEFERRED_CONTEXT_PATHS`` — called with no arguments
      (e.g. ``transaction.atomic()``, ``defer_rbac_cache()``).
    - ``instance_contexts`` are model-specific factories from
      ``delete_deferred_context_managers`` on the model class — called
      with the instance being deleted (e.g. ``bulk_delete_teams(org)``).

    Resolves each import path at call time (not cached) so that
    ``unittest.mock.patch`` works correctly in tests.
    """
    global_contexts = []
    for path in _get_available_paths():
        resolved = _resolve_import_path(path)
        if resolved is not None:
            global_contexts.append(resolved)

    instance_contexts = []
    for extra in getattr(instance, 'delete_deferred_context_managers', []):
        if isinstance(extra, str):
            resolved = _resolve_import_path(extra)
            if resolved is not None:
                instance_contexts.append(resolved)
            else:
                logger.debug('Could not import deferred context manager: %s', extra)
        elif callable(extra):
            instance_contexts.append(extra)
        else:
            logger.warning('Invalid delete_deferred_context_managers entry: %r', extra)

    return global_contexts, instance_contexts


def connect_rbac_signals(cls):
    if cls._meta.model_name == permission_registry.team_model._meta.model_name:
        pre_delete.connect(team_pre_delete, sender=cls, dispatch_uid='stash-team-roles-before-delete')

    post_init.connect(rbac_post_init_set_original_parent, sender=cls, dispatch_uid='permission-registry-save-prior-parent')
    pre_save.connect(rbac_pre_save_identify_changes, sender=cls, dispatch_uid='permission-registry-pre-save')
    post_save.connect(rbac_post_save_update_evaluations, sender=cls, dispatch_uid='permission-registry-post-save')
    post_delete.connect(rbac_post_delete_remove_object_roles, sender=cls, dispatch_uid='permission-registry-post-delete')

    # Wrap delete() to nest all deferred context managers around the cascade.
    #
    # ExitStack dynamically composes context managers from two sources:
    #
    # 1. _DEFAULT_DEFERRED_CONTEXT_PATHS — global defaults, called with NO args:
    #       transaction.atomic(), defer_rbac_cache(), deferred_activity_stream()
    #
    # 2. Model.delete_deferred_context_managers — instance-specific, called
    #    WITH the instance being deleted. These let services pre-delete child
    #    models via raw SQL before Django's collector runs.
    #
    # Execution order:
    #   1. Global context managers entered (transaction, defer, activity stream)
    #   2. Instance context managers entered — these run their pre-delete
    #      logic (e.g. raw SQL child deletion) before yielding
    #   3. _bulk_pre_cascade_rbac_cleanup runs (RBAC raw SQL cleanup)
    #   4. original_delete runs (Django collector for remaining rows)
    #
    # ORDER MATTERS for instance context managers: if child model A has a FK
    # to child model B, delete A's context manager first (list A before B).
    # Wrong order is not a correctness problem (DELETE with no matching rows
    # is a no-op) but misses the optimization since B's cascade would have
    # already deleted A's rows via Django's collector.
    #
    # See _DEFAULT_DEFERRED_CONTEXT_PATHS for the global list.
    # Models can add instance-aware context managers via:
    #   delete_deferred_context_managers = ['myapp.signals.bulk_delete_children', ...]
    original_delete = cls.delete

    @functools.wraps(original_delete)
    def deferred_delete(self, *args, **kwargs):
        from contextlib import ExitStack

        global_contexts, instance_contexts = _get_deferred_context_managers(self)

        with ExitStack() as stack:
            for ctx_factory in global_contexts:
                stack.enter_context(ctx_factory())
            for ctx_factory in instance_contexts:
                stack.enter_context(ctx_factory(self))
            _bulk_pre_cascade_rbac_cleanup(self)

            # Final cleanup: ensure no provides_teams entries reference
            # child teams that are about to be cascade-deleted.
            # This catches entries from ObjectRoles outside the delete set
            # (e.g., parent org roles that provide team membership).
            team_model = permission_registry.team_model
            parent_fd = permission_registry.get_parent_fd_name(team_model)
            if parent_fd and isinstance(self, team_model._meta.get_field(parent_fd).related_model):
                child_team_ids = list(team_model.objects.filter(**{parent_fd: self}).values_list('id', flat=True))
                if child_team_ids:
                    from django.db import connection as _conn

                    provides_table = ObjectRole.provides_teams.through._meta.db_table
                    sql = build_safe_sql(
                        _conn.vendor,
                        "DELETE FROM {I} WHERE {I} IN ({P})",
                        [provides_table, 'team_id', len(child_team_ids)],
                    )
                    with _conn.cursor() as cursor:
                        cursor.execute(sql, child_team_ids)

            return original_delete(self, *args, **kwargs)

    cls.delete = deferred_delete
