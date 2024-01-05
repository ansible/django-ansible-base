from django.conf import settings
from django.contrib.auth import get_user_model
from django.db.models.signals import post_migrate
from django.utils.functional import cached_property

"""
This will record the models that the RBAC system in this app will follow
Other apps should register models with this pattern

from ansible_base.utils.permission_registry import permission_registry

permission_registry.register(MyModel, AnotherModel)
"""


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
                raise Exception(f'model {cls._meta.model_name} already in registry?!')

    def track_relationship(self, cls, relationship, role_name):
        self._tracked_relationships.add((cls, relationship, role_name))

    def get_model_name(self, model_name_or_model):
        if isinstance(model_name_or_model, str):
            return model_name_or_model
        # assume Model instance
        return model_name_or_model._meta.model_name

    def get_parent_model(self, model_name_or_model):
        parent_field_name = self.get_parent_fd_name(self.get_model_name(model_name_or_model))
        if parent_field_name is None:
            return None
        return self._name_to_model[parent_field_name]

    def get_parent_fd_name(self, model_name_or_model):
        return self._parent_fields.get(self.get_model_name(model_name_or_model))

    def get_child_models(self, model_name_or_model, seen=None):
        """
        Returns a set of tuples that give the filter args and the model for child resources
        """
        if not seen:
            seen = set()
        child_filters = []
        parent_model_name = self.get_model_name(model_name_or_model)
        for model_name, parent_field_name in self._parent_fields.items():
            # NOTE: right now this only supports names that are the same as the type
            if parent_field_name == parent_model_name:
                if model_name in seen:
                    continue
                seen.add(model_name)
                child_model = self._name_to_model[model_name]
                child_filters.append((parent_field_name, child_model))
                for next_parent_filter, grandchild_model in self.get_child_models(child_model, seen=seen):
                    child_filters.append((f'{next_parent_filter}__{parent_field_name}', grandchild_model))
        return child_filters

    def call_when_apps_ready(self, apps):
        from ansible_base.rbac.evaluations import bound_has_obj_perm, bound_singleton_permissions, connect_rbac_methods
        from ansible_base.rbac.triggers import TrackedRelationship, connect_rbac_signals, post_migration_rbac_setup

        self.apps = apps
        self.apps_ready = True

        if self.team_model not in self._registry:
            self._registry.add(self.team_model)

        post_migrate.connect(post_migration_rbac_setup, sender=self)

        self.user_model.add_to_class('has_obj_perm', bound_has_obj_perm)
        self.user_model.add_to_class('singleton_permissions', bound_singleton_permissions)

        for cls in self._registry:
            connect_rbac_signals(cls)
            connect_rbac_methods(cls)

        for cls, relationship, role_name in self._tracked_relationships:
            if role_name in self._trackers:
                tracker = self._trackers[role_name]
            else:
                tracker = TrackedRelationship(cls, role_name)
                self._trackers[role_name] = tracker
            tracker.initialize(relationship)

    @cached_property
    def team_model(self):
        return self.apps.get_model(settings.ROLE_TEAM_MODEL)

    @cached_property
    def team_ct_id(self):
        return self.apps.get_model('contenttypes.ContentType').objects.get_for_model(self.team_model).id

    @cached_property
    def user_model(self):
        return get_user_model()

    @cached_property
    def org_ct_id(self):
        team_parent_model = self.get_parent_model(self.team_model)
        return self.apps.get_model('contenttypes.ContentType').objects.get_for_model(team_parent_model).id

    @cached_property
    def permission_model(self):
        return self.apps.get_model(settings.ROLE_PERMISSION_MODEL)

    @cached_property
    def team_permission(self):
        return f'member_{self.team_model._meta.model_name}'

    @property
    def all_registered_models(self):
        return [cls for cls in self._registry]


permission_registry = PermissionRegistry()
