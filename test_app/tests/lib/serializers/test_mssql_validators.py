from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError

from ansible_base.lib.serializers import validators


def test_mssql_text_length_skips_empty_values_and_other_backends(monkeypatch):
    monkeypatch.setattr(validators, 'connection', SimpleNamespace(vendor='microsoft'))
    validators.validate_mssql_text_length('', max_length=1)
    validators.validate_mssql_text_length(None, max_length=1)

    monkeypatch.setattr(validators, 'connection', SimpleNamespace(vendor='postgresql'))
    validators.validate_mssql_text_length('longer than one', max_length=1)


def test_mssql_text_length_accepts_limit_and_rejects_excess(monkeypatch):
    monkeypatch.setattr(validators, 'connection', SimpleNamespace(vendor='microsoft'))
    validators.validate_mssql_text_length('123', max_length=3, field_name='Description')

    with pytest.raises(ValidationError, match='Description is limited to 3 characters'):
        validators.validate_mssql_text_length('1234', max_length=3, field_name='Description')


@pytest.mark.parametrize(
    ('validator', 'value', 'message'),
    [
        (validators.validate_mssql_description, 'x' * 4001, 'Description is limited to 4000 characters'),
        (validators.validate_mssql_object_id, 'x' * 451, 'Object ID is limited to 450 characters'),
        (validators.validate_mssql_codename, 'x' * 101, 'Codename is limited to 100 characters'),
        (validators.validate_mssql_parent_reference, 'x' * 451, 'Parent reference is limited to 450 characters'),
    ],
)
def test_mssql_convenience_validators_enforce_limits(monkeypatch, validator, value, message):
    monkeypatch.setattr(validators, 'connection', SimpleNamespace(vendor='microsoft'))

    with pytest.raises(ValidationError, match=message):
        validator(value)
