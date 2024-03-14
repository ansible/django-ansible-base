import pytest
from rest_framework.reverse import reverse

from ansible_base.rbac import permission_registry
from ansible_base.rbac.models import RoleDefinition
from test_app.models import ImmutableTask


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
def test_get_user_assignment(admin_api_client, inv_rd, rando, inventory):
    assignment = inv_rd.give_permission(rando, inventory)
    url = reverse('roleuserassignment-detail', kwargs={'pk': assignment.pk})
    response = admin_api_client.get(url)
    assert response.data['content_type'] == 'aap.inventory'
    assert int(response.data['object_id']) == inventory.id
    assert response.data['role_definition'] == inv_rd.id
    assert not response.data['created_by']  # created by code, not by view

    summary_fields = response.data['summary_fields']
    assert 'content_object' in summary_fields
    assert summary_fields['content_object'] == {'id': inventory.id, 'name': inventory.name}


@pytest.mark.django_db
def test_make_user_assignment(admin_api_client, inv_rd, rando, inventory):
    url = reverse('roleuserassignment-list')
    data = dict(role_definition=inv_rd.id, user=rando.id, object_id=inventory.id)
    response = admin_api_client.post(url, data=data, format="json")
    assert response.status_code == 201, response.data
    assert response.data['created_by']


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
    assert response.data['created_by']


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
def test_remove_user_assignment_immutable(user_api_client, user, rando):
    task = ImmutableTask.objects.create()
    rd = RoleDefinition.objects.create_from_permissions(
        permissions=['view_immutabletask', 'delete_immutabletask', 'cancel_immutabletask'],
        name='Task Admin',
        content_type=permission_registry.content_type_model.objects.get_for_model(ImmutableTask),
    )
    assignment = rd.give_permission(rando, task)

    url = reverse('roleuserassignment-detail', kwargs={'pk': assignment.pk})
    response = user_api_client.delete(url)
    assert response.status_code == 404, response.data

    rd_view = RoleDefinition.objects.create_from_permissions(
        permissions=['view_immutabletask'],
        name='Task Viewer',
        content_type=permission_registry.content_type_model.objects.get_for_model(ImmutableTask),
    )
    rd_view.give_permission(user, task)
    response = user_api_client.delete(url)
    assert response.status_code == 403, response.data

    rd.give_permission(user, task)
    response = user_api_client.delete(url)
    assert response.status_code == 204, response.data

    assert not type(assignment).objects.filter(pk=assignment.pk).exists()


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
def test_remove_user_assignment_with_global_role(user_api_client, user, inv_rd, global_inv_rd, rando, inventory):
    assignment = inv_rd.give_permission(rando, inventory)
    url = reverse('roleuserassignment-detail', kwargs={'pk': assignment.pk})
    response = user_api_client.delete(url)
    assert response.status_code == 404, response.data

    global_inv_rd.give_global_permission(user)
    response = user_api_client.delete(url)
    assert response.status_code == 204, response.data

    assert not type(assignment).objects.filter(pk=assignment.pk).exists()


@pytest.mark.django_db
def test_remove_global_role_assignment(user_api_client, user, inv_rd, global_inv_rd, rando, inventory):
    assignment = global_inv_rd.give_global_permission(rando)
    url = reverse('roleuserassignment-detail', kwargs={'pk': assignment.pk})
    response = user_api_client.delete(url)
    assert response.status_code == 404, response.data

    global_inv_rd.give_global_permission(user)
    response = user_api_client.delete(url)
    assert response.status_code == 204, response.data

    assert not type(assignment).objects.filter(pk=assignment.pk).exists()
