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

import sys
from unittest.mock import MagicMock

import pytest

from ansible_base.jwt_consumer.common.exceptions import InvalidService
from ansible_base.jwt_consumer.hub.auth import HubJWTAuth


def test_hub_import_error(user):
    authenticator = HubJWTAuth()
    with pytest.raises(InvalidService):
        authenticator.process_permissions(user, {}, {})


@pytest.mark.parametrize(
    'token',
    (
        ({}),
        ({'teams': []}),
        ({'teams': [{'name': 'a'}]}),
        ({'teams': [{'name': 'a'}, {'name': 'b'}]}),
    ),
)
def test_hub_jwt_teams(user, token):
    mock_group = MagicMock()
    mocked_Group = MagicMock(**{'Group.objects.get_or_create.return_value': (mock_group, True)})
    sys.modules['galaxy_ng.app.models.auth'] = mocked_Group
    mocked_authenticator = HubJWTAuth()
    mocked_authenticator.process_permissions(user, token, {})
    call_count = len(token.get('teams', []))
    assert mocked_Group.Group.objects.get_or_create.call_count == call_count
