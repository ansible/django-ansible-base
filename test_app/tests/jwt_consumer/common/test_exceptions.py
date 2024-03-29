import pytest

from ansible_base.jwt_consumer.common import exceptions


def test_invalid_service_exception():
    service = 'testing'
    with pytest.raises(exceptions.InvalidService) as e:
        raise exceptions.InvalidService(service)
    assert f"This authentication class requires {service}." in str(e)
