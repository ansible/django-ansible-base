import uuid
from types import SimpleNamespace

import pytest
from django.db import models

from ansible_base.rbac.remote import RemoteObject, StandInPK


@pytest.mark.django_db
def test_validate_object_id_uuid(foo_type_uuid):
    "The 42 primary key is invalid for uuid type objects"
    with pytest.raises(ValueError):
        RemoteObject(content_type=foo_type_uuid, object_id=42)


@pytest.mark.django_db
def test_validate_object_id_int(foo_type):
    with pytest.raises(ValueError):
        RemoteObject(content_type=foo_type, object_id=str(uuid.uuid4()))


@pytest.mark.parametrize('pk_field_type', ['char(32)', 'uniqueidentifier'])
def test_standin_pk_recognizes_sql_server_uuid_types(pk_field_type):
    """SQL Server's UUID column types should retain UUID semantics for remote objects."""
    pk = StandInPK(SimpleNamespace(pk_field_type=pk_field_type))
    object_id = uuid.uuid4()

    assert pk.to_python(str(object_id)) == object_id
    assert pk.get_prep_value(object_id) == str(object_id)
    assert isinstance(pk.django_field(), models.UUIDField)
