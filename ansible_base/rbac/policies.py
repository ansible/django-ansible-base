from django.apps import apps
from django.conf import settings
from django.db.models import Model
from django.db.models.query import QuerySet
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import PermissionDenied

from ansible_base.lib.utils.settings import get_setting
from ansible_base.rbac.evaluations import has_super_permission
from ansible_base.rbac.models import ObjectRole
from ansible_base.rbac.permission_registry import permission_registry
from ansible_base.rbac.validators import permissions_allowed_for_role


def visible_users(request_user, queryset=None, always_show_superusers=True, always_show_self=True) -> QuerySet:
    """Gives a queryset of users that another user should be able to view"""
    user_cls = permission_registry.user_model
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


def can_change_user(request_user, target_user) -> bool:
    """Tells if the request user can modify details of the target user"""
    if request_user.is_superuser:
        return True
    elif target_user.is_superuser:
        return False  # target is a superuser and request user is not

    if not get_setting('MANAGE_ORGANIZATION_AUTH', False):
        return False

    # All users can change their own password and other details
    if request_user.pk == target_user.pk:
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

    Right now we are not supporting a separate permission to manage permission
    on objects, so we firstly look to a simple matter of having change permission
    If that is not available, then we check all object-level permissions.
    """
    if 'change' in obj._meta.default_permissions:
        # Model has no change permission, so user must have all permissions for the applicable model
        if not request_user.has_obj_perm(obj, 'change'):
            raise PermissionDenied
    else:
        cls = type(obj)
        for codename in permissions_allowed_for_role(cls)[cls]:
            if not request_user.has_obj_perm(obj, codename):
                raise PermissionDenied({'detail': _('You do not have {codename} permission the object').format(codename=codename)})


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
