"""OpenAPI schema fragments for CleanTextMixin validation pattern fields.

Runtime injection (``inject_clean_text_patterns``, ``get_tier1_pattern``,
``get_tier2_pattern``, and component-local JSON sub-schema helpers) adds these
keys to OPTIONS / nested GET field catalogs when
``ENHANCED_INPUT_VALIDATION_ENABLED`` is on. OpenAPI schemas historically
omitted them, creating a documented-vs-actual mismatch.

This module is the least-maintenance source of truth for declaring those
optional fields so Gateway, Hub, Controller, and EDA can ``$ref`` or merge the
same property set instead of hand-copying descriptions.
"""

from copy import deepcopy

# OPTIONS / tier-1 FieldInfo may include all four keys.
CLEAN_TEXT_PATTERN_PROPERTY_KEYS = frozenset({'pattern', 'patternDescription', 'flags', 'normalize'})

# Nested JSON catalogs (credential inputs, etc.) are Tier 2 only — no normalize.
CLEAN_TEXT_NESTED_PATTERN_PROPERTY_KEYS = frozenset({'pattern', 'patternDescription', 'flags'})

_PATTERN_DESCRIPTION = (
    'Regex pattern (ECMAScript-compatible, no delimiters) that API clients can '
    'use for real-time client-side validation before submit. UX convenience '
    'only -- the server independently enforces validation, so clients must not '
    'treat this as a substitute for handling server-side errors. Omitted when '
    'ENHANCED_INPUT_VALIDATION_ENABLED is off, or when the field has no '
    'validation rule (non-text, excluded, or secret).'
)

_PATTERN_DESCRIPTION_DESC = (
    'Human-readable explanation of `pattern`, suitable for display next to the '
    'field. Present under the same condition as `pattern` -- the two always '
    'appear or are absent together.'
)

_FLAGS_DESCRIPTION = (
    'Regex flags to apply when evaluating `pattern` (e.g. "u" for Unicode mode, ' + '"i" for case-insensitive). Present under the same condition as `pattern`.'
)

_NORMALIZE_DESCRIPTION = (
    'Unicode normalization form to apply before evaluating `pattern`. Requires '
    'ENHANCED_INPUT_VALIDATION_ENABLED and a tier-1 "name" field -- narrower '
    'than the other three keys, so it can be absent even when `pattern` is present. '
    'Not used on nested JSON field catalogs (credential inputs, etc.).'
)


def pattern_properties(*, include_normalize: bool = True) -> dict:
    """Return OpenAPI property defs for optional validation-hint keys.

    Properties are never listed in ``required`` -- population is controlled by
    the install-time setting and per-field eligibility, not by schema visibility.
    """
    props = {
        'pattern': {
            'type': 'string',
            'nullable': True,
            'description': _PATTERN_DESCRIPTION,
        },
        'patternDescription': {
            'type': 'string',
            'nullable': True,
            'description': _PATTERN_DESCRIPTION_DESC,
        },
        'flags': {
            'type': 'string',
            'nullable': True,
            'description': _FLAGS_DESCRIPTION,
        },
    }
    if include_normalize:
        props['normalize'] = {
            'type': 'string',
            'nullable': True,
            'enum': ['NFC'],
            'description': _NORMALIZE_DESCRIPTION,
        }
    return props


def merge_clean_text_pattern_properties(properties: dict, *, include_normalize: bool = True) -> dict:
    """Return a copy of ``properties`` with CleanText pattern keys merged in."""
    merged = deepcopy(properties)
    for key, schema in pattern_properties(include_normalize=include_normalize).items():
        merged.setdefault(key, schema)
    return merged


def field_info_schema() -> dict:
    """OpenAPI object schema for DRF OPTIONS field_info entries (CleanTextMetadata)."""
    base_properties = {
        'type': {'type': 'string'},
        'hidden': {'type': 'boolean'},
        'label': {'type': 'string'},
        'help_text': {'type': 'string'},
        'filterable': {'type': 'boolean'},
        'required': {'type': 'boolean'},
        'max_length': {'type': 'integer'},
        'default': {},
    }
    return {
        'type': 'object',
        'description': (
            'Per-field metadata returned in OPTIONS actions. When '
            'ENHANCED_INPUT_VALIDATION_ENABLED is on, CharField/TextField entries '
            'on CleanTextMixin serializers may also include pattern hint keys. '
            'Tier-1 name fields may include normalize=NFC; tier-2 fields do not.'
        ),
        'properties': merge_clean_text_pattern_properties(base_properties, include_normalize=True),
        'required': ['type', 'hidden', 'label'],
        'additionalProperties': True,
    }


def nested_string_field_schema() -> dict:
    """OpenAPI object schema for credential-type ``inputs.fields[]`` entries.

    Matches Controller credential-type catalogs: identity via ``id`` + ``label``,
    requiredness via parent ``inputs.required``, Tier-2 pattern hints only
    (no ``normalize``). Other keys (``default``, ``multiline``, ``format``,
    ``ask_at_runtime``, …) are allowed via additionalProperties.
    """
    base_properties = {
        'id': {
            'type': 'string',
            'description': 'Stable field identifier (used in inputs.required and credential payloads).',
        },
        'label': {'type': 'string', 'description': 'Human-readable field label.'},
        'type': {
            'type': 'string',
            'description': 'Field type (e.g. string, boolean). Pattern hints apply to non-secret strings.',
        },
        'help_text': {'type': 'string'},
        'secret': {
            'type': 'boolean',
            'description': 'When true, pattern hints are omitted.',
        },
        'default': {
            'description': 'Optional default value (string, boolean, etc.).',
        },
        'multiline': {'type': 'boolean'},
        'format': {'type': 'string'},
        'ask_at_runtime': {'type': 'boolean'},
    }
    return {
        'type': 'object',
        'description': (
            'Dynamic credential-type input field catalog entry. When '
            'ENHANCED_INPUT_VALIDATION_ENABLED is on, non-secret string fields '
            'may include pattern, patternDescription, and flags (Tier 2; no normalize).'
        ),
        'properties': merge_clean_text_pattern_properties(base_properties, include_normalize=False),
        'additionalProperties': True,
    }


def authenticator_plugin_field_schema() -> dict:
    """OpenAPI object schema for authenticator ``configuration_schema[]`` entries."""
    base_properties = {
        'name': {'type': 'string', 'description': 'Configuration field name.'},
        'help_text': {'type': 'string'},
        'required': {'type': 'boolean'},
        'default': {},
        'type': {'type': 'string', 'description': 'DRF field class name (e.g. CharField).'},
        'ui_field_label': {'type': 'string'},
        'choices': {
            'type': 'array',
            'items': {},
            'description': 'Optional choice list when the field defines choices.',
        },
    }
    return {
        'type': 'object',
        'description': (
            'Authenticator plugin configuration field. When '
            'ENHANCED_INPUT_VALIDATION_ENABLED is on, non-secret CharField entries '
            'may include pattern, patternDescription, and flags (Tier 2; no normalize).'
        ),
        'properties': merge_clean_text_pattern_properties(base_properties, include_normalize=False),
        'additionalProperties': True,
    }


def openapi_components() -> dict:
    """components.schemas entries for spectacular postprocessing hooks."""
    return {
        'CleanTextFieldInfo': field_info_schema(),
        'CleanTextNestedStringField': nested_string_field_schema(),
        'AuthenticatorPluginConfigurationField': authenticator_plugin_field_schema(),
    }
