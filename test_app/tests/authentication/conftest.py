import pytest

from ansible_base.lib.testing.util import copy_fixture
from ansible_base.rbac.models import RoleDefinition

SYSTEM_ROLE_NAME = 'System role'
TEAM_MEMBER_ROLE_NAME = 'Team Member'
ORG_MEMBER_ROLE_NAME = 'Organization Member'


@pytest.fixture
def system_role():
    return RoleDefinition.objects.create(
        name=SYSTEM_ROLE_NAME,
    )


@copy_fixture(copies=3)  # noqa: F405
@pytest.fixture
def global_role(randname):
    return RoleDefinition.objects.create(name=randname("Global Role"))


@pytest.fixture
def default_rbac_roles_claims():
    return {'system': {'roles': {}}, 'organizations': {}}
