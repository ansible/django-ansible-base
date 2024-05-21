import logging
from collections.abc import Iterable
from typing import Optional, Type

# Django
from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import connection, models, transaction
from django.db.models.functions import Cast
from django.db.models.query import QuerySet
from django.db.utils import IntegrityError
from django.utils.translation import gettext_lazy as _

# Django-rest-framework
from rest_framework.exceptions import ValidationError

# ansible_base lib functions
from ansible_base.lib.abstract_models.common import CommonModel, ImmutableCommonModel

# ansible_base RBAC logic imports
from ansible_base.lib.utils.models import is_add_perm
from ansible_base.rbac.permission_registry import permission_registry
from ansible_base.rbac.prefetch import TypesPrefetch
from ansible_base.rbac.validators import validate_assignment, validate_permissions_for_model

logger = logging.getLogger('ansible_base.rbac.models')


class DABPermission(models.Model):
    "This is a minimal copy of auth.Permission for internal use"

    name = models.CharField("name", max_length=255)
    content_type = models.ForeignKey(ContentType, models.CASCADE, verbose_name="content type")
    codename = models.CharField("codename", max_length=100)

    class Meta:
        app_label = 'dab_rbac'
        verbose_name = "permission"
        verbose_name_plural = "permissions"
        unique_together = [["content_type", "codename"]]
        ordering = ["content_type__model", "codename"]

    def __str__(self):
        return f"<{self.__class__.__name__}: {self.codename}>"


class ManagedRoleFromSetting:
    def __init__(self, role_name):
        super().__init__()
        self.role_name = role_name

    def __get__(self, obj, objtype=None):
        if obj is None:
            return self
        if self.role_name not in obj._cache:
            obj._cache[self.role_name] = RoleDefinition.objects.filter(name=self.role_name).first()
        return obj._cache[self.role_name]


class ManagedRoleManager:
    def __init__(self, apps):
        self._cache = {}
        self.apps = apps

    def clear(self) -> None:
        "Clear any managed roles already loaded into the cache"
        self._cache = {}

    def __getattr__(self, attr):
        if attr in self._cache:
            return self._cache[attr]
        code_definition = permission_registry.get_managed_role_constructor(attr)
        if code_definition:
            rd, _ = code_definition.get_or_create(self.apps)
            return rd


class RoleDefinitionManager(models.Manager):
    def contribute_to_class(self, cls: Type[models.Model], name: str) -> None:
        """After Django populates the model for the manager, attach the manager role manager"""
        super().contribute_to_class(cls, name)
        self.managed = ManagedRoleManager(self.model._meta.apps)

    def give_creator_permissions(self, user, obj) -> Optional['RoleUserAssignment']:
        # If the user is a superuser, no need to bother giving the creator permissions
        for super_flag in settings.ANSIBLE_BASE_BYPASS_SUPERUSER_FLAGS:
            if getattr(user, super_flag):
                return

        needed_actions = settings.ANSIBLE_BASE_CREATOR_DEFAULTS

        # User should get permissions to the object and any child objects under it
        model_and_children = set(cls for rel, cls in permission_registry.get_child_models(obj))
        model_and_children.add(type(obj))
        cts = ContentType.objects.get_for_models(*model_and_children).values()

        needed_perms = set()
        for perm in DABPermission.objects.filter(content_type__in=cts).prefetch_related('content_type'):
            action = perm.codename.split('_', 1)[0]
            if action in needed_actions:
                # do not save add permission on the object level, which does not make sense
                if is_add_perm(perm.codename) and perm.content_type.model == obj._meta.model_name:
                    continue
                needed_perms.add(perm.codename)

        has_permissions = set(RoleEvaluation.get_permissions(user, obj))
        has_permissions.update(user.singleton_permissions())
        if set(needed_perms) - set(has_permissions):
            kwargs = {'permissions': needed_perms, 'name': settings.ANSIBLE_BASE_ROLE_CREATOR_NAME.format(obj=obj, cls=type(obj))}
            defaults = {'content_type': ContentType.objects.get_for_model(obj)}
            try:
                rd, _ = self.get_or_create(defaults=defaults, **kwargs)
            except ValidationError:
                logger.warning(f'Creating role definition {kwargs["name"]} as manged role because this is not allow as a custom role')
                defaults['managed'] = True
                rd, _ = self.get_or_create(defaults=defaults, **kwargs)

            return rd.give_permission(user, obj)

    def get_or_create(self, permissions=(), defaults=None, **kwargs):
        "Add extra feature on top of existing get_or_create to use permissions list"
        if permissions:
            permissions = set(permissions)
            for existing_rd in self.prefetch_related('permissions'):
                existing_set = set(perm.codename for perm in existing_rd.permissions.all())
                if existing_set == permissions:
                    return (existing_rd, False)
            create_kwargs = kwargs.copy()
            if defaults:
                create_kwargs.update(defaults)
            return (self.create_from_permissions(permissions=permissions, **create_kwargs), True)
        return super().get_or_create(defaults=defaults, **kwargs)

    def create_from_permissions(self, permissions=(), **kwargs):
        "Create from a list of text-type permissions and do validation"
        perm_list = [permission_registry.permission_qs.get(codename=str_perm) for str_perm in permissions]

        ct = kwargs.get('content_type', None)
        if kwargs.get('content_type_id', None):
            ct = ContentType.objects.get(id=kwargs['content_type_id'])

        validate_permissions_for_model(perm_list, ct, managed=kwargs.get('managed', False))

        rd = self.create(**kwargs)
        rd.permissions.add(*perm_list)
        return rd


class RoleDefinition(CommonModel):
    "Abstract definition of the permissions a role will grant before it is associated to an object"

    class Meta:
        app_label = 'dab_rbac'
        ordering = ['id']
        verbose_name_plural = _('role_definition')

    name = models.TextField(db_index=True, unique=True)
    description = models.TextField(blank=True)
    managed = models.BooleanField(default=False, editable=False)  # pulp definition of Role uses locked
    permissions = models.ManyToManyField('dab_rbac.DABPermission', related_name='role_definitions')
    content_type = models.ForeignKey(
        ContentType,
        help_text=_('Type of resource this can apply to, only used for validation and user assistance'),
        null=True,
        default=None,
        on_delete=models.CASCADE,
    )

    objects = RoleDefinitionManager()
    router_basename = 'roledefinition'
    ignore_relations = ['permissions', 'object_roles', 'content_type', 'teams', 'users']

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
        if self.content_type is not None:
            raise RuntimeError('Role definition content type must be null to assign globally')

        if actor._meta.model_name == 'user':
            if not settings.ANSIBLE_BASE_ALLOW_SINGLETON_USER_ROLES:
                raise ValidationError('Global roles are not enabled for users')
            kwargs = dict(object_role=None, user=actor, role_definition=self)
            cls = RoleUserAssignment
        elif isinstance(actor, permission_registry.team_model):
            if not settings.ANSIBLE_BASE_ALLOW_SINGLETON_TEAM_ROLES:
                raise ValidationError('Global roles are not enabled for teams')
            kwargs = dict(object_role=None, team=actor, role_definition=self)
            cls = RoleTeamAssignment
        else:
            raise RuntimeError(f'Cannot give permission to {actor}, must be a user or team')

        if giving:
            assignment, _ = cls.objects.get_or_create(**kwargs)
        else:
            assignment = cls.objects.filter(**kwargs).first()
            if assignment:
                assignment.delete()

        # Clear any cached permissions
        if actor._meta.model_name == 'user':
            if hasattr(actor, '_singleton_permissions'):
                delattr(actor, '_singleton_permissions')
        else:
            # when team permissions change, users in memory may be affected by this
            # but there is no way to know what users, so we use a global flag
            from ansible_base.rbac.evaluations import bound_singleton_permissions

            bound_singleton_permissions._team_clear_signal = True

        return assignment

    def give_permission(self, actor, content_object):
        return self.give_or_remove_permission(actor, content_object, giving=True)

    def remove_permission(self, actor, content_object):
        return self.give_or_remove_permission(actor, content_object, giving=False)

    def get_or_create_object_role(self, **kwargs):
        """Transaction-safe method to create ObjectRole

        The UI will assign many permissions concurrently.
        These will be in transactions, but also mutually create the same ObjectRole
        postgres constraints will still be violated by other active transactions
        which gives us a way to gracefully handle this.
        """
        if transaction.get_connection().in_atomic_block:
            try:
                with transaction.atomic():
                    object_role = ObjectRole.objects.create(**kwargs)
                    return (object_role, True)
            except IntegrityError:
                object_role = ObjectRole.objects.get(**kwargs)
                return (object_role, False)
        else:
            object_role = ObjectRole.objects.create(**kwargs)
            return (object_role, True)

    def give_or_remove_permission(self, actor, content_object, giving=True, sync_action=False):
        "Shortcut method to do whatever needed to give user or team these permissions"
        validate_assignment(self, actor, content_object)
        obj_ct = ContentType.objects.get_for_model(content_object)
        # sanitize the object_id to its database version, practically, remove "-" chars from uuids
        object_id = content_object._meta.pk.get_db_prep_value(content_object.pk, connection)
        kwargs = dict(role_definition=self, content_type=obj_ct, object_id=object_id)

        created = False
        object_role = ObjectRole.objects.filter(**kwargs).first()
        if object_role is None:
            if not giving:
                return  # nothing to do
            object_role, created = self.get_or_create_object_role(**kwargs)

        from ansible_base.rbac.triggers import needed_updates_on_assignment, update_after_assignment

        update_teams, to_update = needed_updates_on_assignment(self, actor, object_role, created=created, giving=True)

        assignment = None
        if actor._meta.model_name == 'user':
            if giving:
                assignment, created = RoleUserAssignment.objects.get_or_create(user=actor, object_role=object_role)
            else:
                object_role.users.remove(actor)
        elif isinstance(actor, permission_registry.team_model):
            if giving:
                assignment, created = RoleTeamAssignment.objects.get_or_create(team=actor, object_role=object_role)
            else:
                object_role.teams.remove(actor)

        if (not giving) and (not (object_role.users.exists() or object_role.teams.exists())):
            if object_role in to_update:
                to_update.remove(object_role)
            object_role.delete()

        update_after_assignment(update_teams, to_update)

        if not sync_action and self.name in permission_registry._trackers:
            tracker = permission_registry._trackers[self.name]
            with tracker.sync_active():
                tracker.sync_relationship(actor, content_object, giving=giving)

        return assignment

    @classmethod
    def user_global_permissions(cls, user, permission_qs=None):
        """Evaluation method only for global permissions from global roles

        This is special, in that it bypasses the RoleEvaluation table and methods.
        That is because global roles do not enumerate role permissions there,
        so global permissions are computed separately, here.
        """
        if permission_qs is None:
            # Allowing caller to replace the base permission set allows changing the type of thing returned
            # this is used in the assignment querysets, but these cases must call the method directly
            permission_qs = DABPermission.objects.all()

        perm_set = set()
        if settings.ANSIBLE_BASE_ALLOW_SINGLETON_USER_ROLES:
            rd_qs = cls.objects.filter(user_assignments__user=user, content_type=None)
            perm_qs = permission_qs.filter(role_definitions__in=rd_qs)
            perm_set.update(perm_qs)
        if settings.ANSIBLE_BASE_ALLOW_SINGLETON_TEAM_ROLES:
            # Users gain team membership via object roles that grant the teams member permission
            user_obj_roles = ObjectRole.objects.filter(users=user)
            user_teams_qs = permission_registry.team_model.objects.filter(member_roles__in=user_obj_roles)
            # Those teams (the user is in) then have a set of global roles they have been assigned
            rd_qs = cls.objects.filter(team_assignments__team__in=user_teams_qs, content_type=None)
            perm_qs = permission_qs.filter(role_definitions__in=rd_qs)
            perm_set.update(perm_qs)
        return perm_set

    def summary_fields(self):
        return {'id': self.id, 'name': self.name, 'description': self.description, 'managed': self.managed}


class ObjectRoleFields(models.Model):
    "Fields for core functionality of object-roles"

    class Meta:
        abstract = True

    # role_definition set on child models to set appropriate help_text and related_name
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.TextField(null=False)
    content_object = GenericForeignKey('content_type', 'object_id')

    @classmethod
    def _visible_items(cls, eval_cls, user):
        permission_qs = eval_cls.objects.filter(
            role__in=user.has_roles.all(),
            content_type_id=models.OuterRef('content_type_id'),
        )
        # NOTE: type casting is necessary in postgres but not sqlite3
        object_id_field = cls._meta.get_field('object_id')
        obj_filter = models.Q(object_id__in=permission_qs.values_list(Cast('object_id', output_field=object_id_field)))

        if not hasattr(user, '_singleton_permission_objs'):
            user._singleton_permission_objs = RoleDefinition.user_global_permissions(user)

        if user._singleton_permission_objs:
            super_ct_ids = set(perm.content_type_id for perm in user._singleton_permission_objs)
            # content_type=None condition: A good-enough rule - you can see other global assignments if you have any yourself
            return cls.objects.filter(obj_filter | models.Q(content_type__in=super_ct_ids) | models.Q(content_type=None))
        return cls.objects.filter(obj_filter)

    @classmethod
    def visible_items(cls, user):
        "This ORs querysets to show assignments to both UUID and integer pk models"
        return cls._visible_items(RoleEvaluation, user) | cls._visible_items(RoleEvaluationUUID, user)

    @property
    def cache_id(self):
        "The ObjectRole GenericForeignKey is text, but cache needs to match models"
        return RoleEvaluation._meta.get_field('object_id').to_python(self.object_id)


class AssignmentBase(ImmutableCommonModel, ObjectRoleFields):
    """
    This uses some parts of CommonModel to save metadata like documenting
    the user who assigned the permission and timestamp when it happened.
    This caches ObjectRole fields for purposes of serializers,
    both models are immutable, making caching easy.
    """

    object_role = models.ForeignKey('dab_rbac.ObjectRole', on_delete=models.CASCADE, editable=False, null=True)
    object_id = models.TextField(
        null=True, blank=True, help_text=_('Primary key of the object this assignment applies to, null value indicates system-wide assignment')
    )
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True)

    # object_role is internal, and not shown in serializer
    # content_type does not have a link, and ResourceType will be used in lieu sometime
    ignore_relations = ['content_type', 'object_role']

    class Meta:
        app_label = 'dab_rbac'
        abstract = True

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Cache fields from the associated object_role
        if self.object_role_id and not self.object_id:
            self.object_id = self.object_role.object_id
            self.content_type_id = self.object_role.content_type_id
            self.role_definition_id = self.object_role.role_definition_id


class RoleUserAssignment(AssignmentBase):
    role_definition = models.ForeignKey(
        RoleDefinition,
        on_delete=models.CASCADE,
        help_text=_("The role definition which defines permissions conveyed by this assignment"),
        related_name='user_assignments',
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='role_assignments')
    router_basename = 'roleuserassignment'

    class Meta:
        app_label = 'dab_rbac'
        ordering = ['id']
        unique_together = ('user', 'object_role')

    def __repr__(self):
        return f'RoleUserAssignment(pk={self.id})'

    @property
    def actor(self):
        "Really simple helper to give same behavior between user and role assignments"
        return self.user


class RoleTeamAssignment(AssignmentBase):
    role_definition = models.ForeignKey(
        RoleDefinition,
        on_delete=models.CASCADE,
        help_text=_("The role definition which defines permissions conveyed by this assignment"),
        related_name='team_assignments',
    )
    team = models.ForeignKey(settings.ANSIBLE_BASE_TEAM_MODEL, on_delete=models.CASCADE, related_name='role_assignments')
    router_basename = 'roleteamassignment'

    class Meta:
        app_label = 'dab_rbac'
        ordering = ['id']
        unique_together = ('team', 'object_role')

    def __repr__(self):
        return f'RoleTeamAssignment(pk={self.id})'

    @property
    def actor(self):
        "Really simple helper to give same behavior between user and role assignments"
        return self.team


class ObjectRole(ObjectRoleFields):
    """
    This is the successor to the Role model in the old AWX RBAC system
    It is renamed to ObjectRole to distinguish from the abstract or generic
    RoleDefinition which does not apply to a particular object.

    This matches the RoleDefinition to a content_object.
    After this is created, users and teams can be added to gives those
    permissions to that user or team, for that content_object
    """

    class Meta:
        app_label = 'dab_rbac'
        verbose_name_plural = _('object_roles')
        indexes = [models.Index(fields=["content_type", "object_id"])]
        ordering = ("content_type", "object_id")
        constraints = [models.UniqueConstraint(name='one_object_role_per_object_and_role', fields=['object_id', 'content_type', 'role_definition'])]

    role_definition = models.ForeignKey(
        RoleDefinition,
        on_delete=models.CASCADE,
        help_text=_("The role definition which defines what permissions this object role grants"),
        related_name='object_roles',
    )
    users = models.ManyToManyField(
        to=settings.AUTH_USER_MODEL,
        through='dab_rbac.RoleUserAssignment',
        through_fields=("object_role", "user"),
        related_name='has_roles',
        help_text=_("Users who have access to the permissions defined by this object role"),
    )
    teams = models.ManyToManyField(
        to=settings.ANSIBLE_BASE_TEAM_MODEL,
        through='dab_rbac.RoleTeamAssignment',
        through_fields=("object_role", "team"),
        related_name='has_roles',
        help_text=_("Teams or groups who have access to the permissions defined by this object role"),
    )
    # COMPUTED DATA
    provides_teams = models.ManyToManyField(
        settings.ANSIBLE_BASE_TEAM_MODEL,
        related_name='member_roles',
        editable=False,
        help_text=_("Users who have this role obtain member access to these teams, and inherit all their permissions"),
    )

    def __str__(self):
        return f'ObjectRole(pk={self.id}, {self.content_type.model}={self.object_id})'

    def save(self, *args, **kwargs):
        if self.id:
            raise RuntimeError('ObjectRole model is immutable, use RoleDefinition.give_permission method')
        return super().save(*args, **kwargs)

    def summary_fields(self):
        return {'id': self.id}

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
        role_model = role_content_type.model_class()
        # ObjectRole.object_id is stored as text, we convert it to the model pk native type
        object_id = role_model._meta.pk.to_python(self.object_id)
        for permission in types_prefetch.permissions_for_object_role(self):
            permission_content_type = types_prefetch.get_content_type(permission.content_type_id)

            # direct object permission
            if permission.content_type_id == self.content_type_id:
                expected_evaluations.add((permission.codename, self.content_type_id, object_id))
                continue

            # add child permission on the parent object, usually only for add permission
            if is_add_perm(permission.codename) or settings.ANSIBLE_BASE_CACHE_PARENT_PERMISSIONS:
                expected_evaluations.add((permission.codename, self.content_type_id, object_id))

            # add child object permission on child objects
            # Only propogate add permission to children which are parents of the permission model
            filter_path = None
            child_model = None
            if is_add_perm(permission.codename):
                for path, model in permission_registry.get_child_models(role_model):
                    if '__' in path and model._meta.model_name == permission_content_type.model:
                        path_to_parent, filter_path = path.split('__', 1)
                        child_model = permission_content_type.model_class()._meta.get_field(path_to_parent).related_model
                        eval_ct = ContentType.objects.get_for_model(child_model).id
                if not child_model:
                    continue
            else:
                for path, model in permission_registry.get_child_models(role_model):
                    if model._meta.model_name == permission_content_type.model:
                        filter_path = path
                        child_model = model
                        eval_ct = permission.content_type_id
                        break
                else:
                    logger.warning(f'{self.role_definition} listed {permission.codename} but model is not a child, ignoring')
                    continue

            # fetching child objects of an organization is very performance sensitive
            # for multiple permissions of same type, make sure to only do query once
            id_list = []
            if eval_ct in cached_id_lists:
                id_list = cached_id_lists[eval_ct]
            else:
                id_list = child_model.objects.filter(**{filter_path: object_id}).values_list('pk', flat=True)
                cached_id_lists[eval_ct] = list(id_list)

            for id in id_list:
                expected_evaluations.add((permission.codename, eval_ct, id))
        return expected_evaluations

    def needed_cache_updates(self, types_prefetch=None):
        existing_partials = dict()
        for permission_partial in self.permission_partials.all():
            existing_partials[permission_partial.obj_perm_id()] = permission_partial
        for permission_partial in self.permission_partials_uuid.all():
            existing_partials[permission_partial.obj_perm_id()] = permission_partial

        expected_evaluations = self.expected_direct_permissions(types_prefetch)

        for team in self.provides_teams.all():
            for team_role in team.has_roles.all():
                expected_evaluations.update(team_role.expected_direct_permissions(types_prefetch))

        existing_set = set(existing_partials.keys())

        to_delete = set()
        for identifier in existing_set - expected_evaluations:
            to_delete.add((existing_partials[identifier].id, type(identifier[-1])))

        to_add = []
        for codename, ct_id, obj_pk in expected_evaluations - existing_set:
            to_add.append(RoleEvaluation(codename=codename, content_type_id=ct_id, object_id=obj_pk, role=self))

        return (to_delete, to_add)


class RoleEvaluationMeta:
    app_label = 'dab_rbac'
    verbose_name_plural = _('role_object_permissions')
    indexes = [
        models.Index(fields=["role", "content_type_id", "object_id"]),  # used by get_roles_on_resource
        models.Index(fields=["role", "content_type_id", "codename"]),  # used by accessible_objects
    ]
    constraints = [models.UniqueConstraint(name='one_entry_per_object_permission_and_role', fields=['object_id', 'content_type_id', 'codename', 'role'])]


# COMPUTED DATA
class RoleEvaluationFields(models.Model):
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
        abstract = True

    def __str__(self):
        return (
            f'{self._meta.verbose_name.title()}(pk={self.id}, codename={self.codename}, object_id={self.object_id}, '
            f'content_type_id={self.content_type_id}, role_id={self.role_id})'
        )

    def save(self, *args, **kwargs):
        if self.id:
            raise RuntimeError(f'{self._meta.model_name} model is immutable and only used internally')
        return super().save(*args, **kwargs)

    codename = models.TextField(null=False, help_text=_("The name of the permission, giving the action and the model, from the Django Permission model"))
    # NOTE: we do not form object_id and content_type into a content_object, following from AWX practice
    # this can be relaxed as we have comparative performance testing to confirm doing so does not affect permissions
    content_type_id = models.PositiveIntegerField(null=False)

    def obj_perm_id(self):
        "Used for in-memory hashing of the type of object permission this represents"
        return (self.codename, self.content_type_id, self.object_id)

    @classmethod
    def accessible_ids(cls, model_cls, actor, codename: str, content_types: Optional[Iterable[int]] = None, cast_field=None) -> QuerySet:
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
            filter_kwargs['content_type_id'] = ContentType.objects.get_for_model(model_cls).id
        qs = cls.objects.filter(**filter_kwargs)
        if cast_field is None:
            return qs.values_list('object_id').distinct()
        else:
            return qs.values_list(Cast('object_id', output_field=cast_field)).distinct()

    @classmethod
    def accessible_objects(cls, model_cls, user, codename, queryset: Optional[QuerySet] = None) -> QuerySet:
        if queryset is None:
            queryset = model_cls.objects.all()
        return queryset.filter(pk__in=cls.accessible_ids(model_cls, user, codename))

    @classmethod
    def get_permissions(cls, user, obj):
        """
        Returns permissions that a user has to obj from object-roles,
        does not consider permissions from user flags or system-wide roles
        """
        return cls.objects.filter(role__in=user.has_roles.all(), content_type_id=ContentType.objects.get_for_model(obj).id, object_id=obj.id).values_list(
            'codename', flat=True
        )

    @classmethod
    def has_obj_perm(cls, user, obj, codename) -> bool:
        """
        Note this behaves similar in function to the REST Framework has_object_permission
        method on permission classes, but it is named differently to avoid unintentionally conflicting
        """
        return cls.objects.filter(
            role__in=user.has_roles.all(), content_type_id=ContentType.objects.get_for_model(obj).id, object_id=obj.pk, codename=codename
        ).exists()


class RoleEvaluation(RoleEvaluationFields):
    class Meta(RoleEvaluationMeta):
        pass

    role = models.ForeignKey(
        ObjectRole, null=False, on_delete=models.CASCADE, related_name='permission_partials', help_text=_("The object role that grants this form of permission")
    )
    object_id = models.PositiveIntegerField(null=False)


class RoleEvaluationUUID(RoleEvaluationFields):
    "Cache for UUID type models"

    class Meta(RoleEvaluationMeta):
        constraints = [
            models.UniqueConstraint(name='one_entry_per_object_permission_and_role_uuid', fields=['object_id', 'content_type_id', 'codename', 'role'])
        ]

    role = models.ForeignKey(
        ObjectRole,
        null=False,
        on_delete=models.CASCADE,
        related_name='permission_partials_uuid',
        help_text=_("The object role that grants this form of permission"),
    )
    object_id = models.UUIDField(null=False)


def get_evaluation_model(cls):
    pk_field = cls._meta.pk
    # For proxy models, including django-polymorphic, use the id field from parent table
    if isinstance(pk_field, models.OneToOneField):
        pk_field = pk_field.remote_field.model._meta.pk

    if isinstance(pk_field, models.IntegerField):
        return RoleEvaluation
    elif isinstance(pk_field, models.UUIDField):
        return RoleEvaluationUUID
    else:
        raise RuntimeError(f'Model {cls._meta.model_name} primary key type of {pk_field} is not supported')
