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
