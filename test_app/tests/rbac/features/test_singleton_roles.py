import pytest

from rest_framework.exceptions import ValidationError

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac.models import RoleDefinition
from ansible_base.rbac import permission_registry

from test_app.models import Inventory, User, Organization


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
def test_singleton_role_via_team(rando, organization, team, inventory, global_inv_rd, org_team_member_rd):
    assignment = org_team_member_rd.give_permission(rando, organization)
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
    url = get_relative_url(f"{model}-list")
    response = admin_api_client.post(url, data={"name": "new"}, format="json")
    assert response.status_code == 201, response.data


@pytest.mark.django_db
@pytest.mark.parametrize("model", ["organization", "instancegroup"])
def test_add_root_resource_global_role(organization, user_api_client, user, model):
    url = get_relative_url(f"{model}-list")
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
    response = user_api_client.get(get_relative_url('roleuserassignment-list'), format="json")
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
    response = user_api_client.get(get_relative_url('roleuserassignment-list'), format="json")
    assert response.status_code == 200, response.data
    returned_assignments = set(entry['id'] for entry in response.data['results'])
    expected_assignments = {global_assignment.id, assignment1.id, assignment2.id}
    assert expected_assignments == returned_assignments
    assert len(response.data['results']) == 3


@pytest.mark.django_db
def test_invalid_global_role_assignment(rando, inv_rd, inventory):
    with pytest.raises(ValidationError) as exc:
        inv_rd.give_global_permission(rando)
    assert 'Role definition content type must be null to assign globally' in str(exc)


@pytest.mark.django_db
def test_remove_invalid_user_singleton_assignment(rando, inventory, global_inv_rd):
    # normally give the global role to user
    global_inv_rd.give_global_permission(rando)

    # this will make the assignment from earlier invalid
    global_inv_rd.content_type = permission_registry.content_type_model.objects.get_for_model(Organization)

    # should still be able to remove the permission, even if the configuration is invalid
    global_inv_rd.remove_global_permission(rando)

