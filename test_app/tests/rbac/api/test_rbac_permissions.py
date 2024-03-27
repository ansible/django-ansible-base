#  Copyright 2024 Red Hat, Inc.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import pytest
from django.contrib.contenttypes.models import ContentType
from django.urls import reverse

from ansible_base.rbac import permission_registry
from ansible_base.rbac.models import RoleDefinition, RoleUserAssignment
from test_app.models import Cow, Inventory, Organization


@pytest.fixture
def view_inv_rd():
    view_inv, _ = RoleDefinition.objects.get_or_create(
        name='view-inv', permissions=['view_inventory', 'view_organization'], defaults={'content_type': ContentType.objects.get_for_model(Organization)}
    )
    return view_inv


@pytest.fixture
def org_inv_add():
    return RoleDefinition.objects.create_from_permissions(
        permissions=['view_organization', 'add_inventory'],
        name='org-inv-add',
        content_type=permission_registry.content_type_model.objects.get_for_model(Organization),
    )


@pytest.fixture
def unauthenticated_url_check(unauthenticated_api_client):
    def _rf(url):
        for action in ('get', 'delete'):
            response = getattr(unauthenticated_api_client, action)(url)
            assert response.status_code == 401

        for action in ('patch', 'put'):
            response = getattr(unauthenticated_api_client, action)(url, data={})
            assert response.status_code == 401

    return _rf


@pytest.mark.django_db
def test_unauthenticated_resource_requests(unauthenticated_url_check, inventory, organization):
    cow = Cow.objects.create(organization=organization)
    urls = [
        reverse('inventory-list'),
        reverse('inventory-detail', kwargs={'pk': inventory.id}),
        reverse('inventory-detail', kwargs={'pk': 9000}),
        reverse('cow-cowsay', kwargs={'pk': cow.id}),  # test action endpoint
    ]
    for url in urls:
        unauthenticated_url_check(url)


@pytest.mark.django_db
def test_unauthenticated_role_management_requests(unauthenticated_url_check, inventory, inv_rd, user):
    assignment = inv_rd.give_permission(user, inventory)
    urls = [
        reverse('roledefinition-list'),
        reverse('roledefinition-detail', kwargs={'pk': inv_rd.id}),
        reverse('roledefinition-detail', kwargs={'pk': 9000}),
        reverse('roleuserassignment-list'),
        reverse('roleuserassignment-detail', kwargs={'pk': assignment.id}),
        reverse('roleuserassignment-detail', kwargs={'pk': 9000}),
    ]
    for url in urls:
        unauthenticated_url_check(url)


@pytest.mark.django_db
def test_gain_organization_inventory_view(user_api_client, user, org_inv_rd):
    org = Organization.objects.create(name='foo')
    Inventory.objects.create(name='bar', organization=org)

    r = user_api_client.get(reverse('organization-list'))
    assert r.status_code == 200, r.data
    assert r.data['results'] == []

    r = user_api_client.get(reverse('inventory-list'))
    assert r.status_code == 200, r.data
    assert r.data['results'] == []

    org_inv_rd.give_permission(user, org)

    r = user_api_client.get(reverse('organization-list'))
    assert r.status_code == 200, r.data
    assert len(r.data['results']) == 1

    r = user_api_client.get(reverse('inventory-list'))
    assert r.status_code == 200, r.data
    assert len(r.data['results']) == 1


@pytest.mark.django_db
def test_change_permission(user_api_client, user, org_inv_rd, view_inv_rd, inventory):
    view_inv_rd.give_permission(user, inventory.organization)

    inv_detail = reverse('inventory-detail', kwargs={'pk': inventory.id})
    r = user_api_client.patch(inv_detail, {})
    assert r.status_code == 403, r.data

    org_inv_rd.give_permission(user, inventory.organization)

    r = user_api_client.patch(inv_detail, {})
    assert r.status_code == 200, r.data


@pytest.mark.django_db
def test_revoke_a_permission(admin_api_client, user, org_inv_rd, view_inv_rd, organization):
    assignment = view_inv_rd.give_permission(user, organization)

    assignment_detail = reverse('roleuserassignment-detail', kwargs={'pk': assignment.id})
    r = admin_api_client.delete(assignment_detail, {})
    assert r.status_code == 204, r.data

    assert not RoleUserAssignment.objects.filter(id=assignment.id).exists()


@pytest.mark.django_db
def test_add_permission(user_api_client, user, view_inv_rd, org_inv_add, organization):
    view_inv_rd.give_permission(user, organization)
    r = user_api_client.post(reverse('inventory-list'), {'name': 'test', 'organization': organization.id})
    assert r.status_code == 403, r.data

    org_inv_add.give_permission(user, organization)
    r = user_api_client.post(reverse('inventory-list'), {'name': 'test', 'organization': organization.id})
    assert r.status_code == 201, r.data

    inventory = Inventory.objects.get(id=r.data['id'])
    assert user.has_obj_perm(inventory, 'change')


@pytest.mark.django_db
def test_change_organization(user_api_client, user, inv_rd, org_inv_add, inventory):
    org2 = Organization.objects.create(name='another-org')
    url = reverse('inventory-detail', kwargs={'pk': inventory.pk})
    inv_rd.give_permission(user, inventory)

    # Inventory object admin can change superficial things like the name
    r = user_api_client.patch(url, {'name': 'new inventory name', 'organization': inventory.organization_id})
    assert r.status_code == 200, r.data

    # Inventory object admin can not move to organization they do not own
    r = user_api_client.patch(url, {'organization': org2.pk})
    assert r.status_code == 403, r.data

    org_inv_add.give_permission(user, org2)
    r = user_api_client.patch(url, {'organization': org2.pk})
    assert r.status_code == 200, r.data


@pytest.mark.django_db
def test_remove_organization(user_api_client, user, inv_rd, inventory):
    """You should not be able to null out an organization field unless you have global role"""
    url = reverse('inventory-detail', kwargs={'pk': inventory.pk})
    inv_rd.give_permission(user, inventory)

    # Inventory object admin can not null its organization
    r = user_api_client.patch(url, {'organization': None}, format='json')
    assert r.status_code == 403, r.data

    global_add_inv_rd = RoleDefinition.objects.create_from_permissions(name='system-inventory-add', permissions=['add_inventory'], content_type=None)

    global_add_inv_rd.give_global_permission(user)
    r = user_api_client.patch(url, {'organization': None}, format='json')
    assert r.status_code == 200, r.data


@pytest.mark.django_db
def test_custom_action(user_api_client, user, organization):
    rd = RoleDefinition.objects.create_from_permissions(
        name='change-cow', permissions=['change_cow', 'view_cow', 'delete_cow'], content_type=ContentType.objects.get_for_model(Cow)
    )
    cow = Cow.objects.create(organization=organization)
    rd.give_permission(user, cow)

    cow_url = reverse('cow-detail', kwargs={'pk': cow.id})
    r = user_api_client.patch(cow_url, {})
    assert r.status_code == 200

    cow_say_url = reverse('cow-cowsay', kwargs={'pk': cow.id})
    r = user_api_client.post(cow_say_url, {})
    assert r.status_code == 403

    say_rd = RoleDefinition.objects.create_from_permissions(
        name='say-cow', permissions=['view_cow', 'say_cow'], content_type=ContentType.objects.get_for_model(Cow)
    )
    say_rd.give_permission(user, cow)

    cow_say_url = reverse('cow-cowsay', kwargs={'pk': cow.id})
    r = user_api_client.post(cow_say_url, {})
    assert r.status_code == 200


@pytest.mark.django_db
def test_user_list_admin(admin_api_client, rando):
    url = reverse('user-list')
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert response.data['count'] >= 2

    response = admin_api_client.post(url, data={'username': 'foo', 'password': 'bar'})
    assert response.status_code == 201


@pytest.mark.django_db
def test_user_list_non_admin(user_api_client, rando):
    url = reverse('user-list')
    response = user_api_client.get(url)
    assert response.status_code == 200

    response = user_api_client.post(url, data={'username': 'foo', 'password': 'bar'})
    assert response.status_code == 403


@pytest.mark.django_db
def test_user_detail_works_superuser(admin_api_client, rando):
    url = reverse('user-detail', kwargs={'pk': rando.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200

    user_response = admin_api_client.patch(url, data={})
    assert user_response.status_code == 200
