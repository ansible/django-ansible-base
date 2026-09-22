"""drf-spectacular postprocessing hooks for CleanText pattern schema components.

Register ``inject_clean_text_pattern_components`` in SPECTACULAR_SETTINGS
``POSTPROCESSING_HOOKS`` (or call it from a component-local hook) so the shared
``CleanTextFieldInfo`` / nested field schemas appear under
``components.schemas``. Components then ``$ref`` these instead of duplicating
optional pattern field definitions.
"""


def inject_clean_text_pattern_components(result, generator, request, public):  # noqa: ARG001
    """Ensure CleanText pattern OpenAPI components exist in the generated schema."""
    from ansible_base.lib.schemas.clean_text_patterns import openapi_components

    components = result.setdefault('components', {})
    schemas = components.setdefault('schemas', {})
    for name, schema in openapi_components().items():
        schemas.setdefault(name, schema)
    return result
