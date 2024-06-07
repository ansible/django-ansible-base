from unittest import mock

import pytest


@pytest.mark.django_db
def test_clients_do_not_conflict(unauthenticated_api_client, user_api_client, admin_api_client):
    assert dict(user_api_client.cookies) != dict(admin_api_client.cookies)
    assert dict(unauthenticated_api_client.cookies) == {}


class ThrowawayObject:
    def method_that_should_be_patched(self):
        raise Exception("object was not patched properly")


def test_mock_method(create_mock_method):
    with pytest.raises(StopIteration):
        fields_list = [
            {"field": "hi"},
        ]

        with mock.patch("test_app.tests.fixtures.test_fixtures.ThrowawayObject.method_that_should_be_patched", create_mock_method(fields_list)):
            test_object = ThrowawayObject()
            # Test good path: assert that calling object fields are overwritten
            for fields in fields_list:
                test_object.method_that_should_be_patched()
                for field, value in fields.items():
                    assert getattr(test_object, field, None) == value
            # Test bad path: ie assert that the mock method throws an exception when it is called more than expected
            test_object.method_that_should_be_patched()
