from rest_framework.permissions import SAFE_METHODS, BasePermission

from ansible_base.lib.utils.models import is_system_user


def try_add_oauth2_scope_permission(permission_classes: list):
    """
    Attach the provider-independent read/write scope permission.

    The legacy helper name remains for callers that were originally scoped to
    local OAuth2. External Bearer credentials can now supply the same scope
    contract without installing the OAuth2 provider application.
    """
    from ansible_base.authentication.permissions import TokenScopePermission

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
