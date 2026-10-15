"""
This module provides optional decorators and schema classes that gracefully handle missing dependencies.
"""


class DeprecationAutoSchemaMixin:
    """
    Mixin that adds deprecation support to drf-spectacular AutoSchema.

    Checks three levels for deprecation metadata:
    1. The specific action method (e.g., create, update) — set by @deprecated on a method
    2. The view instance
    3. The view class (e.g., deprecated = True or class-level @deprecated)
    """

    def _get_action_method(self):
        """Resolve the handler method for the current schema operation."""
        action = getattr(self.view, 'action', None) or self.method.lower()
        return getattr(self.view.__class__, action, None)

    def is_deprecated(self):
        view_class = self.view.__class__
        action_method = self._get_action_method()
        return (
            bool(getattr(action_method, 'deprecation', None))
            or getattr(self.view, 'deprecated', False)
            or getattr(view_class, 'deprecated', False)
            or bool(getattr(self.view, 'deprecation', None))
            or bool(getattr(view_class, 'deprecation', None))
        )

    def get_extensions(self):
        extensions = super().get_extensions()

        action_method = self._get_action_method()
        deprecation = getattr(action_method, 'deprecation', None)

        if not deprecation:
            view_class = self.view.__class__
            deprecation = getattr(self.view, 'deprecation', None) or getattr(view_class, 'deprecation', None)

        if deprecation and deprecation.get('detail'):
            extensions['x-api-deprecated-detail'] = deprecation['detail']

        return extensions


def _get_autoschema_base():
    """
    Returns None if drf-spectacular is not installed, allowing services
    to gracefully handle the missing dependency.
    """
    try:
        from drf_spectacular.openapi import AutoSchema
        return AutoSchema
    except ImportError:
        return None


# Conditionally define DABAutoSchema only if drf-spectacular is available
_AutoSchemaBase = _get_autoschema_base()

if _AutoSchemaBase is not None:
    class DABAutoSchema(DeprecationAutoSchemaMixin, _AutoSchemaBase):
        """
        AutoSchema with DAB deprecation support built-in.
        This is a ready-to-use schema class for services that don't need
        custom schema logic.
        """
        pass

else:
    class DABAutoSchema:
        """Placeholder when drf-spectacular is not installed."""

        def __init__(self, *args, **kwargs):
            raise ImportError("DABAutoSchema requires drf-spectacular to be installed. Install it with: pip install drf-spectacular")


def deprecated_fields_detail_hook(result, generator, **kwargs):
    """
    drf-spectacular postprocessing hook that adds x-api-deprecated-detail
    to individual field schemas based on DeprecationSerializerMixin.deprecated_fields.

    Only touches fields already marked deprecated: true. Does not modify
    descriptions or any other schema properties.
    """
    from ansible_base.lib.utils.views.deprecation import _DEPRECATED_FIELD_REGISTRY

    if not _DEPRECATED_FIELD_REGISTRY:
        return result

    ref_map = {}
    for serializer_cls, fields in _DEPRECATED_FIELD_REGISTRY.items():
        ref_name = getattr(getattr(serializer_cls, 'Meta', None), 'ref_name', None)
        if not ref_name:
            name = serializer_cls.__name__
            ref_name = name[:-len('Serializer')] if name.endswith('Serializer') else name
        ref_map[ref_name] = fields

    schemas = result.get('components', {}).get('schemas', {})
    for component_name, schema in schemas.items():
        for ref_name, fields in ref_map.items():
            if component_name != ref_name and component_name != f'Patched{ref_name}':
                continue
            properties = schema.get('properties', {})
            for field_name, detail in fields.items():
                if field_name in properties and properties[field_name].get('deprecated'):
                    properties[field_name]['x-api-deprecated-detail'] = detail

    return result


def extend_schema_if_available(**kwargs):
    """
    Decorator that wraps drf_spectacular's extend_schema if available.

    If drf_spectacular is not installed, this decorator becomes a no-op,
    allowing code to use extend_schema without requiring drf_spectacular
    as a hard dependency.

    Args:
        **kwargs: Arguments to pass to extend_schema if available

    Returns:
        Decorated function with schema extensions if drf_spectacular is available,
        otherwise returns the original function unchanged
    """
    try:
        from drf_spectacular.utils import extend_schema

        return extend_schema(**kwargs)
    except ImportError:
        # If drf_spectacular is not available, return a no-op decorator
        return lambda func: func
