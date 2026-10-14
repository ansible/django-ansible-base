import logging
import operator
from collections.abc import Iterable
from functools import reduce
from typing import TYPE_CHECKING, Optional, Type, Union
from uuid import UUID

# Django
from django.conf import settings
from django.db import models
from django.db.models import Count, Q
from django.db.models.functions import Cast
from django.db.models.query import QuerySet
from django.db.utils import IntegrityError
from django.utils.translation import gettext_lazy as _

# Django-rest-framework
from rest_framework.exceptions import ValidationError

# ansible_base lib functions
from ansible_base.lib.abstract_models.common import CommonModel, ImmutableCommonModel

# ansible_base RBAC logic imports
from ansible_base.lib.utils.auth import get_organization_model, get_team_model
from ansible_base.lib.utils.models import is_add_perm
from ansible_base.rbac.permission_registry import permission_registry
from ansible_base.rbac.sync import maybe_reverse_sync_assignment
from ansible_base.rbac.validators import validate_permissions_for_model
from ansible_base.resource_registry.fields import AnsibleResourceField

from ..remote import GenericObject, RemoteObject, StandInPK
from .content_type import DABContentType
from .fields import FederatedForeignKey

if TYPE_CHECKING:
    from ansible_base.rbac.prefetch import EvaluationsPrefetch
from .permission import DABPermission

# Conditionally import AuditableModel if activitystream is installed
_AuditableBase = object
if 'ansible_base.activitystream' in settings.INSTALLED_APPS:
    from ansible_base.activitystream.models import AuditableModel

    _AuditableBase = AuditableModel

logger = logging.getLogger('ansible_base.rbac.models')


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
        constructor = permission_registry.get_managed_role_constructor(attr)
        if constructor:
            rd, _ = constructor.get_or_create(self.apps)
            return rd


class RoleDefinitionManager(models.Manager):
    def contribute_to_class(self, cls: Type[models.Model], name: str) -> None:
        """After Django populates the model for the manager, attach the manager role manager"""
        super().contribute_to_class(cls, name)
        self.managed = ManagedRoleManager(self.model._meta.apps)

    def give_creator_permissions(self, user, obj) -> Optional['RoleUserAssignment']:
        if not permission_registry.is_registered(obj):
            return None  # Exit before getting content type, which will not exist

        # If the user is a superuser, no need to bother giving the creator permissions
        for super_flag in settings.ANSIBLE_BASE_BYPASS_SUPERUSER_FLAGS:
            if getattr(user, super_flag):
                return None

        needed_actions = settings.ANSIBLE_BASE_CREATOR_DEFAULTS

        # User should get permissions to the object and any child objects under it
        model_and_children = {cls for rel, cls in permission_registry.get_child_models(obj)}
        model_and_children.add(type(obj))
        cts = DABContentType.objects.get_for_models(*model_and_children).values()

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
            defaults = {'content_type': DABContentType.objects.get_for_model(obj)}
            try:
                rd, _ = self.get_or_create(defaults=defaults, **kwargs)
            except ValidationError:
                logger.warning(f'Creating role definition {kwargs["name"]} as manged role because this is not allow as a custom role')
                defaults['managed'] = True
                rd, _ = self.get_or_create(defaults=defaults, **kwargs)

            assignment = rd.give_permission(user, obj)
            # reverse sync the assignment
            maybe_reverse_sync_assignment(assignment)
            return assignment
        return None

    def get_or_create(self, permissions=(), defaults=None, **kwargs):
        """Override get_or_create to support lookup by permissions list.
        Handles race conditions where multiple RoleDefinition's may be
        created simultaneously by using a retry loop.
        """
        if not permissions:
            return super().get_or_create(defaults=defaults, **kwargs)

        permissions = set(permissions)
        create_kwargs = kwargs.copy()
        if defaults:
            create_kwargs.update(defaults)

        # Codenames alone are not a unique identity: a role cascading a permission to children
        # can share codenames with a role scoped directly to that child type.
        target_content_type = create_kwargs.get('content_type')
        if content_type_id := create_kwargs.get('content_type_id'):
            target_content_type = DABContentType.objects.get(id=content_type_id)

        max_retries = 2
        for attempt in range(max_retries):
            # search by permission set
            target_count = len(permissions)
            candidates = (
                self.annotate(perm_count=Count('permissions')).filter(perm_count=target_count, content_type=target_content_type).prefetch_related('permissions')
            )

            for existing_rd in candidates:
                existing_set = {perm.codename for perm in existing_rd.permissions.all()}
                if existing_set == permissions:
                    return (existing_rd, False)

            try:
                rd = self.create_from_permissions(permissions=permissions, **create_kwargs)
                # Always return True for created. Value is not used.
                return (rd, True)
            except IntegrityError:
                logger.info(f"IntegrityError on attempt {attempt + 1}/{max_retries} ")
                if attempt >= max_retries - 1:
                    raise

    def create_from_permissions(self, permissions=(), **kwargs):
        """Create from a list of text-type permissions and do validation."""
        perm_list: list[str] = []
        for str_perm in permissions:
            if '.' in str_perm:
                service, codename = str_perm.split('.', 1)
                perm_list.append(permission_registry.permission_qs.get(content_type__service=service, codename=codename))
            else:
                # Giving a codename by itself like "change_inventory" implies a local or shared permission
                perm_list.append(permission_registry.permission_qs.get(codename=str_perm))

        ct = kwargs.get('content_type', None)
        if kwargs.get('content_type_id', None):
            ct = DABContentType.objects.get(id=kwargs['content_type_id'])

        validate_permissions_for_model(perm_list, ct, managed=kwargs.get('managed', False))

        # Use get_or_create to handle IntegrityError
        rd, created = super(RoleDefinitionManager, self).get_or_create(**kwargs)
        if created:
            rd.permissions.add(*perm_list)
        else:
            logger.debug(f'Reused existing RoleDefinition {rd.id} due to name collision')
        return rd


class RoleDefinition(CommonModel):
    "Abstract definition of the permissions a role will grant before it is associated to an object"

    class Meta:
        app_label = 'dab_rbac'
        ordering = ['id']
        verbose_name_plural = _('role_definition')

    name = models.TextField(db_index=True, unique=True, help_text=_("The name of this role."))
    description = models.TextField(blank=True, help_text=_("A description of this role."))
    managed = models.BooleanField(
        default=False, editable=False, help_text=_("Is this role managed by the system (not changeable by the users).")
    )  # pulp definition of Role uses locked
    permissions = models.ManyToManyField('dab_rbac.DABPermission', related_name='role_definitions')
    content_type = models.ForeignKey(
        DABContentType,
        help_text=_('The type of resource this can apply to; used for validation and user assistance.'),
        null=True,
        default=None,
        on_delete=models.CASCADE,
    )
    # This is a synchronized field, so add reverse relation for resource
    resource = AnsibleResourceField(primary_key_field="id")

    objects = RoleDefinitionManager()
    router_basename = 'roledefinition'
    _base_ignore_relations = ['permissions', 'object_roles', 'content_type', 'teams', 'users']

    def __str__(self):
        managed_str = ''
        if self.managed:
            managed_str = ', managed=True'
        return f'RoleDefinition(pk={self.id}, name={self.name}{managed_str})'

    # See assignable_scope_q() below for what each of these scopes means.
    ASSIGNABLE_SCOPE_SYSTEM = 'system'
    ASSIGNABLE_SCOPE_ORGANIZATION = 'organization'
    ASSIGNABLE_SCOPE_TEAM = 'team'
    ASSIGNABLE_SCOPES = (ASSIGNABLE_SCOPE_SYSTEM, ASSIGNABLE_SCOPE_ORGANIZATION, ASSIGNABLE_SCOPE_TEAM)

    @classmethod
    def assignable_scope_q(cls, scopes: Iterable[str]) -> models.Q:
        """A Q object matching every RoleDefinition whose scope is one of `scopes`.

        A role's scope is 'system' if it has no content type, or 'organization'/
        'team' if its content type is (a subclass of) the organization/team
        model; anything else is resource-scoped and excluded. Raises ValueError
        if `scopes` contains a value not in ASSIGNABLE_SCOPES. An empty `scopes`
        matches no roles.
        """
        scopes = set(scopes)
        if unknown := scopes - set(cls.ASSIGNABLE_SCOPES):
            raise ValueError(f"Unknown scope(s): {', '.join(sorted(unknown))}. Valid scopes are: {', '.join(cls.ASSIGNABLE_SCOPES)}")

        conditions = []
        if cls.ASSIGNABLE_SCOPE_SYSTEM in scopes:
            conditions.append(models.Q(content_type__isnull=True))

        wanted_models = []
        if cls.ASSIGNABLE_SCOPE_ORGANIZATION in scopes:
            wanted_models.append(get_organization_model())
        if cls.ASSIGNABLE_SCOPE_TEAM in scopes:
            wanted_models.append(get_team_model())
        wanted_models = tuple(wanted_models)
        if wanted_models:
            candidate_models = [model for model in permission_registry.all_registered_models if issubclass(model, wanted_models)]
            eligible_ct_ids = [ct.id for ct in DABContentType.objects.get_for_models(*candidate_models).values()]
            conditions.append(models.Q(content_type_id__in=eligible_ct_ids))

        if not conditions:
            return models.Q(pk__in=[])
        return reduce(operator.or_, conditions)

    def give_global_permission(self, actor, return_created=False):
        """Grant a global role, optionally returning ``(assignment, created)``.

        ``created`` is false when the assignment already existed.
        """
        return self.give_or_remove_global_permission(actor, giving=True, return_created=return_created)

    def remove_global_permission(self, actor):
        return self.give_or_remove_global_permission(actor, giving=False)

    def _get_global_assignment_details(self, actor, giving):
        """Return the assignment model and lookup fields for a user or team."""
        if actor._meta.model_name == 'user':
            if giving and (not settings.ANSIBLE_BASE_ALLOW_SINGLETON_USER_ROLES):
                raise ValidationError('Global roles are not enabled for users')
            kwargs = {'object_role': None, 'user': actor, 'role_definition': self}
            cls = RoleUserAssignment
        elif isinstance(actor, permission_registry.team_model):
            if not settings.ANSIBLE_BASE_ALLOW_SINGLETON_TEAM_ROLES:
                raise ValidationError('Global roles are not enabled for teams')
            kwargs = {'object_role': None, 'team': actor, 'role_definition': self}
            cls = RoleTeamAssignment
        else:
            raise RuntimeError(f'Cannot {giving and "give" or "remove"} permission for {actor}, must be a user or team')

        return cls, kwargs

    @staticmethod
    def _clear_global_permission_cache(actor):
        """Invalidate cached global permissions affected by an assignment change."""
        if actor._meta.model_name == 'user':
            if hasattr(actor, '_singleton_permissions'):
                delattr(actor, '_singleton_permissions')
        else:
            # when team permissions change, users in memory may be affected by this
            # but there is no way to know what users, so we use a global flag
            from ansible_base.rbac.evaluations import bound_singleton_permissions

            bound_singleton_permissions._team_clear_signal = True

    def give_or_remove_global_permission(self, actor, giving=True, return_created=False):
        """Create or remove a global assignment and optionally report its insert result.

        For grants, ``return_created`` selects an ``(assignment, created)`` result.
        """
        if giving and (self.content_type is not None):
            raise ValidationError('Role definition content type must be null to assign globally')

        cls, kwargs = self._get_global_assignment_details(actor, giving)
        created = False
        if giving:
            assignment, created = cls.objects.get_or_create(**kwargs)
        else:
            assignment = cls.objects.filter(**kwargs).first()
            if assignment:
                assignment.delete()

        self._clear_global_permission_cache(actor)
        if return_created:
            return assignment, created
        return assignment

    def give_permission(self, actor, content_object):
        from ansible_base.rbac.pipeline import bulk_give_permissions

        is_user = actor._meta.model_name == 'user'
        perm = [(self, actor, content_object)]
        assignments = bulk_give_permissions(
            user_permissions=perm if is_user else [],
            team_permissions=[] if is_user else perm,
        )
        return assignments[0]

    def remove_permission(self, actor, content_object):
        from ansible_base.rbac.pipeline import bulk_remove_permissions

        is_user = actor._meta.model_name == 'user'
        perm = [(self, actor, content_object)]
        bulk_remove_permissions(
            user_permissions=perm if is_user else [],
            team_permissions=[] if is_user else perm,
        )

    def give_or_remove_permission(self, actor, content_object, giving=True):
        """Compat shim — AWX calls this via awx.main.models.rbac.give_or_remove_permission."""
        if giving:
            return self.give_permission(actor, content_object)
        else:
            return self.remove_permission(actor, content_object)

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

    @property
    def ignore_relations(self):
        "If the RoleDefinition model is not registered with resource registry then do not reference related resource"
        if 'ansible_base.resource_registry' in settings.INSTALLED_APPS:
            from ansible_base.resource_registry.registry import get_registry

            if 'dab_rbac.RoleDefinition' not in get_registry().registry:
                return self._base_ignore_relations + ['resource']

        return self._base_ignore_relations

    def summary_fields(self):
        return {'id': self.id, 'name': self.name, 'description': self.description, 'managed': self.managed}


class ObjectRoleFields(models.Model):
    "Fields for core functionality of object-roles"

    class Meta:
        abstract = True

    # role_definition set on child models to set appropriate help_text and related_name
    content_type = models.ForeignKey(
        DABContentType,
        on_delete=models.CASCADE,
        help_text=_("The content type of the subject of permission assignments. Duplicated from related RoleDefinition."),
    )
    object_id = models.TextField(null=False, help_text=_("The database primary key of the subject of permission assignments."))
    content_object = FederatedForeignKey('content_type', 'object_id')

    @classmethod
    def _visible_items(cls, eval_cls, user, qs=None):
        """Return a queryset of assignment records that ``user`` is allowed to see."""
        # NOTE: type casting is necessary in postgres but not sqlite3
        object_id_field = cls._meta.get_field('object_id')
        permission_qs = eval_cls.objects.filter(
            **eval_cls._actor_role_filter(user),
            content_type_id=models.OuterRef('content_type_id'),
        )
        # alias() keeps the Cast in WHERE only (not SELECT), enabling a semi-join point lookup
        obj_filter = models.Exists(
            permission_qs.alias(
                _obj_id_text=Cast('object_id', output_field=object_id_field),
            ).filter(
                _obj_id_text=models.OuterRef('object_id'),
            )
        )

        if not hasattr(user, '_singleton_permission_objs'):
            user._singleton_permission_objs = RoleDefinition.user_global_permissions(user)

        if qs is None:
            qs = cls.objects.all()

        if user._singleton_permission_objs:
            super_ct_ids = {perm.content_type_id for perm in user._singleton_permission_objs}
            # content_type=None condition: A good-enough rule - you can see other global assignments if you have any yourself
            return qs.filter(obj_filter | models.Q(content_type__in=super_ct_ids) | models.Q(content_type=None))
        return qs.filter(obj_filter)

    @classmethod
    def visible_items(cls, user, qs=None):
        "This ORs querysets to show assignments to both UUID and integer pk models"
        return cls._visible_items(RoleEvaluation, user, qs) | cls._visible_items(RoleEvaluationUUID, user, qs)

    @property
    def cache_id(self):
        "The ObjectRole GenericForeignKey is text, but cache needs to match models"
        return RoleEvaluation._meta.get_field('object_id').to_python(self.object_id)


class AssignmentBase(ImmutableCommonModel, ObjectRoleFields, _AuditableBase):
    """
    This uses some parts of CommonModel to save metadata like documenting
    the user who assigned the permission and timestamp when it happened.
    This caches ObjectRole fields for purposes of serializers,
    both models are immutable, making caching easy.
    """

    # When activitystream is installed (_AuditableBase = AuditableModel), these flags
    # configure AuditableModel to enable audit logging and suppress activity stream entries.
    # When activitystream is absent, _AuditableBase = object and these flags are inert.
    audit_log_enabled = True
    activity_stream_enabled = False

    object_role = models.ForeignKey(
        'dab_rbac.ObjectRole', on_delete=models.CASCADE, editable=False, null=True, help_text=_("A roll-up of the fields (role_definition, content_type).")
    )
    object_id = models.TextField(
        null=True, blank=True, help_text=_('The primary key of the object this assignment applies to; null value indicates system-wide assignment.')
    )
    object_ansible_id = models.UUIDField(
        null=True,
        blank=True,
        help_text=_('Cached ansible_id of the resource this assignment applies to.'),
    )
    content_type = models.ForeignKey(DABContentType, on_delete=models.CASCADE, null=True, help_text=_("The content type this applies to."))

    # object_role is internal, and not shown in serializer
    # content_type does not have a link, and ResourceType will be used in lieu sometime
    ignore_relations = ['content_type', 'object_role']

    class Meta:
        app_label = 'dab_rbac'
        abstract = True

    def save(self, *args, **kwargs):
        if not self.id:  # usually only new objects can be saved, but super needs to do error handling
            if self.object_role_id and (not self.object_id):
                # Cache fields from the associated object_role
                self.object_id = self.object_role.object_id
                self.content_type_id = self.object_role.content_type_id
                self.role_definition_id = self.object_role.role_definition_id
        return super().save(*args, **kwargs)


class RoleUserAssignment(AssignmentBase):
    role_definition = models.ForeignKey(
        RoleDefinition,
        on_delete=models.CASCADE,
        help_text=_("The role definition which defines permissions conveyed by this assignment."),
        related_name='user_assignments',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='role_assignments', help_text=_("The user this role is assigned to.")
    )
    router_basename = 'roleuserassignment'

    class Meta:
        app_label = 'dab_rbac'
        ordering = ['id']
        unique_together = ('user', 'object_role')
        constraints = [
            models.UniqueConstraint(
                fields=['user', 'role_definition'],
                condition=models.Q(object_role__isnull=True),
                name='unique_global_user_assignment',
            ),
        ]

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
        help_text=_("The role definition which defines permissions conveyed by this assignment."),
        related_name='team_assignments',
    )
    team = models.ForeignKey(
        settings.ANSIBLE_BASE_TEAM_MODEL, on_delete=models.CASCADE, related_name='role_assignments', help_text=_("The team that receives permissions.")
    )
    router_basename = 'roleteamassignment'

    class Meta:
        app_label = 'dab_rbac'
        ordering = ['id']
        unique_together = ('team', 'object_role')
        constraints = [
            models.UniqueConstraint(
                fields=['team', 'role_definition'],
                condition=models.Q(object_role__isnull=True),
                name='unique_global_team_assignment',
            ),
        ]

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
        help_text=_("The role definition which defines what permissions this object role grants."),
        related_name='object_roles',
    )
    users = models.ManyToManyField(
        to=settings.AUTH_USER_MODEL,
        through='dab_rbac.RoleUserAssignment',
        through_fields=("object_role", "user"),
        related_name='has_roles',
        help_text=_("Users who have access to the permissions defined by this object role."),
    )
    teams = models.ManyToManyField(
        to=settings.ANSIBLE_BASE_TEAM_MODEL,
        through='dab_rbac.RoleTeamAssignment',
        through_fields=("object_role", "team"),
        related_name='has_roles',
        help_text=_("Teams or groups who have access to the permissions defined by this object role."),
    )
    # Only for remote models
    parent_reference = models.TextField(blank=True, db_index=True, help_text=_("The ansible_id or object_id of the parent resource."))
    # COMPUTED DATA
    provides_teams = models.ManyToManyField(
        settings.ANSIBLE_BASE_TEAM_MODEL,
        related_name='member_roles',
        editable=False,
        help_text=_("Users who have this role obtain member access to these teams, and inherit all their permissions."),
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

    def get_child_filters(self, permission, role_content_type, types_prefetch):
        "Given a permission that a certain object role grants, returns child object filter instructions"
        filter_path = None
        child_model = None
        role_model = role_content_type.model_class()
        permission_content_type = types_prefetch.get_content_type(permission.content_type_id)
        permission_model = permission_content_type.model_class()
        if is_add_perm(permission.codename):
            # Add evaluations for add permission to children which are parents of the permission model
            # this only matters when for multi-layer inheritance (grandchildren)
            if issubclass(permission_model, RemoteObject):
                eval_ct = permission_content_type.parent_content_type
                if eval_ct == role_content_type:
                    return (None, None, None)  # this permission is for a direct child model
            else:
                for path, model in permission_registry.get_child_models(role_model):
                    if '__' in path and model._meta.model_name == permission_content_type.model:
                        path_to_parent, filter_path = path.split('__', 1)
                        child_model = permission_model._meta.get_field(path_to_parent).related_model
                        eval_ct = DABContentType.objects.get_for_model(child_model).id
                        break
                if not child_model:
                    return (None, None, None)  # this permission is for a direct child model
        elif issubclass(permission_model, RemoteObject):
            eval_ct = permission.content_type_id
        else:
            for path, model in permission_registry.get_child_models(role_model):
                if model._meta.model_name == permission_content_type.model:
                    filter_path = path
                    child_model = model
                    eval_ct = permission.content_type_id
                    break
            else:
                logger.warning(f'{self.role_definition} listed {permission.codename} but model is not a child, ignoring')
                return (None, None, None)

        return (eval_ct, child_model, filter_path)

    def _native_object_id(self, role_content_type) -> int | UUID:
        """ObjectRole.object_id is stored as text; return it as the model's own pk type."""
        if role_content_type.is_remote:
            return StandInPK(role_content_type).to_python(self.object_id)
        return role_content_type.model_class()._meta.pk.to_python(self.object_id)

    def _grants_on_own_object(self, permission) -> bool:
        """Whether this permission is cached as an evaluation on the role's own object.

        That is the case for the role's own model, and for permissions on child models
        when they are add permissions or ANSIBLE_BASE_CACHE_PARENT_PERMISSIONS is set.
        """
        if permission.content_type_id == self.content_type_id:
            return True
        return is_add_perm(permission.codename) or settings.ANSIBLE_BASE_CACHE_PARENT_PERMISSIONS

    @staticmethod
    def _child_ids(permission, eval_ct, child_model, filter_path, object_id, types_prefetch, look_ahead) -> list:
        """Ids of the eval_ct children of the role's object.

        Remote children are found through the ObjectRoles that reference the role's object
        as their parent. With look_ahead the query is narrowed to that one object in SQL,
        instead of fetching every child id of the parent (which for an organization can be
        tens of thousands of rows).
        """
        permission_model = types_prefetch.get_content_type(permission.content_type_id).model_class()
        if issubclass(permission_model, RemoteObject):
            qs = ObjectRole.objects.filter(parent_reference=object_id, content_type=eval_ct)
            if look_ahead:
                qs = qs.filter(object_id=str(look_ahead.pk))
            return list(qs.values_list(Cast('object_id', output_field=permission_model._meta.pk.django_field()), flat=True).distinct())
        qs = child_model.objects.filter(**{filter_path: object_id})
        if look_ahead:
            qs = qs.filter(pk=look_ahead.pk)
        return list(qs.values_list('pk', flat=True))

    def _child_evaluations(self, permission, role_content_type, object_id, types_prefetch, look_ahead, cached_id_lists) -> set:
        """Evaluations this permission confers on child objects of the role's object.

        Child types that don't match the look-ahead object are skipped. Child id lists are
        cached per content type in cached_id_lists, since fetching the children of an
        organization is performance sensitive and several permissions share a child type.
        """
        eval_ct, child_model, filter_path = self.get_child_filters(permission, role_content_type, types_prefetch)
        if not eval_ct or (look_ahead and eval_ct != look_ahead.content_type_id):
            return set()
        if eval_ct not in cached_id_lists:
            cached_id_lists[eval_ct] = self._child_ids(permission, eval_ct, child_model, filter_path, object_id, types_prefetch, look_ahead)
        return {(permission.codename, eval_ct, child_id) for child_id in cached_id_lists[eval_ct] if not look_ahead or child_id == look_ahead.pk}

    def expected_direct_permissions(self, types_prefetch, look_ahead: GenericObject | None = None) -> set[tuple[str, int, int | UUID]]:
        """The expected permissions that holding this ObjectRole confers to the holder

        This is given in the form of tuples, which represent RoleEvaluation entries.
        Values are (permission codename, content type id, object primary key)

        In the case of remote objects, this list may not be comprehensive

        With a look_ahead object, child content types that don't match it are
        skipped entirely and matching id lists are narrowed to its single pk,
        avoiding large querysets. Evaluations on the role's own object are only
        included when that object is the look-ahead object; otherwise a role like
        "JobTemplate Execute on JT 42", reached through a team, would contribute
        evaluations for JT 42 while JT 43 is being computed.
        """
        expected_evaluations = set()
        cached_id_lists: dict = {}
        role_content_type = types_prefetch.get_content_type(self.content_type_id)
        object_id = self._native_object_id(role_content_type)
        own_object_is_target = not look_ahead or (self.content_type_id == look_ahead.content_type_id and object_id == look_ahead.pk)

        for permission in types_prefetch.permissions_for_object_role(self):
            if own_object_is_target and self._grants_on_own_object(permission):
                expected_evaluations.add((permission.codename, self.content_type_id, object_id))
            if permission.content_type_id != self.content_type_id:
                expected_evaluations |= self._child_evaluations(permission, role_content_type, object_id, types_prefetch, look_ahead, cached_id_lists)
        return expected_evaluations

    @staticmethod
    def _log_partials_count(count, label, role_pk):
        msg = '%s: %d cached evaluation entries for object-role pk=%s'
        if count >= 500_000:
            logger.warning(msg + ', expected during global recalculations', label, count, role_pk)
        elif count >= 50_000:
            logger.info(msg, label, count, role_pk)
        else:
            logger.debug(msg, label, count, role_pk)

    def _load_existing_partials(
        self,
        look_ahead: GenericObject | None,
        evaluations_prefetch: Optional['EvaluationsPrefetch'],
    ) -> dict[tuple[str, int, Union[int, UUID]], int]:
        existing_partials = {}

        if look_ahead:
            # Look-ahead: query only the table matching the pk type, filtered
            # to the single target object.
            partial_filter = {'object_id': look_ahead.pk, 'content_type_id': look_ahead.content_type_id}
            source = self.permission_partials_uuid if isinstance(look_ahead.pk, UUID) else self.permission_partials
            for eval_id, codename, content_type_id, object_id in source.filter(**partial_filter).values_list('id', 'codename', 'content_type_id', 'object_id'):
                existing_partials[(codename, content_type_id, object_id)] = eval_id
            self._log_partials_count(len(existing_partials), f'existing evaluation (look_ahead={look_ahead.pk})', self.pk)
        elif evaluations_prefetch is not None:
            existing_partials.update(evaluations_prefetch.get_partials(self.pk))
            existing_partials.update(evaluations_prefetch.get_partials_uuid(self.pk))
            self._log_partials_count(len(existing_partials), 'existing evaluation (full)', self.pk)
        else:
            for source in (self.permission_partials, self.permission_partials_uuid):
                for eval_id, codename, content_type_id, object_id in source.values_list('id', 'codename', 'content_type_id', 'object_id'):
                    existing_partials[(codename, content_type_id, object_id)] = eval_id
            self._log_partials_count(len(existing_partials), 'existing evaluation (full)', self.pk)

        return existing_partials

    def _team_role_evaluations(self, types_prefetch, look_ahead, target_parents, lookahead_cache=None):
        """Return the evaluations this role grants through the teams it provides membership to.

        Holding this role makes the actor a member of the teams in provides_teams, so the actor
        inherits every role those teams hold. The result is the union of the expected direct
        permissions of those team-held roles, as (codename, content_type_id, object_id) tuples.

        With look_ahead, each team-held role is evaluated for that object only. If target_parents
        is also given, only team-held roles on the look-ahead object or one of its parents are
        visited, since no other role can grant permissions on it.
        """
        team_role_filter = None
        if look_ahead and target_parents is not None:
            team_role_filter = Q()
            for target in (look_ahead, *target_parents):
                team_role_filter |= Q(content_type_id=target.content_type_id, object_id=str(target.pk))

        expected_evaluations = set()
        team_roles = ObjectRole.objects.filter(teams__in=self.provides_teams.all()).distinct()
        if team_role_filter is not None:
            team_roles = team_roles.filter(team_role_filter)
        for team_role in team_roles:
            if lookahead_cache is not None and team_role.pk in lookahead_cache:
                expected_evaluations.update(lookahead_cache[team_role.pk])
                continue
            team_role_expected = team_role.expected_direct_permissions(types_prefetch, look_ahead=look_ahead)
            if lookahead_cache is not None:
                lookahead_cache[team_role.pk] = team_role_expected
            expected_evaluations.update(team_role_expected)
        return expected_evaluations

    def needed_cache_updates(
        self,
        types_prefetch=None,
        evaluations_prefetch=None,
        look_ahead: GenericObject | None = None,
        target_parents: Iterable[GenericObject] | None = None,
        lookahead_cache: dict | None = None,
    ):
        """Return (to_delete, to_add) changes needed in the RoleEvaluation table
        to make cached object-role permissions accurate for this role.

        When look_ahead is given, the scope is narrowed to that single
        object. In the RBAC inheritance system, signals
        can start from a resource and crawl up the inheritance tree to
        find ancestor roles (e.g. organization roles that grant permissions to
        child inventories). The look-ahead object is that originating resource,
        and filtering to it avoids loading the full set of cached evaluations
        for roles that may span thousands of child objects.

        Without look_ahead, a full recompute is performed for all
        objects this role grants permissions to.

        evaluations_prefetch: an EvaluationsPrefetch instance with batch-loaded
        evaluation data for this role's chunk, avoiding per-role queries.

        target_parents: in look-ahead mode, the look-ahead object's parent chain.
        When given, team-held roles are filtered to those on the look-ahead object
        or on one of its parents, the only roles that can grant evaluations on it.

        lookahead_cache: optional dict shared across one recompute, memoising the
        expected evaluations of team-held roles by ObjectRole pk. The same
        organization role is typically reached through many teams; compute it once.
        """

        if types_prefetch is None:
            from ansible_base.rbac.prefetch import TypesPrefetch

            types_prefetch = TypesPrefetch.from_db()

        existing_partials = self._load_existing_partials(look_ahead, evaluations_prefetch)
        expected_evaluations = self.expected_direct_permissions(types_prefetch, look_ahead=look_ahead)

        if evaluations_prefetch is not None:
            for team_role in evaluations_prefetch.get_team_roles(self.pk):
                expected_evaluations.update(team_role.expected_direct_permissions(types_prefetch, look_ahead=look_ahead))
        else:
            expected_evaluations.update(self._team_role_evaluations(types_prefetch, look_ahead, target_parents, lookahead_cache))

        self._log_partials_count(len(expected_evaluations), 'expected evaluation', self.pk)

        existing_set = set(existing_partials.keys())

        to_delete = set()
        for codename, content_type_id, object_id in existing_set - expected_evaluations:
            to_delete.add((existing_partials[(codename, content_type_id, object_id)], type(object_id)))

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
      the only methods that should ever write to this table are
        recompute_role_evaluations() and recompute_all_role_evaluations()

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

    codename = models.TextField(null=False, help_text=_("The name of the permission, giving the action and the model, from the Django Permission model."))
    # NOTE: we do not form object_id and content_type into a content_object, following from AWX practice
    # this can be relaxed as we have comparative performance testing to confirm doing so does not affect permissions
    content_type_id = models.PositiveIntegerField(null=False, help_text=_("The related content type id."))

    @staticmethod
    def _actor_role_filter(actor):
        """Return filter kwargs that skip the objectrole table entirely.

        Uses ``role_id__in`` with a subquery on the assignment table, which
        avoids JOINing through ``dab_rbac_objectrole``.  Both
        ``roleevaluation.role_id`` and ``assignment.object_role_id`` reference
        the same objectrole PK, so the intermediate table is unnecessary.
        """
        if actor._meta.model_name == permission_registry.user_model._meta.model_name:
            return {'role_id__in': RoleUserAssignment.objects.filter(user_id=actor.id).values('object_role_id')}
        return {'role_id__in': RoleTeamAssignment.objects.filter(team_id=actor.id).values('object_role_id')}

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
        filter_kwargs = {**cls._actor_role_filter(actor), 'codename': codename}
        if content_types:
            filter_kwargs['content_type_id__in'] = content_types
        else:
            filter_kwargs['content_type_id'] = DABContentType.objects.get_for_model(model_cls).id
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
        return cls.objects.filter(**cls._actor_role_filter(user), content_type_id=DABContentType.objects.get_for_model(obj).id, object_id=obj.id).values_list(
            'codename', flat=True
        )

    @classmethod
    def has_obj_perm(cls, user, obj, codename) -> bool:
        """
        Note this behaves similar in function to the REST Framework has_object_permission
        method on permission classes, but it is named differently to avoid unintentionally conflicting
        """
        return cls.objects.filter(
            **cls._actor_role_filter(user), content_type_id=DABContentType.objects.get_for_model(obj).id, object_id=obj.pk, codename=codename
        ).exists()


class RoleEvaluation(RoleEvaluationFields):
    class Meta(RoleEvaluationMeta):
        constraints = [models.UniqueConstraint(name='one_entry_per_object_permission_and_role', fields=['object_id', 'content_type_id', 'codename', 'role'])]
        ordering = ['id']

    role = models.ForeignKey(
        ObjectRole,
        null=False,
        on_delete=models.CASCADE,
        related_name='permission_partials',
        help_text=_("The object role that grants this form of permission."),
    )
    object_id = models.PositiveIntegerField(null=False, help_text=_("The id of the object that the related role gives the related permission to."))


class RoleEvaluationUUID(RoleEvaluationFields):
    "Cache for UUID type models"

    class Meta(RoleEvaluationMeta):
        constraints = [
            models.UniqueConstraint(name='one_entry_per_object_permission_and_role_uuid', fields=['object_id', 'content_type_id', 'codename', 'role'])
        ]
        ordering = ['id']

    role = models.ForeignKey(
        ObjectRole,
        null=False,
        on_delete=models.CASCADE,
        related_name='permission_partials_uuid',
        help_text=_("The object role that grants this form of permission."),
    )
    object_id = models.UUIDField(null=False, help_text=_("The object UUID this role evaluation will be applied to."))
