"""Permission classes shared by optional ansible-base applications."""

from typing import Any

from rest_framework.permissions import SAFE_METHODS, BasePermission, IsAuthenticated


class TokenScopePermission(BasePermission):
    """Require read for safe requests and write for unsafe scoped credentials.

    Authentication mechanisms without a scope-bearing ``request.auth`` object
    (sessions, Basic authentication, and service authentication) retain their
    existing authorization behavior. OAuth2 access tokens and verified external
    Bearer credentials both expose a space-delimited ``scope`` value.
    """

    def has_permission(self, request: Any, view: Any) -> bool:
        """Allow unscoped authentication schemes or enforce read/write scopes."""
        if not IsAuthenticated().has_permission(request, view):
            return False

        scope = getattr(request.auth, "scope", None)
        if not isinstance(scope, str):
            return True

        scopes = set(scope.split())
        if "write" in scopes:
            # A write-capable credential is necessarily read-capable without
            # mutating local OAuth2 model instances during authorization.
            scopes.add("read")
        required_scope = "read" if request.method in SAFE_METHODS else "write"
        return required_scope in scopes
