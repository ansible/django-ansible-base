"""Validate CleanText OpenAPI fragments against runtime injection keys."""

import pytest
from django.test import override_settings
from rest_framework import serializers

from ansible_base.api_documentation.clean_text_schema_hooks import inject_clean_text_pattern_components
from ansible_base.lib.metadata import (
    TIER1_PATTERN_DESCRIPTION,
    TIER2_PATTERN_DESCRIPTION,
    get_tier1_pattern,
    get_tier2_pattern,
    inject_clean_text_patterns,
)
from ansible_base.lib.schemas.clean_text_patterns import (
    CLEAN_TEXT_NESTED_PATTERN_PROPERTY_KEYS,
    CLEAN_TEXT_PATTERN_PROPERTY_KEYS,
    field_info_schema,
    nested_string_field_schema,
    openapi_components,
    pattern_properties,
)
from ansible_base.lib.serializers.mixins import CleanTextMixin
from test_app.models import Organization


class _OrgSerializer(CleanTextMixin, serializers.ModelSerializer):
    class Meta:
        model = Organization
        fields = ('name', 'description')


def test_pattern_properties_keys():
    props = pattern_properties()
    assert set(props) == {'pattern', 'patternDescription', 'flags', 'normalize'}
    assert props['normalize']['enum'] == ['NFC']
    for schema in props.values():
        assert schema.get('nullable') is True


def test_field_info_schema_marks_pattern_keys_optional():
    schema = field_info_schema()
    for key in CLEAN_TEXT_PATTERN_PROPERTY_KEYS:
        assert key in schema['properties']
        assert key not in schema['required']
    assert set(schema['required']) == {'type', 'hidden', 'label'}


def test_nested_schema_is_camel_case_without_normalize():
    schema = nested_string_field_schema()
    assert 'patternDescription' in schema['properties']
    assert 'pattern_description' not in schema['properties']
    assert 'normalize' not in schema['properties']
    assert CLEAN_TEXT_NESTED_PATTERN_PROPERTY_KEYS <= set(schema['properties'])


def test_openapi_components():
    comps = openapi_components()
    assert set(comps) == {
        'CleanTextFieldInfo',
        'CleanTextNestedStringField',
        'AuthenticatorPluginConfigurationField',
    }
    assert 'patternDescription' in comps['AuthenticatorPluginConfigurationField']['properties']
    assert 'patternDescription' in comps['CleanTextNestedStringField']['properties']
    assert 'normalize' not in comps['CleanTextNestedStringField']['properties']
    assert 'normalize' not in comps['AuthenticatorPluginConfigurationField']['properties']


@override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=True)
def test_schema_keys_cover_runtime_tier1_injection():
    ser = _OrgSerializer()
    field = ser.fields['name']
    info = inject_clean_text_patterns(field, {'type': 'string', 'hidden': False, 'label': 'Name'})
    runtime_keys = set(info) & CLEAN_TEXT_PATTERN_PROPERTY_KEYS
    assert runtime_keys == CLEAN_TEXT_PATTERN_PROPERTY_KEYS
    assert runtime_keys <= set(field_info_schema()['properties'])
    assert info['flags'] == 'u'
    assert info['normalize'] == 'NFC'
    assert info['patternDescription'] == TIER1_PATTERN_DESCRIPTION


@override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=True)
def test_schema_keys_cover_runtime_tier2_without_normalize():
    ser = _OrgSerializer()
    field = ser.fields['description']
    info = inject_clean_text_patterns(field, {'type': 'string', 'hidden': False, 'label': 'Description'})
    assert 'pattern' in info
    assert info['flags'] == 'i'
    assert 'normalize' not in info
    assert info['patternDescription'] == TIER2_PATTERN_DESCRIPTION
    assert 'normalize' in field_info_schema()['properties']


@override_settings(ENHANCED_INPUT_VALIDATION_ENABLED=False)
def test_runtime_omits_keys_when_setting_off_schema_still_declares_them():
    ser = _OrgSerializer()
    field = ser.fields['name']
    info = inject_clean_text_patterns(field, {'type': 'string', 'hidden': False, 'label': 'Name'})
    assert CLEAN_TEXT_PATTERN_PROPERTY_KEYS.isdisjoint(info)
    assert CLEAN_TEXT_PATTERN_PROPERTY_KEYS <= set(field_info_schema()['properties'])


def test_public_helpers_align_with_mapped_wire_keys():
    tier1 = get_tier1_pattern()
    tier2 = get_tier2_pattern()
    assert set(tier1) == {'pattern', 'description', 'flags', 'normalize'}
    assert set(tier2) == {'pattern', 'description', 'flags'}
    assert {'pattern', 'patternDescription', 'flags', 'normalize'} == set(pattern_properties())


def test_inject_clean_text_pattern_components_hook():
    result = inject_clean_text_pattern_components({}, None, None, True)
    schemas = result['components']['schemas']
    assert 'CleanTextFieldInfo' in schemas
    assert 'AuthenticatorPluginConfigurationField' in schemas
    result2 = inject_clean_text_pattern_components(result, None, None, True)
    assert result2['components']['schemas']['CleanTextFieldInfo'] is schemas['CleanTextFieldInfo']


def test_authenticator_plugins_view_declares_pattern_keys_in_extend_schema():
    """OpenAPI decorator payload includes optional pattern fields (camelCase)."""
    from ansible_base.authentication.views.authenticator_plugins import _authenticator_plugins_response_schema

    schema = _authenticator_plugins_response_schema()
    items = schema['properties']['authenticators']['items']['properties']['configuration_schema']['items']
    props = items['properties']
    assert 'pattern' in props
    assert 'patternDescription' in props
    assert 'flags' in props
    assert 'normalize' not in props
