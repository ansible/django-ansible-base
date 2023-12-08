import logging

from django.db.models import Model
from django.http import Http404
from rest_framework.permissions import SAFE_METHODS, BasePermission, DjangoObjectPermissions

from ansible_base.lib.utils.models import is_add_perm
from ansible_base.rbac import permission_registry
from ansible_base.rbac.evaluations import has_super_permission

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


class AnsibleBaseObjectPermissions(DjangoObjectPermissions):

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
            # Identify cloned requests used by API browser
            # the renderer class calls show_form_for_method which checks POST permissions
            # on a GET request about whether to show the POST form
            # philosophy is that all users have the abstract ability to post
            # and the object permissions (data) tells whether it is possible
            if request.method != request._request.method and (not request.data):
                return True

            model_cls = self._queryset(view).model
            full_codename = f'add_{model_cls._meta.model_name}'
            parent_field_name = permission_registry.get_parent_fd_name(model_cls)
            if parent_field_name is None or parent_field_name not in request.data:
                return has_super_permission(request.user, full_codename)

            parent_model = permission_registry.get_parent_model(model_cls)
            parent_obj = parent_model.objects.get(pk=request.data[parent_field_name])
            return request.user.has_obj_perm(parent_obj, full_codename)

        # We are not checking many things here, a GET to list views can return 0 objects
        return True

    def get_required_object_permissions(self, method, model_cls, view=None):
        special_action = getattr(view, 'rbac_action', None)
        if special_action:
            return [f'{special_action}_{model_cls._meta.model_name}']
        perms = super().get_required_object_permissions(method, model_cls)
        # Remove add permissions, since they are handled in has_permission
        return [p for p in perms if not is_add_perm(p)]

    def has_object_permission(self, request, view, obj):
        if not isinstance(obj, Model):
            logger.info(f'Object-permission check called with non-object {type(obj)} for {request.method}')
            return True  # for the DRF browsable API, showing PATCH form field

        queryset = self._queryset(view)
        model_cls = queryset.model
        user = request.user

        perms = self.get_required_object_permissions(request.method, model_cls, view=view)

        if not all(user.has_obj_perm(obj, perm) for perm in perms):
            # If the user does not have permissions we need to determine if
            # they have read permissions to see 403, or not, and simply see
            # a 404 response.

            if request.method in SAFE_METHODS:
                # Read permissions already checked and failed, no need
                # to make another lookup.
                raise Http404

            read_perms = self.get_required_object_permissions('GET', model_cls)
            if not all(user.has_obj_perm(obj, perm) for perm in read_perms):
                raise Http404

            # Has read permissions.
            return False

        return True
