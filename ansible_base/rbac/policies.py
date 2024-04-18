from django.apps import apps
from django.conf import settings
from django.db.models.query import QuerySet
from rest_framework.exceptions import PermissionDenied

from ansible_base.lib.utils.settings import get_setting
from ansible_base.rbac.evaluations import has_super_permission
from ansible_base.rbac.models import ObjectRole
from ansible_base.rbac.validators import permissions_allowed_for_role


def visible_users(request_user) -> QuerySet:
    "Gives a queryset of users that another user should be able to view"
    user_cls = apps.get_model(settings.AUTH_USER_MODEL)
    org_cls = apps.get_model(settings.ANSIBLE_BASE_ORGANIZATION_MODEL)

    if has_super_permission(request_user, 'view') or (
        get_setting('ORG_ADMINS_CAN_SEE_ALL_USERS', False) and org_cls.access_ids_qs(request_user, 'change').exists()
    ):
        return user_cls.objects.all()

    object_id_fd = ObjectRole._meta.get_field('object_id')
    members_of_visble_orgs = ObjectRole.objects.filter(
        role_definition__permissions__codename='member_organization', object_id__in=org_cls.access_ids_qs(request_user, 'view', cast_field=object_id_fd)
    ).values('users')
    return (
        user_cls.objects.filter(pk__in=members_of_visble_orgs) | user_cls.objects.filter(pk=request_user.id) | user_cls.objects.filter(is_superuser=True)
    ).distinct()


def can_change_user(request_user, target_user) -> bool:
    if request_user.is_superuser:
        return True

    if not get_setting('MANAGE_ORGANIZATION_AUTH', False):
        return False

    org_cls = apps.get_model(settings.ANSIBLE_BASE_ORGANIZATION_MODEL)
    return not org_cls.access_qs(target_user, 'member_organization').exclude(pk__in=org_cls.access_ids_qs(request_user, 'change_organization')).exists()


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
                raise PermissionDenied({'detail': f'You do not have {codename} permission the object'})
