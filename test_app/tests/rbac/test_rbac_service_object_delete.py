"""
Unit tests for ServiceObjectDeleteViewSet - AAP-51985 Gateway cleanup endpoint

Tests the new service API endpoint that handles bulk deletion of role assignments
when Controller resources are deleted. This endpoint uses the standard create()
method to bypass service token authentication restrictions.
"""

import pytest

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac.models import RoleTeamAssignment, RoleUserAssignment
from ansible_base.rbac.permission_registry import permission_registry


@pytest.fixture
def inventory_with_assignments(inventory, rando, team, inv_rd):
    """Inventory with both user and team role assignments"""
    user_assignment = inv_rd.give_permission(rando, inventory)
    team_assignment = inv_rd.give_permission(team, inventory)
    return inventory, user_assignment, team_assignment


@pytest.mark.django_db
def test_bulk_delete_user_and_team_assignments(admin_api_client, inventory_with_assignments):
    """
    Test that the endpoint deletes both user and team assignments in one call.
    This is the key efficiency improvement over separate API calls.
    """
    inventory, user_assignment, team_assignment = inventory_with_assignments

    # Get content type info for the request
    ct = permission_registry.content_type_model.objects.get_for_model(inventory)

    url = get_relative_url('serviceobjectdelete-list')
    data = {'resource_type': f'{ct.app_label}.{ct.model}', 'resource_pk': str(inventory.pk)}

    # Verify assignments exist before deletion
    user_assignments_before = RoleUserAssignment.objects.filter(object_role__content_type=ct, object_role__object_id=inventory.pk).count()
    team_assignments_before = RoleTeamAssignment.objects.filter(object_role__content_type=ct, object_role__object_id=inventory.pk).count()

    assert user_assignments_before > 0
    assert team_assignments_before > 0

    # Call the service endpoint
    response = admin_api_client.post(url, data, format='json')

    # Verify successful response
    assert response.status_code == 200
    response_data = response.json()

    # Verify response format matches specification
    assert 'message' in response_data
    assert 'deleted_count' in response_data
    assert response_data['deleted_count'] > 0

    # Verify breakdown is provided
    assert 'breakdown' in response_data
    breakdown = response_data['breakdown']
    assert 'user_assignments_deleted' in breakdown
    assert 'team_assignments_deleted' in breakdown

    # Verify actual cleanup occurred
    user_assignments_after = RoleUserAssignment.objects.filter(object_role__content_type=ct, object_role__object_id=inventory.pk).count()
    team_assignments_after = RoleTeamAssignment.objects.filter(object_role__content_type=ct, object_role__object_id=inventory.pk).count()

    assert user_assignments_after == 0
    assert team_assignments_after == 0


@pytest.mark.django_db
def test_delete_nonexistent_resource_assignments(admin_api_client):
    """
    Test cleanup request for resource with no assignments returns appropriate response.
    This tests the performance optimization path.
    """
    # Use a resource type and ID that has no assignments
    url = get_relative_url('serviceobjectdelete-list')
    data = {'resource_type': 'test_app.inventory', 'resource_pk': '99999'}  # Non-existent ID

    response = admin_api_client.post(url, data, format='json')

    # Should still succeed but with 0 deletions
    assert response.status_code == 200
    response_data = response.json()

    assert response_data['deleted_count'] == 0
    assert 'Deleted 0 role assignments' in response_data['message']


@pytest.mark.django_db
def test_invalid_resource_type_format(admin_api_client):
    """Test handling of malformed resource_type parameter"""
    url = get_relative_url('serviceobjectdelete-list')
    data = {'resource_type': 'invalid-format', 'resource_pk': '123'}  # Missing app_label.model format

    response = admin_api_client.post(url, data, format='json')
    assert response.status_code == 400

    # Test missing resource_type
    data = {'resource_pk': '123'}
    response = admin_api_client.post(url, data, format='json')
    assert response.status_code == 400


@pytest.mark.django_db
def test_invalid_resource_pk_format(admin_api_client):
    """Test handling of invalid resource_pk parameter"""
    url = get_relative_url('serviceobjectdelete-list')
    data = {'resource_type': 'test_app.inventory', 'resource_pk': 'not-a-number'}  # Invalid for integer PK

    # Service doesn't validate PK format - it just returns 0 deletions for non-existent objects
    response = admin_api_client.post(url, data, format='json')
    assert response.status_code == 200
    assert response.json()['deleted_count'] == 0

    # Test missing resource_pk
    data = {'resource_type': 'test_app.inventory'}
    response = admin_api_client.post(url, data, format='json')
    assert response.status_code == 400


@pytest.mark.django_db
def test_unknown_content_type(admin_api_client):
    """Test handling of non-existent content type"""
    url = get_relative_url('serviceobjectdelete-list')
    data = {'resource_type': 'nonexistent.model', 'resource_pk': '123'}

    response = admin_api_client.post(url, data, format='json')
    assert response.status_code == 400


@pytest.mark.django_db
def test_only_user_assignments_deleted(admin_api_client, inventory, rando, inv_rd):
    """Test cleanup when only user assignments exist (no team assignments)"""
    # Create only user assignment
    inv_rd.give_permission(rando, inventory)

    ct = permission_registry.content_type_model.objects.get_for_model(inventory)
    url = get_relative_url('serviceobjectdelete-list')
    data = {'resource_type': f'{ct.app_label}.{ct.model}', 'resource_pk': str(inventory.pk)}

    response = admin_api_client.post(url, data, format='json')
    assert response.status_code == 200

    response_data = response.json()
    breakdown = response_data['breakdown']
    assert breakdown['user_assignments_deleted'] > 0
    assert breakdown['team_assignments_deleted'] == 0


@pytest.mark.django_db
def test_only_team_assignments_deleted(admin_api_client, inventory, team, inv_rd):
    """Test cleanup when only team assignments exist (no user assignments)"""
    # Create only team assignment
    inv_rd.give_permission(team, inventory)

    ct = permission_registry.content_type_model.objects.get_for_model(inventory)
    url = get_relative_url('serviceobjectdelete-list')
    data = {'resource_type': f'{ct.app_label}.{ct.model}', 'resource_pk': str(inventory.pk)}

    response = admin_api_client.post(url, data, format='json')
    assert response.status_code == 200

    response_data = response.json()
    breakdown = response_data['breakdown']
    assert breakdown['user_assignments_deleted'] == 0
    assert breakdown['team_assignments_deleted'] > 0


@pytest.mark.django_db
def test_organization_resource_cleanup(admin_api_client, organization, rando, org_admin_rd):
    """
    Test cleanup works for different resource types (not just inventories).
    This verifies the generic nature of the endpoint.
    """
    # Create organization-level assignment
    org_admin_rd.give_permission(rando, organization)

    ct = permission_registry.content_type_model.objects.get_for_model(organization)
    url = get_relative_url('serviceobjectdelete-list')
    data = {'resource_type': f'{ct.app_label}.{ct.model}', 'resource_pk': str(organization.pk)}

    response = admin_api_client.post(url, data, format='json')
    assert response.status_code == 200

    response_data = response.json()
    assert response_data['deleted_count'] > 0

    # Verify assignment was deleted
    remaining_assignments = RoleUserAssignment.objects.filter(object_role__content_type=ct, object_role__object_id=organization.pk).count()
    assert remaining_assignments == 0


@pytest.mark.django_db
def test_response_message_formatting(admin_api_client, inventory_with_assignments):
    """Test that response messages are properly formatted and informative"""
    inventory, user_assignment, team_assignment = inventory_with_assignments

    ct = permission_registry.content_type_model.objects.get_for_model(inventory)
    url = get_relative_url('serviceobjectdelete-list')
    data = {'resource_type': f'{ct.app_label}.{ct.model}', 'resource_pk': str(inventory.pk)}

    response = admin_api_client.post(url, data, format='json')
    assert response.status_code == 200

    response_data = response.json()
    message = response_data['message']

    # Message should include resource type, ID, and count
    assert f'{ct.app_label}.{ct.model}' in message
    assert str(inventory.pk) in message
    assert str(response_data['deleted_count']) in message

    # Response should be JSON serializable (no datetime/model objects)
    import json

    json.dumps(response_data)  # Should not raise exception
