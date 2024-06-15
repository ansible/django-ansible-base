import logging
from typing import Optional, Type, Union

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Model
from django.db.models.base import ModelBase  # post_migrate may call with phony objects
from django.db.models.signals import post_delete, post_migrate
from django.utils.functional import cached_property

from ansible_base.rbac.managed import ManagedRoleConstructor, get_managed_role_constructors

"""
This will record the models that the RBAC system in this app will follow
Other apps should register models with this pattern

from ansible_base.utils.permission_registry import permission_registry

permission_registry.register(MyModel, AnotherModel)
"""

logger = logging.getLogger('ansible_base.rbac.permission_registry')


class ModelPermissionInfo:
    """Container of RBAC registration information for a model in permission_registry"""
    def __init__(self, model, parent_field_name='organization', allow_object_roles=True):
        self.model_name = model._meta.model_name
        self.app_label = model._meta.app_label
        if parent_field_name == self.model_name:
            # model can not be its own parent
            self.parent_field_name = None
        else:
            self.parent_field_name = parent_field_name
        self.allow_object_roles = allow_object_roles
        self.model = model


class PermissionRegistry:
    def __init__(self):
        self._registry = dict()  # model registry
        self._managed_roles = dict()  # code-defined role definitions, managed=True
        self.apps_ready = False
        self._tracked_relationships = set()
        self._trackers = dict()

    def register(self, *args, **kwargs):
        if self.apps_ready:
            raise RuntimeError('Cannot register model to permission_registry after apps are ready')
        for model in args:
            if model._meta.model_name not in self._registry:
                info = ModelPermissionInfo(model, **kwargs)
                self._registry[info.model_name] = info
            elif self._registry[model._meta.model_name] is model:
                logger.debug(f'Model {model._meta.model_name} registered to permission registry more than once')
            else:
                raise RuntimeError(f'Two models registered with same name {model._meta.model_name}')

    def get_info(self, obj: Union[ModelBase, Model]) -> ModelPermissionInfo:
        return self._registry[obj._meta.model_name]

    def track_relationship(self, cls, relationship, role_name):
        self._tracked_relationships.add((cls, relationship, role_name))

    def get_parent_model(self, model) -> Optional[type]:
        info = self._registry[model._meta.model_name]
        if info.parent_field_name is None:
            return None
        return model._meta.get_field(info.parent_field_name).related_model

    def get_parent_fd_name(self, model) -> Optional[str]:
        model_name = model._meta.model_name
        if model_name not in self._registry:
            return None
        info = self._registry[model_name]
        return info.parent_field_name

    def get_child_models(self, parent_model, seen=None) -> list[tuple[str, Type[Model]]]:
        """Returns child models and the filter relationship to the parent

        This is used for rebuilding RoleEvaluation entries.
        For the given parent model like organization, this returns a list of tuples that contains
         - path like "parent__organization" in Model.objects.filter(parent__organization=organization)
         - the model class which is a child resource of the parent model
        """
        if not seen:
            seen = set()
        child_filters = []
        parent_model_name = parent_model._meta.model_name
        for model_name, info in self._registry.items():
            if info.parent_field_name is None:
                continue
            this_parent_name = info.model._meta.get_field(info.parent_field_name).related_model._meta.model_name
            if this_parent_name == parent_model_name:
                if model_name in seen:
                    continue
                seen.add(model_name)

                child_filters.append((info.parent_field_name, info.model))
                for next_parent_filter, grandchild_model in self.get_child_models(info.model, seen=seen):
                    child_filters.append((f'{next_parent_filter}__{info.parent_field_name}', grandchild_model))
        return child_filters

    def get_resource_prefix(self, cls: Type[Model]) -> str:
        """For a given model class, give the prefix like shared, of API naming like shared.team"""
        if registry := self.get_resource_registry():
            # duplicates logic in ansible_base/resource_registry/apps.py
            try:
                resource_config = registry.get_config_for_model(cls)
                if resource_config.managed_serializer:
                    return "shared"  # shared model
            except KeyError:
                pass  # unregistered model

            # Fallback for unregistered and non-shared models
            return registry.api_config.service_type
        else:
            return 'local'

    def get_resource_registry(self):
        if 'ansible_base.resource_registry' not in settings.INSTALLED_APPS:
            return None

        from ansible_base.resource_registry.registry import get_registry

        return get_registry()

    def get_managed_role_constructor(self, shortname: str) -> Optional[ManagedRoleConstructor]:
        return self._managed_roles.get(shortname)

    def get_managed_role_constructor_by_name(self, name: str) -> Optional[ManagedRoleConstructor]:
        for managed_role in self._managed_roles.values():
            if managed_role.name == name:
                return managed_role

    def register_managed_role_constructor(self, shortname: str, managed_role: ManagedRoleConstructor) -> None:
        """Add the given managed role to the managed role registry"""
        self._managed_roles[shortname] = managed_role

    def register_managed_role_constructors(self) -> None:
        """Adds the data in setting ANSIBLE_BASE_MANAGED_ROLE_REGISTRY to the managed role registry"""
        managed_defs = get_managed_role_constructors(self.apps, settings.ANSIBLE_BASE_MANAGED_ROLE_REGISTRY)
        for shortname, constructor in managed_defs.items():
            self.register_managed_role_constructor(shortname, constructor)

    def create_managed_roles(self, apps) -> list[tuple[Model, bool]]:
        """Safe-ish method to create managed roles inside of a migration

        Returns a list with all the managed RoleDefinition objects and whether they were created
        in case you have to make decisions based on that"""
        if not self.apps_ready:
            raise RuntimeError('Cannot create managed roles before apps are ready')
        ret = []
        for managed_role in self._managed_roles.values():
            rd, created = managed_role.get_or_create(apps)
            ret.append((rd, created))
        return ret

    def call_when_apps_ready(self, apps, app_config):
        from ansible_base.rbac import triggers
        from ansible_base.rbac.evaluations import bound_has_obj_perm, bound_singleton_permissions, connect_rbac_methods
        from ansible_base.rbac.management import create_dab_permissions

        self.apps = apps
        self.apps_ready = True

        if self.team_model._meta.model_name not in self._registry:
            self.register(self.team_model)

        # Do no specify sender for create_dab_permissions, because that is passed as app_config
        # and we want to create permissions for external apps, not the dab_rbac app
        post_migrate.connect(
            create_dab_permissions,
            dispatch_uid="ansible_base.rbac.management.create_dab_permissions",
        )
        post_migrate.connect(
            triggers.post_migration_rbac_setup,
            sender=app_config,
            dispatch_uid="ansible_base.rbac.triggers.post_migration_rbac_setup",
        )

        self.user_model.add_to_class('has_obj_perm', bound_has_obj_perm)
        self.user_model.add_to_class('singleton_permissions', bound_singleton_permissions)
        post_delete.connect(triggers.rbac_post_user_delete, sender=self.user_model, dispatch_uid='permission-registry-user-delete')

        for cls in self._registry.values():
            triggers.connect_rbac_signals(cls.model)
            connect_rbac_methods(cls.model)

        for cls, relationship, role_name in self._tracked_relationships:
            if role_name in self._trackers:
                tracker = self._trackers[role_name]
            else:
                tracker = triggers.TrackedRelationship(cls, role_name)
                self._trackers[role_name] = tracker
            tracker.initialize(relationship)

        self.register_managed_role_constructors()

    @property
    def team_model(self):
        return self.apps.get_model(settings.ANSIBLE_BASE_TEAM_MODEL)

    @cached_property
    def team_ct_id(self):
        return self.content_type_model.objects.get_for_model(self.team_model).id

    @property
    def user_model(self):
        return get_user_model()

    @property
    def content_type_model(self):
        return self.apps.get_model('contenttypes.ContentType')

    @cached_property
    def org_ct_id(self):
        team_parent_model = self.get_parent_model(self.team_model)
        return self.content_type_model.objects.get_for_model(team_parent_model).id

    @property
    def permission_qs(self):
        """Return a queryset of the permission model restricted to the RBAC-tracked models

        Note that this should not be necessary, since the post_migrate signal for DABPermission
        will only create entries for registered models.
        However, removing permission entries after a model definition changes is still unsolved
        and this is already problematic for auth.Permission.
        """
        all_cts = self.content_type_model.objects.get_for_models(*self.all_registered_models)
        return self.apps.get_model('dab_rbac.DABPermission').objects.filter(content_type__in=all_cts.values())

    @property
    def team_permission(self):
        return f'member_{self.team_model._meta.model_name}'

    @property
    def all_registered_models(self) -> list[Type[Model]]:
        return [info.model for info in self._registry.values()]

    def is_registered(self, obj: Union[ModelBase, Model]) -> bool:
        """Tells if the given object or class is a type tracked by DAB RBAC"""
        return bool(obj._meta.model_name in self._registry)


permission_registry = PermissionRegistry()
