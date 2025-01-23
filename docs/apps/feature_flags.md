# Feature Flags documentation

django-ansible-base uses django-flags to manage feature flags in the API.
Additional library documentation can be found at https://cfpb.github.io/django-flags/

## Settings

Add `ansible_base.feature_flags` to your installed apps:

```python
INSTALLED_APPS = [
    ...
    'ansible_base.feature_flags',
]
```

### Additional Settings

Additional settings are required to enable feature_flags.
This will happen automatically if using [dynamic_settings](../Installation.md)

First, you need to add `flags` to your `INSTALLED_APPS`:

```python
INSTALLED_APPS = [
    ...
    'flags',
    ...
]
```

Additionally, create a `FLAGS` entry:

```python
FLAGS = {}
```

Finally, add `django.template.context_processors.request` to your `TEMPLATES` `context_processors` setting:

```python
TEMPLATES = [
    {
        'BEACKEND': 'django.template.backends.django.DjangoTemplates',
        ...
        'OPTIONS': {
            ...
            'context_processors': [
                ...
                'django.template.context_processors.request',
                ...
            ]
            ...
        }
        ...
    }
]
```

## URLS

This feature includes URLs which you will get if you are using [dynamic urls](../..//Installation.md)

If you want to manually add the urls without dynamic urls add the following to your urls.py:

```python
from ansible_base.feature_flags import urls
urlpatterns = [
    ...
    path('api/v1/', include(feature_flags.api_version_urls)),
    ...
]
```
