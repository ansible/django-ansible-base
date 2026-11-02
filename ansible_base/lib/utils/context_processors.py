from ansible_base.lib.utils.settings import get_function_from_setting


def _check_deprecation(view, method):
    """Resolve handler metadata before view metadata and the legacy deprecation flag."""
    if not view:
        return None

    action = getattr(view, 'action', None) or method.lower()
    action_method = getattr(view, action, None)
    deprecation_metadata = getattr(action_method, 'deprecation', None) or getattr(view, 'deprecation', None)
    if deprecation_metadata:
        return deprecation_metadata

    if getattr(view, 'deprecated', False):
        return {
            'detail': 'This resource has been deprecated and will be removed in a future release.',
        }

    return None


def version(request):
    """
    Context processor that provides version and deprecation information.
    Usage in settings.py:
        TEMPLATES = [{
            'OPTIONS': {
                'context_processors': [
                    'ansible_base.lib.utils.context_processors.version',
                ],
            },
        }]
    """
    context = getattr(request, 'parser_context', {})
    view = context.get('view')
    deprecation_metadata = _check_deprecation(view, getattr(request, 'method', ''))
    deprecated = deprecation_metadata is not None
    deprecated_message = deprecation_metadata['detail'] if deprecation_metadata else ''
    api_version = 'Unknown'
    try:
        version_func = get_function_from_setting('ANSIBLE_BASE_PRODUCT_VERSION_FUNCTION')
        if version_func:
            api_version = version_func()
    except Exception:
        pass

    return {
        'api_version': api_version,
        'deprecated': deprecated,
        'deprecated_message': deprecated_message,
    }
