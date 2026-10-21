from ansible_base.authentication.permissions import TokenScopePermission

# This is not in views/permissions.py because we import that in other oauth2_provider files
# and when we try to specify this OAuth2ScopePermission in an app's settings.py, we get a
# cyclic dependency.


class OAuth2ScopePermission(TokenScopePermission):
    """Backward-compatible name for the provider-independent scope permission.

    New code should import ``TokenScopePermission`` from authentication.
    """
