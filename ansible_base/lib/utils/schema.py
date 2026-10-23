"""
This module provides optional decorators and schema classes that gracefully handle missing dependencies.
"""

from typing import TYPE_CHECKING


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
        """Report deprecation from the action, view metadata, or legacy flag."""
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
        """Add the most specific deprecation detail to the existing schema extensions."""
        extensions = super().get_extensions()

        action_method = self._get_action_method()
        deprecation_metadata = getattr(action_method, 'deprecation', None)

        if not deprecation_metadata:
            view_class = self.view.__class__
            deprecation_metadata = getattr(self.view, 'deprecation', None) or getattr(view_class, 'deprecation', None)

        if deprecation_metadata and deprecation_metadata.get('detail'):
            extensions['x-api-deprecated-detail'] = deprecation_metadata['detail']

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


def _add_deprecated_field_details(schema, fields):
    """Attach supplied details only to properties already marked deprecated."""
    properties = schema.get('properties', {})
    for field_name, detail in fields.items():
        property_schema = properties.get(field_name, {})
        if property_schema.get('deprecated'):
            property_schema['x-api-deprecated-detail'] = detail


class _MissingAutoSchema:
    """Placeholder base that preserves the optional drf-spectacular dependency."""

    def __init__(self, *args, **kwargs):
        """Reject schema construction when the optional drf-spectacular dependency is unavailable."""
        raise ImportError("DABAutoSchema requires drf-spectacular to be installed. Install it with: pip install drf-spectacular")


if TYPE_CHECKING:
    from drf_spectacular.openapi import AutoSchema as _AutoSchemaBase
else:
    _AutoSchemaBase = _get_autoschema_base() or _MissingAutoSchema


class DABAutoSchema(DeprecationAutoSchemaMixin, _AutoSchemaBase):
    """
    AutoSchema with DAB deprecation support built-in.
    This is a ready-to-use schema class for services that don't need
    custom schema logic.
    """

    pass


def deprecated_fields_detail_hook(result, generator, **kwargs):
    """
    drf-spectacular postprocessing hook that adds x-api-deprecated-detail
    to individual field schemas based on DeprecationSerializerMixin.deprecated_fields.

    Only touches fields already marked deprecated: true. Does not modify
    descriptions or any other schema properties. Uses each component's registered
    serializer identity so same-named serializers cannot overwrite its details.
    """
    from ansible_base.lib.utils.views.deprecation import _DEPRECATED_FIELD_REGISTRY

    if not _DEPRECATED_FIELD_REGISTRY:
        return result

    schemas = result.get('components', {}).get('schemas', {})
    for component_name, schema in schemas.items():
        try:
            component = generator.registry[component_name, 'schemas']
        except KeyError:
            # Manually appended components may not have a registered serializer.
            continue

        serializer = component.object
        serializer_cls = serializer if isinstance(serializer, type) else type(serializer)
        fields = _DEPRECATED_FIELD_REGISTRY.get(serializer_cls)
        if fields:
            _add_deprecated_field_details(schema, fields)

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
