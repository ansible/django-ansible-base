import re
from collections import defaultdict
from collections.abc import Iterable
from typing import Optional, Type, Union

from django.conf import settings
from django.db.models import Model
from rest_framework.exceptions import ValidationError

from ansible_base.lib.utils.models import is_add_perm
from ansible_base.rbac.permission_registry import permission_registry


def system_roles_enabled():
    return bool(
        settings.ANSIBLE_BASE_ALLOW_SINGLETON_ROLES_API
        and (settings.ANSIBLE_BASE_ALLOW_SINGLETON_USER_ROLES or settings.ANSIBLE_BASE_ALLOW_SINGLETON_TEAM_ROLES)
    )


def codenames_for_cls(cls) -> list[str]:
    "Helper method that gives the Django permission codenames for a given class"
    return [t[0] for t in cls._meta.permissions] + [f'{act}_{cls._meta.model_name}' for act in cls._meta.default_permissions]


def permissions_allowed_for_system_role() -> dict[type, list[str]]:
    "Permission codenames useable in system-wide roles, which have content_type set to None"
    permissions_by_model = defaultdict(list)
    for cls in sorted(permission_registry.all_registered_models, key=lambda cls: cls._meta.model_name):
        is_team = bool(cls._meta.model_name == 'team')
        for codename in codenames_for_cls(cls):
            if is_team and (not codename.startswith('view')):
                continue  # special exclusion of team object permissions from system-wide roles
            permissions_by_model[cls].append(codename)
    return permissions_by_model


def permissions_allowed_for_role(cls) -> dict[type, list[str]]:
    "Permission codenames valid for a RoleDefinition of given class, organized by permission class"
    if cls is None:
        return permissions_allowed_for_system_role()

    if not permission_registry.is_registered(cls):
        raise ValidationError(f'Django-ansible-base RBAC does not track permissions for model {cls._meta.model_name}')

    # Include direct model permissions (except for add permission)
    permissions_by_model = defaultdict(list)
    permissions_by_model[cls] = [codename for codename in codenames_for_cls(cls) if not is_add_perm(codename)]

    # Include model permissions for all child models, including the add permission
    for rel, child_cls in permission_registry.get_child_models(cls):
        permissions_by_model[child_cls] += codenames_for_cls(child_cls)

    return permissions_by_model


def combine_values(data: dict[type, list[str]]) -> set[str]:
    "Utility method to merge everything in .values() into a single set"
    ret = set()
    for this_list in data.values():
        ret |= set(this_list)
    return ret


def validate_role_definition_enabled(permissions, content_type) -> None:
    """Called by API and managers, raises exception if settings allow this role type

    Like the similar method for assignments, this policies the ANSIBLE_BASE_ALLOW_ settings
    """
    if not settings.ANSIBLE_BASE_ALLOW_CUSTOM_ROLES:
        raise ValidationError('Creating custom roles is disabled')

    if content_type is None and (not system_roles_enabled()):
        raise ValidationError({'content_type': 'System-wide roles are not enabled'})

    if not settings.ANSIBLE_BASE_ALLOW_CUSTOM_TEAM_ROLES and content_type:
        if content_type.id == permission_registry.team_ct_id:
            raise ValidationError('Creating custom roles for teams is disabled')
        for perm in permissions:
            if perm.content_type_id == permission_registry.team_ct_id:
                raise ValidationError('Creating custom roles that include team permissions is disabled')


def validate_permissions_for_model(permissions, content_type: Optional[Model], managed: bool = False) -> None:
    """Validation for creating a RoleDefinition

    This is called by the RoleDefinitionSerializer so clients will get these errors.
    It is also called by manager helper methods like RoleDefinition.objects.create_from_permissions
    which is done as an aid to tests and other apps integrating this library.
    """
    if not managed:
        validate_role_definition_enabled(permissions, content_type)

    codename_list = {perm.codename for perm in permissions}
    if content_type is None and permission_registry.team_permission in codename_list:
        # Special validation case, global team permissions are not allowed in any scenario
        raise ValidationError({'permissions': f'The {permission_registry.team_permission} permission can not be used in global roles'})

    role_model = None
    if content_type:
        role_model = content_type.model_class()
    permissions_by_model = permissions_allowed_for_role(role_model)

    invalid_codenames = codename_list - combine_values(permissions_by_model)
    if invalid_codenames:
        print_codenames = ', '.join(f'"{codename}"' for codename in invalid_codenames)
        print_model = role_model._meta.model_name if role_model else 'global roles'
        raise ValidationError({'permissions': f'Permissions {print_codenames} are not valid for {print_model} roles'})

    # Check that view permission is given for every model that has update/delete/special actions listed
    for cls, valid_model_permissions in permissions_by_model.items():
        if 'view' in cls._meta.default_permissions:
            model_permissions = set(valid_model_permissions) & codename_list
            non_add_model_permissions = {codename for codename in model_permissions if not is_add_perm(codename)}
            if non_add_model_permissions and not any('view' in codename for codename in non_add_model_permissions):
                display_perms = ', '.join(non_add_model_permissions)
                raise ValidationError({'permissions': f'Permissions for model {role_model._meta.verbose_name} needs to include view, got: {display_perms}'})

    # check change edit permissions is given for every model that has update/delete/special actions listed
    for cls, valid_model_permissions in permissions_by_model.items():
        if 'delete' in cls._meta.default_permissions:
            # import pdb; pdb.set_trace()
            model_permissions = set(valid_model_permissions) & codename_list
            non_add_model_permissions = {codename for codename in model_permissions if not is_add_perm(codename)}
            if 'delete' in non_add_model_permissions and not any('change' in codename for codename in non_add_model_permissions):
                display_perms = ', '.join(non_add_model_permissions)
                raise ValidationError({'permissions': f'Permissions for model {role_model._meta.verbose_name} needs to include change, got: {display_perms}'})


def validate_codename_for_model(codename: str, model: Union[Model, Type[Model]]) -> str:
    """Shortcut method and validation to allow action name, codename, or app_name.codename

    This institutes a shortcut for easier use of the evaluation methods
    so that user.has_obj_perm(obj, 'change') is the same as user.has_obj_perm(obj, 'change_inventory')
    assuming obj is an inventory.
    It also tries to protect the user by throwing an error if the permission does not work.
    """
    valid_codenames = codenames_for_cls(model)
    if (not codename.startswith('add')) and codename in valid_codenames:
        return codename
    if re.match(r'^[a-z]+$', codename):
        # convience to call JobTemplate.accessible_objects(u, 'execute')
        name = f'{codename}_{model._meta.model_name}'
    else:
        # sometimes permissions are referred to with the app name, like test_app.say_cow
        if '.' in codename:
            name = codename.split('.')[-1]
        else:
            name = codename
    if name in valid_codenames:
        if name.startswith('add'):
            raise RuntimeError(f'Add permissions only valid for parent models, received for {model._meta.model_name}')
        return name

    for rel, child_cls in permission_registry.get_child_models(model):
        if name in codenames_for_cls(child_cls):
            return name
    raise RuntimeError(f'The permission {name} is not valid for model {model._meta.model_name}')


def validate_team_assignment_enabled(content_type: Optional[Model], has_team_perm: bool = False, has_org_member: bool = False) -> None:
    """Called in role assignment logic, inside RoleDefinition.give_permission

    Raises error if a setting disables the kind of permission being given.
    This mostly deals with team permissions.
    """
    team_team_allowed = settings.ANSIBLE_BASE_ALLOW_TEAM_PARENTS
    team_org_allowed = settings.ANSIBLE_BASE_ALLOW_TEAM_ORG_PERMS
    team_org_member_allowed = settings.ANSIBLE_BASE_ALLOW_TEAM_ORG_MEMBER
    team_org_team_allowed = settings.ANSIBLE_BASE_ALLOW_TEAM_ORG_ADMIN

    if all([team_team_allowed, team_org_allowed, team_org_member_allowed, team_org_team_allowed]):
        return  # Everything is allowed
    team_model_name = permission_registry.team_model._meta.model_name

    if not team_team_allowed and content_type.model == team_model_name:
        raise ValidationError('Assigning team permissions to other teams is not allowed')

    team_parent_model_name = permission_registry.get_parent_model(permission_registry.team_model)._meta.model_name
    if not team_org_allowed and content_type.model == team_parent_model_name:
        raise ValidationError(f'Assigning {team_parent_model_name} permissions to teams is not allowed')

    if (not team_org_member_allowed) and has_org_member:
        raise ValidationError(f'Assigning {team_parent_model_name} member permission to teams is not allowed')

    if not team_org_team_allowed and content_type.model == team_parent_model_name and has_team_perm:
        raise ValidationError(f'Assigning {team_parent_model_name} permissions that manage other teams is not allowed')


def validate_assignment(rd, actor, obj) -> None:
    """General validation for making a role assignment

    This is called programatically in the give_permission and give_global_permission methods.
    Some of this covered by serializers as well by basic field validation and param gathering.
    """
    if actor._meta.model_name not in ('user', 'team'):
        raise ValidationError(f'Cannot give permission to {actor}, must be a user or team')

    obj_ct = permission_registry.content_type_model.objects.get_for_model(obj)
    if obj_ct.id != rd.content_type_id:
        rd_model = getattr(rd.content_type, "model", "global")
        raise ValidationError(f'Role type {rd_model} does not match object {obj_ct.model}')


def check_locally_managed(permissions_qs: Iterable[Model], role_content_type: Optional[Model]) -> None:
    """Can the given role definition be managed here, or is it externally managed

    If the role definition manages permissions on any shared resources, then
    those should be locked down locally.
    This rule is a bridge solution until the RoleDefinition model declares
    explicitly whether it is managed locally or by a remote system.
    """
    if settings.ALLOW_LOCAL_RESOURCE_MANAGEMENT is True:
        return
    for perm in permissions_qs:
        # View permission for shared objects is interpreted as permission to view
        # the resource locally, which is needed to be able to view parent objects
        # For system roles, this exception is not allowed
        if role_content_type and perm.codename.startswith('view'):
            continue
        model = perm.content_type.model_class()
        if permission_registry.get_resource_prefix(model) == 'shared':
            raise ValidationError('Not managed locally, use the resource server instead')
