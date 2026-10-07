"""Reusable OpenAPI / JSON Schema fragments shared across AAP components."""

from ansible_base.lib.schemas.clean_text_patterns import (  # noqa: F401
    CLEAN_TEXT_NESTED_PATTERN_PROPERTY_KEYS,
    CLEAN_TEXT_PATTERN_PROPERTY_KEYS,
    authenticator_plugin_field_schema,
    field_info_schema,
    merge_clean_text_pattern_properties,
    nested_string_field_schema,
    openapi_components,
    pattern_properties,
)
