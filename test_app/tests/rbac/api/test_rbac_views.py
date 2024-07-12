import pytest
from django.test.utils import override_settings
from rest_framework.reverse import reverse

from ansible_base.rbac.models import RoleDefinition


@pytest.mark.django_db
def test_get_role_definition(admin_api_client, inv_rd):
    url = reverse('roledefinition-detail', kwargs={'pk': inv_rd.pk})
    response = admin_api_client.get(url)
    assert response.status_code == 200
    assert set(response.data['permissions']) == set(['aap.change_inventory', 'aap.view_inventory'])


@pytest.mark.django_db
def test_create_role_definition(admin_api_client):
    """
    Test creation of a custom role definition.
    """
    url = reverse("roledefinition-list")
    data = dict(name='foo-role-def', description='bar', permissions=['aap.view_organization', 'aap.change_organization'], content_type='shared.organization')
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 201, response.data
    assert response.data['name'] == 'foo-role-def'


@pytest.mark.django_db
def test_create_global_role_definition(admin_api_client):
    url = reverse("roledefinition-list")
    data = dict(name='global_view_org', description='bar', permissions=['aap.view_organization'])
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 201, response.data
    assert response.data['name'] == 'global_view_org'


@pytest.mark.django_db
def test_delete_role_definition(admin_api_client, inv_rd):
    url = reverse('roledefinition-detail', kwargs={'pk': inv_rd.pk})
    response = admin_api_client.delete(url)
    assert response.status_code == 204, response.data
    assert not RoleDefinition.objects.filter(pk=inv_rd.pk).exists()


@pytest.mark.django_db
def test_get_user_assignment(system_user, admin_api_client, inv_rd, rando, inventory):
    assignment = inv_rd.give_permission(rando, inventory)
    url = reverse('roleuserassignment-detail', kwargs={'pk': assignment.pk})
    response = admin_api_client.get(url)
    assert response.data['content_type'] == 'aap.inventory'
    assert int(response.data['object_id']) == inventory.id
    assert response.data['role_definition'] == inv_rd.id
    assert response.data['created_by'] == system_user.id  # created by code, not by view

    summary_fields = response.data['summary_fields']
    assert 'content_object' in summary_fields
    assert summary_fields['content_object'] == {'id': inventory.id, 'name': inventory.name}
    # object_role is an internal objects, and is hidden to avoid API commitments
    assert 'object_role' not in summary_fields


@pytest.mark.django_db
def test_get_user_assignment_no_system_user(admin_api_client, inv_rd, rando, inventory):
    with override_settings(SYSTEM_USERNAME=None):
        assignment = inv_rd.give_permission(rando, inventory)
    url = reverse('roleuserassignment-detail', kwargs={'pk': assignment.pk})
    response = admin_api_client.get(url)
    assert response.data['created_by'] is None


@pytest.mark.django_db
def test_make_user_assignment(admin_api_client, inv_rd, rando, inventory):
    url = reverse('roleuserassignment-list')
    data = dict(role_definition=inv_rd.id, user=rando.id, object_id=inventory.id)
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 201, response.data
    assert response.data['user'] == rando.pk
    assert int(response.data['object_id']) == inventory.pk
    assert response.data['role_definition'] == inv_rd.pk

    assert rando.has_obj_perm(inventory, 'change')


@pytest.mark.django_db
def test_invalid_user_assignment(admin_api_client, inv_rd, inventory):
    url = reverse('roleuserassignment-list')
    data = dict(role_definition=inv_rd.id, user=12345, object_id=inventory.id)
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 400, response.data
    assert 'object does not exist' in str(response.data['user'])


@pytest.mark.django_db
def test_make_global_user_assignment(admin_api_client, rando, inventory):
    rd = RoleDefinition.objects.create_from_permissions(
        permissions=['change_inventory', 'view_inventory'],
        name='global-change-inv',
        content_type=None,
    )
    url = reverse('roleuserassignment-list')
    data = dict(role_definition=rd.id, user=rando.id, object_id=None)
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 201, response.data
    assert response.data['user'] == rando.pk
    assert response.data['object_id'] is None
    assert response.data['role_definition'] == rd.pk

    assert rando.has_obj_perm(inventory, 'change')


@pytest.mark.django_db
def test_remove_user_assignment(user_api_client, user, inv_rd, rando, inventory):
    assignment = inv_rd.give_permission(rando, inventory)
    url = reverse('roleuserassignment-detail', kwargs={'pk': assignment.pk})
    response = user_api_client.delete(url)
    assert response.status_code == 404, response.data

    inv_rd.give_permission(user, inventory)
    response = user_api_client.delete(url)
    assert response.status_code == 204, response.data

    assert not type(assignment).objects.filter(pk=assignment.pk).exists()


@pytest.mark.django_db
def test_filtering_related_assignments(user_api_client, user, rando, inventory, inv_rd):
    rando_assignment = inv_rd.give_permission(rando, inventory)
    url = reverse('roledefinition-user_assignments-list', kwargs={'pk': inv_rd.id})
    response = user_api_client.get(url)
    assert response.status_code == 200, response.data
    assert response.data['count'] == 0

    user_assignment = inv_rd.give_permission(user, inventory)
    response = user_api_client.get(url)
    assert response.status_code == 200, response.data
    # Make sure this does not return duplicate items
    assignment_ids = [item['id'] for item in response.data['results']]
    assert sorted(list(set(assignment_ids))) == sorted(assignment_ids)
    # Now assure we have the expected content
    assert set(assignment_ids) == {rando_assignment.id, user_assignment.id}


@pytest.mark.django_db
def test_remove_team_assignment(user_api_client, user, inv_rd, team, inventory):
    assignment = inv_rd.give_permission(team, inventory)
    url = reverse('roleteamassignment-detail', kwargs={'pk': assignment.pk})
    response = user_api_client.delete(url)
    assert response.status_code == 404, response.data

    inv_rd.give_permission(user, inventory)
    response = user_api_client.delete(url)
    assert response.status_code == 204, response.data

    assert not type(assignment).objects.filter(pk=assignment.pk).exists()


@pytest.mark.django_db
def test_team_assignment_validation_error(admin_api_client, team, organization, org_member_rd):
    url = reverse('roleteamassignment-list')
    response = admin_api_client.post(url, data={'team': team.id, 'object_id': organization.id, 'role_definition': org_member_rd.id})
    assert response.status_code == 400, response.data
    assert 'Assigning organization member permission to teams is not allowed' in str(response.data)


@pytest.mark.django_db
def test_filter_queryset(user_api_client, user, inventory, inv_rd):
    "This tests that filter_queryset usage in test_app is effective"
    url = reverse("inventory-list")
    response = user_api_client.get(url, format="json")
    assert response.data['count'] == 0

    inv_rd.give_permission(user, inventory)
    response = user_api_client.get(url, format="json")
    assert response.data['count'] == 1


@pytest.mark.django_db
def test_role_metadata_view(user_api_client):
    response = user_api_client.get(reverse('role-metadata'))
    assert response.status_code == 200
    allowed_permissions = response.data['allowed_permissions']
    assert 'aap.change_collectionimport' in allowed_permissions['aap.namespace']


@override_settings(ANSIBLE_BASE_ALLOW_CUSTOM_ROLES=False)
def test_role_definitions_post_disabled_by_settings(admin_api_client):
    url = reverse('roledefinition-list')
    response = admin_api_client.options(url)
    assert response.status_code == 200, response.data
    print(response.data)
    assert 'POST' not in response.data.get('actions', {})
