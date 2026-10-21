from rest_framework.permissions import SAFE_METHODS, BasePermission

from ansible_base.lib.permissions import TokenScopePermission
from ansible_base.lib.utils.models import is_system_user
from ansible_base.lib.utils.settings import get_setting


def try_add_oauth2_scope_permission(permission_classes: list):
    """
    Attach the provider-independent read/write scope permission.

    The legacy helper name remains for callers that were originally scoped to
    local OAuth2. Add the permission only when an authentication mechanism
    capable of producing scoped credentials is installed.
    """
    installed_apps = get_setting("INSTALLED_APPS", [])
    scope_authentication_apps = {"ansible_base.authentication", "ansible_base.oauth2_provider"}
    if scope_authentication_apps.isdisjoint(installed_apps):
        return permission_classes

    return [TokenScopePermission] + permission_classes


def check_service_token_auth(request, view):
    if is_system_user(request.user) and getattr(view, 'allow_service_token', False) is True and request.auth == 'ServiceTokenAuthentication':
        return True
    return False


class IsSuperuser(BasePermission):
    """
    Allows access only to superusers.
    """

    def has_permission(self, request, view):
        if check_service_token_auth(request, view):
            return True

        return bool(request.user and request.user.is_authenticated and request.user.is_superuser)


class IsSuperuserOrAuditor(BasePermission):
    """
    Allows write access only to system admin users.
    Allows read access only to system auditor users.
    """

    def has_permission(self, request, view):
        if check_service_token_auth(request, view):
            return True
        if not (request.user and request.user.is_authenticated):
            return False
        if request.user.is_superuser:
            return True
        if request.method in SAFE_METHODS:
            return getattr(request.user, 'is_platform_auditor', False)
        return False
