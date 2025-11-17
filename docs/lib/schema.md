# Schema Utilities

Since DAB functions as a base for a variety of applications, we need a way to provide additional OpenAPI spec
details without a hard dependency on libraries that may not be present. 

These utilities reside in `ansible_base.lib.utils.schema`.

## `extend_schema_if_available`

The `extend_schema_if_available` decorator is a simple wrapper around `drf_spectacular.utils.extend_schema` that gracefully handles missing dependencies.

If `drf-spectacular` is installed, then any arguments are passed through. If this library is not installed, then
it functions as a no-op decorator.

### Usage Example

```python
from ansible_base.lib.utils.schema import extend_schema_if_available

class MyViewSet(ModelViewSet):
    """API endpoint for my resource."""

    @extend_schema_if_available(
        request=MyRequestSerializer,
        responses={200: MyResponseSerializer},
    )
    def custom_action(self, request, pk=None):
        """Custom action implementation."""
        pass
```