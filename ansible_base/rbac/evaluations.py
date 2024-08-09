from typing import Optional

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.db.models.functions import Cast
from django.db.models.query import QuerySet
from rest_framework.serializers import ValidationError

from ansible_base.rbac import permission_registry
from ansible_base.rbac.models import DABPermission, RoleDefinition, get_evaluation_model
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
    if isinstance(user, AnonymousUser):
        return False

    if user._meta.model_name == permission_registry.user_model._meta.model_name:
        # Super permission flags only exist for users, teams can use global roles
        for super_flag in settings.ANSIBLE_BASE_BYPASS_SUPERUSER_FLAGS:
            if getattr(user, super_flag):
                return True  # User has admin flag like is_superuser
        if full_codename:
            for action, super_flag in settings.ANSIBLE_BASE_BYPASS_ACTION_FLAGS.items():
                if full_codename == action and getattr(user, super_flag):
                    return True  # User has action-specific flag like is_platform_auditor
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
        permission_qs = DABPermission.objects.values_list('codename', flat=True)
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
    def __call__(self, actor, codename: str = 'view', queryset: Optional[QuerySet] = None) -> QuerySet:
        if queryset is None:
            queryset = self.cls.objects.all()
        if isinstance(actor, AnonymousUser):
            return queryset.model.objects.none()
        if codename == 'view' and ('view' not in self.cls._meta.default_permissions):
            # Model does not track view permissions
            return queryset
        full_codename = validate_codename_for_model(codename, self.cls)
        if actor._meta.model_name == 'user' and has_super_permission(actor, full_codename):
            return queryset
        return get_evaluation_model(self.cls).accessible_objects(self.cls, actor, full_codename, queryset=queryset)


class AccessibleIdsDescriptor(BaseEvaluationDescriptor):
    def __call__(self, actor, codename: str = 'view', content_types=None, cast_field=None) -> QuerySet:
        full_codename = validate_codename_for_model(codename, self.cls)
        if isinstance(actor, AnonymousUser):
            return self.cls.objects.none().values_list()
        if actor._meta.model_name == 'user' and has_super_permission(actor, full_codename):
            if cast_field is None:
                return self.cls.objects.values_list('id', flat=True)
            else:
                return self.cls.objects.values_list(Cast('id', output_field=cast_field), flat=True)
        return get_evaluation_model(self.cls).accessible_ids(self.cls, actor, full_codename, content_types=content_types, cast_field=cast_field)


def bound_has_obj_perm(self, obj, codename) -> bool:
    if not permission_registry.is_registered(obj):
        raise ValidationError(f'Object of {obj._meta.model_name} type is not registered with DAB RBAC')
    full_codename = validate_codename_for_model(codename, obj)
    if has_super_permission(self, full_codename):
        return True
    return get_evaluation_model(obj).has_obj_perm(self, obj, full_codename)


def connect_rbac_methods(cls):
    cls.add_to_class('access_qs', AccessibleObjectsDescriptor(cls))
    cls.add_to_class('access_ids_qs', AccessibleIdsDescriptor(cls))
