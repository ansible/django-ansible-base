import pytest

from ansible_base.rbac.models import RoleDefinition

SYSTEM_ROLE_NAME = 'System role'
TEAM_MEMBER_ROLE_NAME = 'Team Member'
ORG_MEMBER_ROLE_NAME = 'Organization Member'


@pytest.fixture
def system_role():
    return RoleDefinition.objects.create(
        name=SYSTEM_ROLE_NAME,
    )
