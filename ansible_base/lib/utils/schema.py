"""
This module provides optional decorators and schema classes that gracefully handle missing dependencies.
"""


class DeprecationAutoSchemaMixin:
    """
    Mixin that adds deprecation support to drf-spectacular AutoSchema.
    """
    def is_deprecated(self):
        """
        Return True if this operation should be marked as deprecated.
        """
        view_class = self.view.__class__
        return (
            getattr(self.view, 'deprecated', False)
            or getattr(view_class, 'deprecated', False)
            or bool(getattr(self.view, 'deprecation', None))
            or bool(getattr(view_class, 'deprecation', None))
        )

    def get_extensions(self):
        """
        Add x-api-deprecated-detail extension with the actual deprecation message.
        """
        extensions = super().get_extensions()
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
