from types import SimpleNamespace

import pytest
from django.apps import apps
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.validators import MaxLengthValidator

from ansible_base.lib.serializers import common as common_serializers
from ansible_base.lib.serializers.common import CommonModelSerializer
from ansible_base.rbac.api.serializers import RoleDefinitionSerializer


@pytest.mark.django_db
def test_invalid_content_type(admin_api_client):
    serializer = RoleDefinitionSerializer(
        data=dict(name='foo-role-def', description='bar', permissions=['shared.view_organization'], content_type='aap.foo_does_not_exist_model')
    )
    assert not serializer.is_valid()
    assert 'object does not exist' in str(serializer.errors['content_type'])
    assert 'permissions' not in serializer.errors


@pytest.mark.django_db
def test_invalid_permission(admin_api_client):
    serializer = RoleDefinitionSerializer(
        data=dict(name='foo-role-def', description='bar', permissions=['aap.view_foohomeosi'], content_type='shared.organization')
    )
    assert not serializer.is_valid()
    assert 'object does not exist' in str(serializer.errors['permissions'])
    assert 'content_type' not in serializer.errors


def test_role_definition_name_matches_mssql_column_limit(monkeypatch):
    monkeypatch.setattr(common_serializers, 'connection', SimpleNamespace(vendor='microsoft'))
    serializer = RoleDefinitionSerializer()
    name_field = serializer.fields['name']

    assert name_field.max_length == 255
    max_length_validator = next(validator for validator in name_field.validators if isinstance(validator, MaxLengthValidator))
    with pytest.raises(DjangoValidationError, match='at most 255 characters'):
        max_length_validator('x' * 256)


def test_role_definition_name_has_no_mssql_limit_on_postgresql(monkeypatch):
    monkeypatch.setattr(common_serializers, 'connection', SimpleNamespace(vendor='postgresql'))
    serializer = RoleDefinitionSerializer()

    assert serializer.fields['name'].max_length is None


@pytest.mark.parametrize(
    ('app_label', 'model_name', 'field_name', 'expected_max_length'),
    [
        ('dab_rbac', 'ObjectRole', 'object_id', 450),
        ('dab_rbac', 'ObjectRole', 'parent_reference', 450),
        ('dab_rbac', 'RoleEvaluation', 'codename', 100),
        ('dab_resource_registry', 'Resource', 'object_id', 450),
    ],
)
def test_common_serializer_uses_schema_limits_for_constrained_text_fields(monkeypatch, app_label, model_name, field_name, expected_max_length):
    monkeypatch.setattr(common_serializers, 'connection', SimpleNamespace(vendor='microsoft'))
    model = apps.get_model(app_label, model_name)
    meta = type('Meta', (CommonModelSerializer.Meta,), {'model': model, 'fields': (field_name,)})
    serializer_class = type(f'{model_name}LimitSerializer', (CommonModelSerializer,), {'Meta': meta})

    serializer_field = serializer_class().fields[field_name]

    assert serializer_field.max_length == expected_max_length
