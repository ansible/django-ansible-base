# Security (Permissions)

Token "scopes" are meaningless, until and unless they are checked. The upstream
Django OAuth Toolit provides DRF permissions classes for checking them. In fact,
they have some that get close to what we want, but none that exactly seem to do
what we need. We really want a mix of their `IsAuthenticatedOrTokenHasScope` and
their `TokenHasReadWriteScope`.

Since this doesn't exist upstream, the DAB `oauth2_provider` app provides its
own implementation,
`ansible_base.oauth2_provider.permissions.OAuth2ScopePermission`.

**You should set this as a default permission class in your app's settings.py**
because for any view that doesn't include it, token scopes have no meaning, and
every token is given full access.

For example:

```python
REST_FRAMEWORK = {
    # ...
    'DEFAULT_PERMISSION_CLASSES': [
        'ansible_base.oauth2_provider.permissions.OAuth2ScopePermission',
        'ansible_base.rbac.api.permissions.AnsibleBaseObjectPermissions',
    ],
    # ...
}
```

# Differences from AWX

* Because of how DAB's router works, we don't allow for POSTing to (for example)
  `/applications/PK/tokens/` to create a token which belongs to an application.
  The workaround is to just use /tokens/ and in the body specify
  `{"application": PK}`.
