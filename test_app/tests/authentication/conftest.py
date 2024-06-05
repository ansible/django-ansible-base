import pytest

from ansible_base.lib.utils.auth import get_organization_model, get_team_model
from ansible_base.rbac import permission_registry
from ansible_base.rbac.models import RoleDefinition

SYSTEM_ROLE_NAME = 'System role'
TEAM_MEMBER_ROLE_NAME = 'Team Member'
ORG_MEMBER_ROLE_NAME = 'Organization Member'


@pytest.fixture
def system_role():
    return RoleDefinition.objects.create(
        name=SYSTEM_ROLE_NAME,
    )


@pytest.fixture
def team_member_role():
    return RoleDefinition.objects.create(
        name=TEAM_MEMBER_ROLE_NAME,
        content_type=permission_registry.content_type_model.objects.get_for_model(get_team_model()),
        managed=True,
    )


@pytest.fixture
def organization_member_role():
    return RoleDefinition.objects.create(
        name=ORG_MEMBER_ROLE_NAME,
        content_type=permission_registry.content_type_model.objects.get_for_model(get_organization_model()),
        managed=True,
    )
