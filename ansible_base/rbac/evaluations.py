from django.conf import settings

from ansible_base.models.rbac import ObjectRole, RoleEvaluation
from ansible_base.rbac import permission_registry

'''
The model RoleEvaluation is the authority for making any permission evaluations,
meaning, determining whether a user has a permission to an object.

Methods needed for producing querysets (of objects a user has a permission to
or users that have a permission to an object) or making single evaluations
are defined on the RoleEvaluation model.

This module has logic to attach those evaluation methods to the external
models in an app using these RBAC internals.
'''


def validate_codename_for_model(codename, model):
    if '_' not in codename:
        # convience to call JobTemplate.accessible_objects(u, 'execute')
        name = f'{codename}_{model._meta.model_name}'
    else:
        name = codename
    if name.startswith('add'):
        if model._meta.model_name != 'organization':
            raise RuntimeError(f'Add permissions only valid for organization, received for {model._meta.model_name}')
    else:
        if (name not in [t[0] for t in model._meta.permissions]) and (name.split('_', 1)[0] not in model._meta.default_permissions):
            raise RuntimeError(f'The permission {name} is not valid for model {model._meta.model_name}')
    return name


class BaseEvaluationDescriptor:
    '''
    Descriptors have to be used to attach what are effectively a @classmethod
    to an external model, like MyModel.accessible_objects(u, 'view_mymodel')
    because this how we obtain a reference to MyModel
    '''

    def __init__(self, cls):
        self.cls = cls


def has_super_permission(user, codename):
    if user._meta.model_name != permission_registry.user_model._meta.model_name:
        if user._meta.model_name == permission_registry.team_model._meta.model_name:
            return False  # Super permission flags only exist for users, teams can use global roles
        else:
            raise RuntimeError(f'Evaluation methods are for users or teams, got {user._meta.model_name}: {user}')
    for super_flag in settings.ROLE_BYPASS_SUPERUSER_FLAGS:
        if getattr(user, super_flag):
            return True
    for action, super_flag in settings.ROLE_BYPASS_ACTION_FLAGS.items():
        if codename.startswith(action) and getattr(user, super_flag):
            return True
    return False


class AccessibleObjectsDescriptor(BaseEvaluationDescriptor):
    def __call__(self, user, codename, **kwargs):
        full_codename = validate_codename_for_model(codename, self.cls)
        if has_super_permission(user, codename):
            return self.cls.objects.all()
        return RoleEvaluation.accessible_objects(self.cls, user, full_codename, **kwargs)


class AccessibleIdsDescriptor(BaseEvaluationDescriptor):
    def __call__(self, user, codename, **kwargs):
        full_codename = validate_codename_for_model(codename, self.cls)
        if has_super_permission(user, codename):
            return self.cls.objects.values_list('id', flat=True)  # hopefully we never need this...
        return RoleEvaluation.accessible_ids(self.cls, user, full_codename, **kwargs)


def bound_has_obj_perm(self, obj, codename):
    full_codename = validate_codename_for_model(codename, obj)
    if has_super_permission(self, codename):
        return True
    if full_codename in self.singleton_permissions():
        return True
    return RoleEvaluation.has_obj_perm(self, obj, full_codename)


def bound_singleton_permissions(self):
    if hasattr(self, '_singleton_permissions'):
        return self._singleton_permissions
    perm_set = set()
    if settings.ROLE_SINGLETON_USER_RELATIONSHIP:
        field = permission_registry.user_model._meta.get_field(settings.ROLE_SINGLETON_USER_RELATIONSHIP)
        reverse_name = field.remote_field.name
        perm_set.update(
            set(permission_registry.permission_model.objects.filter(**{f'roledefinition__{reverse_name}': self}).values_list('codename', flat=True))
        )
    if settings.ROLE_SINGLETON_TEAM_RELATIONSHIP:
        field = permission_registry.team_model._meta.get_field(settings.ROLE_SINGLETON_TEAM_RELATIONSHIP)
        reverse_name = field.remote_field.name
        all_user_teams_qs = permission_registry.team_model.objects.filter(member_roles__in=ObjectRole.objects.filter(users=self))
        perm_set.update(
            set(
                permission_registry.permission_model.objects.filter(**{f'roledefinition__{reverse_name}__in': all_user_teams_qs}).values_list(
                    'codename', flat=True
                )
            )
        )
    return perm_set


def connect_rbac_methods(cls):
    cls.add_to_class('new_accessible_objects', AccessibleObjectsDescriptor(cls))
    cls.add_to_class('accessible_ids', AccessibleIdsDescriptor(cls))
