# API Deprecations

DAB supports endpoint deprecations, deprecated request fields, and deprecated query parameters. These are separate mechanisms: manually adding a response header does not update the schema or browser UI, and query parameter deprecations are not added to the schema automatically.

## Deprecate an endpoint

Use `@deprecated` on a view or action. A class-level decorator relies on `AnsibleBaseView` (or equivalent `finalize_response` behavior) for runtime headers; a method-level decorator marks its returned response directly.

```python
from ansible_base.lib.utils.views.ansible_base import AnsibleBaseView
from ansible_base.lib.utils.views.deprecation import deprecated

@deprecated(detail="Use /api/v2/new-resource/ instead.")
class ResourceViewSet(ModelViewSet, AnsibleBaseView):
    ...
```

Configure drf-spectacular's `DEFAULT_SCHEMA_CLASS` as `ansible_base.lib.utils.schema.DABAutoSchema` to mark operations `deprecated: true` and add `x-api-deprecated-detail`. For a custom schema class, inherit `DeprecationAutoSchemaMixin` before `AutoSchema`. `mark_deprecated(response, detail)` is for conditional runtime warnings and only adds response headers.

## Deprecate request fields or query parameters

For request fields, pair the serializer and view mixins. Headers are emitted only when a deprecated field is present in the submitted data.

```python
class ResourceSerializer(DeprecationSerializerMixin, serializers.Serializer):
    legacy_id = serializers.IntegerField(required=False)
    deprecated_fields = {'legacy_id': 'Use resource_id instead.'}


class ResourceView(DeprecatedFieldsViewMixin, GenericAPIView):
    serializer_class = ResourceSerializer
```

To mark fields deprecated in OpenAPI, annotate the serializer with `@extend_schema_serializer(deprecate_fields=[...])` and add `ansible_base.lib.utils.schema.deprecated_fields_detail_hook` to the existing drf-spectacular `POSTPROCESSING_HOOKS`. The hook adds `x-api-deprecated-detail` and supports split request components, including `ResourceRequest` and `PatchedResourceRequest`.

The hook uses the actual serializer registered for each schema component, so importing another serializer with the same class name does not replace its deprecation details. If two different serializers appear in the same schema, give them distinct component names using `Meta.ref_name` or `@extend_schema_serializer(component_name=...)`; the hook does not resolve duplicate OpenAPI component names.

For query parameters, use `DeprecatedQueryParamsViewMixin`:

```python
class ResourceView(DeprecatedQueryParamsViewMixin, APIView):
    deprecated_query_params = {'legacy_filter': 'Use filter instead.'}
```

The header is emitted only when the parameter is present. Document its schema deprecation separately if needed.

## Browsable API

Add `ansible_base.lib.utils.context_processors.version` to Django's template context processors. For views with deprecation metadata, it provides `deprecated` and `deprecated_message`; templates must render those values to show a banner.
