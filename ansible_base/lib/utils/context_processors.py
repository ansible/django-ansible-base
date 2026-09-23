from ansible_base.lib.utils.settings import get_function_from_setting, get_setting


def _check_deprecation(view):
    """Check if view has deprecation info."""
    if not view:
        return None

    # Check for the new deprecation dict attribute
    deprecation = getattr(view, 'deprecation', None)
    if deprecation:
        return deprecation

    # Fall back to legacy deprecated boolean
    if getattr(view, 'deprecated', False):
        return {
            'detail': 'This resource has been deprecated and will be removed in a future release.',
            'link': None
        }

    return None


def version(request):
    """
    Context processor that provides version and deprecation information.

    Can be used in Django templates and imported by other services.

    Usage in settings.py:
        TEMPLATES = [{
            'OPTIONS': {
                'context_processors': [
                    'ansible_base.lib.utils.context_processors.version',
                ],
            },
        }]

    Returns:
        dict: Context with api_version, deprecated, and deprecated_message
    """
    context = getattr(request, 'parser_context', {})
    view = context.get('view')

    # Check for deprecation
    deprecation = _check_deprecation(view)
    deprecated = deprecation is not None
    deprecated_message = deprecation['detail'] if deprecation else ''
    deprecated_link = deprecation.get('link') if deprecation else None

    # Get product version
    api_version = 'Unknown'
    try:
        version_func = get_function_from_setting('ANSIBLE_BASE_PRODUCT_VERSION_FUNCTION')
        if version_func:
            api_version = version_func()
    except Exception:
        pass

    result = {
        'api_version': api_version,
        'deprecated': deprecated,
        'deprecated_message': deprecated_message,
    }

    if deprecated_link:
        result['deprecated_link'] = deprecated_link

    return result
