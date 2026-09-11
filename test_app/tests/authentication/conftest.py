import pytest

from ansible_base.lib.testing.util import copy_fixture
from ansible_base.rbac import permission_registry
from ansible_base.rbac.models import RoleDefinition
from test_app.models import Inventory

SYSTEM_ROLE_NAME = 'System role'
TEAM_MEMBER_ROLE_NAME = 'Team Member'
TEAM_ADMIN_ROLE_NAME = 'Team Admin'
ORG_MEMBER_ROLE_NAME = 'Organization Member'
ORG_ADMIN_ROLE_NAME = 'Organization Admin'
OBJECT_SCOPED_ROLE_NAME = 'Inventory Admin'


@pytest.fixture
def system_role():
    return RoleDefinition.objects.create(
        name=SYSTEM_ROLE_NAME,
    )


@pytest.fixture
def object_scoped_role():
    return RoleDefinition.objects.create_from_permissions(
        permissions=['change_inventory', 'view_inventory'],
        name=OBJECT_SCOPED_ROLE_NAME,
        content_type=permission_registry.content_type_model.objects.get_for_model(Inventory),
    )


@copy_fixture(copies=3)  # noqa: F405
@pytest.fixture
def global_role(randname):
    return RoleDefinition.objects.create(name=randname("Global Role"))


@pytest.fixture
def default_rbac_roles_claims():
    return {'system': {'roles': {}}, 'organizations': {}}
