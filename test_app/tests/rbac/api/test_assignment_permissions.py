import pytest

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac import permission_registry
from ansible_base.rbac.models import RoleDefinition
from test_app.models import ImmutableTask


@pytest.fixture
def task_admin_rd():
    return RoleDefinition.objects.create_from_permissions(
        permissions=['view_immutabletask', 'delete_immutabletask', 'cancel_immutabletask'],
        name='Task Admin',
        content_type=permission_registry.content_type_model.objects.get_for_model(ImmutableTask),
    )


@pytest.fixture
def task_view_rd():
    return RoleDefinition.objects.create_from_permissions(
        permissions=['view_immutabletask'],
        name='Task View',
        content_type=permission_registry.content_type_model.objects.get_for_model(ImmutableTask),
    )


@pytest.mark.django_db
def test_create_user_assignment_immutable(user_api_client, user, rando, task_admin_rd, task_view_rd, org_admin_rd, organization):
    task = ImmutableTask.objects.create()
    org_admin_rd.give_permission(user, organization)  # setup so that user can see rando
    url = get_relative_url('roleuserassignment-list')
    request_data = {"user": rando.pk, "role_definition": task_admin_rd.pk, "object_id": task.pk}

    response = user_api_client.post(url, data=request_data)
    assert response.status_code == 400, response.data
    assert 'object does not exist' in response.data['object_id'][0]

    task_view_rd.give_permission(user, task)
    response = user_api_client.post(url, data=request_data)
    assert response.status_code == 403, response.data
    # Test custom error message
    assert 'You do not have cancel_immutabletask permission' in str(response.data)

    task_admin_rd.give_permission(user, task)
    response = user_api_client.post(url, data=request_data)
    assert response.status_code == 201, response.data


@pytest.mark.django_db
def test_remove_user_assignment_immutable(user_api_client, user, rando, task_admin_rd, task_view_rd):
    task = ImmutableTask.objects.create()
    assignment = task_admin_rd.give_permission(rando, task)
    url = get_relative_url('roleuserassignment-detail', kwargs={'pk': assignment.pk})

    response = user_api_client.delete(url)
    assert response.status_code == 404, response.data

    task_view_rd.give_permission(user, task)
    response = user_api_client.delete(url)
    assert response.status_code == 403, response.data
    # Test custom error message
    assert 'You do not have cancel_immutabletask permission' in str(response.data)

    task_admin_rd.give_permission(user, task)
    response = user_api_client.delete(url)
    assert response.status_code == 204, response.data

    assert not type(assignment).objects.filter(pk=assignment.pk).exists()


@pytest.mark.django_db
def test_remove_user_assignment_with_global_role(user_api_client, user, inv_rd, global_inv_rd, rando, inventory):
    assignment = inv_rd.give_permission(rando, inventory)
    url = get_relative_url('roleuserassignment-detail', kwargs={'pk': assignment.pk})
    response = user_api_client.delete(url)
    assert response.status_code == 404, response.data

    global_inv_rd.give_global_permission(user)
    response = user_api_client.delete(url)
    assert response.status_code == 204, response.data

    assert not type(assignment).objects.filter(pk=assignment.pk).exists()


@pytest.mark.django_db
def test_remove_global_role_assignment(user_api_client, admin_api_client, user, global_inv_rd, rando):
    assignment = global_inv_rd.give_global_permission(rando)
    url = get_relative_url('roleuserassignment-detail', kwargs={'pk': assignment.pk})
    response = user_api_client.delete(url)
    assert response.status_code == 404, response.data

    # Having the role itself does not give permission to remove assignments, but this user can view
    global_inv_rd.give_global_permission(user)
    response = user_api_client.delete(url)
    assert response.status_code == 403, response.data

    # Only superuser can remove global assignments
    response = admin_api_client.delete(url)
    assert response.status_code == 204, response.data

    assert not type(assignment).objects.filter(pk=assignment.pk).exists()


@pytest.mark.django_db
def test_remove_global_assignment_yourself(user_api_client, global_inv_rd, user, inventory):
    assert not user.has_obj_perm(inventory, 'change')

    assignment = global_inv_rd.give_global_permission(user)
    assert user.has_obj_perm(inventory, 'change')

    url = get_relative_url('roleuserassignment-detail', kwargs={'pk': assignment.pk})
    response = user_api_client.delete(url)
    # Manually delete cache, because view operates on a User instance loaded anew from DB
    delattr(user, '_singleton_permissions')
    assert response.status_code == 204, response.data
    assert not user.has_obj_perm(inventory, 'change')


@pytest.mark.django_db
def test_remove_object_assignment_yourself(user_api_client, user, inventory):
    assert not user.has_obj_perm(inventory, 'view')

    rd = RoleDefinition.objects.create_from_permissions(
        name='inventory viewer role', permissions=['view_inventory'], content_type=permission_registry.content_type_model.objects.get_for_model(inventory)
    )
    assignment = rd.give_permission(user, inventory)
    assert user.has_obj_perm(inventory, 'view')

    url = get_relative_url('roleuserassignment-detail', kwargs={'pk': assignment.pk})
    response = user_api_client.delete(url)
    assert response.status_code == 204, response.data
    assert not user.has_obj_perm(inventory, 'change')
