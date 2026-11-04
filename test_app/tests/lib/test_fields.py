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
        field.run_validators('\U0001f600')  # exactly 2 units, passes
        with pytest.raises(ValidationError):
            field.run_validators('a\U0001f600')  # 3 units, fails


def test_inherited_fields_validator_is_not_bound_to_abstract_field():
    """Fields inherited from abstract bases must carry a validator that holds its own
    bound, not a method bound to the abstract base's field instance (which would
    report the abstract field's model/name and share mutable state across copies)."""
    from ansible_base.rbac.models import ObjectRole, RoleEvaluation, RoleEvaluationUUID

    for model, field_name in [(ObjectRole, 'object_id'), (RoleEvaluation, 'codename'), (RoleEvaluationUUID, 'codename')]:
        field = model._meta.get_field(field_name)
        for v in field.validators:
            owner = getattr(v, '__self__', None)
            if owner is None:
                continue
            assert (
                not hasattr(owner, 'sql_server_max_length') or owner is field
            ), f'{model.__name__}.{field_name}: validator is bound to {owner!r} instead of carrying its own bound'


@pytest.mark.parametrize('bound, flagged', [(0, True), (-1, True), (4001, True), (4000, False), (255, False), (1, False)])
def test_check_flags_out_of_range_sql_server_bound(bound, flagged):
    """The field's own system check rejects bounds nvarchar cannot hold (max 4000)."""
    from ansible_base.rbac.models import RoleDefinition

    field = RoleDefinition._meta.get_field('name')
    with mock.patch.object(field, 'sql_server_max_length', new=bound):
        errors = [e for e in field.check() if e.id == 'ansible_base.E003']
        assert bool(errors) is flagged


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
