import sys
from copy import deepcopy

import pytest
from django.urls import path
from drf_spectacular.generators import SchemaGenerator
from drf_spectacular.plumbing import ResolvedComponent
from drf_spectacular.settings import spectacular_settings
from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers
from rest_framework.generics import GenericAPIView
from rest_framework.response import Response

from ansible_base.lib.utils import schema as schema_utils
from ansible_base.lib.utils.views import deprecation as deprecation_utils


@pytest.fixture
def generate_deprecated_field_schema(monkeypatch):
    """Provide isolated schema generation with the deprecation hook and split components enabled."""
    monkeypatch.setattr(deprecation_utils, '_DEPRECATED_FIELD_REGISTRY', {})
    monkeypatch.setattr(spectacular_settings, 'POSTPROCESSING_HOOKS', [schema_utils.deprecated_fields_detail_hook])
    monkeypatch.setattr(spectacular_settings, 'PREPROCESSING_HOOKS', [])
    monkeypatch.setattr(spectacular_settings, 'COMPONENT_SPLIT_REQUEST', True)
    monkeypatch.setattr(spectacular_settings, 'COMPONENT_SPLIT_PATCH', True)

    def generate(*serializer_classes):
        """Generate POST and PATCH operations for the supplied serializer classes."""

        class ExampleView(GenericAPIView):
            schema = schema_utils.DABAutoSchema()
            authentication_classes = []
            permission_classes = []

            def post(self, request):
                """Expose a creation operation for request and response schema generation."""
                return Response({})

            def patch(self, request):
                """Expose a partial-update operation for patched request schema generation."""
                return Response({})

        generator = SchemaGenerator(
            patterns=[path(f'example-{index}/', ExampleView.as_view(serializer_class=serializer)) for index, serializer in enumerate(serializer_classes)]
        )
        return generator.get_schema(public=True)

    return generate


def _inventory_source_serializer(detail):
    """Create a distinct serializer class with a reused name and its own deprecation detail."""

    @extend_schema_serializer(deprecate_fields=['credential'])
    class InventorySourceSerializer(deprecation_utils.DeprecationSerializerMixin, serializers.Serializer):
        credential = serializers.IntegerField(required=False)
        deprecated_fields = {'credential': detail}

    return InventorySourceSerializer


def test_deprecated_field_details_ignore_unused_same_named_serializer(generate_deprecated_field_schema):
    """An unused same-named serializer must not replace the active serializer's full message."""
    detail = 'The credential field has been deprecated. Use credentials instead.'
    awx_serializer = _inventory_source_serializer(detail)
    unused_plugin_serializer = _inventory_source_serializer('Use credential_id instead.')
    assert awx_serializer is not unused_plugin_serializer
    assert awx_serializer.__name__ == unused_plugin_serializer.__name__

    schema = generate_deprecated_field_schema(awx_serializer)

    for name in ('InventorySource', 'InventorySourceRequest', 'PatchedInventorySourceRequest'):
        credential = schema['components']['schemas'][name]['properties']['credential']
        assert credential['deprecated'] is True
        assert credential['x-api-deprecated-detail'] == detail


@pytest.mark.parametrize('name_override', ['meta', 'decorator'])
def test_same_named_serializers_keep_their_own_deprecation_details(generate_deprecated_field_schema, name_override):
    """Distinct component names preserve each serializer's details across request and response variants."""
    awx_detail = 'The credential field has been deprecated. Use credentials instead.'
    plugin_detail = 'The credential field has been deprecated. Use credential_id instead.'
    awx_serializer = _inventory_source_serializer(awx_detail)
    plugin_serializer = _inventory_source_serializer(plugin_detail)

    for serializer, component_name in ((awx_serializer, 'AwxInventorySource'), (plugin_serializer, 'PluginInventorySource')):
        if name_override == 'meta':

            class Meta:
                ref_name = component_name

            serializer.Meta = Meta
        else:
            extend_schema_serializer(component_name=component_name)(serializer)

    schema = generate_deprecated_field_schema(awx_serializer, plugin_serializer)

    for name, detail in (('AwxInventorySource', awx_detail), ('PluginInventorySource', plugin_detail)):
        for component_name in (name, f'{name}Request', f'Patched{name}Request'):
            credential = schema['components']['schemas'][component_name]['properties']['credential']
            assert credential['deprecated'] is True
            assert credential['x-api-deprecated-detail'] == detail


@pytest.mark.parametrize('component_object', [None, object(), serializers.Serializer()])
def test_deprecated_field_detail_hook_leaves_unrelated_components_unchanged(monkeypatch, component_object):
    """Components without a registered deprecated serializer must not inherit details by name."""
    monkeypatch.setattr(deprecation_utils, '_DEPRECATED_FIELD_REGISTRY', {})
    _inventory_source_serializer('Use credentials instead.')
    generator = SchemaGenerator(patterns=[])
    generator.registry.register(ResolvedComponent(name='InventorySource', type=ResolvedComponent.SCHEMA, object=component_object))
    result = {
        'components': {
            'schemas': {
                'InventorySource': {'properties': {'credential': {'deprecated': True}}},
                'InventorySourceRequest': {'properties': {'credential': {'deprecated': True}}},
            }
        }
    }
    original = deepcopy(result)

    assert schema_utils.deprecated_fields_detail_hook(result=result, generator=generator) is result
    assert result == original


def test_get_autoschema_base_returns_none_when_dependency_is_missing(monkeypatch):
    """A missing optional dependency leaves the AutoSchema base unavailable."""
    monkeypatch.setitem(sys.modules, 'drf_spectacular.openapi', None)

    assert schema_utils._get_autoschema_base() is None


def test_missing_autoschema_raises_a_helpful_import_error():
    """Instantiating the fallback schema explains which optional dependency is required."""
    with pytest.raises(ImportError, match='DABAutoSchema requires drf-spectacular'):
        schema_utils._MissingAutoSchema()


def test_deprecated_fields_detail_hook_returns_unchanged_schema_without_registry(monkeypatch):
    """An empty deprecation registry leaves the schema untouched without consulting a generator."""
    monkeypatch.setattr(deprecation_utils, '_DEPRECATED_FIELD_REGISTRY', {})
    result = {'components': {'schemas': {'Example': {'properties': {}}}}}

    assert schema_utils.deprecated_fields_detail_hook(result, None) is result
