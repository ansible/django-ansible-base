"""Tests for UUID type detection in rbac.remote.StandInPK.

Remote content types store the remote model's primary key database type as a
string ("uuid", "integer", ...). Those strings are vendor-specific: a UUID
primary key is "uuid" on PostgreSQL but "uniqueidentifier" on SQL Server, and
models that store UUIDs in text columns report "char(32)". StandInPK must
recognize all of them as UUID types.
"""

import uuid
from unittest.mock import Mock

import pytest

from ansible_base.rbac.remote import StandInPK


def make_stand_in_pk(pk_field_type):
    ct = Mock(pk_field_type=pk_field_type)
    return StandInPK(ct)


@pytest.mark.parametrize('db_type', ['uuid', 'uniqueidentifier', 'char(32)'])
def test_is_uuid_type_accepts_all_uuid_storage_types(db_type):
    assert make_stand_in_pk(db_type)._is_uuid_type() is True


@pytest.mark.parametrize('db_type', ['integer', 'bigint', 'integer unsigned', 'char(36)'])
def test_is_uuid_type_rejects_non_uuid_types(db_type):
    assert make_stand_in_pk(db_type)._is_uuid_type() is False


def test_uniqueidentifier_field_preps_uuid_values():
    """A StandInPK over a uniqueidentifier (SQL Server UUID) column formats
    UUID params like the uuid path does."""
    stand_in_pk = make_stand_in_pk('uniqueidentifier')
    value = uuid.uuid4()

    assert stand_in_pk.get_prep_value(value) == str(value)
    assert stand_in_pk.get_prep_value(str(value)) == str(value)
    assert stand_in_pk.to_python(str(value)) == value


def test_db_type_reports_vendor_specific_uuid_type():
    """db_type delegates to the mimicked Django field, returning the
    vendor-specific column type for get_evaluation_model comparisons."""
    connection = Mock(data_types={'UUIDField': 'uniqueidentifier', 'IntegerField': 'int'})

    assert make_stand_in_pk('uniqueidentifier').db_type(connection) == 'uniqueidentifier'
    assert make_stand_in_pk('char(32)').db_type(connection) == 'uniqueidentifier'
    assert make_stand_in_pk('uuid').db_type(connection) == 'uniqueidentifier'
    assert make_stand_in_pk('integer').db_type(connection) == 'int'
