# API Deprecation Mechanism

## Overview

DAB provides a comprehensive deprecation mechanism for signaling API deprecations to consumers through three complementary channels:

1. **Runtime HTTP headers** (`X-API-Deprecated`, `X-API-Deprecated-Detail`) for programmatic clients
2. **OpenAPI schema annotations** (`deprecated: true`, `x-api-deprecated-detail`) for tooling and generated clients
3. **Browsable API visual banners** for developers using the API in a browser

All three signals derive from the same source of truth (the `@deprecated` decorator or `mark_deprecated()` utility), ensuring consistency across documentation and runtime behavior.

## Quick Start

### Deprecate an Entire Endpoint

```python
@deprecated(detail="The /v2/roles/ endpoint is deprecated. Use /v2/role_definitions/ instead.")
class RoleViewSet(ModelViewSet, AnsibleBaseView):
    serializer_class = RoleSerializer
    queryset = Role.objects.all()
```

**Result:**
- ✅ Runtime: Every response includes `X-API-Deprecated: true` and `X-API-Deprecated-Detail` headers
- ✅ Schema: Operation marked `deprecated: true` with `x-api-deprecated-detail` extension
- ✅ Browsable API: Red banner with deprecation message (if context processor enabled)

### Conditional Deprecation (Parameter, Field, or Behavior)

```python
class HostViewSet(ModelViewSet, AnsibleBaseView):
    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        if request.query_params.get('legacy_filter'):
            mark_deprecated(response, detail="The legacy_filter parameter is deprecated.")
        
        return response
```

**Result:**
- Headers emitted **only when** `?legacy_filter=` is present in the request
- OpenAPI schema does NOT mark operation as deprecated (since it's conditional)

## OpenAPI Schema Support

DAB provides two ways to add deprecation metadata to your OpenAPI schema, depending on whether you need custom schema logic.

### Option 1: Ready-to-Use Schema Class (Simple Services)

For services that don't need custom schema behavior, use the pre-configured `DABAutoSchema`:

```python
# settings.py
REST_FRAMEWORK = {
    'DEFAULT_SCHEMA_CLASS': 'ansible_base.lib.utils.schema.DABAutoSchema',
}
```

This automatically:
- Marks operations as `deprecated: true` when the view has `deprecated` or `deprecation` attributes
- Adds `x-api-deprecated-detail` extension with the actual deprecation message

### Option 2: Mixin for Custom Schema Classes (Advanced Services)

For services like AWX or Gateway that need custom schema logic (custom tags, filters, etc.), use the mixin:

```python
# yourapp/schema.py
from drf_spectacular.openapi import AutoSchema
from ansible_base.lib.utils.schema import DeprecationAutoSchemaMixin

class CustomAutoSchema(DeprecationAutoSchemaMixin, AutoSchema):
    """Custom AutoSchema with your service-specific logic."""
    
    def get_tags(self):
        # Your custom tag logic
        if hasattr(self.view, 'swagger_topic'):
            return [str(self.view.swagger_topic).title()]
        return super().get_tags()
    
    # Deprecation support is inherited from DeprecationAutoSchemaMixin
```

Then configure it:

```python
# settings.py
REST_FRAMEWORK = {
    'DEFAULT_SCHEMA_CLASS': 'yourapp.schema.CustomAutoSchema',
}
```

### What Gets Added to the Schema

When a view is decorated with `@deprecated(detail="...")`, the OpenAPI schema includes:

```yaml
/api/v2/roles/:
  get:
    deprecated: true  # ← From is_deprecated()
    x-api-deprecated-detail: "The /v2/roles/ endpoint is deprecated. Use /v2/role_definitions/ instead."  # ← From get_extensions()
    responses:
      200:
        description: Success
```

## Browsable API Visual Signals

For developers using the DRF browsable API in a web browser, DAB provides a context processor that makes deprecation information available to templates for displaying visual warnings.

### Enable the Context Processor

Add the context processor to your Django settings:

```python
# settings.py
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'OPTIONS': {
            'context_processors': [
                # Add the version context processor
                'ansible_base.lib.utils.context_processors.version',
            ],
        },
    },
]
```

### Configure Product Version (Optional)

To show the API version in templates:

```python
# settings.py
ANSIBLE_BASE_PRODUCT_VERSION_FUNCTION = 'yourapp.utils.get_version'

# yourapp/utils.py
def get_version():
    return "YourApp 1.2.3"
```

## Related Documentation

- [Deprecation Headers Implementation](../ansible_base/lib/utils/views/deprecation.py): The decorator and utility functions
- [AnsibleBaseView](../ansible_base/lib/utils/views/ansible_base.py): Base view class that applies deprecation headers
- [Schema Support](../ansible_base/lib/utils/schema.py): DeprecationAutoSchemaMixin and DABAutoSchema
- [Context Processor](../ansible_base/lib/utils/context_processors.py): Template variable provider
