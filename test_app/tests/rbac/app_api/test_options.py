import pytest
from django.urls import reverse

from ansible_base.rbac import permission_registry
from ansible_base.rbac.models import RoleDefinition
from test_app.models import Organization


@pytest.fixture
def org_inv_admin():
    return RoleDefinition.objects.create_from_permissions(
        name='org-inv-admin',
        permissions=['add_inventory', 'view_organization'],
        content_type=permission_registry.content_type_model.objects.get_for_model(Organization),
    )


@pytest.mark.django_db
def test_inventory_creator_options(user, user_api_client, organization, org_inv_admin):
    url = reverse('inventory-list')

    # User has no ability to add an inventory, OPTIONS should not show POST
    r = user_api_client.options(url)
    assert r.status_code == 200, r.data
    assert 'actions' not in r.data  # no POST results in no actions

    org_inv_admin.give_permission(user, organization)
    r = user_api_client.options(url)
    assert r.status_code == 200
    assert 'POST' in r.data['actions']


@pytest.mark.django_db
def test_organization_creator_options(user, user_api_client, admin_api_client):
    url = reverse('organization-list')

    r = user_api_client.options(url)
    assert r.status_code == 200, r.data
    assert 'actions' not in r.data

    r = admin_api_client.options(url)
    assert r.status_code == 200
    assert 'POST' in r.data['actions']


@pytest.mark.django_db
def test_object_change_permission(user, user_api_client, inventory, inv_rd, view_inv_rd):
    url = reverse('inventory-detail', kwargs={'pk': inventory.pk})
    view_inv_rd.give_permission(user, inventory)

    r = user_api_client.options(url)
    assert r.status_code == 200, r.data
    assert 'actions' not in r.data  # no PATCH or PUT

    inv_rd.give_permission(user, inventory)
    r = user_api_client.options(url)
    assert r.status_code == 200
    assert 'actions' in r.data
    assert 'PUT' in r.data['actions']
