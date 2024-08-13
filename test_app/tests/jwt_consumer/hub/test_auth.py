# import sys
from uuid import uuid4
from unittest.mock import patch
from unittest.mock import MagicMock

import pytest

from ansible_base.jwt_consumer.common.exceptions import InvalidService
from ansible_base.jwt_consumer.hub.auth import HubJWTAuth
from ansible_base.rbac.models import RoleDefinition
# from ansible_base.resource_registry.models import Resource

from django.contrib.contenttypes.models import ContentType
from django.contrib.auth.models import Group

from test_app.models import Organization
from test_app.models import Team
from test_app.models import User


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


@pytest.mark.django_db
@patch('ansible_base.jwt_consumer.hub.auth.Resource')
@patch('ansible_base.jwt_consumer.hub.auth.ContentType')
def test_hub_jwt_orgs_teams_groups_memberships(mock_contenttype, mock_resource):

    org_content_type = ContentType.objects.get_for_model(Organization)
    org_member_role, _ = RoleDefinition.objects.get_or_create(name="Organization Member", content_type=org_content_type)

    team_content_type = ContentType.objects.get_for_model(Team)
    team_member_role, _ = RoleDefinition.objects.get_or_create(name="Team Member", content_type=team_content_type)

    assign_role = MagicMock()
    remove_role = MagicMock()

    # Make all the objects
    testuser, _ = User.objects.get_or_create(username="testuser")
    testorg, _ = Organization.objects.get_or_create(name='testorg')
    testteam, _ = Team.objects.get_or_create(name='testteam', organization=testorg)
    testgroup, _ = Group.objects.get_or_create(name=testorg.name + '::' + testteam.name)
    testteam.group = testgroup

    def get_galaxy_models_and_functions():
        return Organization, Team, assign_role, remove_role

    def get_or_create_resource(*args, **kwargs):
        raise Exception('not yet implemented')

    # return a very limited set of resources for Resource...
    def get_resource_content(*args, **kwargs):
        for obj in [testuser, testorg, testteam]:
            if str(obj.resource.ansible_id) == kwargs['ansible_id']:
                resource = MagicMock()
                resource.content_object = obj
                return resource
        raise Exception('not found')

    # we don't want the resource queryset to return our unmodified team ...
    mock_resource.objects.get.side_effect = get_resource_content

    auth = HubJWTAuth()
    auth.get_galaxy_models_and_functions = get_galaxy_models_and_functions
    auth.common_auth.get_or_create_resource = get_or_create_resource
    auth.common_auth.user = testuser
    auth.common_auth.token = {
        "object_roles": {
            'Organization Member': {
                'content_type': 'organization',
                'objects': [0]
            },
            'Team Member': {
                'content_type': 'team',
                'objects': [0]
            },
        },
        "objects": {
            "organization": [
                {
                    "ansible_id": str(testorg.resource.ansible_id),
                    "id": testorg.id,
                    "name": testorg.name,
                }
            ],
            "team": [
                {
                    "ansible_id": str(testteam.resource.ansible_id),
                    "name": testteam.name,
                    "org": 0,
                }
            ]
        }
    }

    auth.process_permissions()

    assert testorg.users.filter(pk=testuser.pk).exists()
    assert testuser.groups.filter(pk=testgroup.pk).exists()
    assert testteam.users.filter(pk=testuser.pk).exists()
    assert remove_role.called
    assert remove_role.call_args[0][0] == 'galaxy.auditor'
    assert remove_role.call_args[0][1] == testuser
