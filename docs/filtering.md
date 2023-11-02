# Filtering

django-ansible-base has a built in mechanism for filtering query sets based on django-filters. 

To enable filtering on your rest endpoints edit your settings file and modify `REST_FRAMEWORK` with the following entry:
```
REST_FRAMEWORK = {
    ...
    'DEFAULT_FILTER_BACKENDS': ['ansible_base.utils.filtering.AutomaticDjangoFilterBackend'],
    ...
}
```

be sure to also add `django_filters` to your `INSTALLED_APPS` setting:
```
INSTALLED_APPS = [
    ...
    'django_filters',
    '''
]
```
