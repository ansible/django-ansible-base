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
from rest_framework.reverse import reverse

from ansible_base.rbac.models import RoleDefinition
from test_app.models import Inventory, User


@pytest.mark.django_db
def test_user_singleton_role(rando, inventory, global_inv_rd):
    global_inv_rd.give_global_permission(rando)
    assert rando.has_obj_perm(inventory, 'change_inventory')
    assert rando.singleton_permissions() == {'change_inventory', 'view_inventory'}
    assert list(Inventory.access_qs(rando, 'change')) == [inventory]

    global_inv_rd.remove_global_permission(rando)
    assert not rando.has_obj_perm(inventory, 'change_inventory')
    assert rando.singleton_permissions() == set()
    assert list(Inventory.access_qs(rando, 'change')) == []


@pytest.mark.django_db
def test_singleton_role_via_team(rando, organization, team, inventory, global_inv_rd, org_member_rd):
    assignment = org_member_rd.give_permission(rando, organization)
    assert list(assignment.object_role.provides_teams.all()) == [team]

    global_inv_rd.give_global_permission(team)
    assert rando.has_obj_perm(inventory, 'change_inventory')
    assert rando.singleton_permissions() == {'change_inventory', 'view_inventory'}
    assert list(Inventory.access_qs(rando, 'change')) == [inventory]

    global_inv_rd.remove_global_permission(team)
    assert not rando.has_obj_perm(inventory, 'change_inventory')
    assert rando.singleton_permissions() == set()
    assert list(Inventory.access_qs(rando, 'change')) == []


@pytest.mark.django_db
@pytest.mark.parametrize("model", ["organization", "instancegroup"])
def test_add_root_resource_admin(organization, admin_api_client, model):
    url = reverse(f"{model}-list")
    response = admin_api_client.post(url, data={"name": "new"}, format="json")
    assert response.status_code == 201, response.data


@pytest.mark.django_db
@pytest.mark.parametrize("model", ["organization", "instancegroup"])
def test_add_root_resource_global_role(organization, user_api_client, user, model):
    url = reverse(f"{model}-list")
    response = user_api_client.post(url, data={"name": "new"}, format="json")
    assert response.status_code == 403, response.data

    RoleDefinition.objects.create_from_permissions(
        name='system-creator-permission-for-model', permissions=[f'add_{model}'], content_type=None
    ).give_global_permission(user)

    assert RoleDefinition.objects.count() >= 1

    response = user_api_client.post(url, data={"name": "new"}, format="json")
    assert response.status_code == 201, response.data


@pytest.mark.django_db
def test_view_assignments_with_global_role(inventory, user, user_api_client, inv_rd):
    global_assignment = RoleDefinition.objects.create_from_permissions(
        name='system-view-inventory', permissions=['view_inventory'], content_type=None
    ).give_global_permission(user)

    # create a new, different, user and assign them permission to an inventory
    rando = User.objects.create(username='rando')
    assignment = inv_rd.give_permission(rando, inventory)

    # you should be able to view that assignment if you are a global inventory viewer
    response = user_api_client.get(reverse('roleuserassignment-list'), format="json")
    assert response.status_code == 200, response.data
    returned_assignments = set(entry['id'] for entry in response.data['results'])
    expected_assignments = {global_assignment.id, assignment.id}
    assert expected_assignments == returned_assignments
    assert len(response.data['results']) == 2


@pytest.mark.django_db
def test_view_assignments_with_global_and_org_role(inventory, organization, user, user_api_client, org_inv_rd):
    "This mainly exists as regression coverage for duplicate entries in the returned assignments"
    global_assignment = RoleDefinition.objects.create_from_permissions(
        name='system-view-inventory', permissions=['view_inventory'], content_type=None
    ).give_global_permission(user)

    # give a different user AND that user an organization permission - duplicate hits likely
    rando = User.objects.create(username='rando')
    assignment1 = org_inv_rd.give_permission(rando, organization)
    assignment2 = org_inv_rd.give_permission(user, organization)

    # you should be able to view that assignment if you are a global inventory viewer
    response = user_api_client.get(reverse('roleuserassignment-list'), format="json")
    assert response.status_code == 200, response.data
    returned_assignments = set(entry['id'] for entry in response.data['results'])
    expected_assignments = {global_assignment.id, assignment1.id, assignment2.id}
    assert expected_assignments == returned_assignments
    assert len(response.data['results']) == 3
