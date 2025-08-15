import uuid

import pytest

from ansible_base.lib.utils.response import get_relative_url
from test_app.models import Team, User


@pytest.mark.django_db
class TestUserAccessAssignmentUUIDLookup:
    """Test UUID-based lookup for UserAccessAssignmentViewSet"""

    def test_get_url_actor_with_primary_key(self, admin_api_client, inventory, inv_rd):
        """Test existing functionality - lookup by primary key should still work"""
        user = User.objects.create(username='test-user')
        inv_rd.give_permission(user, inventory)

        url = get_relative_url('role-user-access-assignments', kwargs={'model_name': 'aap.inventory', 'pk': inventory.pk, 'actor_pk': str(user.pk)})

        response = admin_api_client.get(url)
        assert response.status_code == 200
        assert response.data['count'] >= 1

    def test_get_url_actor_with_ansible_id(self, admin_api_client, inventory, inv_rd):
        """Test new functionality - lookup by ansible_id (UUID)"""
        user = User.objects.create(username='test-user')
        inv_rd.give_permission(user, inventory)

        # Get the user's ansible_id from their resource
        user_ansible_id = user.resource.ansible_id

        url = get_relative_url('role-user-access-assignments', kwargs={'model_name': 'aap.inventory', 'pk': inventory.pk, 'actor_pk': str(user_ansible_id)})

        response = admin_api_client.get(url)
        assert response.status_code == 200
        assert response.data['count'] >= 1

    def test_get_url_actor_with_invalid_uuid(self, admin_api_client, inventory):
        """Test error handling for invalid UUID"""
        invalid_uuid = str(uuid.uuid4())

        url = get_relative_url('role-user-access-assignments', kwargs={'model_name': 'aap.inventory', 'pk': inventory.pk, 'actor_pk': invalid_uuid})

        response = admin_api_client.get(url)
        assert response.status_code == 404
        assert 'can not be found' in response.data['detail']

    def test_get_url_actor_with_nonexistent_pk(self, admin_api_client, inventory):
        """Test error handling for non-existent primary key"""
        nonexistent_pk = '99999'

        url = get_relative_url('role-user-access-assignments', kwargs={'model_name': 'aap.inventory', 'pk': inventory.pk, 'actor_pk': nonexistent_pk})

        response = admin_api_client.get(url)
        assert response.status_code == 404
        assert 'can not be found' in response.data['detail']


@pytest.mark.django_db
class TestTeamAccessAssignmentUUIDLookup:
    """Test UUID-based lookup for TeamAccessAssignmentViewSet"""

    def test_get_url_actor_with_primary_key(self, admin_api_client, inventory, inv_rd, organization):
        """Test existing functionality - lookup by primary key should still work"""
        team = Team.objects.create(name='test-team', organization=organization)
        inv_rd.give_permission(team, inventory)

        url = get_relative_url('role-team-access-assignments', kwargs={'model_name': 'aap.inventory', 'pk': inventory.pk, 'actor_pk': str(team.pk)})

        response = admin_api_client.get(url)
        assert response.status_code == 200
        assert response.data['count'] >= 1

    def test_get_url_actor_with_ansible_id(self, admin_api_client, inventory, inv_rd, organization):
        """Test new functionality - lookup by ansible_id (UUID)"""
        team = Team.objects.create(name='test-team', organization=organization)
        inv_rd.give_permission(team, inventory)

        # Get the team's ansible_id from their resource
        team_ansible_id = team.resource.ansible_id

        url = get_relative_url('role-team-access-assignments', kwargs={'model_name': 'aap.inventory', 'pk': inventory.pk, 'actor_pk': str(team_ansible_id)})

        response = admin_api_client.get(url)
        assert response.status_code == 200
        assert response.data['count'] >= 1

    def test_get_url_actor_with_invalid_uuid(self, admin_api_client, inventory):
        """Test error handling for invalid UUID"""
        invalid_uuid = str(uuid.uuid4())

        url = get_relative_url('role-team-access-assignments', kwargs={'model_name': 'aap.inventory', 'pk': inventory.pk, 'actor_pk': invalid_uuid})

        response = admin_api_client.get(url)
        assert response.status_code == 404
        assert 'can not be found' in response.data['detail']


@pytest.mark.django_db
class TestAccessListRelatedLinksWithAnsibleID:
    """Test that related links in access list serializers use ansible_id when available"""

    def test_user_access_list_related_links_use_ansible_id(self, admin_api_client, inventory, inv_rd):
        """Test that user access list provides related links with ansible_id"""
        user = User.objects.create(username='test-user')
        inv_rd.give_permission(user, inventory)

        url = get_relative_url('role-user-access', kwargs={'pk': inventory.pk, 'model_name': 'aap.inventory'})
        response = admin_api_client.get(url)
        assert response.status_code == 200

        # Find our test user in the results
        user_data = None
        for user_detail in response.data['results']:
            if user_detail['username'] == 'test-user':
                user_data = user_detail
                break

        assert user_data is not None
        assert 'related' in user_data
        assert 'details' in user_data['related']

        # The details URL should use ansible_id instead of primary key
        expected_ansible_id = str(user.resource.ansible_id)
        assert expected_ansible_id in user_data['related']['details']

        # Check that the URL ends with the ansible_id, not the primary key
        assert user_data['related']['details'].endswith(f'{expected_ansible_id}/')

        # More robust check: ensure the URL contains the full UUID, not just ends with PK digits
        # This handles the edge case where UUID might end with the same digits as the PK
        details_url = user_data['related']['details']

        # Extract the last path segment (should be the ansible_id)
        url_parts = details_url.rstrip('/').split('/')
        last_segment = url_parts[-1]

        # The last segment should be the full UUID, not just the PK
        assert last_segment == expected_ansible_id, f"Expected UUID {expected_ansible_id}, but URL ends with {last_segment}"

        # Additional check: ensure it's not just the primary key
        assert last_segment != str(user.pk), f"URL incorrectly uses primary key {user.pk} instead of ansible_id"

    def test_team_access_list_related_links_use_ansible_id(self, admin_api_client, inventory, inv_rd, organization):
        """Test that team access list provides related links with ansible_id"""
        team = Team.objects.create(name='test-team', organization=organization)
        inv_rd.give_permission(team, inventory)

        url = get_relative_url('role-team-access', kwargs={'pk': inventory.pk, 'model_name': 'aap.inventory'})
        response = admin_api_client.get(url)
        assert response.status_code == 200

        # Find our test team in the results
        team_data = None
        for team_detail in response.data['results']:
            if team_detail['name'] == 'test-team':
                team_data = team_detail
                break

        assert team_data is not None
        assert 'related' in team_data
        assert 'details' in team_data['related']

        # The details URL should use ansible_id instead of primary key
        expected_ansible_id = str(team.resource.ansible_id)
        assert expected_ansible_id in team_data['related']['details']

        # Check that the URL ends with the ansible_id, not the primary key
        assert team_data['related']['details'].endswith(f'{expected_ansible_id}/')

        # More robust check: ensure the URL contains the full UUID, not just ends with PK digits
        # This handles the edge case where UUID might end with the same digits as the PK
        details_url = team_data['related']['details']

        # Extract the last path segment (should be the ansible_id)
        url_parts = details_url.rstrip('/').split('/')
        last_segment = url_parts[-1]

        # The last segment should be the full UUID, not just the PK
        assert last_segment == expected_ansible_id, f"Expected UUID {expected_ansible_id}, but URL ends with {last_segment}"

        # Additional check: ensure it's not just the primary key
        assert last_segment != str(team.pk), f"URL incorrectly uses primary key {team.pk} instead of ansible_id"

    def test_user_access_list_uuid_ending_with_pk_digits(self, admin_api_client, inventory, inv_rd):
        """Test edge case where UUID happens to end with the same digits as the user's PK"""
        # Create multiple users to increase the chance of getting a higher PK
        for i in range(10):
            User.objects.create(username=f'dummy-user-{i}')

        user = User.objects.create(username='test-user-edge-case')
        inv_rd.give_permission(user, inventory)

        # Get the user's UUID and PK
        expected_ansible_id = str(user.resource.ansible_id)
        user_pk = str(user.pk)

        # This test specifically validates the scenario mentioned in the bug report
        # Even if UUID ends with PK digits, the test should correctly identify the full UUID

        url = get_relative_url('role-user-access', kwargs={'pk': inventory.pk, 'model_name': 'aap.inventory'})
        response = admin_api_client.get(url)
        assert response.status_code == 200

        # Find our test user in the results
        user_data = None
        for user_detail in response.data['results']:
            if user_detail['username'] == 'test-user-edge-case':
                user_data = user_detail
                break

        assert user_data is not None
        assert 'related' in user_data
        assert 'details' in user_data['related']

        details_url = user_data['related']['details']

        # Extract the last path segment (should be the ansible_id)
        url_parts = details_url.rstrip('/').split('/')
        last_segment = url_parts[-1]

        # The critical test: last segment should be the full UUID, not just the PK
        # This should pass even if the UUID ends with the same digits as the PK
        assert last_segment == expected_ansible_id, (
            f"URL should end with full UUID {expected_ansible_id}, not PK {user_pk}. " f"Actual last segment: {last_segment}. Full URL: {details_url}"
        )

        # Ensure the full UUID is present in the URL
        assert expected_ansible_id in details_url

        # Additional validation: if UUID ends with PK digits, ensure we're still using the full UUID
        if expected_ansible_id.endswith(user_pk):
            # This is the problematic case that was failing
            # The URL should still contain the full UUID, not just end with PK
            assert len(last_segment) > len(user_pk), f"UUID {expected_ansible_id} ends with PK {user_pk}, but URL should use full UUID, not just PK"

    def test_user_access_list_fallback_to_pk_when_no_resource(self, admin_api_client, inventory, inv_rd):
        """Test fallback to primary key when user has no resource (edge case)"""
        user = User.objects.create(username='test-user-no-resource')

        # Manually delete the resource to simulate edge case
        if hasattr(user, 'resource') and user.resource:
            user.resource.delete()

        inv_rd.give_permission(user, inventory)

        url = get_relative_url('role-user-access', kwargs={'pk': inventory.pk, 'model_name': 'aap.inventory'})
        response = admin_api_client.get(url)
        assert response.status_code == 200

        # Find our test user in the results
        user_data = None
        for user_detail in response.data['results']:
            if user_detail['username'] == 'test-user-no-resource':
                user_data = user_detail
                break

        assert user_data is not None
        assert 'related' in user_data
        assert 'details' in user_data['related']

        # Should fall back to primary key when no resource available
        assert str(user.pk) in user_data['related']['details']
