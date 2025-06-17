# Feature Flags documentation

django-ansible-base uses django-flags to manage feature flags in the API.
Additional library documentation can be found at https://cfpb.github.io/django-flags/

## Settings

Add `ansible_base.feature_flags` to your installed apps and ensure `ansible_base.resource_registry` as added to enable flag state to sync across the platform:

```python
INSTALLED_APPS = [
    ...
    'ansible_base.feature_flags',
    'ansible_base.resource_registry', # Must also be added
]
```

## Detail

By adding the `ansible_base.feature_flags` app to your application, all Ansible Automation Platform feature flags will be loaded and available in your component.
To receive flag state updates, ensure the following definition is available in your components `RESOURCE_LIST` - 

```python
from ansible_base.feature_flags.models import AAPFlag
from ansible_base.resource_registry.shared_types import FeatureFlagType

RESOURCE_LIST = (
    ...
    ResourceConfig(
        AAPFlag,
        shared_resource=SharedResource(serializer=FeatureFlagType, is_provider=False),
    ),
)
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

## Adding Feature Flags

To add a feature flag to the platform, specify it in the following [file](../../ansible_base/feature_flags/definitions/feature_flags.yaml)

An example flag could resemble -

```yaml
- name: FEATURE_FOO_ENABLED
  ui_name: Foo
  visibility: True
  condition: boolean
  value: 'False'
  support_level: NOT_FOR_PRODUCTION
  description: TBD
  support_url: https://docs.redhat.com/en/documentation/red_hat_ansible_automation_platform/2.5/
  labels:
    - controller
```

Validate this file against the json schema by running `check-jsonschema` -

```bash
pip install check-jsonschema
check-jsonschema --schemafile ansible_base/feature_flags/definitions/schema.json ansible_base/feature_flags/definitions/feature_flags.yaml
```
