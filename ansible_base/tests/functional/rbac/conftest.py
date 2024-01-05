import pytest
from django.contrib.auth import get_user_model

from ansible_base.models.rbac import RoleDefinition
from ansible_base.rbac import permission_registry
from ansible_base.tests.functional.models import Inventory, Organization


@pytest.fixture
def organization():
    return Organization.objects.create(name='Default')


@pytest.fixture
def team(organization):
    return permission_registry.team_model.objects.create(name='example-team-or-group', organization=organization)


@pytest.fixture
def inventory(organization):
    return Inventory.objects.create(name='Default-inv', organization=organization)


@pytest.fixture
def rando():
    return get_user_model().objects.create(username='rando')


@pytest.fixture
def org_inv_rd():
    admin_permissions = ['change_organization', 'view_organization', 'change_inventory', 'view_inventory']
    return RoleDefinition.objects.create_from_permissions(permissions=admin_permissions, name='org-admin')


@pytest.fixture
def inv_rd():
    return RoleDefinition.objects.create_from_permissions(permissions=['change_inventory', 'view_inventory'], name='change-inv')


@pytest.fixture
def member_rd():
    return RoleDefinition.objects.create_from_permissions(
        permissions=[permission_registry.team_permission, f'view_{permission_registry.team_model._meta.model_name}'], name='team-member'
    )
