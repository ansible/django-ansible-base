# Open API and Swagger documentation

django-ansible-base uses django-spectacular to auto-generate both Open API and Swagger documentation of the API.

## Settings

Add `ansible_base.api_documentation` to your installed apps:

```
INSTALLED_APPS = [
    ...
    'ansible_base.api_documentation',
]
```

### Additional Settings
Additional settings are required to enable api_documentation.
This will happen automatically if using [dynamic_settings](../Installation.md)

First, you need to add `drf_spectacular` to your `INSTALLED_APPS`:
```
INSTALLED_APPS = [
    ...
    'drf_spectacular',
    ...
]
```

Additionally, we create a `SPECTACULAR_SETTINGS` entry if its not already present:
```
SPECTACULAR_SETTINGS = {
    'TITLE': 'AAP Open API',
    'DESCRIPTION': 'AAP Open API',
    'VERSION': 'v1',
    'SCHEMA_PATH_PREFIX': '/api/v1/',
}
```

Finally, add a `DEFAULT_SCHEMA_CLASS` to your `REST_FRAMEWORK` setting:
```
REST_FRAMEWORK = {
    ...
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    ...
}
```

## URLS

This feature includes URLs which you will get if you are using [dynamic urls](../..//Installation.md)

If you want to manually add the urls without dynamic urls add the following to your urls.py:
```
from ansible_base.api_documentation import urls

urlpatterns = [
    ...
    path('api/v1/', include(base_auth_urls.api_version_urls)),
    ...
]
```
