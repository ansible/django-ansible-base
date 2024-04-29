import pytest
from django.urls import reverse

from ansible_base.rbac import permission_registry
from ansible_base.rbac.models import RoleDefinition
from ansible_base.rbac.policies import can_change_user, visible_users
from test_app.models import Namespace, Organization, User


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


@pytest.mark.django_db
def test_user_change_permission(user_api_client, user, organization, org_member_rd, org_admin_rd):
    other_user = User.objects.create(username='another-user')
    url = reverse('user-detail', kwargs={'pk': other_user.pk})

    # Give user ability to view other user, and OPTIONS should indicate PUT not possible
    for u in (user, other_user):
        org_member_rd.give_permission(u, organization)
    assert visible_users(user).filter(pk=other_user.pk)  # sanity
    assert not can_change_user(user, other_user)  # sanity
    r = user_api_client.options(url)
    assert r.status_code == 200, r.data
    assert 'actions' not in r.data  # no PATCH or PUT

    # Org admins can modify users
    org_admin_rd.give_permission(user, organization)
    r = user_api_client.options(url)
    assert can_change_user(user, other_user)  # sanity
    assert r.status_code == 200
    assert 'actions' in r.data
    assert 'PUT' in r.data['actions']


@pytest.mark.django_db
def test_user_creator_options(user, user_api_client, organization, org_admin_rd):
    url = reverse('user-list')

    # Normal users can not create new users
    r = user_api_client.options(url)
    assert r.status_code == 200, r.data
    assert 'actions' not in r.data

    # Organization admins can create new users
    org_admin_rd.give_permission(user, organization)
    r = user_api_client.options(url)
    assert r.status_code == 200
    assert 'POST' in r.data['actions']


@pytest.mark.django_db
def test_no_parent_objects(admin_api_client):
    url = reverse('collectionimport-list')

    assert Namespace.objects.count() == 0  # sanity

    r = admin_api_client.options(url)
    assert r.status_code == 200, r.data
    assert 'actions' in r.data
    assert 'POST' in r.data['actions']
