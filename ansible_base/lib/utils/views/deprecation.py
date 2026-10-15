import functools


class DeprecationSerializerMixin:
    """
    Mixin for serializers to detect deprecated fields in request data
    and propagate warnings to the view for HTTP header emission.

    Usage:
        class MySerializer(DeprecationSerializerMixin, Serializer):
            old_field = CharField(required=False)

            deprecated_fields = {
                'old_field': 'old_field is deprecated. Use new_field instead.'
            }

    When a request includes a deprecated field, the mixin stores the warnings
    on the view instance (via DRF's serializer context) so that
    DeprecatedFieldsViewMixin.finalize_response can emit X-API-Deprecated headers.
    """

    deprecated_fields = {}

    def _check_deprecated_fields(self):
        initial_data = getattr(self, 'initial_data', {})
        if not initial_data:
            return

        warnings = []
        for field_name, detail in self.deprecated_fields.items():
            if field_name in initial_data:
                warnings.append({'field': field_name, 'message': detail})

        if warnings:
            view = self.context.get('view')
            if view is not None:
                existing = getattr(view, '_deprecated_field_warnings', [])
                seen = {w['field'] for w in existing}
                for w in warnings:
                    if w['field'] not in seen:
                        existing.append(w)
                view._deprecated_field_warnings = existing

    def run_validation(self, data):
        self._check_deprecated_fields()
        return super().run_validation(data)


def mark_deprecated(response, detail: str) -> None:
    """
    Add deprecation headers to an HTTP response.
    Headers set:
        X-API-Deprecated: true
        X-API-Deprecated-Detail: <detail sentence(s)>
    """
    if not detail.endswith('.'):
        detail = detail + '.'

    response['X-API-Deprecated'] = 'true'
    existing_detail = response.get('X-API-Deprecated-Detail', '')
    if existing_detail:
        if detail in existing_detail:
            return
        response['X-API-Deprecated-Detail'] = f'{existing_detail} {detail}'
    else:
        response['X-API-Deprecated-Detail'] = detail


class DeprecatedFieldsViewMixin:
    """
    View mixin that emits X-API-Deprecated headers for deprecated serializer fields.

    Pair with DeprecationSerializerMixin on the serializer side.
    The serializer detects which deprecated fields the caller actually sent
    and stores warnings on the view instance. This mixin reads them in
    finalize_response and calls mark_deprecated for each.

    Usage:
        class MyViewSet(DeprecatedFieldsViewMixin, ModelViewSet):
            serializer_class = MySerializer  # uses DeprecationSerializerMixin
    """

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        for warning in getattr(self, '_deprecated_field_warnings', []):
            mark_deprecated(response, detail=warning['message'])
        return response


class DeprecatedQueryParamsViewMixin:
    """
    View mixin that emits X-API-Deprecated headers when deprecated query
    parameters are present in the request.

    Usage:
        class MyViewSet(DeprecatedQueryParamsViewMixin, ModelViewSet):
            deprecated_query_params = {
                'legacy_format': 'The legacy_format parameter is deprecated. Use format=v2 instead.',
            }
    """

    deprecated_query_params = {}

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        for param, detail in self.deprecated_query_params.items():
            if param in request.query_params:
                mark_deprecated(response, detail=detail)
        return response


_DRF_ACTION_METHODS = ('list', 'create', 'retrieve', 'update', 'partial_update', 'destroy')


def _apply_to_class(cls, detail):
    """
    Apply deprecation metadata to a class (ViewSet).
    """
    cls.deprecation = {"detail": detail}

    from ansible_base.lib.utils.schema import extend_schema_if_available

    schema_decorator = extend_schema_if_available(deprecated=True)
    for method_name in _DRF_ACTION_METHODS:
        method = getattr(cls, method_name, None)
        if method is not None:
            setattr(cls, method_name, schema_decorator(method))

    return cls


def _apply_to_method(method, detail):
    """
    Apply deprecation metadata to a single view method.
    """
    from ansible_base.lib.utils.schema import extend_schema_if_available

    @functools.wraps(method)
    def wrapper(self, request, *args, **kwargs):
        response = method(self, request, *args, **kwargs)
        mark_deprecated(response, detail)
        return response

    wrapper.deprecation = {"detail": detail}
    schema_decorator = extend_schema_if_available(deprecated=True)
    wrapper = schema_decorator(wrapper)

    return wrapper


def deprecated(detail: str):
    """
    Decorator that marks a view method or class as deprecated.
    """
    def decorator(target):
        if isinstance(target, type):
            return _apply_to_class(target, detail)
        return _apply_to_method(target, detail)

    return decorator
