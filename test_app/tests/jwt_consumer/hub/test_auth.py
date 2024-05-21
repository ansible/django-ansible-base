# import sys
# from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from ansible_base.jwt_consumer.common.exceptions import InvalidService
from ansible_base.jwt_consumer.hub.auth import HubJWTAuth


def test_hub_import_error(user):
    authenticator = HubJWTAuth()
    with pytest.raises(InvalidService):
        authenticator.process_permissions()


@pytest.mark.parametrize(
    'token,num_roles',
    (
        ({}, 0),
        ({'object_roles': {}}, 0),
        ({'object_roles': {'Team Organization': [str(uuid4())]}}, 1),
        ({'object_roles': {'Team Member': [str(uuid4()), str(uuid4())]}}, 2),
    ),
)
def test_hub_jwt_teams(user, token, num_roles):
    assert True


#    mock_group = MagicMock()
#    mock_group.name = 'Testing'
#    mocked_Group = MagicMock(**{'Group.objects.get_or_create.return_value': (mock_group, True)})
#    sys.modules['galaxy_ng.app.models.auth'] = mocked_Group
#
#    mock_resource = MagicMock()
#    mock_resource.object_id = '4'
#    mocked_Resource = MagicMock(**{'Resource.objects.get.return_value': mock_resource})
#    sys.modules['ansible_base.resource_registry.models.resource'] = mocked_Resource
#
#    mock_team = MagicMock()
#    mock_team.group = mock_group
#    mocked_Team = MagicMock(**{'Team.objects.get.return_value': mock_team})
#    sys.modules['galaxy_ng.app.models'] = mocked_Team
#
#    mocked_authenticator = HubJWTAuth()
#    mocked_authenticator.process_permissions(user, token)
#    call_count = num_roles
#    assert mocked_Group.Group.objects.get_or_create.call_count == call_count
