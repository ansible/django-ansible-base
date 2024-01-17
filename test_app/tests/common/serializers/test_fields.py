import pytest
from rest_framework.serializers import ValidationError

from ansible_base.common.serializers.fields import UserAttrMap


def test_check_user_attribute_map_success():
    attr_map = UserAttrMap()
    attr_map.run_validation(data={"username": "uid", "email": "mail", "first_name": "givenName", "last_name": "sn"})
    assert True


@pytest.mark.parametrize(
    "user_attr_map, exception",
    [
        ({"email": False}, {"email": "Must be a string"}),
        ({"username": "uid"}, {"email": "Must be present"}),
        ({"weird_field": "oh_no"}, {"email": "Must be present", "weird_field": "Is not valid"}),
        ({"weird_field": "oh_no", "email": "mail"}, {"weird_field": "Is not valid"}),
        ("string!", 'Expected a dictionary of items but got type "str".'),
    ],
)
def test_check_user_attribute_map_exceptions(user_attr_map, exception):
    with pytest.raises(ValidationError) as generated_exception:
        attr_map = UserAttrMap()
        attr_map.run_validation(data=user_attr_map)
    assert generated_exception.value.args[0] == exception
