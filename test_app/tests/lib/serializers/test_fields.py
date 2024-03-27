#  Copyright 2024 Red Hat, Inc.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import pytest
from rest_framework.serializers import ValidationError

from ansible_base.lib.serializers.fields import UserAttrMap


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
