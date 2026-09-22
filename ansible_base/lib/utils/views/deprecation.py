import functools

from ansible_base.lib.utils.settings import get_setting


def mark_deprecated(response, detail: str, link: str = None) -> None:
    """
    Add deprecation headers to an HTTP response.

    Can be called multiple times on the same response — detail sentences
    accumulate and duplicate sentences are ignored.

    Headers set:
        X-Deprecated: true
        X-Deprecated-Detail: <detail sentence(s)>
        Link: <url>; rel="deprecation"  (first link wins)
    """
    if not detail.endswith('.'):
        detail = detail + '.'

    response['X-Deprecated'] = 'true'

    existing_detail = response.get('X-Deprecated-Detail', '')
    if existing_detail:
        if detail in existing_detail:
            return
        response['X-Deprecated-Detail'] = f'{existing_detail} {detail}'
    else:
        response['X-Deprecated-Detail'] = detail

    if 'Link' not in response:
        resolved_link = link or get_setting('ANSIBLE_BASE_DEPRECATION_LINK', '')
        if resolved_link:
            response['Link'] = f'<{resolved_link}>; rel="deprecation"'


def deprecated(detail: str, link: str = None):
    """
    Decorator that marks a view method or class as deprecated.

    When applied to a method, wraps it to add deprecation headers to every
    response and marks the method as deprecated in the OpenAPI schema.

    When applied to a class, sets attributes that AnsibleBaseView.finalize_response()
    reads to add deprecation headers, and marks all standard DRF action methods
    as deprecated in the OpenAPI schema.
    """

    def decorator(target):
        if isinstance(target, type):
            return _apply_to_class(target, detail, link)
        return _apply_to_method(target, detail, link)

    return decorator


_DRF_ACTION_METHODS = ('list', 'create', 'retrieve', 'update', 'partial_update', 'destroy')


def _apply_to_class(cls, detail, link):
    cls._dab_deprecated = True
    cls._dab_deprecated_detail = detail
    cls._dab_deprecated_link = link

    from ansible_base.lib.utils.schema import extend_schema_if_available

    schema_decorator = extend_schema_if_available(deprecated=True)
    for method_name in _DRF_ACTION_METHODS:
        method = getattr(cls, method_name, None)
        if method is not None:
            setattr(cls, method_name, schema_decorator(method))

    return cls


def _apply_to_method(method, detail, link):
    from ansible_base.lib.utils.schema import extend_schema_if_available

    @functools.wraps(method)
    def wrapper(self, request, *args, **kwargs):
        response = method(self, request, *args, **kwargs)
        mark_deprecated(response, detail, link)
        return response

    wrapper._dab_deprecated = True
    wrapper._dab_deprecated_detail = detail
    wrapper._dab_deprecated_link = link

    schema_decorator = extend_schema_if_available(deprecated=True)
    wrapper = schema_decorator(wrapper)

    return wrapper
