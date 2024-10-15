# Features

The django-ansible-base `features` app provides a way to have new features
in development that an end use can opt into.

## Consumer Docs

To make use of `features` in your application, first add
`ansible_base.features` to your `INSTALLED_APPS`.

Now in your code you can:

```python
from ansible_base.features import  feature_enabled

if feature_enabled('some_feature_short_name')
    ... feature code here ...
```

### Caching

The feature enabled/disabled flags are stored in the database but can be cached
out by setting: ANSIBLE_BASE_FEATURE_CACHE=<cache name>

### Registering Features

Once the features app is installed we have to tell it to register features. To do this add a file called `dab_features.py` at the root of your application. This file should have a single variable called `FEATURES` in it that is an array of dicts describing features:
```
FEATURES = [
    {
        'short_name': 'SLO',
        'name': 'Single Logout',
        'description': 'Add single logout to SAML and OIDC authenticators',
        'status': 'a',
        'requires_restart': True,
    }
]
```

`short_name` str, an easy to reference name that will be used as an identifier inside the code
`name` str, the display name for the feature (end user facing)
`description` str, a brief description of the feature
`status` one of ['a', 'b'], the status of the feature (Alpha or Beta, see Feature Status)
`requires_restart` boolean indicating if the feature requires a restart in order for its state to be changed

### Feature status

We currently support 2 feature statuses:
  * alpha - This is a new feature under development, there is no support for it
  * beta - This feature is going through testing/hardening, there is no support for it


### Migrations

If your feature has migrations you should always have those applied.
If your feature requires changes to existing fields you will have to consider how to make that condition. i.e. maybe instead of changing an existing field you need a new field and to have both fields written to during a save or something along those lines.

### URLs

This feature includes URLs which you will get if you are using
[dynamic urls](../Installation.md).

If you want to manually add the URLs without dynamic urls, add the following to
your `urls.py`:

```
from ansible_base.features import urls as feature_urls
urlpatterns = [
    ...
    path('api/v1/', include(feature_urls.api_version_urls)),
    ...
]
```

## Scenarios to Think Through

What if you need to add a new app to INSTALLED_APPS?
Right now things are stored in the DB as models.... do we need a simple function that could load the enabled status outside of context of Django?

