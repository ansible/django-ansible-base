import pytest
from django.contrib.auth import get_user_model

from ansible_base.rbac import permission_registry
from ansible_base.rbac.models import RoleDefinition
from test_app.models import Inventory, Organization


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
def global_inv_rd():
    return RoleDefinition.objects.create_from_permissions(
        permissions=['change_inventory', 'view_inventory'],
        name='global-change-inv',
        content_type=None,
    )


@pytest.fixture
def org_inv_rd():
    return RoleDefinition.objects.create_from_permissions(
        permissions=['change_organization', 'view_organization', 'change_inventory', 'view_inventory'],
        name='org-admin',
        content_type=permission_registry.content_type_model.objects.get_for_model(Organization),
    )


@pytest.fixture
def inv_rd():
    return RoleDefinition.objects.create_from_permissions(
        permissions=['change_inventory', 'view_inventory'],
        name='change-inv',
        content_type=permission_registry.content_type_model.objects.get_for_model(Inventory),
    )


@pytest.fixture
def org_member_rd():
    "Gives membership to all teams in an organization"
    return RoleDefinition.objects.create_from_permissions(
        permissions=[permission_registry.team_permission, f'view_{permission_registry.team_model._meta.model_name}'],
        name='org-level-team-member',
        content_type=permission_registry.content_type_model.objects.get_for_model(Organization),
        managed=True,
    )


@pytest.fixture
def member_rd():
    return RoleDefinition.objects.create_from_permissions(
        permissions=[permission_registry.team_permission, f'view_{permission_registry.team_model._meta.model_name}'],
        name='team-member',
        content_type=permission_registry.content_type_model.objects.get_for_model(permission_registry.team_model),
        managed=True,
    )
