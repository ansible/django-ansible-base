import logging
import threading
from contextlib import contextmanager
from typing import Union
from uuid import UUID

from django.db.models import Model, Q
from django.db.models.signals import m2m_changed, post_delete, post_init, post_save, pre_delete, pre_save
from django.dispatch import Signal

from ansible_base.lib.utils.db import migrations_are_complete
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


_defer_rbac_cache = _DeferRBACCache()


# allows deferring the rbac computation in cases where many object roles are updated in short order
@contextmanager
def defer_rbac_cache():
    if _defer_rbac_cache.active:
        raise RuntimeError("defer_rbac_cache cannot be nested")
    _defer_rbac_cache.active = True
    try:
        yield
    finally:
        team_ids = _defer_rbac_cache.team_ids
        object_roles = _defer_rbac_cache.object_roles
        _defer_rbac_cache.active = False
        _defer_rbac_cache.team_ids = set()
        _defer_rbac_cache.object_roles = set()

        if team_ids:
            compute_team_member_roles(team_ids=team_ids)

        if object_roles:
            compute_object_role_permissions(object_roles=object_roles)


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


def rbac_post_delete_remove_object_roles(instance, *args, **kwargs):
    """
    Call this when deleting an object to cascade delete its object roles
    Deleting a team can have consequences for the rest of the graph
    """
    if instance._meta.model_name == permission_registry.team_model._meta.model_name:
        indirectly_affected_roles = set()
        indirectly_affected_roles.update(team_ancestor_roles(instance))
        for team_role in instance.__rbac_stashed_member_roles:
            indirectly_affected_roles.update(team_role.descendent_roles())
        compute_team_member_roles(team_ids=instance.__rbac_stashed_recompute_team_ids)
        compute_object_role_permissions(object_roles=indirectly_affected_roles)

        # Similar to user deletion, clean up any orphaned object roles
        ObjectRole.objects.filter(users__isnull=True, teams__isnull=True).delete()
        deleted_count, _ = ObjectRole.objects.filter(users__isnull=True, teams__isnull=True).delete()
        if deleted_count:
            had_object_assignments = True

    ct = permission_registry.content_type_model.objects.get_for_model(instance)

    # Use bulk delete return value to determine if object-level assignments existed
    # This avoids the inefficient .exists() query and works correctly for team deletion cases
    deleted_count, _ = ObjectRole.objects.filter(content_type=ct, object_id=instance.pk).delete()
    had_object_assignments = deleted_count > 0

    parent_field_name = permission_registry.get_parent_fd_name(instance)
    if parent_field_name:
        # Delete all evaluations from inherited permissions
        get_evaluation_model(instance).objects.filter(content_type_id=ct.id, object_id=instance.pk).delete()

    # Only sync when object-level assignments existed - this is the key performance optimization
    if had_object_assignments:
        try:
            from ansible_base.rbac.sync import maybe_reverse_sync_object_deletion

            maybe_reverse_sync_object_deletion(instance)
        except Exception:
            # Continue with local deletion even if cross-service sync fails
            # This ensures we don't break local operations due to network/auth issues
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

    compute_team_member_roles()
    compute_object_role_permissions()


def connect_rbac_signals(cls):
    if cls._meta.model_name == permission_registry.team_model._meta.model_name:
        pre_delete.connect(team_pre_delete, sender=cls, dispatch_uid='stash-team-roles-before-delete')

    post_init.connect(rbac_post_init_set_original_parent, sender=cls, dispatch_uid='permission-registry-save-prior-parent')
    pre_save.connect(rbac_pre_save_identify_changes, sender=cls, dispatch_uid='permission-registry-pre-save')
    post_save.connect(rbac_post_save_update_evaluations, sender=cls, dispatch_uid='permission-registry-post-save')
    post_delete.connect(rbac_post_delete_remove_object_roles, sender=cls, dispatch_uid='permission-registry-post-delete')
