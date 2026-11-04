from types import SimpleNamespace
from unittest import mock

import pytest
from django.core.exceptions import ValidationError

from ansible_base.lib.fields import BoundedTextField


class FakeConnection:
    """Minimal stand-in for db_type(): data_types by internal type, ops.quote_name."""

    vendor = 'postgresql'
    data_types = {'TextField': 'text'}
    ops = SimpleNamespace(quote_name=str)


def test_db_type_microsoft():
    field = BoundedTextField(sql_server_max_length=255)
    conn = FakeConnection()
    conn.vendor = 'microsoft'
    assert field.db_type(conn) == 'nvarchar(255)'


def test_db_type_non_microsoft_unchanged():
    field = BoundedTextField(sql_server_max_length=255)
    assert field.db_type(FakeConnection()) == 'text'


def test_deconstruct_roundtrip():
    field = BoundedTextField(sql_server_max_length=255, db_index=True, unique=True)
    name, path, args, kwargs = field.deconstruct()
    assert kwargs == {'sql_server_max_length': 255, 'db_index': True, 'unique': True}
    BoundedTextField(*args, **kwargs)  # reconstructs without error


def test_validator_rejects_overlength_on_microsoft():
    field = BoundedTextField(sql_server_max_length=10)
    with mock.patch('ansible_base.lib.fields.connection') as conn:
        conn.vendor = 'microsoft'
        with pytest.raises(ValidationError):
            field.run_validators('a' * 11)


def test_validator_allows_exactly_at_limit():
    field = BoundedTextField(sql_server_max_length=10)
    with mock.patch('ansible_base.lib.fields.connection') as conn:
        conn.vendor = 'microsoft'
        field.run_validators('a' * 10)  # no raise


def test_validator_inactive_on_other_vendors():
    field = BoundedTextField(sql_server_max_length=10)
    with mock.patch('ansible_base.lib.fields.connection') as conn:
        conn.vendor = 'postgresql'
        field.run_validators('a' * 500)  # no raise


def test_validator_counts_utf16_code_units():
    # U+1F600 encodes as a surrogate pair: 2 UTF-16 code units
    field = BoundedTextField(sql_server_max_length=2)
    with mock.patch('ansible_base.lib.fields.connection') as conn:
        conn.vendor = 'microsoft'
        field.run_validators('\U0001F600')  # exactly 2 units, passes
        with pytest.raises(ValidationError):
            field.run_validators('a\U0001F600')  # 3 units, fails


@pytest.mark.django_db
def test_serializer_enforces_bound_on_microsoft_only():
    from ansible_base.rbac.api.serializers import RoleDefinitionSerializer

    with mock.patch('ansible_base.lib.fields.connection') as conn:
        conn.vendor = 'microsoft'
        serializer = RoleDefinitionSerializer(data={'name': 'a' * 300, 'description': ''})
        assert not serializer.is_valid()
        assert 'name' in serializer.errors

        conn.vendor = 'postgresql'
        serializer = RoleDefinitionSerializer(data={'name': 'a' * 300, 'description': ''})
        errors = {} if serializer.is_valid() else serializer.errors
        assert 'name' not in errors  # postgres: overlength name is not a field error
