import inspect
from typing import Iterable, Optional, Type

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.db.models.functions import Cast
from django.db.models.query import QuerySet
from rest_framework.serializers import ValidationError

from ansible_base.rbac import permission_registry
from ansible_base.rbac.models import DABPermission, RoleDefinition, get_evaluation_model
from ansible_base.rbac.validators import validate_codename_for_model

from .remote import RemoteObject

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
    def __call__(self, actor, codename: str = 'view', content_types: Optional[Iterable[int]] = None, cast_field=None) -> QuerySet:
        full_codename = validate_codename_for_model(codename, self.cls)
        if isinstance(actor, AnonymousUser):
            return self.cls.objects.none().values_list()
        if actor._meta.model_name == 'user' and has_super_permission(actor, full_codename):
            if cast_field is None:
                return self.cls.objects.values_list('id', flat=True)
            else:
                return self.cls.objects.values_list(Cast('id', output_field=cast_field), flat=True)
        return get_evaluation_model(self.cls).accessible_ids(self.cls, actor, full_codename, content_types=content_types, cast_field=cast_field)


def remote_obj_id_qs(actor, remote_cls: Type[RemoteObject], codename: str = 'view', content_types: Optional[Iterable[int]] = None, cast_field=None) -> QuerySet:
    """Returns a queryset of ids for a remote object"""
    full_codename = validate_codename_for_model(codename, remote_cls)
    evaluation_model = get_evaluation_model(remote_cls)
    if isinstance(actor, AnonymousUser):
        return evaluation_model.objects.none().values_list('object_id')
    if actor._meta.model_name == 'user' and has_super_permission(actor, full_codename):
        # Return all known objects on this server, some objects on remote server may not be known
        if content_types:
            filter_kwargs = {'content_type_id__in': content_types}
        else:
            filter_kwargs = {'content_type': remote_cls.get_ct_from_type()}
        if cast_field is None:
            return evaluation_model.objects.filter(**filter_kwargs).values_list('object_id').distinct()
        else:
            return evaluation_model.objects.filter(**filter_kwargs).values_list(Cast('object_id', output_field=cast_field)).distinct()
    return evaluation_model.accessible_ids(remote_cls, actor, full_codename, content_types=content_types, cast_field=cast_field)


def bound_has_obj_perm(self, obj, codename) -> bool:
    from ansible_base.rbac.caching import defer_rbac_state

    if defer_rbac_state.active and defer_rbac_state.has_deferred_data:
        raise RuntimeError(
            "has_obj_perm cannot be called inside defer_rbac_computations after resources have been created or deleted. Evaluations may be stale."
        )
    if (inspect.isclass(obj) and issubclass(obj, RemoteObject)) or isinstance(obj, RemoteObject):
        pass  # no need to validate remote content type, assumed we have content type entry already
    elif not permission_registry.is_registered(obj):
        raise ValidationError(f'Object of {obj._meta.model_name} type is not registered with DAB RBAC')
    full_codename = validate_codename_for_model(codename, obj)
    if has_super_permission(self, full_codename):
        return True
    return get_evaluation_model(obj).has_obj_perm(self, obj, full_codename)


def connect_rbac_methods(cls):
    cls.add_to_class('access_qs', AccessibleObjectsDescriptor(cls))
    cls.add_to_class('access_ids_qs', AccessibleIdsDescriptor(cls))
