# Pagination

django-ansible-base provides a method for paginating rest framework list views.

## Installation

Add `ansible_base.rest_pagination` to your installed apps:

```
INSTALLED_APPS = [
    ...
    'ansible_base.rest_pagination',
]
```

### Additional Settings
Additional settings are required to enable pagination on your rest endpoints.
This will happen automatically if using [dynamic_settings](../Installation.md)

To manually enable filtering without dynamic settings the following items need to be included in your settings:
```
REST_FRAMEWORK = {
    ...
    'DEFAULT_PAGINATION_CLASS': 'ansible_base.rest_pagination.DefaultPaginator'
    ...
}
```


### Runtime settings

The paginator will look for two runtime settings:
`MAX_PAGE_SIZE` - the maximum number of page items allowed by the server, defaults to 200
`DEFAULT_PAGE_SIZE` - the number of page items if left unspecified by the request, defaults to 50
