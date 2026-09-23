# Context Processors

## Overview

The `ansible_base.lib.utils.context_processors` module provides Django template context processors that can be imported and used by other services in the same way as deprecation utilities.

## Version Context Processor

The `version` context processor provides version and deprecation information for DRF API views.

### Usage in Django Settings

Add the context processor to your Django settings:

```python
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                # Add the version context processor
                'ansible_base.lib.utils.context_processors.version',
            ],
        },
    },
]
```

### Importing in Other Services

Other services can import and use the context processor just like they import deprecations:

```python
from ansible_base.lib.utils.context_processors import version
```

### What It Provides

The context processor returns a dictionary with the following keys:

- `api_version`: The API version (from `ANSIBLE_BASE_PRODUCT_VERSION_FUNCTION`)
- `deprecated`: Boolean indicating if the current view is deprecated
- `deprecated_message`: The deprecation detail message (empty string if not deprecated)
- `deprecated_link`: The deprecation documentation link (only present if a link is set)

### Example in Templates

In Django templates, you can use these variables:

```django
{% if deprecated %}
<div class="alert alert-warning">
    <strong>Deprecated:</strong> {{ deprecated_message }}
    {% if deprecated_link %}
    <a href="{{ deprecated_link }}">Learn more</a>
    {% endif %}
</div>
{% endif %}

<footer>
    API Version: {{ api_version }}
</footer>
```

### Deprecation Detection

The context processor automatically detects deprecation using the same mechanism as the deprecation headers:

1. **New style**: Checks for `view.deprecation` dict with `detail` and optional `link`
2. **Legacy style**: Falls back to `view.deprecated = True` boolean

This matches the behavior in `AnsibleBaseView.finalize_response()`.

### Example View Integration

The context processor works seamlessly with views using the `@deprecated` decorator:

```python
from ansible_base.lib.utils.views.deprecation import deprecated
from ansible_base.lib.utils.views.ansible_base import AnsibleBaseView
from rest_framework.viewsets import ModelViewSet

@deprecated(detail="This endpoint is deprecated. Use /api/v2/resources/ instead.")
class LegacyResourceViewSet(ModelViewSet, AnsibleBaseView):
    # ... viewset implementation
    pass
```

When a request is made to this view, the context processor will automatically set:
- `deprecated = True`
- `deprecated_message = "This endpoint is deprecated. Use /api/v2/resources/ instead."`

## Related

- [Deprecation Headers](../ansible_base/lib/utils/views/deprecation.py): The deprecation decorator and header mechanism
- [AnsibleBaseView](../ansible_base/lib/utils/views/ansible_base.py): The base view class that applies deprecation headers
