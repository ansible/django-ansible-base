import functools


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
