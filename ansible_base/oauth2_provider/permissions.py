from ansible_base.lib.permissions import TokenScopePermission

# Retain the old import path while making local OAuth2 and external Bearer
# callers share one class object. This also lets applications that patch the
# legacy name affect the canonical permission during a staged migration.
OAuth2ScopePermission = TokenScopePermission
