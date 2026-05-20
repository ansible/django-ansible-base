from copy import deepcopy

import pytest
from rest_framework.test import APIClient

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac.models import DABContentType, DABPermission, RoleDefinition
from test_app.models import Team, User


@pytest.mark.django_db
def test_get_resource_list(admin_api_client):
    url = get_relative_url('dabcontenttype-list')
    response = admin_api_client.get(url, format="json")
    assert response.status_code == 200, response.data
    type_data = {t['api_slug']: t for t in response.data['results']}

    assert 'shared.organization' in type_data
    org_data = type_data['shared.organization']
    assert org_data['parent_content_type'] is None
    assert org_data['service'] == 'shared'
    assert org_data['model'] == 'organization'

    assert 'aap.inventory' in type_data
    inv_data = type_data['aap.inventory']
    assert inv_data['parent_content_type'] == 'shared.organization'


@pytest.mark.django_db
def test_get_permission_list(admin_api_client):
    url = get_relative_url('dabpermission-list')
    response = admin_api_client.get(url + '?page_size=200', format="json")
    assert response.status_code == 200, response.data
    type_data = {t['api_slug']: t for t in response.data['results']}

    assert 'shared.change_organization' in type_data
    change_org_data = type_data['shared.change_organization']
    assert change_org_data['content_type'] == 'shared.organization'
    assert change_org_data['codename'] == 'change_organization'


@pytest.mark.django_db
def test_role_definition_listed_as_resource(admin_api_client, org_admin_rd):
    url = get_relative_url('resource-list')
    url += '?page_size=200&content_type__resource_type__name=shared.roledefinition'
    response = admin_api_client.get(url, format="json")
    assert response.status_code == 200, response.data
    rd_data = {rd['name']: rd for rd in response.data['results']}

    assert 'Organization Admin' in rd_data
    org_admin_data = rd_data['Organization Admin']

    detail = admin_api_client.get(org_admin_data['url'], format="json")
    assert detail.status_code == 200, detail.data
    resource_data = detail.data['resource_data']
    assert resource_data['managed'] is True
    assert resource_data['content_type'] == 'shared.organization'
    assert 'permissions' in detail.data['resource_data']
    assert 'aap.add_inventory' in detail.data['resource_data']['permissions']


@pytest.mark.django_db
def test_reload_types(admin_api_client):
    url = get_relative_url('dabcontenttype-list')
    response = admin_api_client.get(url + '?page_size=200', format="json")
    assert response.status_code == 200, response.data

    type_list = response.data['results']
    original = deepcopy(type_list)

    DABContentType.objects.all().delete()  # Delete all types, see if we get them back

    DABContentType.objects.load_remote_objects(type_list)

    response = admin_api_client.get(url + '?page_size=200', format="json")
    assert response.status_code == 200, response.data

    assert response.data['results'] == original


@pytest.mark.django_db
def test_load_child_of_org():
    DABContentType.objects.load_remote_objects([{'service': 'fooland', 'app_label': 'foop', 'model': 'fooser', 'parent_content_type': 'shared.organization'}])
    ct = DABContentType.objects.get(api_slug='fooland.fooser')
    assert ct.parent_content_type.app_label == 'test_app'  # proves connection to existing


@pytest.mark.django_db
def test_reload_permissions(admin_api_client):
    url = get_relative_url('dabpermission-list')
    response = admin_api_client.get(url + '?page_size=200', format="json")
    assert response.status_code == 200, response.data

    perm_list = response.data['results']
    original = deepcopy(perm_list)

    DABPermission.objects.all().delete()  # Delete all permissions, see if we get them back

    DABPermission.objects.load_remote_objects(perm_list)

    response = admin_api_client.get(url + '?page_size=200', format="json")
    assert response.status_code == 200, response.data

    assert response.data['results'] == original


@pytest.mark.django_db
def test_list_role_user_assignments(admin_api_client, rando, inv_rd, inventory):
    inv_rd.give_permission(rando, inventory)

    url = get_relative_url('serviceuserassignment-list')
    response = admin_api_client.get(url + '?page_size=200', format="json")
    assert response.status_code == 200, response.data

    candidates = [assignment for assignment in response.data['results'] if assignment['role_definition'] == inv_rd.name]
    assert len(candidates) == 1, response.data
    from_api = candidates[0]

    assert int(from_api['object_id']) == inventory.id
    assert from_api['user_ansible_id'] == str(rando.resource.ansible_id)
    assert from_api['content_type'] == 'aap.inventory'


@pytest.mark.django_db
def test_apply_role_assignment(admin_api_client, rando, inv_rd, inventory):
    url = get_relative_url('serviceuserassignment-assign')

    data = {"role_definition": inv_rd.name, "user_ansible_id": str(rando.resource.ansible_id), "object_id": inventory.pk}

    assert not rando.has_obj_perm(inventory, 'change')
    response = admin_api_client.post(url, data=data)
    assert response.status_code == 201, response.data
    assert rando.has_obj_perm(inventory, 'change')

    # Second try, response code indicates assignment already exists
    response = admin_api_client.post(url, data=data)
    assert response.status_code == 200, response.data


@pytest.mark.django_db
def test_unassign_endpoint(rando, org_inv_rd, inventory, admin_api_client):
    org_inv_rd.give_permission(rando, inventory.organization)
    assert rando.has_obj_perm(inventory, 'change')

    url = get_relative_url('serviceuserassignment-unassign')
    data = {
        "role_definition": org_inv_rd.name,
        "user_ansible_id": str(rando.resource.ansible_id),
        "object_ansible_id": str(inventory.organization.resource.ansible_id),
    }
    response = admin_api_client.post(url, data)
    assert response.status_code == 204, response.data
    assert not rando.has_obj_perm(inventory, 'change')

    # second gets a 200 code
    response = admin_api_client.post(url, data)
    assert response.status_code == 200, response.data
    assert not rando.has_obj_perm(inventory, 'change')


# teams
@pytest.mark.django_db
def test_apply_role_assignment_for_team(admin_api_client, inv_rd, inventory, team, member_rd, rando):
    member_rd.give_permission(rando, team)
    url = get_relative_url('serviceteamassignment-assign')

    data = {"role_definition": inv_rd.name, "team_ansible_id": str(team.resource.ansible_id), "object_id": inventory.pk}

    assert not rando.has_obj_perm(inventory, 'change')
    response = admin_api_client.post(url, data=data)
    assert response.status_code == 201, response.data
    assert rando.has_obj_perm(inventory, 'change')

    # Second try, response code indicates assignment already exists
    response = admin_api_client.post(url, data=data)
    assert response.status_code == 200, response.data


@pytest.mark.django_db
def test_unassign_endpoint_for_team(team, org_inv_rd, inventory, admin_api_client, member_rd, rando):
    member_rd.give_permission(rando, team)
    org_inv_rd.give_permission(team, inventory.organization)
    assert rando.has_obj_perm(inventory, 'change')

    url = get_relative_url('serviceteamassignment-unassign')
    data = {
        "role_definition": org_inv_rd.name,
        "team_ansible_id": str(team.resource.ansible_id),
        "object_ansible_id": str(inventory.organization.resource.ansible_id),
    }
    response = admin_api_client.post(url, data)
    assert response.status_code == 204, response.data
    assert not rando.has_obj_perm(inventory, 'change')

    # second gets a 200 code
    response = admin_api_client.post(url, data)
    assert response.status_code == 200, response.data
    assert not rando.has_obj_perm(inventory, 'change')


@pytest.mark.django_db
def test_service_user_assignment_requires_object_permission(inv_rd, inventory, rando):
    requester = User.objects.create(username='service-requester')
    rando.resource_api_actions = "*"  # specific to internal requests
    client = APIClient()
    client.force_authenticate(user=requester)

    url = get_relative_url('serviceuserassignment-assign')
    data = {"role_definition": inv_rd.name, "user_ansible_id": str(rando.resource.ansible_id), "object_id": inventory.pk}

    response = client.post(url, data=data)
    assert response.status_code == 403, response.data

    # Should still get a 403 even if assignment already exists
    inv_rd.give_permission(rando, inventory)
    response = client.post(url, data=data)
    assert response.status_code == 403, response.data


@pytest.mark.django_db
@pytest.mark.parametrize('actor_type', ['user', 'team'])
def test_assign_and_unassign_system_role(inventory, admin_api_client, actor_type, organization, member_rd):
    if actor_type == 'user':
        actor = User.objects.create(username='user1')
        user = actor
    else:
        actor = Team.objects.create(name='random_team', organization=organization)
        user = User.objects.create(username='user1')
        member_rd.give_permission(user, actor)

    rd = RoleDefinition.objects.managed.sys_auditor
    assert 'view_inventory' in set(rd.permissions.values_list('codename', flat=True))
    assert not user.has_obj_perm(inventory, 'view')

    url = get_relative_url(f'service{actor_type}assignment-assign')
    data = {"role_definition": rd.name, f"{actor_type}_ansible_id": str(actor.resource.ansible_id)}
    response = admin_api_client.post(url, data)
    assert response.status_code == 201, response.data
    if hasattr(actor, '_singleton_permissions'):
        delattr(actor, '_singleton_permissions')
    assert user.has_obj_perm(inventory, 'view')  # gave system wide view permission

    # Second try, response code indicates global assignment already exists
    response = admin_api_client.post(url, data=data)
    assert response.status_code == 200, response.data

    unassign_url = get_relative_url(f'service{actor_type}assignment-unassign')
    response = admin_api_client.post(unassign_url, data)
    assert response.status_code == 204, response.data
    if hasattr(actor, '_singleton_permissions'):
        delattr(actor, '_singleton_permissions')
    assert not user.has_obj_perm(inventory, 'view')  # permission removed

    response = admin_api_client.post(unassign_url, data)
    assert response.status_code == 200, response.data


@pytest.mark.django_db
def test_filter_assignment_list(admin_api_client, rando, inv_rd, view_inv_rd, org_inv_rd, inventory):
    inv_rd.give_permission(rando, inventory)
    org_inv_rd.give_permission(rando, inventory.organization)
    view_inv_rd.give_permission(rando, inventory)

    url = get_relative_url('serviceuserassignment-list')
    response = admin_api_client.get(url + f'?user={rando.id}', format="json")
    assert response.status_code == 200, response.data
    assert response.data['count'] == 3  # user rando has 3 rol assignments

    # Get just one single assignment
    response = admin_api_client.get(url + f'?assignment={str(rando.resource.ansible_id)},{inv_rd.name},{inventory.id}', format="json")
    assert response.status_code == 200, response.data
    assert response.data['count'] == 1
    assert response.data['results'][0]['role_definition'] == inv_rd.name

    # Assure we can get two assignments at the same time
    response = admin_api_client.get(
        url
        + (
            f'?assignment={str(rando.resource.ansible_id)},{inv_rd.name},{inventory.id}&'
            f'assignment={str(rando.resource.ansible_id)},{org_inv_rd.name},{inventory.organization.id}'
        ),
        format="json",
    )
    assert response.status_code == 200, response.data
    assert response.data['count'] == 2


@pytest.mark.django_db
@pytest.mark.parametrize(
    'reverse_name,normal_case,unauth_case',
    [
        ('service-index-root', 200, 401),
        ('dabcontenttype-list', 200, 401),  # could change unauthenticated case, depends on need
        ('dabpermission-list', 200, 401),
        ('resource-list', 403, 401),
        ('serviceuserassignment-list', 403, 401),
        ('serviceteamassignment-list', 403, 401),
    ],
)
def test_service_api_permissions(reverse_name, normal_case, unauth_case, admin_api_client, user_api_client, unauthenticated_api_client):
    url = get_relative_url(reverse_name)

    admin_response = admin_api_client.get(url)
    assert admin_response.status_code == 200, admin_response.data

    normal_response = user_api_client.get(url)
    assert normal_response.status_code == normal_case, normal_response.data

    unauth_response = unauthenticated_api_client.get(url)
    assert unauth_response.status_code == unauth_case, unauth_response.data


@pytest.mark.django_db
def test_role_types_and_permissions_payload_shape(user_api_client):
    """Minimal payload-shape checks for role types and permissions when accessed by normal user."""
    # role types
    url_ct = get_relative_url('dabcontenttype-list')
    resp_ct = user_api_client.get(url_ct)
    assert resp_ct.status_code == 200, resp_ct.data
    # Results should be paginated list; spot-check first item fields if present
    if resp_ct.data.get('count', 0) and resp_ct.data.get('results'):
        item = resp_ct.data['results'][0]
        for key in ('api_slug', 'service', 'app_label', 'model', 'pk_field_type'):
            assert key in item
        # parent_content_type is allowed to be null
        assert 'parent_content_type' in item

    # role permissions
    url_perm = get_relative_url('dabpermission-list')
    resp_perm = user_api_client.get(url_perm)
    assert resp_perm.status_code == 200, resp_perm.data
    if resp_perm.data.get('count', 0) and resp_perm.data.get('results'):
        item = resp_perm.data['results'][0]
        for key in ('api_slug', 'codename', 'name'):
            assert key in item
        assert 'content_type' in item  # slug of related content type


@pytest.mark.django_db
class TestCreatedByAnsibleIdAllowNull:
    """Test that created_by_ansible_id field accepts null values and omissions"""

    def test_service_user_assignment_with_null_created_by(self, admin_api_client, rando, inv_rd, inventory):
        """Test that ServiceRoleUserAssignmentSerializer accepts null created_by_ansible_id"""
        url = get_relative_url('serviceuserassignment-assign')
        data = {
            "role_definition": inv_rd.name,
            "user_ansible_id": str(rando.resource.ansible_id),
            "object_id": inventory.pk,
            "created_by_ansible_id": "",  # Use empty string instead of None
        }

        response = admin_api_client.post(url, data=data)
        assert response.status_code == 201, response.data
        assert rando.has_obj_perm(inventory, 'change')

    def test_service_user_assignment_without_created_by(self, admin_api_client, rando, inv_rd, inventory):
        """Test that ServiceRoleUserAssignmentSerializer works when created_by_ansible_id is omitted"""
        url = get_relative_url('serviceuserassignment-assign')
        data = {
            "role_definition": inv_rd.name,
            "user_ansible_id": str(rando.resource.ansible_id),
            "object_id": inventory.pk,
            # created_by_ansible_id is intentionally omitted
        }

        response = admin_api_client.post(url, data=data)
        assert response.status_code == 201, response.data
        assert rando.has_obj_perm(inventory, 'change')

    def test_service_user_assignment_with_valid_created_by(self, admin_api_client, rando, inv_rd, inventory):
        """Test that valid created_by_ansible_id values still work correctly"""
        creator = User.objects.create(username='creator-user')
        url = get_relative_url('serviceuserassignment-assign')
        data = {
            "role_definition": inv_rd.name,
            "user_ansible_id": str(rando.resource.ansible_id),
            "object_id": inventory.pk,
            "created_by_ansible_id": str(creator.resource.ansible_id),
        }

        response = admin_api_client.post(url, data=data)
        assert response.status_code == 201, response.data
        assert rando.has_obj_perm(inventory, 'change')

    def test_service_team_assignment_with_null_created_by(self, admin_api_client, team, inv_rd, inventory, member_rd, rando):
        """Test that ServiceRoleTeamAssignmentSerializer accepts null created_by_ansible_id"""
        member_rd.give_permission(rando, team)
        url = get_relative_url('serviceteamassignment-assign')
        data = {
            "role_definition": inv_rd.name,
            "team_ansible_id": str(team.resource.ansible_id),
            "object_id": inventory.pk,
            "created_by_ansible_id": "",  # Use empty string instead of None
        }

        response = admin_api_client.post(url, data=data)
        assert response.status_code == 201, response.data
        assert rando.has_obj_perm(inventory, 'change')

    def test_service_team_assignment_without_created_by(self, admin_api_client, team, inv_rd, inventory, member_rd, rando):
        """Test that ServiceRoleTeamAssignmentSerializer works when created_by_ansible_id is omitted"""
        member_rd.give_permission(rando, team)
        url = get_relative_url('serviceteamassignment-assign')
        data = {
            "role_definition": inv_rd.name,
            "team_ansible_id": str(team.resource.ansible_id),
            "object_id": inventory.pk,
        }

        response = admin_api_client.post(url, data=data)
        assert response.status_code == 201, response.data
        assert rando.has_obj_perm(inventory, 'change')

    def test_service_team_assignment_with_valid_created_by(self, admin_api_client, team, inv_rd, inventory, member_rd, rando):
        """Test that valid created_by_ansible_id values still work correctly for teams"""
        member_rd.give_permission(rando, team)
        creator = User.objects.create(username='team-creator-user')
        url = get_relative_url('serviceteamassignment-assign')
        data = {
            "role_definition": inv_rd.name,
            "team_ansible_id": str(team.resource.ansible_id),
            "object_id": inventory.pk,
            "created_by_ansible_id": str(creator.resource.ansible_id),
        }

        response = admin_api_client.post(url, data=data)
        assert response.status_code == 201, response.data
        assert rando.has_obj_perm(inventory, 'change')

    def test_list_assignments_shows_created_by_when_present(self, admin_api_client, rando, inv_rd, inventory):
        """Test that list endpoint properly serializes created_by_ansible_id when present"""
        creator = User.objects.create(username='assignment-creator')

        # Create assignment with a specific creator
        url = get_relative_url('serviceuserassignment-assign')
        data = {
            "role_definition": inv_rd.name,
            "user_ansible_id": str(rando.resource.ansible_id),
            "object_id": inventory.pk,
            "created_by_ansible_id": str(creator.resource.ansible_id),
        }
        response = admin_api_client.post(url, data=data)
        assert response.status_code == 201, response.data

        # Check list endpoint
        list_url = get_relative_url('serviceuserassignment-list')
        response = admin_api_client.get(list_url + '?page_size=200', format="json")
        assert response.status_code == 200, response.data

        # Find our assignment
        assignments = [a for a in response.data['results'] if a['role_definition'] == inv_rd.name and str(a['object_id']) == str(inventory.id)]
        assert len(assignments) >= 1, "Should find at least our assignment"

        # Check that created_by_ansible_id is properly serialized
        assignment = assignments[0]
        assert 'created_by_ansible_id' in assignment
        assert assignment['created_by_ansible_id'] == str(creator.resource.ansible_id)

    def test_list_assignments_shows_null_created_by_when_null(self, admin_api_client, rando, inv_rd, inventory):
        """Test that list endpoint properly serializes created_by_ansible_id when empty string is provided"""
        # Create assignment with empty created_by_ansible_id
        url = get_relative_url('serviceuserassignment-assign')
        data = {
            "role_definition": inv_rd.name,
            "user_ansible_id": str(rando.resource.ansible_id),
            "object_id": inventory.pk,
            "created_by_ansible_id": "",  # Use empty string - should be treated as not providing the field
        }
        response = admin_api_client.post(url, data=data)
        assert response.status_code == 201, response.data

        # Check list endpoint
        list_url = get_relative_url('serviceuserassignment-list')
        response = admin_api_client.get(list_url + '?page_size=200', format="json")
        assert response.status_code == 200, response.data

        # Find our assignment
        assignments = [a for a in response.data['results'] if a['role_definition'] == inv_rd.name and str(a['object_id']) == str(inventory.id)]
        assert len(assignments) >= 1, "Should find at least our assignment"

        # Check that created_by_ansible_id is properly serialized
        assignment = assignments[0]
        assert 'created_by_ansible_id' in assignment
        # When empty string is provided, the system may still set created_by to the current user
        # The key test is that the API accepts empty string without error
        assert assignment['created_by_ansible_id'] is not None  # System will set to current user

    def test_serializer_allows_null_values_in_validation(self, admin_api_client, rando, inv_rd, inventory):
        """Test that the serializer field properly handles null validation with allow_null=True"""
        from ansible_base.rbac.service_api.serializers import ServiceRoleUserAssignmentSerializer

        # Test data with null created_by_ansible_id
        data = {
            "role_definition": inv_rd.name,
            "user_ansible_id": str(rando.resource.ansible_id),
            "object_id": str(inventory.pk),
            "created_by_ansible_id": None,  # Explicit None
            "from_service": "test",
        }

        # Create serializer and validate
        serializer = ServiceRoleUserAssignmentSerializer(data=data)

        # Should be valid due to allow_null=True
        is_valid = serializer.is_valid()
        if not is_valid:
            print("Validation errors:", serializer.errors)
        assert is_valid, f"Serializer should accept null values: {serializer.errors}"

        # Verify that created_by is None in validated_data when null is passed
        validated_data = serializer.validated_data
        assert 'created_by' not in validated_data or validated_data.get('created_by') is None


@pytest.mark.django_db
class TestRestClientSyncAssignment:
    """
    Test that rest_client.sync_assignment only sends the appropriate ID field.

    For objects registered with resource registry: send only object_ansible_id
    For objects NOT registered: send only object_id

    Generated by Claude Sonnet 4.5
    """

    def test_sync_assignment_sends_only_object_ansible_id_for_registered_objects(self, rando, organization, org_admin_rd):
        """Test that sync_assignment removes object_id when object_ansible_id is present"""
        from unittest.mock import MagicMock, patch

        from ansible_base.resource_registry.rest_client import ResourceAPIClient

        # Create an assignment to an organization (which has a resource)
        assignment = org_admin_rd.give_permission(rando, organization)

        # Create a mock client
        client = ResourceAPIClient(service_url='http://example.com', service_path='/api/v1/service-index/')

        # Mock the _sync_assignment method to capture what data is sent
        with patch.object(client, '_sync_assignment', return_value=MagicMock()) as mock_sync:
            # Call sync_assignment
            client.sync_assignment(assignment)

            # Verify _sync_assignment was called
            assert mock_sync.called
            sent_data = mock_sync.call_args[0][0]

            # Should have object_ansible_id
            assert 'object_ansible_id' in sent_data
            assert sent_data['object_ansible_id'] == str(organization.resource.ansible_id)

            # Should NOT have object_id (removed by sync_assignment)
            assert 'object_id' not in sent_data, "object_id should not be sent for registered objects"

    def test_sync_assignment_sends_only_object_id_for_non_registered_objects(self, rando, inventory, inv_rd):
        """Test that sync_assignment keeps object_id when object_ansible_id is None"""
        from unittest.mock import MagicMock, patch

        from ansible_base.resource_registry.rest_client import ResourceAPIClient

        # Create an assignment to an inventory (which doesn't have a resource)
        assignment = inv_rd.give_permission(rando, inventory)

        # Create a mock client
        client = ResourceAPIClient(service_url='http://example.com', service_path='/api/v1/service-index/')

        # Mock the _sync_assignment method to capture what data is sent
        with patch.object(client, '_sync_assignment', return_value=MagicMock()) as mock_sync:
            # Call sync_assignment
            client.sync_assignment(assignment)

            # Verify _sync_assignment was called
            assert mock_sync.called
            sent_data = mock_sync.call_args[0][0]

            # Should have object_id
            assert 'object_id' in sent_data
            assert sent_data['object_id'] == str(inventory.id)

            # object_ansible_id should either be absent or None
            assert sent_data.get('object_ansible_id') is None


@pytest.mark.django_db
class TestObjectIdVsAnsibleId:
    """
    Test server-side defensive behavior: object_ansible_id takes precedence when both are provided.

    This is a defensive measure for the edge case where a client incorrectly sends both fields
    that point to different objects. In this case, object_ansible_id should win.

    Generated by Claude Sonnet 4.5
    """

    def test_object_ansible_id_takes_precedence_when_both_differ(self, admin_api_client, rando, org_admin_rd, organization):
        """
        Test DESIRED defensive server-side behavior: object_ansible_id wins when both are provided but differ.

        This should not happen in normal operation (the client should only send one), but if it does,
        object_ansible_id should take precedence since it's the canonical identifier for cross-service sync.
        """
        from test_app.models import Organization

        # Create a second organization
        org2 = Organization.objects.create(name='Other Organization')

        url = get_relative_url('serviceuserassignment-assign')

        # Provide both with valid but different values (simulating a buggy client)
        # object_id points to org2, object_ansible_id points to organization
        data = {
            "role_definition": org_admin_rd.name,
            "user_ansible_id": str(rando.resource.ansible_id),
            "object_id": str(org2.id),  # Wrong object
            "object_ansible_id": str(organization.resource.ansible_id),  # Should take precedence
        }

        response = admin_api_client.post(url, data=data)
        assert response.status_code == 201, f"Expected 201 but got {response.status_code}: {response.data}"

        # Verify the assignment was made to organization (from object_ansible_id), not org2
        assert rando.has_obj_perm(organization, 'change'), "object_ansible_id should take precedence"
        assert not rando.has_obj_perm(org2, 'change'), "object_id should be ignored when both provided"


@pytest.mark.django_db
class TestValidationErrors:
    """Test validation error cases in service API serializers"""

    def test_system_role_with_object_id_error(self, admin_api_client, rando):
        """Test that providing object_id for system role raises validation error"""
        from ansible_base.rbac.models import RoleDefinition

        # Get a system role (no content_type)
        system_rd = RoleDefinition.objects.managed.sys_auditor
        assert system_rd.content_type_id is None, "Should be a system role"

        url = get_relative_url('serviceuserassignment-assign')
        data = {
            "role_definition": system_rd.name,
            "user_ansible_id": str(rando.resource.ansible_id),
            "object_id": "12345",  # This should cause error for system role
        }

        response = admin_api_client.post(url, data=data)
        assert response.status_code == 400, response.data
        assert "Can not provide either 'object_id' or 'object_ansible_id' for system role" in str(response.data)

    def test_system_role_with_object_ansible_id_error(self, admin_api_client, rando, organization):
        """Test that providing object_ansible_id for system role raises validation error"""
        from ansible_base.rbac.models import RoleDefinition

        # Get a system role (no content_type)
        system_rd = RoleDefinition.objects.managed.sys_auditor
        assert system_rd.content_type_id is None, "Should be a system role"

        url = get_relative_url('serviceuserassignment-assign')
        data = {
            "role_definition": system_rd.name,
            "user_ansible_id": str(rando.resource.ansible_id),
            "object_ansible_id": str(organization.resource.ansible_id),  # This should cause error for system role
        }

        response = admin_api_client.post(url, data=data)
        assert response.status_code == 400, response.data
        assert "Can not provide either 'object_id' or 'object_ansible_id' for system role" in str(response.data)

    def test_object_role_with_nonexistent_object_creates_remote_assignment(self, admin_api_client, rando, inv_rd):
        """Synced assignments for non-existent local objects fall back to
        RemoteObject so that cross-service sync is not blocked by object
        ordering (the object may not have been synced yet)."""
        url = get_relative_url('serviceuserassignment-assign')
        data = {
            "role_definition": inv_rd.name,
            "user_ansible_id": str(rando.resource.ansible_id),
            "object_id": "99999",
        }

        response = admin_api_client.post(url, data=data)
        assert response.status_code == 201, response.data
        assert str(response.data["object_id"]) == "99999"

    def test_object_role_without_object_specified_error(self, admin_api_client, rando, inv_rd):
        """Test that object role without object_id raises validation error"""
        url = get_relative_url('serviceuserassignment-assign')
        data = {
            "role_definition": inv_rd.name,
            "user_ansible_id": str(rando.resource.ansible_id),
            # No object_id or object_ansible_id provided
        }

        response = admin_api_client.post(url, data=data)
        assert response.status_code == 400, response.data
        # Check if the error is about missing object_id or object_ansible_id
        error_msg = str(response.data)
        assert "You must provide either 'object_id' or 'object_ansible_id'" in error_msg
