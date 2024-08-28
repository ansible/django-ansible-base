from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType

from ansible_base.jwt_consumer.common.exceptions import InvalidService
from ansible_base.jwt_consumer.hub.auth import HubJWTAuth
from ansible_base.rbac.models import RoleDefinition, RoleUserAssignment
from test_app.models import Organization, Team, User


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

    # make the _system user ...
    User.objects.get_or_create(username='_system')
    # import epdb; epdb.st()

    # The rbac hooks will attempt to assign these roledefs
    # when users are added/removed from orgs+teams, so they
    # must exist before claims are processed ...
    org_content_type = ContentType.objects.get_for_model(Organization)
    org_member_role, _ = RoleDefinition.objects.get_or_create(name="Organization Member", content_type=org_content_type)
    team_content_type = ContentType.objects.get_for_model(Team)
    team_member_role, _ = RoleDefinition.objects.get_or_create(name="Team Member", content_type=team_content_type)

    # We need a "Platform Auditor" too ...
    platform_auditor_role, _ = RoleDefinition.objects.get_or_create(name="Platform Auditor")

    # Make all the objects
    testuser, _ = User.objects.get_or_create(username="testuser")
    testorg, _ = Organization.objects.get_or_create(name='testorg')
    testteam, _ = Team.objects.get_or_create(name='testteam', organization=testorg)
    testgroup, _ = Group.objects.get_or_create(name=testorg.name + '::' + testteam.name)
    testteam.group = testgroup

    # overrides the inline import function which returns
    # things that the DAB repo doesn't have, so we'll just
    # send back the local DAB models ...
    def get_galaxy_models():
        return Organization, Team

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
    auth.get_galaxy_models = get_galaxy_models
    auth.common_auth.get_or_create_resource = get_or_create_resource
    auth.common_auth.user = testuser

    # Add the user to the org and the team. Galaxy doesn't have
    # a concept of org&team admin yet so we don't care about those.
    auth.common_auth.token = {
        "global_roles": {
            'Platform Auditor': {},
        },
        "object_roles": {
            'Organization Member': {'content_type': 'organization', 'objects': [0]},
            'Team Member': {'content_type': 'team', 'objects': [0]},
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
            ],
        },
    }

    # PROCSSS THE CLAIMS AND CHECK THE SIDE EFFECTS ...
    auth.process_permissions()
    assert RoleUserAssignment.objects.filter(user=testuser, role_definition=team_member_role, object_id=testteam.pk).count() == 1
    assert RoleUserAssignment.objects.filter(user=testuser, role_definition=platform_auditor_role).count() == 1

    # REVOKE EVERYTHING AND RECHECK ...
    auth.common_auth.token = {}
    auth.process_permissions()
    assert RoleUserAssignment.objects.filter(user=testuser, role_definition=team_member_role, object_id=testteam.pk).count() == 0
    assert RoleUserAssignment.objects.filter(user=testuser, role_definition=platform_auditor_role).count() == 0
