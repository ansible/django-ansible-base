import logging
from typing import Optional

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models import Model
from django.db.models.signals import post_delete, post_migrate, pre_delete
from django.utils.functional import cached_property

"""
This will record the models that the RBAC system in this app will follow
Other apps should register models with this pattern

from ansible_base.utils.permission_registry import permission_registry

permission_registry.register(MyModel, AnotherModel)
"""

logger = logging.getLogger('ansible_base.rbac.permission_registry')


class PermissionRegistry:
    def __init__(self):
        self._registry = set()
        self._name_to_model = dict()
        self._parent_fields = dict()
        self.apps_ready = False
        self._tracked_relationships = set()
        self._trackers = dict()

    def register(self, *args, parent_field_name='organization'):
        if self.apps_ready:
            raise RuntimeError('Cannot register model to permission_registry after apps are ready')
        for cls in args:
            if cls not in self._registry:
                self._registry.add(cls)
                model_name = cls._meta.model_name
                if model_name in self._name_to_model:
                    raise RuntimeError(f'Two models registered with same name {model_name}')
                self._name_to_model[model_name] = cls
                if model_name != 'organization':
                    self._parent_fields[model_name] = parent_field_name
            else:
                logger.debug(f'Model {cls._meta.model_name} registered to permission registry more than once')

    def track_relationship(self, cls, relationship, role_name):
        self._tracked_relationships.add((cls, relationship, role_name))

    def get_parent_model(self, model) -> Optional[Model]:
        model = self._name_to_model[model._meta.model_name]
        parent_field_name = self.get_parent_fd_name(model)
        if parent_field_name is None:
            return None
        return model._meta.get_field(parent_field_name).related_model

    def get_parent_fd_name(self, model) -> Optional[str]:
        return self._parent_fields.get(model._meta.model_name)

    def get_child_models(self, parent_model, seen=None):
        """
        Returns a set of tuples that give the filter args and the model for child resources
        """
        if not seen:
            seen = set()
        child_filters = []
        parent_model_name = parent_model._meta.model_name
        for model_name, parent_field_name in self._parent_fields.items():
            if parent_field_name is None:
                continue
            child_model = self._name_to_model[model_name]
            this_parent_name = child_model._meta.get_field(parent_field_name).related_model._meta.model_name
            if this_parent_name == parent_model_name:
                if model_name in seen:
                    continue
                seen.add(model_name)

                child_filters.append((parent_field_name, child_model))
                for next_parent_filter, grandchild_model in self.get_child_models(child_model, seen=seen):
                    child_filters.append((f'{next_parent_filter}__{parent_field_name}', grandchild_model))
        return child_filters

    def call_when_apps_ready(self, apps, app_config):
        from ansible_base.rbac import triggers
        from ansible_base.rbac.evaluations import bound_has_obj_perm, bound_singleton_permissions, connect_rbac_methods

        self.apps = apps
        self.apps_ready = True

        if self.team_model not in self._registry:
            self._registry.add(self.team_model)

        post_migrate.connect(triggers.post_migration_rbac_setup, sender=app_config)

        self.user_model.add_to_class('has_obj_perm', bound_has_obj_perm)
        self.user_model.add_to_class('singleton_permissions', bound_singleton_permissions)
        post_delete.connect(triggers.rbac_post_user_delete, sender=self.user_model, dispatch_uid='permission-registry-user-delete')

        # Temporary HACK until the created_by and modified_by cascade behavior is resolved
        def clear_created_assignments(instance, *args, **kwargs):
            from ansible_base.rbac.models import RoleTeamAssignment, RoleUserAssignment

            RoleUserAssignment.objects.filter(created_by=instance).update(created_by=None)
            RoleTeamAssignment.objects.filter(created_by=instance).update(created_by=None)

        pre_delete.connect(clear_created_assignments, sender=self.user_model, dispatch_uid='permission-registry-clear-created-assignments')

        # end HACK

        for cls in self._registry:
            triggers.connect_rbac_signals(cls)
            connect_rbac_methods(cls)

        for cls, relationship, role_name in self._tracked_relationships:
            if role_name in self._trackers:
                tracker = self._trackers[role_name]
            else:
                tracker = triggers.TrackedRelationship(cls, role_name)
                self._trackers[role_name] = tracker
            tracker.initialize(relationship)

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
    def permission_model(self):
        return self.apps.get_model(settings.ANSIBLE_BASE_PERMISSION_MODEL)

    @property
    def permission_qs(self):
        "Return a queryset of the permission model restricted to the RBAC-tracked models"
        all_cts = self.content_type_model.objects.get_for_models(*self.all_registered_models)
        return self.permission_model.objects.filter(content_type__in=all_cts.values())

    @property
    def team_permission(self):
        return f'member_{self.team_model._meta.model_name}'

    @property
    def all_registered_models(self):
        return [cls for cls in self._registry]

    def is_registered(self, obj: Model) -> bool:
        return any(obj._meta.model_name == cls._meta.model_name for cls in self._registry)


permission_registry = PermissionRegistry()
