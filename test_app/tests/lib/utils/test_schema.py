import sys

import pytest

from ansible_base.lib.utils import schema as schema_utils
from ansible_base.lib.utils.views import deprecation as deprecation_utils


def test_serializer_ref_name_uses_meta_override():
    class CustomSerializer:
        class Meta:
            ref_name = 'CustomPayload'

    assert schema_utils._get_serializer_ref_name(CustomSerializer) == 'CustomPayload'


def test_serializer_ref_name_without_serializer_suffix_uses_class_name():
    class CustomPayload:
        pass

    assert schema_utils._get_serializer_ref_name(CustomPayload) == 'CustomPayload'


def test_get_autoschema_base_returns_none_when_dependency_is_missing(monkeypatch):
    monkeypatch.setitem(sys.modules, 'drf_spectacular.openapi', None)

    assert schema_utils._get_autoschema_base() is None


def test_missing_autoschema_raises_a_helpful_import_error():
    with pytest.raises(ImportError, match='DABAutoSchema requires drf-spectacular'):
        schema_utils._MissingAutoSchema()


def test_deprecated_fields_detail_hook_returns_unchanged_schema_without_registry(monkeypatch):
    monkeypatch.setattr(deprecation_utils, '_DEPRECATED_FIELD_REGISTRY', {})
    result = {'components': {'schemas': {'Example': {'properties': {}}}}}

    assert schema_utils.deprecated_fields_detail_hook(result, None) is result
