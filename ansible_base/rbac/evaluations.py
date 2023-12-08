from django.conf import settings

from ansible_base.rbac import permission_registry
from ansible_base.rbac.models import RoleDefinition, get_evaluation_model
from ansible_base.rbac.validators import validate_codename_for_model

"""
RoleEvaluation or RoleEvaluationUUID models are the authority for permission evaluations,
meaning, determining whether a user has a permission to an object.

Methods needed for producing querysets (of objects a user has a permission to
or users that have a permission to an object) or making single evaluations
are defined on the RoleEvaluation model.

This module has logic to attach those evaluation methods to the external
models in an app using these RBAC internals.
"""


def has_super_permission(user, full_codename=None) -> bool:
    "Analog to has_obj_perm but only evaluates to True if user has this permission system-wide"
    if user._meta.model_name == permission_registry.user_model._meta.model_name:
        # Super permission flags only exist for users, teams can use global roles
        for super_flag in settings.ANSIBLE_BASE_BYPASS_SUPERUSER_FLAGS:
            if getattr(user, super_flag):
                return True  # User has admin flag like is_superuser
        if full_codename:
            for action, super_flag in settings.ANSIBLE_BASE_BYPASS_ACTION_FLAGS.items():
                if full_codename == action and getattr(user, super_flag):
                    return True  # User has action-specific flag like is_system_auditor
    elif user._meta.model_name != permission_registry.team_model._meta.model_name:
        raise RuntimeError(f'Evaluation methods are for users or teams, got {user._meta.model_name}: {user}')

    if full_codename:
        if full_codename in user.singleton_permissions():
            return True  # User has system role for this action
    return False


def bound_singleton_permissions(self):
    "Method attached to User model as singleton_permissions"
    if not hasattr(self, '_singleton_permissions') or bound_singleton_permissions._team_clear_signal:
        # values_list will make the return type set[str]
        permission_qs = permission_registry.permission_model.objects.values_list('codename', flat=True)
        self._singleton_permissions = RoleDefinition.user_global_permissions(self, permission_qs=permission_qs)
        bound_singleton_permissions._team_clear_signal = False
    return self._singleton_permissions


bound_singleton_permissions._team_clear_signal = False


class BaseEvaluationDescriptor:
    """
    Descriptors have to be used to attach what are effectively a @classmethod
    to an external model, like MyModel.accessible_objects(u, 'view_mymodel')
    because this how we obtain a reference to MyModel
    """

    def __init__(self, cls):
        self.cls = cls


class AccessibleObjectsDescriptor(BaseEvaluationDescriptor):
    def __call__(self, user, codename='view', **kwargs):
        full_codename = validate_codename_for_model(codename, self.cls)
        if has_super_permission(user, full_codename):
            return self.cls.objects.all()
        return get_evaluation_model(self.cls).accessible_objects(self.cls, user, full_codename, **kwargs)


class AccessibleIdsDescriptor(BaseEvaluationDescriptor):
    def __call__(self, user, codename, **kwargs):
        full_codename = validate_codename_for_model(codename, self.cls)
        if has_super_permission(user, full_codename):
            return self.cls.objects.values_list('id', flat=True)
        return get_evaluation_model(self.cls).accessible_ids(self.cls, user, full_codename, **kwargs)


def bound_has_obj_perm(self, obj, codename) -> bool:
    full_codename = validate_codename_for_model(codename, obj)
    if has_super_permission(self, full_codename):
        return True
    return get_evaluation_model(obj).has_obj_perm(self, obj, full_codename)


def connect_rbac_methods(cls):
    cls.add_to_class('access_qs', AccessibleObjectsDescriptor(cls))
    cls.add_to_class('access_ids_qs', AccessibleIdsDescriptor(cls))
