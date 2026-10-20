from ansible_base.authentication.permissions import ReadWriteScopePermission

# This is not in views/permissions.py because we import that in other oauth2_provider files
# and when we try to specify this OAuth2ScopePermission in an app's settings.py, we get a
# cyclic dependency.


class OAuth2ScopePermission(ReadWriteScopePermission):
    """
    A DRF Permission class to be used by apps that functions in the following way:

    Backwards-compatible name for the provider-independent permission. New
    code should import ``ReadWriteScopePermission`` from authentication.
    """
