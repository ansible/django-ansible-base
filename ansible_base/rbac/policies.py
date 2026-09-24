from typing import Optional

from django.apps import apps
from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser
from django.db.models import Model, Q
from django.db.models.query import QuerySet
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import PermissionDenied

from ansible_base.lib.utils.settings import get_setting
from ansible_base.rbac.evaluations import has_super_permission
from ansible_base.rbac.models import DABContentType, DABPermission, ObjectRole
from ansible_base.rbac.permission_registry import permission_registry
from ansible_base.rbac.remote import RemoteObject
from ansible_base.rbac.validators import permissions_allowed_for_role

ContentObject = Model | RemoteObject


def visible_users(request_user, queryset=None, always_show_superusers=True, always_show_self=True) -> QuerySet:
    """Gives a queryset of users that another user should be able to view"""
    user_cls = permission_registry.user_model

    if not getattr(request_user, "is_authenticated", False):
        return user_cls.objects.none()

    org_cls = apps.get_model(settings.ANSIBLE_BASE_ORGANIZATION_MODEL)

    if can_view_all_users(request_user):
        if queryset is not None:
            return queryset
        else:
            return user_cls.objects.all()

    object_id_fd = ObjectRole._meta.get_field('object_id')
    members_of_visible_orgs = ObjectRole.objects.filter(
        role_definition__permissions__codename='member_organization', object_id__in=org_cls.access_ids_qs(request_user, 'view', cast_field=object_id_fd)
    ).values('users')
    if queryset is None:
        queryset = user_cls.objects

    queryset = queryset.filter(pk__in=members_of_visible_orgs)
    if always_show_superusers:
        queryset = queryset | user_cls.objects.filter(is_superuser=True)
    if always_show_self:
        queryset = queryset | user_cls.objects.filter(pk=request_user.id)
    return queryset.distinct()


def can_view_all_users(request_user):
    org_cls = apps.get_model(settings.ANSIBLE_BASE_ORGANIZATION_MODEL)

    return has_super_permission(request_user, 'view') or (
        get_setting('ORG_ADMINS_CAN_SEE_ALL_USERS', False) and org_cls.access_ids_qs(request_user, 'change').exists()
    )


def can_change_user(request_user: Optional[AbstractBaseUser], target_user: Optional[AbstractBaseUser], can_self_edit: bool = True) -> bool:
    """Tells if the request user can modify details of the target user"""
    if request_user is None or target_user is None:
        return False

    if request_user.is_superuser:
        return True
    elif target_user.is_superuser:
        return False  # target is a superuser and request user is not

    if not get_setting('MANAGE_ORGANIZATION_AUTH', False):
        return False

    if request_user.pk == target_user.pk and (can_self_edit or get_setting('ALLOW_USER_EMAIL_SELF_EDIT', False)):
        return True

    # If the user is not in any organizations, answer can not consider organization permissions
    org_cls = apps.get_model(settings.ANSIBLE_BASE_ORGANIZATION_MODEL)
    target_user_orgs = org_cls.access_qs(target_user, 'member_organization')
    if not target_user_orgs.exists():
        return request_user.is_superuser

    # Organization admins can manage users in their organization
    # this requires change permission to all organizations the target user is a member of
    return not target_user_orgs.exclude(pk__in=org_cls.access_ids_qs(request_user, 'change_organization')).exists()


def _model_has_permission_action(cls: type[Model], action: str) -> bool:
    """Check if a model has a permission for the given action (default or custom)"""
    if action in cls._meta.default_permissions:
        return True
    codename = f'{action}_{cls._meta.model_name}'
    return any(code == codename for code, _ in cls._meta.permissions)


def _check_all_obj_permissions(request_user: Model, obj: ContentObject) -> None:
    """Require user to have all object-level permissions"""
    cls = type(obj)
    for codename in permissions_allowed_for_role(cls)[cls]:
        if not request_user.has_obj_perm(obj, codename):
            raise PermissionDenied({'detail': _('You do not have {codename} permission the object').format(codename=codename)})


def _user_permission_ids_from_role_definitions(request_user: Model, obj: ContentObject) -> set[int]:
    """Get permission IDs a user holds on an object by inspecting role definitions directly.

    This is an alternative to has_obj_perm for the escalation check, needed when
    ANSIBLE_BASE_CACHE_PARENT_PERMISSIONS is False (the default). In that case,
    child-model permissions (e.g. view_team in an org-scoped role) do not get
    RoleEvaluation entries on the parent object, so has_obj_perm(org, 'view_team')
    returns False even though the user's role definition includes that permission.

    This function bypasses the evaluation table entirely and instead queries which
    RoleDefinitions the user holds on the object — directly or via team membership —
    and collects their declared permissions.
    """
    ct = DABContentType.objects.get_for_model(obj)
    user_teams = permission_registry.team_model.objects.filter(member_roles__users=request_user)
    obj_roles = ObjectRole.objects.filter(
        content_type_id=ct.id,
        object_id=obj.pk,
    ).filter(Q(users=request_user) | Q(teams__in=user_teams))
    return set(DABPermission.objects.filter(role_definitions__object_roles__in=obj_roles).values_list('pk', flat=True))


def _check_assignment_permissions_non_cached(request_user: Model, obj: ContentObject, role_definition: Model) -> None:
    """Verify user has every permission contained in the role being assigned.

    For each permission, uses has_obj_perm when the permission's content type matches
    the object (the evaluation table handles this correctly). For cross-content-type
    permissions (e.g. view_team in an org-scoped role), falls back to inspecting
    role definitions directly, since has_obj_perm can't find those entries on a
    mismatched object type.
    """
    role_perms = list(role_definition.permissions.all())

    # has_super_permission covers is_superuser, action-specific bypass flags,
    # and singleton (global) role assignments.
    missing_perms = [p for p in role_perms if not has_super_permission(request_user, p.codename)]
    if not missing_perms:
        return

    obj_ct = DABContentType.objects.get_for_model(obj)
    cross_type_perms = []

    for permission in missing_perms:
        if permission.content_type_id == obj_ct.id:
            if not request_user.has_obj_perm(obj, permission.codename):
                raise PermissionDenied(
                    {'detail': _('You do not have {codename} permission and cannot assign it to others').format(codename=permission.codename)}
                )
        else:
            cross_type_perms.append(permission)

    if cross_type_perms:
        user_perm_ids = _user_permission_ids_from_role_definitions(request_user, obj)
        for permission in cross_type_perms:
            if permission.pk not in user_perm_ids:
                raise PermissionDenied(
                    {'detail': _('You do not have {codename} permission and cannot assign it to others').format(codename=permission.codename)}
                )


def check_content_obj_permission(request_user, obj, role_definition=None) -> None:
    """Permission policy rules for giving or removing obj permission

    Controlled by ANSIBLE_BASE_MANAGE_PERMISSION_ACTION setting:
    - If set to an action (default 'change'), users need that permission to manage role assignments
      AND must have every permission contained in the role being assigned (escalation prevention)
    - If falsy (None or ''), users must have ALL object-level permissions
    If the model does not have the configured action, falls back to requiring all permissions.
    """
    manage_action = get_setting('ANSIBLE_BASE_MANAGE_PERMISSION_ACTION', 'change')

    if isinstance(obj, RemoteObject):
        if not get_setting('ANSIBLE_BASE_ENFORCE_REMOTE_OBJECT_PERMISSIONS', True):
            return
        if manage_action:
            permissions = DABPermission.objects.filter(content_type=obj.content_type)
            for permission in permissions:
                if permission.codename.startswith(manage_action):
                    if not request_user.has_obj_perm(obj, manage_action):
                        raise PermissionDenied
                    if role_definition:
                        _check_assignment_permissions_non_cached(request_user, obj, role_definition)
                    return
        _check_all_obj_permissions(request_user, obj)
    elif manage_action and _model_has_permission_action(type(obj), manage_action):
        if not request_user.has_obj_perm(obj, manage_action):
            raise PermissionDenied
        if role_definition:
            _check_assignment_permissions_non_cached(request_user, obj, role_definition)
    else:
        _check_all_obj_permissions(request_user, obj)


def check_can_remove_assignment(request_user: Model, assignment: Model):
    """Removing a role assignment will OR checks for the actor and the object

    You can remove a permission if you can manage the user or team given the role
    OR, if you have change permission to the content object targeted by the assignment.
    """
    if request_user.is_superuser:
        return

    assignment_model_name = assignment._meta.model_name
    if assignment_model_name == 'roleuserassignment':
        if can_change_user(request_user, assignment.user):
            return
    elif assignment_model_name == 'roleteamassignment':
        if request_user.has_obj_perm(assignment.team, 'change'):
            return
    else:
        raise RuntimeError(f'Assignment model {assignment_model_name} not recognized as a role assignment model')

    # request user is not a manager of the actor of the assignment
    # but can still remove the assignment if they manage the content object it applies to
    if assignment.content_type_id:
        check_content_obj_permission(request_user, assignment.content_object)
    else:
        # Case of a system role with a non-superuser user
        raise PermissionDenied
