import oauth2_provider.models as oauth2_models
from oauth2_provider.contrib.rest_framework import TokenHasReadWriteScope
from rest_framework.permissions import BasePermission, IsAuthenticated

# This is not in views/permissions.py because we import that in other oauth2_provider files
# and when we try to specify this OAuth2ScopePermission in an app's settings.py, we get a
# cyclic dependency.


class OAuth2ScopePermission(BasePermission):
    """
    A DRF Permission class to be used by apps that functions in the following way:

    - If an OAuth 2 token is used to authenticate, then its scope must contain the required scope
      (i.e. "read" cannot use "unsafe" methods)
    - Otherwise, fall back.
    """

    def has_permission(self, request, view):
        is_authenticated = IsAuthenticated().has_permission(request, view)
        is_oauth = False
        has_oauth_permission = False
        if is_authenticated and request.auth and isinstance(request.auth, oauth2_models.AbstractAccessToken):
            is_oauth = True
            scopes = request.auth.scope.split()
            if 'write' in scopes and 'read' not in scopes:
                request.auth.scope += ' read'  # write implies read
            token_permission = TokenHasReadWriteScope()
            has_oauth_permission = token_permission.has_permission(request, view)
        return is_authenticated and (not is_oauth or has_oauth_permission)
