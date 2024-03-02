import uuid

from rest_framework.serializers import CharField, IntegerField, Serializer, UUIDField
from beartype import beartype, BeartypeConf, BeartypeStrategy

from ansible_base.lib.utils.hashing import hash_serializer_data

nobeartype = beartype(conf=BeartypeConf(strategy=BeartypeStrategy.O0))

DATA = {"name": "foo", "id": 1234, "uuid": uuid.uuid4()}


class DataSerializer(Serializer):
    name = CharField()
    id = IntegerField()
    uuid = UUIDField()


@nobeartype
def test_hash_serializer_data_idempotency():
    """Test hashing same data gives same output"""
    assert hash_serializer_data(DATA, DataSerializer) == hash_serializer_data(DATA, DataSerializer)


@nobeartype
def test_hash_serializer_data_difference():
    """Test hashing different data changes the hash"""
    assert hash_serializer_data(DATA, DataSerializer) != hash_serializer_data({**DATA, **{"id": 4567}}, DataSerializer)


@nobeartype
def test_hash_serializer_with_nested_field():
    """Test hashing can be performed on nested data"""
    NESTED_DATA = {"field": {"name": "foo", "id": 1234}}

    class NestedSerializer(Serializer):
        def to_representation(self, instance):
            return instance

    assert hash_serializer_data(NESTED_DATA, NestedSerializer, "field") == hash_serializer_data(NESTED_DATA["field"], NestedSerializer)
