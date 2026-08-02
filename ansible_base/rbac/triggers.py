import logging
import threading
from contextlib import contextmanager
from typing import Generator, Optional, Union
from uuid import UUID

from django.db import connection
from django.db.models import Model, Q
from django.db.models.signals import m2m_changed, post_delete, post_init, post_save, pre_delete, pre_save
from django.dispatch import Signal

from ansible_base.lib.utils.db import migrations_are_complete
from ansible_base.rbac.caching import (
    cleanup_deleted_object_roles,
    cleanup_deleted_team_roles,
    compute_object_role_permissions,
    compute_team_member_roles,
    object_roles_for_parents,
)
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


def team_ancestor_roles(team: Model) -> set['ObjectRole']:
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


def _recompute_team_ids_for_assignment(
    object_role: 'ObjectRole',
    created: bool,
    deleted: bool,
    has_team_perm: bool,
    changes_team_owners: bool,
) -> Optional[set[int]]:
    """Determine which team IDs need provides_teams recomputation after an assignment change."""
    if not (has_team_perm and (created or deleted or changes_team_owners)):
        return None
    if created:
        # provides_teams not yet computed for new ObjectRoles
        return _team_ids_from_role_target(object_role)
    # For existing roles, provides_teams already captures which
    # teams this role grants membership to
    return set(object_role.provides_teams.values_list('id', flat=True))


def needed_updates_on_assignment(
    role_definition: 'RoleDefinition',
    actor: Model,
    object_role: 'ObjectRole',
    created: bool = False,
    giving: bool = True,
) -> tuple[Optional[set[int]], set['ObjectRole']]:
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
    role_has_no_actors = not giving and not (object_role.users.exists() or object_role.teams.exists())
    if role_has_no_actors:
        # time to delete the object role because it is unused
        to_update.discard(object_role)
        deleted = True

    # giving or revoking team permissions may not change the parentage
    # but this will still change what downstream roles grant what permissions
    if (has_team_perm and created) or (giving and changes_team_owners):
        to_update.update(object_role.descendent_roles())

    # actions which can change the team parentage structure
    recompute_team_ids = _recompute_team_ids_for_assignment(object_role, created, deleted, has_team_perm, changes_team_owners)

    return (recompute_team_ids, to_update)


class _DeferRBACComputations(threading.local):
    def __init__(self):
        self.active = False
        self.deleted_team_pks: set[int] = set()
        self.deleted_object_pks: list[tuple[int, Union[int, UUID]]] = []
        self.created_instances: list[tuple[Model, int, int]] = []

    @property
    def has_deferred_data(self):
        return bool(self.deleted_team_pks or self.deleted_object_pks or self.created_instances)


_defer_rbac = _DeferRBACComputations()


def _reset_and_flush_deferred_rbac(suppress_flush_errors: bool = False) -> None:
    """Reset deferred RBAC state and flush pending computations.

    Args:
        suppress_flush_errors: If True, log but do not raise flush errors
            (used during exception handling to avoid masking the original error).
    """
    deleted_team_pks = _defer_rbac.deleted_team_pks
    deleted_object_pks = _defer_rbac.deleted_object_pks
    created_instances = _defer_rbac.created_instances
    _defer_rbac.active = False
    _defer_rbac.deleted_team_pks = set()
    _defer_rbac.deleted_object_pks = []
    _defer_rbac.created_instances = []

    if not (deleted_team_pks or deleted_object_pks or created_instances):
        return

    if suppress_flush_errors and connection.in_atomic_block and connection.needs_rollback:
        logger.debug("Skipping RBAC flush — transaction is marked for rollback")
        return

    if suppress_flush_errors:
        try:
            _flush_rbac(deleted_team_pks, deleted_object_pks, created_instances)
        except Exception:
            logger.exception("Failed to flush RBAC computations during exception handling")
    else:
        _flush_rbac(deleted_team_pks, deleted_object_pks, created_instances)


@contextmanager
def defer_rbac_computations() -> Generator[None, None, None]:
    """Defer RBAC signal-driven recomputation during bulk resource operations.

    This is ONLY for creating or deleting non-RBAC resources (e.g. Inventory,
    Team, Organization). It defers the RBAC signal handlers that normally fire
    on every save/delete, then flushes all recomputation in a single pass on
    exit.

    While deferred data is pending, the following will raise RuntimeError:
    - give_permission / remove_permission (use RoleDefinition.bulk_give_permissions
      or bulk_remove_permissions OUTSIDE this context manager instead)
    - has_obj_perm (evaluations are stale until the flush)

    These calls are allowed before any resources are created or deleted inside
    the context manager, so DRF permission checks that run before the view
    action will work normally.

    Cannot be nested. For permission assignment, use
    RoleDefinition.bulk_give_permissions / bulk_remove_permissions separately.

    Limitation: the deferred flush does not recompute descendant roles from
    member_team permissions. This is correct when the objects granting
    member_team cascade-delete with the parent (the normal case), but would
    leave stale evaluations if member_team targets survive the deletion.
    """
    if _defer_rbac.active:
        raise RuntimeError("defer_rbac_computations cannot be nested")
    _defer_rbac.active = True
    try:
        yield
    except BaseException:
        _reset_and_flush_deferred_rbac(suppress_flush_errors=True)
        raise
    else:
        _reset_and_flush_deferred_rbac(suppress_flush_errors=False)


def _process_created_instances(created_instances) -> tuple[set[tuple], set[int]]:
    """Extract parent GFKs and team IDs from deferred created instances."""
    all_parent_gfks: set[tuple] = set()
    team_ids: set[int] = set()
    for instance, _, _ in created_instances:
        parent_gfks = get_parent_ids(instance)
        if parent_gfks:
            all_parent_gfks.update(parent_gfks)
        if instance._meta.model_name == permission_registry.team_model._meta.model_name:
            team_ids.add(instance.id)
    return all_parent_gfks, team_ids


def _flush_rbac(deleted_team_pks, deleted_object_pks, created_instances):
    object_roles: set[ObjectRole] = set()

    if deleted_team_pks:
        ancestor_roles, deleted_or_ids = cleanup_deleted_team_roles(deleted_team_pks)
        object_roles.update(r for r in ancestor_roles if r.pk not in deleted_or_ids)

    if deleted_object_pks:
        deleted_or_ids = cleanup_deleted_object_roles(deleted_object_pks)
        object_roles = {r for r in object_roles if r.pk not in deleted_or_ids}

    team_ids: set[int] = set()
    if created_instances:
        all_parent_gfks, team_ids = _process_created_instances(created_instances)
        if all_parent_gfks:
            object_roles.update(object_roles_for_parents(all_parent_gfks))

    if deleted_team_pks:
        team_ids.update(deleted_team_pks)

    if team_ids:
        compute_team_member_roles(team_ids=team_ids)

    if object_roles:
        compute_object_role_permissions(object_roles=object_roles)

    ObjectRole.objects.filter(users__isnull=True, teams__isnull=True).delete()


def update_after_assignment(recompute_team_ids: Optional[set[int]], to_update: Optional[set['ObjectRole']]) -> None:
    "Call this with the output of needed_updates_on_assignment"
    if recompute_team_ids is not None:
        compute_team_member_roles(team_ids=recompute_team_ids)

    compute_object_role_permissions(object_roles=to_update)


def _handle_permission_add_or_remove(to_recompute: set['ObjectRole'], pk_set: set, action: str) -> None:
    """Handle post_add / post_remove m2m signal for RoleDefinition permissions."""
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


def _handle_permission_clear(to_recompute: set['ObjectRole']) -> None:
    """Handle post_clear m2m signal for RoleDefinition permissions."""
    # unfortunately this does not give us a list of permissions to work with
    # provides_teams captures teams if member_team was among the cleared permissions;
    # content-type derivation covers the case where it wasn't yet computed
    team_ids = set()
    for object_role in to_recompute:
        team_ids.update(object_role.provides_teams.values_list('id', flat=True))
        team_ids.update(_team_ids_from_role_target(object_role))
    compute_team_member_roles(team_ids=team_ids)


def permissions_changed(instance: 'RoleDefinition', action: str, model: type, pk_set: Optional[set], reverse: bool, **kwargs) -> None:
    """Recompute object role permissions when a RoleDefinition's permissions m2m changes."""
    if action.startswith('pre_'):
        return
    to_recompute = set(ObjectRole.objects.filter(role_definition=instance).prefetch_related('teams__member_roles'))
    if not to_recompute:
        return
    if reverse:
        raise RuntimeError('Removal of permssions through reverse relationship not supported')

    if action in ('post_add', 'post_remove'):
        _handle_permission_add_or_remove(to_recompute, pk_set, action)
    elif action == 'post_clear':
        _handle_permission_clear(to_recompute)
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
        if _defer_rbac.active:
            _defer_rbac.created_instances.append((instance, instance.pk, obj_ct_id))
            return
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


def team_pre_delete(instance: Model, *args, **kwargs) -> None:
    if _defer_rbac.active:
        return
    instance.__rbac_stashed_member_roles = list(instance.member_roles.all())
    stashed_team_ids = set()
    for object_role in ObjectRole.objects.filter(teams=instance, role_definition__permissions__codename=permission_registry.team_permission):
        stashed_team_ids.update(object_role.provides_teams.values_list('id', flat=True))
    stashed_team_ids.discard(instance.id)
    instance.__rbac_stashed_recompute_team_ids = stashed_team_ids


def rbac_post_delete_remove_object_roles(instance: Model, *args, **kwargs) -> None:
    """
    Call this when deleting an object to cascade delete its object roles
    Deleting a team can have consequences for the rest of the graph
    """
    if instance._meta.model_name == permission_registry.team_model._meta.model_name:
        if _defer_rbac.active:
            _defer_rbac.deleted_team_pks.add(instance.pk)
            return
        indirectly_affected_roles = set()
        indirectly_affected_roles.update(team_ancestor_roles(instance))
        for team_role in instance.__rbac_stashed_member_roles:
            indirectly_affected_roles.update(team_role.descendent_roles())
        compute_team_member_roles(team_ids=instance.__rbac_stashed_recompute_team_ids)
        compute_object_role_permissions(object_roles=indirectly_affected_roles)
        ObjectRole.objects.filter(users__isnull=True, teams__isnull=True).delete()

    if _defer_rbac.active:
        ct_id = permission_registry.content_type_model.objects.get_for_model(instance).pk
        _defer_rbac.deleted_object_pks.append((ct_id, instance.pk))
        return

    ct = permission_registry.content_type_model.objects.get_for_model(instance)
    deleted_count, _ = ObjectRole.objects.filter(content_type=ct, object_id=instance.pk).delete()

    parent_field_name = permission_registry.get_parent_fd_name(instance)
    if parent_field_name:
        get_evaluation_model(instance).objects.filter(content_type_id=ct.id, object_id=instance.pk).delete()

    if deleted_count:
        try:
            from ansible_base.rbac.sync import maybe_reverse_sync_object_deletion

            maybe_reverse_sync_object_deletion(instance)
        except Exception:
            logger.exception(f"Failed to sync object deletion for {instance}")


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

    plan = kwargs.get('plan', None)
    if plan is not None and len(plan) == 0:
        logger.info('Skipping RBAC recompute — no migrations were applied')
        return

    compute_team_member_roles()
    compute_object_role_permissions()


def connect_rbac_signals(cls):
    if cls._meta.model_name == permission_registry.team_model._meta.model_name:
        pre_delete.connect(team_pre_delete, sender=cls, dispatch_uid='stash-team-roles-before-delete')

    post_init.connect(rbac_post_init_set_original_parent, sender=cls, dispatch_uid='permission-registry-save-prior-parent')
    pre_save.connect(rbac_pre_save_identify_changes, sender=cls, dispatch_uid='permission-registry-pre-save')
    post_save.connect(rbac_post_save_update_evaluations, sender=cls, dispatch_uid='permission-registry-post-save')
    post_delete.connect(rbac_post_delete_remove_object_roles, sender=cls, dispatch_uid='permission-registry-post-delete')
