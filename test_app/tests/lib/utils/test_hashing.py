import uuid
from ansible_base.lib.utils.hashing import hash_serializer_data


DATA = {
    "name": "foo",
    "id": 1234,
    "uuid": uuid.uuid4() 
}
    

def test_hash_serializer_data_idempotency():
    """Test hashing same data gives same output"""
    assert hash_serializer_data(DATA) == hash_serializer_data(DATA)



def test_hash_serializer_data_difference():
    """Test hashing different data changes the hash"""
    assert hash_serializer_data(DATA) != hash_serializer_data({"version": 4, **DATA})