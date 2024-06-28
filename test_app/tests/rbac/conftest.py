import pytest
from django.contrib.auth import get_user_model

from ansible_base.rbac import permission_registry
from ansible_base.rbac.models import RoleDefinition
from test_app.models import Inventory, Organization


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
        permissions=['view_organization', 'change_inventory', 'view_inventory'],
        name='org-inv-rd',
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
def view_inv_rd():
    return RoleDefinition.objects.create_from_permissions(
        name='view-inv',
        permissions=['view_inventory'],
        content_type=permission_registry.content_type_model.objects.get_for_model(Inventory),
    )


@pytest.fixture
def org_team_member_rd():
    """Gives membership to all teams in an organization"""
    return RoleDefinition.objects.create_from_permissions(
        permissions=[permission_registry.team_permission, f'view_{permission_registry.team_model._meta.model_name}'],
        name='org-level-team-member',
        content_type=permission_registry.content_type_model.objects.get_for_model(Organization),
        managed=True,
    )
