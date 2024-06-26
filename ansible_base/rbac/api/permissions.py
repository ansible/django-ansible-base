import logging

from django.apps import apps
from django.conf import settings
from django.db.models import Model
from django.http import Http404
from django.utils.translation import gettext_lazy as _
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import SAFE_METHODS, BasePermission, DjangoObjectPermissions

from ansible_base.lib.utils.models import is_add_perm
from ansible_base.lib.utils.settings import get_setting
from ansible_base.rbac import permission_registry
from ansible_base.rbac.evaluations import has_super_permission
from ansible_base.rbac.policies import can_change_user

logger = logging.getLogger('ansible_base.rbac.api.permissions')


class IsSystemAdminOrAuditor(BasePermission):
    """
    Allows write access only to system admin users.
    Allows read access only to system auditor users.
    """

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return has_super_permission(request.user, 'view')
        return has_super_permission(request.user)


class AuthenticatedReadAdminChange(IsSystemAdminOrAuditor):
    "Any authenticated user can view, but only admin users can do CRUD"

    def has_permission(self, request, view):
        if not (request.user and request.user.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return has_super_permission(request.user)


def is_cloned_request(request) -> bool:
    """Tells whether this is a fake request

    The DRF API browser and schema generators call permission methods
    multiple times for form generation purposes.
    In these cases, a request wrapps the original and the method will not match.
    """
    return bool(request.method != request._request.method)


class RoleDefinitionPermissions(AuthenticatedReadAdminChange):
    def has_permission(self, request, view):
        if is_cloned_request(request) and settings.ANSIBLE_BASE_ALLOW_CUSTOM_ROLES is False:
            return False
        return super().has_permission(request, view)


class AnsibleBaseObjectPermissions(DjangoObjectPermissions):
    def has_create_permission(self, request, model_cls) -> bool:
        "Does the request user absolutely have permission to create an object via superuser or system role"
        full_codename = f'add_{model_cls._meta.model_name}'
        return has_super_permission(request.user, full_codename)

    def abstract_create_permission(self, request, model_cls) -> bool:
        "Abstractly, without knowing the request data, could the request user theoretically create an object"
        parent_model = permission_registry.get_parent_model(model_cls)
        if parent_model is None:
            return self.has_create_permission(request, model_cls)
        else:
            if request.user.is_superuser:
                return True  # special case only for superuser when no objects exist
            return parent_model.access_qs(request.user, f'add_{model_cls._meta.model_name}').exists()

    def has_permission(self, request, view):
        "Some of this comes from ModelAccessPermission. We assume user.permissions is unused"
        if not request.user or (not request.user.is_authenticated and self.authenticated_users_only):
            return False

        # Workaround to ensure DjangoModelPermissions are not applied
        # to the root view when using DefaultRouter.
        if getattr(view, '_ignore_model_permissions', False):
            return True

        # Following is DAB RBAC specific, handle add permission checking
        if request.method == 'POST' and view.action == 'create':
            model_cls = self._queryset(view).model
            parent_field_name = permission_registry.get_parent_fd_name(model_cls)
            if parent_field_name is None:
                result = self.has_create_permission(request, model_cls)
                if (not result) and (not is_cloned_request(request)):
                    logger.warning(f'User {request.user.pk} lacks global add_{model_cls._meta.model_name} permission to create {model_cls._meta.model_name}')
                return result
        elif request.method == 'POST' and is_cloned_request(request):
            # If this is OPTIONS purposes
            # return a speculative answer about whether user might be generally able to create
            model_cls = self._queryset(view).model
            return self.abstract_create_permission(request, model_cls)

        # We are not checking many things here, a GET to list views can return 0 objects
        return True

    def get_required_object_permissions(self, method, model_cls, view=None):
        special_action = getattr(view, 'rbac_action', None)
        if special_action:
            return [f'{special_action}_{model_cls._meta.model_name}']
        perms = super().get_required_object_permissions(method, model_cls)
        # Remove add permissions, since they are handled in has_permission
        return [p for p in perms if not is_add_perm(p)]

    def has_object_permission_by_codename(self, request, obj, perms):
        return all(request.user.has_obj_perm(obj, perm) for perm in perms)

    def model_is_valid(self, model_cls):
        return permission_registry.is_registered(model_cls)

    def has_object_permission(self, request, view, obj):
        if not isinstance(obj, Model):
            logger.info(f'Object-permission check called with non-object {type(obj)} for {request.method}')
            return True  # for the DRF browsable API, showing PATCH form field

        queryset = self._queryset(view)
        model_cls = queryset.model
        if not self.model_is_valid(model_cls):
            if request.user.is_superuser:
                return True
            logger.warning(f'User {request.user.pk} denied {request.method} to {obj._meta.model_name}, not in DAB RBAC permission registry')
            raise Http404

        perms = self.get_required_object_permissions(request.method, model_cls, view=view)

        if not self.has_object_permission_by_codename(request, obj, perms):
            # If the user does not have permissions we need to determine if
            # they have read permissions to see 403, or not, and simply see
            # a 404 response.
            if not is_cloned_request(request):
                logger.warning(f'User {request.user.pk} lacks {perms} permission to obj {obj._meta.model_name}-{obj.pk}')

            if request.method in SAFE_METHODS:
                # Read permissions already checked and failed, no need
                # to make another lookup.
                raise Http404

            read_perms = self.get_required_object_permissions('GET', model_cls)
            if not all(request.user.has_obj_perm(obj, perm) for perm in read_perms):
                raise Http404

            # Has read permissions.
            return False

        return True


class AnsibleBaseUserPermissions(AnsibleBaseObjectPermissions):
    def model_is_valid(self, model_cls):
        return bool(model_cls._meta.model_name == 'user')

    def has_create_permission(self, request, model_cls):
        org_cls = apps.get_model(settings.ANSIBLE_BASE_ORGANIZATION_MODEL)

        if request.user.is_superuser:
            return True

        if not get_setting('MANAGE_ORGANIZATION_AUTH', False):
            return False

        return org_cls.access_qs(request.user, 'change_organization').exists()

    def abstract_create_permission(self, request, model_cls):
        # For users, only, ability to create a new user does not depend on the data
        return self.has_create_permission(request, model_cls)

    def has_object_permission_by_codename(self, request, obj, perms):
        if perms:
            if request.method == 'DELETE' and request.user.pk == obj.pk:
                raise PermissionDenied({'detail': _("You can't delete yourself")})
            return can_change_user(request.user, obj)
        return True
