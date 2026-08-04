from typing import Optional

from django.apps import apps
from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser
from django.db.models import Model
from django.db.models.query import QuerySet
from rest_framework.exceptions import PermissionDenied

from ansible_base.lib.utils.models import is_add_perm
from ansible_base.lib.utils.settings import get_setting
from ansible_base.rbac.evaluations import has_super_permission
from ansible_base.rbac.models import DABPermission, ObjectRole
from ansible_base.rbac.permission_registry import permission_registry
from ansible_base.rbac.remote import RemoteObject
from ansible_base.rbac.validators import permissions_allowed_for_role


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


def check_content_obj_permission(request_user, obj) -> None:
    """Permission policy rules for giving or removing obj permission

    User must hold all object-level permissions for the model to manage
    role assignments on that object. This prevents privilege escalation
    where a user with partial permissions (e.g. change but not execute)
    could assign themselves a role containing permissions they lack.
    """
    if isinstance(obj, RemoteObject):
        # we retain this check: Gateway uses this to skip enforcing permissions on objects
        # it considers remote like JobTemplates, Inventories etc.
        if not get_setting('ANSIBLE_BASE_ENFORCE_REMOTE_OBJECT_PERMISSIONS', True):
            return
        for permission in DABPermission.objects.filter(content_type=obj.content_type):
            # we need to skip checking add permissions: they are not meant for remote objects but
            # are evaluated at a higher level (organization). Checking here would raise a RuntimeError.
            if is_add_perm(permission.codename):
                continue

            # to add or remove role assignments to remote objects, the user is required to hold
            # *every* permission that exists for this model (except add). This prevents users
            # with insufficient permission from assigning themselves a role containing permissions they lack.
            if not request_user.has_obj_perm(obj, permission.codename):
                raise PermissionDenied
        return

    # Non-remote objects: again, the user must hold *every* (non-add) permission in order to change
    # role assignments
    cls = type(obj)
    for codename in permissions_allowed_for_role(cls)[cls]:
        if not request_user.has_obj_perm(obj, codename):
            raise PermissionDenied


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
