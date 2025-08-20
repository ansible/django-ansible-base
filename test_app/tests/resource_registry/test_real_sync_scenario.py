"""
Tests for real end-to-end UUID synchronization scenarios without mocks.

This module tests the UUID serialization fix by using real service-index endpoints
instead of heavily mocking the synchronization process. It reproduces the error
scenario that occurred when syncing RemoteObject assignments with UUID primary keys.

Bug: TypeError: Object of type UUID is not JSON serializable
Fix: Convert UUID objects to strings before JSON serialization in sync operations
"""

import uuid

import pytest
from django.contrib.auth import get_user_model

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac.models import DABContentType, DABPermission, RoleDefinition
from test_app.models import Organization, Team


@pytest.fixture
def rando():
    return get_user_model().objects.create(username='rando')


@pytest.fixture
def galaxy_content_type():
    """Create a realistic galaxy content type with UUID primary key."""
    org_ct = DABContentType.objects.get_for_model(Organization)
    return DABContentType.objects.create(service='galaxy', model='collectionremote', app_label='galaxy', pk_field_type='uuid', parent_content_type=org_ct)


@pytest.fixture
def galaxy_permissions(galaxy_content_type):
    """Create permissions for the galaxy content type."""
    view_perm = DABPermission.objects.create(codename='view_collectionremote', content_type=galaxy_content_type)
    change_perm = DABPermission.objects.create(codename='change_collectionremote', content_type=galaxy_content_type)
    return view_perm, change_perm


@pytest.fixture
def galaxy_role(galaxy_content_type, galaxy_permissions):
    """Create a role definition for galaxy collections."""
    view_perm, change_perm = galaxy_permissions
    return RoleDefinition.objects.create_from_permissions(
        name='Galaxy Collection Remote Owner', permissions=[view_perm.api_slug, change_perm.api_slug], content_type=galaxy_content_type
    )


@pytest.mark.django_db
def test_uuid_remote_object_assignment_via_service_index(admin_api_client, rando, galaxy_role):
    """Test creating and removing assignments to UUID remote objects via real endpoints."""
    # Generate a realistic UUID for a galaxy collection
    collection_uuid = uuid.uuid4()

    # Assignment data for service-index endpoint
    assignment_data = {
        'role_definition': galaxy_role.name,
        'user_ansible_id': str(rando.resource.ansible_id),
        'object_id': str(collection_uuid),  # This is the UUID that was causing JSON serialization issues
        'from_service': 'test',
    }

    # Test assignment creation via service-index endpoint
    assign_url = get_relative_url('serviceuserassignment-assign')
    response = admin_api_client.post(assign_url, assignment_data, format='json')

    # Should succeed without JSON serialization errors
    assert response.status_code == 201, f"Assignment creation failed: {response.data}"

    # The main goal is to test that UUID serialization works without errors
    # The fact that we got a 201 status means the assignment was created successfully
    # and no JSON serialization errors occurred during the process

    # Test unassignment via service-index endpoint
    unassign_url = get_relative_url('serviceuserassignment-unassign')
    unassign_response = admin_api_client.post(unassign_url, assignment_data, format='json')

    # Should succeed without JSON serialization errors
    assert unassign_response.status_code == 204, f"Unassignment failed: {unassign_response.data}"


@pytest.mark.django_db
def test_uuid_remote_object_team_assignment_via_service_index(admin_api_client, galaxy_role, organization):
    """Test team assignments to UUID remote objects via real endpoints."""
    # Create a team for testing
    test_team = Team.objects.create(name='Test Team', organization=organization)
    collection_uuid = uuid.uuid4()

    # Team assignment data for service-index endpoint
    assignment_data = {
        'role_definition': galaxy_role.name,
        'team_ansible_id': str(test_team.resource.ansible_id),
        'object_id': str(collection_uuid),
        'from_service': 'test',
    }

    # Test team assignment creation
    assign_url = get_relative_url('serviceteamassignment-assign')
    response = admin_api_client.post(assign_url, assignment_data, format='json')

    # Should succeed without JSON serialization errors
    assert response.status_code == 201, f"Team assignment creation failed: {response.data}"

    # Test team unassignment
    unassign_url = get_relative_url('serviceteamassignment-unassign')
    unassign_response = admin_api_client.post(unassign_url, assignment_data, format='json')

    # Should succeed without JSON serialization errors
    assert unassign_response.status_code == 204, f"Team unassignment failed: {unassign_response.data}"


@pytest.mark.django_db
def test_integer_pk_still_works_with_service_index(admin_api_client, rando):
    """Test that integer primary keys continue to work correctly with real endpoints."""
    # Create a content type with integer primary key (default)
    awx_ct = DABContentType.objects.create(
        service='awx',
        model='job_template',
        app_label='awx',
        # pk_field_type defaults to 'integer'
    )

    awx_permission = DABPermission.objects.create(codename='execute_job_template', content_type=awx_ct)

    awx_role = RoleDefinition.objects.create_from_permissions(name='AWX Job Template Executor', permissions=[awx_permission.api_slug], content_type=awx_ct)

    # Integer job template ID
    job_template_id = 42

    assignment_data = {
        'role_definition': awx_role.name,
        'user_ansible_id': str(rando.resource.ansible_id),
        'object_id': str(job_template_id),  # Integer PK as string
        'from_service': 'test',
    }

    # Test assignment and unassignment work normally
    assign_url = get_relative_url('serviceuserassignment-assign')
    response = admin_api_client.post(assign_url, assignment_data, format='json')
    assert response.status_code == 201

    unassign_url = get_relative_url('serviceuserassignment-unassign')
    unassign_response = admin_api_client.post(unassign_url, assignment_data, format='json')
    assert unassign_response.status_code == 204


@pytest.mark.django_db
def test_global_assignment_still_works_with_service_index(admin_api_client, rando):
    """Test that global assignments (no content_object) work correctly."""
    # Create a global role (no content_type)
    global_role = RoleDefinition.objects.create_from_permissions(
        name='Global Administrator', permissions=['view_organization'], content_type=None  # Shared permission available globally  # Global role
    )

    assignment_data = {
        'role_definition': global_role.name,
        'user_ansible_id': str(rando.resource.ansible_id),
        # No object_id for global assignments
        'from_service': 'test',
    }

    # Test global assignment
    assign_url = get_relative_url('serviceuserassignment-assign')
    response = admin_api_client.post(assign_url, assignment_data, format='json')
    assert response.status_code == 201

    # Test global unassignment
    unassign_url = get_relative_url('serviceuserassignment-unassign')
    unassign_response = admin_api_client.post(unassign_url, assignment_data, format='json')
    assert unassign_response.status_code == 204


@pytest.mark.django_db
def test_local_object_assignment_via_service_index(admin_api_client, rando, organization):
    """Test creating and removing assignments to local Django model instances via real endpoints."""
    from test_app.models import Inventory

    # Create a local inventory object
    inventory = Inventory.objects.create(name='Test Inventory', organization=organization)

    # Create a role for inventories
    inv_ct = DABContentType.objects.get_for_model(Inventory)
    change_permission, _ = DABPermission.objects.get_or_create(codename='change_inventory', content_type=inv_ct, defaults={'name': 'Can change inventory'})
    view_permission, _ = DABPermission.objects.get_or_create(codename='view_inventory', content_type=inv_ct, defaults={'name': 'Can view inventory'})
    inv_role = RoleDefinition.objects.create_from_permissions(
        name='Inventory Admin Local Test', permissions=[change_permission.api_slug, view_permission.api_slug], content_type=inv_ct
    )

    # Assignment data for local object (using object_id for objects without resource field)
    assignment_data = {
        'role_definition': inv_role.name,
        'user_ansible_id': str(rando.resource.ansible_id),
        'object_id': str(inventory.pk),  # Local objects without resource field use pk
        'from_service': 'test',
    }

    # Test assignment creation via service-index endpoint
    assign_url = get_relative_url('serviceuserassignment-assign')
    response = admin_api_client.post(assign_url, assignment_data, format='json')

    # Should succeed - local objects have real content_object instances
    assert response.status_code == 201, f"Local object assignment creation failed: {response.data}"

    # Test unassignment via service-index endpoint
    unassign_url = get_relative_url('serviceuserassignment-unassign')
    unassign_response = admin_api_client.post(unassign_url, assignment_data, format='json')

    # Should succeed without JSON serialization errors
    assert unassign_response.status_code == 204, f"Local object unassignment failed: {unassign_response.data}"


@pytest.mark.django_db
def test_uuid_local_object_assignment_via_service_index(admin_api_client, rando, organization):
    """Test assignments to local Django models with UUID primary keys."""
    from test_app.models import UUIDModel

    # Create a local UUID model instance
    uuid_obj = UUIDModel.objects.create(organization=organization)

    # Create a role for UUID models
    uuid_ct = DABContentType.objects.get_for_model(UUIDModel)
    change_permission, _ = DABPermission.objects.get_or_create(codename='change_uuidmodel', content_type=uuid_ct, defaults={'name': 'Can change UUID model'})
    view_permission, _ = DABPermission.objects.get_or_create(codename='view_uuidmodel', content_type=uuid_ct, defaults={'name': 'Can view UUID model'})
    uuid_role = RoleDefinition.objects.create_from_permissions(
        name='UUID Model Admin Local Test', permissions=[change_permission.api_slug, view_permission.api_slug], content_type=uuid_ct
    )

    # Assignment data for local UUID object
    assignment_data = {
        'role_definition': uuid_role.name,
        'user_ansible_id': str(rando.resource.ansible_id),
        'object_id': str(uuid_obj.pk),  # Local UUID objects without resource field use pk
        'from_service': 'test',
    }

    # Test assignment creation
    assign_url = get_relative_url('serviceuserassignment-assign')
    response = admin_api_client.post(assign_url, assignment_data, format='json')

    # Should succeed - local UUID objects should work without serialization issues
    assert response.status_code == 201, f"Local UUID object assignment failed: {response.data}"

    # Test unassignment
    unassign_url = get_relative_url('serviceuserassignment-unassign')
    unassign_response = admin_api_client.post(unassign_url, assignment_data, format='json')

    # Should succeed (200 means already unassigned, 204 means successfully unassigned)
    assert unassign_response.status_code in [200, 204], f"Local UUID object unassignment failed: {unassign_response.data}"


@pytest.mark.django_db
def test_mixed_assignment_scenarios_via_service_index(admin_api_client, rando, galaxy_role, organization):
    """Test multiple assignment scenarios to ensure content_object handling works correctly."""
    from test_app.models import Inventory

    # Create local object
    inventory = Inventory.objects.create(name='Mixed Test Inventory', organization=organization)

    # Create role for local object
    inv_ct = DABContentType.objects.get_for_model(Inventory)

    inv_permission, _ = DABPermission.objects.get_or_create(codename='view_inventory', content_type=inv_ct, defaults={'name': 'Can view inventory'})

    inv_role = RoleDefinition.objects.create_from_permissions(name='Mixed Inventory Viewer', permissions=[inv_permission.api_slug], content_type=inv_ct)

    # Test 1: Local inventory assignment (content_object != None)
    local_assignment_data = {
        'role_definition': inv_role.name,
        'user_ansible_id': str(rando.resource.ansible_id),
        'object_id': str(inventory.pk),  # Local inventory uses pk
        'from_service': 'test',
    }

    assign_url = get_relative_url('serviceuserassignment-assign')
    response = admin_api_client.post(assign_url, local_assignment_data, format='json')
    assert response.status_code == 201, "Local inventory assignment should succeed"

    # Test 2: Remote object assignment (content_object = RemoteObject instance)
    remote_uuid = uuid.uuid4()
    remote_assignment_data = {
        'role_definition': galaxy_role.name,
        'user_ansible_id': str(rando.resource.ansible_id),
        'object_id': str(remote_uuid),
        'from_service': 'test',
    }

    response = admin_api_client.post(assign_url, remote_assignment_data, format='json')
    assert response.status_code == 201, "Remote object assignment should succeed"

    # Test cleanup: Unassign all
    unassign_url = get_relative_url('serviceuserassignment-unassign')

    for assignment_data in [local_assignment_data, remote_assignment_data]:
        response = admin_api_client.post(unassign_url, assignment_data, format='json')
        assert response.status_code in [200, 204], f"Unassignment should succeed for {assignment_data}"
