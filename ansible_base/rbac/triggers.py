import logging
from contextlib import contextmanager
from typing import Optional, Union
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


def needed_updates_on_assignment(role_definition, actor, object_role, created=False, giving=True):
    """
    If a user or a team is granted a role or has a role revoked,
    then this returns instructions for what needs to be updated
    returns tuple
        (bool: should update team owners, set: object roles to update)
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
        if object_role in to_update:
            to_update.remove(object_role)
        deleted = True

    # giving or revoking team permissions may not change the parentage
    # but this will still change what downstream roles grant what permissions
    if (has_team_perm and created) or (giving and changes_team_owners):
        to_update.update(object_role.descendent_roles())

    # actions which can change the team parentage structure
    recompute_teams = bool(has_team_perm and (created or deleted or changes_team_owners))

    return (recompute_teams, to_update)


def update_after_assignment(update_teams, to_update):
    "Call this with the output of needed_updates_on_assignment"
    if update_teams:
        compute_team_member_roles()

    compute_object_role_permissions(object_roles=to_update)


def permissions_changed(instance, action, model, pk_set, reverse, **kwargs):
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
            compute_team_member_roles()
        # All team member roles that give this permission through this role need to be updated
        for role in to_recompute.copy():
            for team in role.teams.all():
                for team_role in team.member_roles.all():
                    to_recompute.add(team_role)
    elif action == 'post_clear':
        # unfortunately this does not give us a list of permissions to work with
        # this is slow, not ideal, but will at least be correct
        compute_team_member_roles()
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


def post_save_update_obj_permissions(instance):
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
        compute_team_member_roles()

    if to_update:
        compute_object_role_permissions(object_roles=to_update)


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
        post_save_update_obj_permissions(instance)
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
        compute_team_member_roles()
        compute_object_role_permissions(object_roles=indirectly_affected_roles)

        # Similar to user deletion, clean up any orphaned object roles
        ObjectRole.objects.filter(users__isnull=True, teams__isnull=True).delete()

    ct = permission_registry.content_type_model.objects.get_for_model(instance)
    ObjectRole.objects.filter(content_type=ct, object_id=instance.pk).delete()

    parent_field_name = permission_registry.get_parent_fd_name(instance)
    if parent_field_name:
        # Delete all evaluations from inherited permissions
        get_evaluation_model(instance).objects.filter(content_type_id=ct.id, object_id=instance.pk).delete()


def rbac_post_user_delete(instance, *args, **kwargs):
    """
    After you delete a user, all their permissions should be removed as well
    """
    # Any RoleUserAssignment entries will already be cascade deleted
    # Just clean up any object roles that may be orphaned by this deletion
    ObjectRole.objects.filter(users__isnull=True, teams__isnull=True).delete()


def post_migration_rbac_setup(sender, *args, **kwargs):
    if not migrations_are_complete():
        logger.info('Not running DAB RBAC post_migrate logic because of suspected reverse migration')
        return

    dab_post_migrate.send(sender=sender)

    compute_team_member_roles()
    compute_object_role_permissions()


class TrackedRelationship:
    def __init__(self, cls, role_name):
        self.cls = cls
        self.role_name = role_name
        self.user_relationship = None
        self.team_relationship = None
        self._active_sync_flag = False

    def initialize(self, relationship):
        manager = getattr(self.cls, relationship)
        related_model_name = manager.field.related_model._meta.model_name
        if related_model_name == permission_registry.team_model._meta.model_name:
            self.team_relationship = relationship
            m2m_changed.connect(self.sync_team_to_role, sender=manager.through)
        elif related_model_name == permission_registry.user_model._meta.model_name:
            self.user_relationship = relationship
            m2m_changed.connect(self.sync_user_to_role, sender=manager.through)
        else:
            raise RuntimeError(f'Can only register user or team relationships, obtained {related_model_name}')

    @contextmanager
    def sync_active(self):
        try:
            self._active_sync_flag = True
            yield
        finally:
            self._active_sync_flag = False

    def sync_relationship(self, actor, content_object, giving=True):
        # Exit if role does not apply for the intended model type, for example
        # if user is given "team-member" role to organization, do not add user to the team members
        if content_object._meta.model_name != self.cls._meta.model_name:
            return

        if actor._meta.model_name == permission_registry.team_model._meta.model_name:
            if self.team_relationship is None:
                return
            manager = getattr(content_object, self.team_relationship)
        elif actor._meta.model_name == permission_registry.user_model._meta.model_name:
            if self.user_relationship is None:
                return
            manager = getattr(content_object, self.user_relationship)

        if giving:
            manager.add(actor)
        else:
            manager.remove(actor)

    def _sync_actor_to_role(self, actor_model: type, instance: Model, action: str, pk_set: Optional[set[int]]):
        if self._active_sync_flag:
            return
        if action.startswith('pre_'):
            return
        rd = RoleDefinition.objects.get(name=self.role_name)

        if action in ('post_add', 'post_remove'):
            actor_set = pk_set
        elif action == 'post_clear':
            ct = permission_registry.content_type_model.objects.get_for_model(instance)
            role = ObjectRole.objects.get(object_id=instance.pk, content_type=ct, role_definition=rd)
            if actor_model._meta.model_name == 'team':
                actor_set = set(role.teams.values_list('id', flat=True))
            else:
                actor_set = set(role.users.values_list('id', flat=True))

        giving = bool(action == 'post_add')
        for actor in actor_model.objects.filter(pk__in=actor_set):
            rd.give_or_remove_permission(actor, instance, giving=giving, sync_action=True)

    def sync_team_to_role(self, instance: Model, action: str, model: type, pk_set: Optional[set[int]], reverse: bool, **kwargs):
        if not reverse:
            self._sync_actor_to_role(permission_registry.team_model, instance, action, pk_set)
        else:
            for pk in pk_set:
                self._sync_actor_to_role(permission_registry.team_model, model(pk=pk), action, {instance.pk})

    def sync_user_to_role(self, instance: Model, action: str, model: type, pk_set: Optional[set[int]], reverse: bool, **kwargs):
        if not reverse:
            self._sync_actor_to_role(permission_registry.user_model, instance, action, pk_set)
        else:
            for pk in pk_set:
                self._sync_actor_to_role(permission_registry.user_model, model(pk=pk), action, {instance.pk})


def connect_rbac_signals(cls):
    if cls._meta.model_name == permission_registry.team_model._meta.model_name:
        pre_delete.connect(team_pre_delete, sender=cls, dispatch_uid='stash-team-roles-before-delete')

    post_init.connect(rbac_post_init_set_original_parent, sender=cls, dispatch_uid='permission-registry-save-prior-parent')
    pre_save.connect(rbac_pre_save_identify_changes, sender=cls, dispatch_uid='permission-registry-pre-save')
    post_save.connect(rbac_post_save_update_evaluations, sender=cls, dispatch_uid='permission-registry-post-save')
    post_delete.connect(rbac_post_delete_remove_object_roles, sender=cls, dispatch_uid='permission-registry-post-delete')
