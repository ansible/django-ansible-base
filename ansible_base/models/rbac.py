import logging

# Django
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

# ansible_base RBAC logic imports
from ansible_base.rbac.permission_registry import permission_registry
from ansible_base.rbac.prefetch import TypesPrefetch

logger = logging.getLogger('ansible_base.models.rbac')


class RoleDefinitionManager(models.Manager):
    def give_creator_permissions(self, user, obj):
        needed_actions = settings.ROLE_CREATOR_DEFAULTS

        needed_perms = set()
        for perm in permission_registry.permission_model.objects.filter(content_type=ContentType.objects.get_for_model(obj)):
            action = perm.codename.split('_', 1)[0]
            if action in needed_actions:
                needed_perms.add(perm.codename)

        has_permissions = RoleEvaluation.get_permissions(user, obj)
        if set(needed_perms) - set(has_permissions):
            rd, _ = self.get_or_create(permissions=needed_perms, name=f'{obj._meta.model_name}-creator-permission')

            rd.give_permission(user, obj)

    def get_or_create(self, permissions=(), **kwargs):
        "Add extra feature on top of existing get_or_create to use permissions list"
        if permissions:
            permissions = set(permissions)
            for existing_rd in self.prefetch_related('permissions'):
                existing_set = set(perm.codename for perm in existing_rd.permissions.all())
                if existing_set == permissions:
                    return (existing_rd, False)
            return (self.create_from_permissions(permissions=permissions, **kwargs), True)
        return super().get_or_create(**kwargs)

    def create_from_permissions(self, permissions=(), **kwargs):
        "Create from a list of text-type permissions and do validation"
        perm_list = [permission_registry.permission_model.objects.get(codename=str_perm) for str_perm in permissions]
        permissions_by_model = {}
        for perm in perm_list:
            cls = perm.content_type.model_class()
            if perm.codename.startswith('add_'):
                to_model = permission_registry.get_parent_model(cls)
            else:
                to_model = cls
            permissions_by_model.setdefault(to_model, [])
            permissions_by_model[to_model].append(perm)

        # check that all provided permissions are for registered models
        unregistered_models = set(permissions_by_model.keys()) - set(permission_registry.all_registered_models)
        if unregistered_models:
            display_models = ', '.join(str(cls._meta.verbose_name) for cls in unregistered_models)
            raise ValidationError(f'Permissions for unregistered models were given: {display_models}')

        # check that view permission is given for every model that has any permission listed
        for cls, model_perm_list in permissions_by_model.items():
            for perm in model_perm_list:
                if 'view' in perm.codename:
                    break
            else:
                display_perms = ', '.join([perm.codename for perm in model_perm_list])
                raise ValidationError(f'Permissions for model {cls._meta.verbose_name} needs to include view, got: {display_perms}')

        rd = self.create(**kwargs)
        rd.permissions.add(*perm_list)
        return rd


class RoleDefinition(models.Model):
    "Abstract definition of the permissions a role will grant before it is associated to an object"

    class Meta:
        app_label = 'ansible_base'
        verbose_name_plural = _('role_definition')

    name = models.TextField(db_index=True, unique=True)
    description = models.TextField(null=True)
    managed = models.BooleanField(default=False)  # pulp definition of Role uses locked
    permissions = models.ManyToManyField(settings.ROLE_PERMISSION_MODEL)
    objects = RoleDefinitionManager()

    def __str__(self):
        managed_str = ''
        if self.managed:
            managed_str = ', managed=True'
        return f'RoleDefinition(pk={self.id}, name={self.name}{managed_str})'

    def give_global_permission(self, actor):
        return self.give_or_remove_global_permission(actor, giving=True)

    def remove_global_permission(self, actor):
        return self.give_or_remove_global_permission(actor, giving=False)

    def give_or_remove_global_permission(self, actor, giving=True):
        if actor._meta.model_name == 'user':
            rel = settings.ROLE_SINGLETON_USER_RELATIONSHIP
            if not rel:
                raise RuntimeError('No global role relationship configured for users')
        elif isinstance(actor, permission_registry.team_model):
            rel = settings.ROLE_SINGLETON_TEAM_RELATIONSHIP
            if not rel:
                raise RuntimeError('No global role relationship configured for users')
        else:
            raise RuntimeError(f'Cannot give permission to {actor}, must be a user or team')

        manager = getattr(actor, rel)
        if giving:
            manager.add(self)
        else:
            manager.remove(self)

        # Clear any cached permissions, if applicable
        if hasattr(actor, '_singleton_permissions'):
            delattr(actor, '_singleton_permissions')

    def give_permission(self, actor, content_object):
        return self.give_or_remove_permission(actor, content_object, giving=True)

    def remove_permission(self, actor, content_object):
        return self.give_or_remove_permission(actor, content_object, giving=False)

    def give_or_remove_permission(self, actor, content_object, giving=True, sync_action=False):
        "Shortcut method to do whatever needed to give user or team these permissions"
        obj_ct = ContentType.objects.get_for_model(content_object)
        kwargs = dict(role_definition=self, content_type=obj_ct, object_id=content_object.id)

        created = False
        object_role = ObjectRole.objects.filter(**kwargs).first()
        if object_role is None:
            if not giving:
                return  # nothing to do
            object_role = ObjectRole.objects.create(**kwargs)
            created = True

        from ansible_base.rbac.triggers import needed_updates_on_assignment, update_after_assignment

        update_teams, to_update = needed_updates_on_assignment(self, actor, object_role, created=created, giving=True)

        if actor._meta.model_name == 'user':
            if giving:
                object_role.users.add(actor)
            else:
                object_role.users.remove(actor)
        elif isinstance(actor, permission_registry.team_model):
            if giving:
                object_role.teams.add(actor)
            else:
                object_role.teams.remove(actor)
        else:
            raise RuntimeError(f'Cannot give permission to {actor}, must be a user or team')

        if (not giving) and (not (object_role.users.exists() or object_role.teams.exists())):
            if object_role in to_update:
                to_update.remove(object_role)
            object_role.delete()

        update_after_assignment(update_teams, to_update)

        if not sync_action and self.name in permission_registry._trackers:
            tracker = permission_registry._trackers[self.name]
            with tracker.sync_active():
                tracker.sync_relationship(actor, content_object, giving=giving)

        return object_role


class ObjectRole(models.Model):
    """
    This is the successor to the Role model in the old AWX RBAC system
    It is renamed to ObjectRole to distinguish from the abstract or generic
    RoleDefinition which does not apply to a particular object.

    This matches the RoleDefinition to a content_object.
    After this is created, users and teams can be added to gives those
    permissions to that user or team, for that content_object
    """

    class Meta:
        app_label = 'ansible_base'
        verbose_name_plural = _('object_roles')
        indexes = [models.Index(fields=["content_type", "object_id"])]
        ordering = ("content_type", "object_id")
        constraints = [models.UniqueConstraint(name='one_object_role_per_object_and_role', fields=['object_id', 'content_type', 'role_definition'])]

    role_definition = models.ForeignKey(
        RoleDefinition,
        on_delete=models.CASCADE,
        help_text=_("The role definition which defines what permissions this object role grants"),
    )

    users = models.ManyToManyField(
        settings.AUTH_USER_MODEL, related_name='has_roles', help_text=_("Users who have access to the permissions defined by this object role")
    )
    teams = models.ManyToManyField(
        settings.ROLE_TEAM_MODEL, related_name='has_roles', help_text=_("Teams or groups who have access to the permissions defined by this object role")
    )
    # COMPUTED DATA
    provides_teams = models.ManyToManyField(
        settings.ROLE_TEAM_MODEL,
        related_name='member_roles',
        help_text=_("Users who have this role obtain member access to these teams, and inherit all their permissions"),
    )

    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    # help_text=_("Either the object this grants permissions to, or the parent object this will give permissions to sub-objects for")
    content_object = GenericForeignKey('content_type', 'object_id')

    def __str__(self):
        return f'ObjectRole(pk={self.id}, {self.content_type.model}={self.object_id})'

    def save(self, *args, **kwargs):
        if self.id:
            raise RuntimeError('ObjectRole model is immutable, use RoleDefinition.give_permission method')
        return super().save(*args, **kwargs)

    @classmethod
    def visible_roles(cls, user):
        "Return a querset of object roles that this user should be allowed to view"
        return cls.objects.filter(permission_partials__role__in=user.has_roles.all()).distinct()

    def descendent_roles(self):
        "Returns a set of roles that you implicitly have if you have this role"
        descendents = set()
        for target_team in self.provides_teams.all():
            # the roles that offer these permissions could change as a result of adding teams
            descendents.update(set(target_team.has_roles.all()))
        return descendents

    def expected_direct_permissions(self, types_prefetch=None):
        expected_evaluations = set()
        cached_id_lists = {}
        if not types_prefetch:
            types_prefetch = TypesPrefetch()
        role_content_type = types_prefetch.get_content_type(self.content_type_id)
        for permission in types_prefetch.permissions_for_object_role(self):
            permission_content_type = types_prefetch.get_content_type(permission.content_type_id)

            if permission.content_type_id == self.content_type_id:
                expected_evaluations.add((permission.codename, self.content_type_id, self.object_id))
            elif permission.codename.startswith('add'):
                role_child_models = set(cls for filter_path, cls in permission_registry.get_child_models(role_content_type.model))
                if permission_content_type.model_class() not in role_child_models:
                    # NOTE: this should also be validated when creating a role definition
                    logger.warning(f'{self} lists {permission.codename} for an object that is not a child object')
                    continue
                expected_evaluations.add((permission.codename, self.content_type_id, self.object_id))
            else:
                id_list = []
                # fetching child objects of an organization is very performance sensitive
                # for multiple permissions of same type, make sure to only do query once
                if permission.content_type_id in cached_id_lists:
                    id_list = cached_id_lists[permission.content_type_id]
                else:
                    # model must be in same app as organization
                    for filter_path, model in permission_registry.get_child_models(role_content_type.model):
                        if model._meta.model_name == permission_content_type.model:
                            id_list = model.objects.filter(**{filter_path: self.object_id}).values_list('id', flat=True)
                            cached_id_lists[permission.content_type_id] = list(id_list)
                            break
                    else:
                        logger.warning(f'{self.role_definition} listed {permission.codename} but model is not a child, ignoring')
                        continue

                for id in id_list:
                    expected_evaluations.add((permission.codename, permission.content_type_id, id))
        return expected_evaluations

    def needed_cache_updates(self, types_prefetch=None):
        existing_partials = dict()
        for permission_partial in self.permission_partials.all():
            existing_partials[permission_partial.obj_perm_id()] = permission_partial

        expected_evaluations = self.expected_direct_permissions(types_prefetch)

        for team in self.provides_teams.all():
            for team_role in team.has_roles.all():
                expected_evaluations.update(team_role.expected_direct_permissions(types_prefetch))

        existing_set = set(existing_partials.keys())

        to_delete = set()
        for identifier in existing_set - expected_evaluations:
            to_delete.add(existing_partials[identifier].id)

        to_add = []
        for codename, ct_id, obj_id in expected_evaluations - existing_set:
            to_add.append(RoleEvaluation(codename=codename, content_type_id=ct_id, object_id=obj_id, role=self))

        return (to_delete, to_add)


# COMPUTED DATA
class RoleEvaluation(models.Model):
    """
    Cached data that shows what permissions an ObjectRole gives its owners
    example:
        ObjectRole 423 gives users execute access to job template 37

    RoleAncestorEntry model in old AWX RBAC system is a direct analog

    This is used to make permission evaluations via querysets returning object ids
    the data in this table is created from the ObjectRole and RoleDefinition data
      you should not interact with this table yourself
      the only method that should ever write to this table is
        compute_object_role_permissions()

    In the above example, "ObjectRole 423" may be a role that grants membership
    to a team, and that team was given permission to another ObjectRole.
    """

    class Meta:
        app_label = 'ansible_base'
        verbose_name_plural = _('role_object_permissions')
        indexes = [
            models.Index(fields=["role", "content_type_id", "object_id"]),  # used by get_roles_on_resource
            models.Index(fields=["role", "content_type_id", "codename"]),  # used by accessible_objects
        ]
        constraints = [models.UniqueConstraint(name='one_entry_per_object_permission_and_role', fields=['object_id', 'content_type_id', 'codename', 'role'])]

    def __str__(self):
        return f'RoleEvaluation(pk={self.id}, codename={self.codename}, object_id={self.object_id}, content_type_id={self.content_type_id}, role_id={self.role_id})'

    def save(self, *args, **kwargs):
        if self.id:
            raise RuntimeError('RoleEvaluation model is immutable and only used internally')
        return super().save(*args, **kwargs)

    role = models.ForeignKey(
        ObjectRole, null=False, on_delete=models.CASCADE, related_name='permission_partials', help_text=_("The object role that grants this form of permission")
    )
    codename = models.TextField(null=False, help_text=_("The name of the permission, giving the action and the model, from the Django Permission model"))
    # NOTE: we awkwardly do not form these into a content_object, following from AWX practice
    # this can be relaxed as we have comparative performance testing to confirm doing so does not affect permissions
    content_type_id = models.PositiveIntegerField(null=False)
    object_id = models.PositiveIntegerField(null=False)

    def obj_perm_id(self):
        "Used for in-memory hashing of the type of object permission this represents"
        return (self.codename, self.content_type_id, self.object_id)

    @staticmethod
    def accessible_ids(cls, actor, codename, content_types=None):
        """
        Corresponds to AWX accessible_pk_qs

        Use instead of `MyModel.objects` when you want to only consider
        resources that a user has specific permissions for. For example:
        MyModel.accessible_objects(user, 'view_mymodel').filter(name__istartswith='bar')

        Intended to be used for users, but should also be valid for teams
        """
        # We only have a content_types exception for multiple content types for polymorphic models
        # for normal models you should not need it, but AWX unified_ models need it to get by
        filter_kwargs = dict(role__in=actor.has_roles.all(), codename=codename)
        if content_types:
            filter_kwargs['content_type_id__in'] = content_types
        else:
            filter_kwargs['content_type_id'] = ContentType.objects.get_for_model(cls).id
        return RoleEvaluation.objects.filter(**filter_kwargs).values_list('object_id').distinct()

    @staticmethod
    def accessible_objects(cls, user, codename):
        return cls.objects.filter(pk__in=RoleEvaluation.accessible_ids(cls, user, codename))

    @staticmethod
    def get_permissions(user, obj):
        return RoleEvaluation.objects.filter(
            role__in=user.has_roles.all(), content_type_id=ContentType.objects.get_for_model(obj).id, object_id=obj.id
        ).values_list('codename', flat=True)

    @staticmethod
    def has_obj_perm(user, obj, codename):
        """
        Note this behaves similar in function to the REST Framework has_object_permission
        method on permission classes, but it is named differently to avoid unintentionally conflicting
        """
        return RoleEvaluation.objects.filter(
            role__in=user.has_roles.all(), content_type_id=ContentType.objects.get_for_model(obj).id, object_id=obj.id, codename=codename
        ).exists()
