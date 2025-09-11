"""
Unit tests for sync_object_deletion method - AAP-51985 cross-service sync integration

Tests the new DABResourceAPIClient.sync_object_deletion method that handles
the HTTP communication between Controller and Gateway for role cleanup.
"""

from unittest.mock import MagicMock, patch

import pytest
from django.test.utils import override_settings

from ansible_base.rbac.permission_registry import permission_registry

# Make reverse sync fixtures available
from test_app.tests.resource_registry.conftest import enable_reverse_sync  # noqa: F401


@pytest.mark.django_db
def test_sync_object_deletion_success(inventory, enable_reverse_sync):  # noqa: F811
    """
    Test successful sync_object_deletion call with proper request/response format.
    This verifies the complete request/response cycle.
    """
    with enable_reverse_sync():
        with override_settings(RESOURCE_SERVER={'URL': 'http://gateway.example.com', 'SECRET_KEY': 'test-secret'}):
            with patch('ansible_base.resource_registry.rest_client.ResourceAPIClient._make_request') as mock_request:
                # Mock successful Gateway response
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {
                    'message': 'Deleted 2 role assignments for test_app.inventory 123',
                    'deleted_count': 2,
                    'breakdown': {'user_assignments_deleted': 1, 'team_assignments_deleted': 1},
                }
                mock_request.return_value = mock_response

                # Import and call the sync function
                from ansible_base.rbac.sync import maybe_reverse_sync_object_deletion

                maybe_reverse_sync_object_deletion(inventory)

                # Verify the request was made
                assert mock_request.called

                # Verify request details - _make_request uses positional arguments
                call_args = mock_request.call_args
                call_positional = call_args[0]  # Positional arguments
                call_kwargs = call_args[1]  # Keyword arguments

                # Check positional arguments: method and path
                assert len(call_positional) >= 2
                assert call_positional[0] == 'post'  # method
                assert 'object-delete' in call_positional[1]  # path
                assert 'data' in call_kwargs

                data = call_kwargs['data']
                # Verify request payload format
                assert 'resource_type' in data
                assert 'resource_pk' in data
                assert data['resource_pk'] == str(inventory.pk)

                ct = permission_registry.content_type_model.objects.get_for_model(inventory)
                expected_resource_type = f'{ct.app_label}.{ct.model}'
                assert data['resource_type'] == expected_resource_type


@pytest.mark.django_db
def test_sync_object_deletion_gateway_unavailable(inventory, enable_reverse_sync):  # noqa: F811
    """
    Test handling when Gateway is unavailable (network/connection errors).
    The sync should fail gracefully without breaking local deletion.
    """
    with enable_reverse_sync():
        with override_settings(RESOURCE_SERVER={'URL': 'http://gateway.example.com', 'SECRET_KEY': 'test-secret'}):
            with patch('ansible_base.resource_registry.rest_client.ResourceAPIClient._make_request') as mock_request:
                # Simulate network error
                mock_request.side_effect = Exception("Connection refused")

                from ansible_base.rbac.sync import maybe_reverse_sync_object_deletion

                # Should not raise exception
                try:
                    maybe_reverse_sync_object_deletion(inventory)
                except Exception as e:
                    pytest.fail(f"Sync should handle Gateway unavailability gracefully, but raised: {e}")


@pytest.mark.django_db
def test_sync_object_deletion_gateway_error_response(inventory, enable_reverse_sync):  # noqa: F811
    """
    Test handling of Gateway error responses (4xx, 5xx HTTP status codes).
    """
    with enable_reverse_sync():
        with override_settings(RESOURCE_SERVER={'URL': 'http://gateway.example.com', 'SECRET_KEY': 'test-secret'}):
            with patch('ansible_base.resource_registry.rest_client.ResourceAPIClient._make_request') as mock_request:
                # Mock Gateway error response
                mock_response = MagicMock()
                mock_response.status_code = 500
                mock_response.json.return_value = {'error': 'Internal server error'}
                mock_request.return_value = mock_response

                from ansible_base.rbac.sync import maybe_reverse_sync_object_deletion

                # Should handle error response gracefully
                try:
                    maybe_reverse_sync_object_deletion(inventory)
                except Exception as e:
                    pytest.fail(f"Sync should handle Gateway errors gracefully, but raised: {e}")


@pytest.mark.django_db
def test_sync_object_deletion_no_resource_server_config(inventory):
    """
    Test behavior when RESOURCE_SERVER is not configured.
    Should skip sync without errors.
    """
    # No RESOURCE_SERVER setting configured
    with override_settings():
        # Remove RESOURCE_SERVER if it exists
        from django.conf import settings

        if hasattr(settings, 'RESOURCE_SERVER'):
            delattr(settings, 'RESOURCE_SERVER')

        from ansible_base.rbac.sync import maybe_reverse_sync_object_deletion

        # Should not raise exception when no config
        try:
            maybe_reverse_sync_object_deletion(inventory)
        except Exception as e:
            pytest.fail(f"Should handle missing config gracefully, but raised: {e}")


@pytest.mark.django_db
def test_sync_object_deletion_reverse_sync_disabled(inventory, enable_reverse_sync):  # noqa: F811
    """
    Test behavior when reverse sync is disabled.
    Should skip sync operations entirely.
    """
    # Don't use enable_reverse_sync context manager - leave it disabled
    with override_settings(RESOURCE_SERVER={'URL': 'http://gateway.example.com', 'SECRET_KEY': 'test-secret'}):
        with patch('ansible_base.resource_registry.rest_client.ResourceAPIClient._make_request') as mock_request:
            from ansible_base.rbac.sync import maybe_reverse_sync_object_deletion

            maybe_reverse_sync_object_deletion(inventory)

            # Should not make any requests when reverse sync disabled
            mock_request.assert_not_called()


@pytest.mark.django_db
def test_sync_multiple_resource_types(inventory, organization, enable_reverse_sync):  # noqa: F811
    """
    Test that sync works for different resource types (inventories, organizations, etc.).
    This verifies the generic nature of the sync mechanism.
    """
    with enable_reverse_sync():
        with override_settings(RESOURCE_SERVER={'URL': 'http://gateway.example.com', 'SECRET_KEY': 'test-secret'}):
            with patch('ansible_base.resource_registry.rest_client.ResourceAPIClient._make_request') as mock_request:
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {'deleted_count': 1}
                mock_request.return_value = mock_response

                from ansible_base.rbac.sync import maybe_reverse_sync_object_deletion

                # Test inventory sync
                maybe_reverse_sync_object_deletion(inventory)

                # Test organization sync
                maybe_reverse_sync_object_deletion(organization)

                # Should have made 2 requests
                assert mock_request.call_count == 2

                # Verify different resource types in requests
                calls = mock_request.call_args_list

                inv_call_data = calls[0][1]['data']  # data from first call kwargs
                org_call_data = calls[1][1]['data']  # data from second call kwargs

                assert 'inventory' in inv_call_data['resource_type']
                assert 'organization' in org_call_data['resource_type']


@pytest.mark.django_db
def test_sync_service_token_authentication(inventory, enable_reverse_sync):  # noqa: F811
    """
    Test that sync uses the ResourceAPIClient authentication framework correctly.
    This verifies the authentication mechanism is set up for the new endpoint.
    """
    with enable_reverse_sync():
        with override_settings(RESOURCE_SERVER={'URL': 'http://gateway.example.com', 'SECRET_KEY': 'test-secret-key'}):
            with patch('ansible_base.resource_registry.rest_client.ResourceAPIClient._make_request') as mock_request:
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {'deleted_count': 0}
                mock_request.return_value = mock_response

                from ansible_base.rbac.sync import maybe_reverse_sync_object_deletion

                maybe_reverse_sync_object_deletion(inventory)

                # Verify that sync attempted to make a request through the ResourceAPIClient
                assert mock_request.called
                call_args = mock_request.call_args
                call_positional = call_args[0]  # Positional arguments
                call_kwargs = call_args[1]  # Keyword arguments

                # Verify the request was properly structured for the object-delete endpoint
                assert call_positional[0] == 'post'  # method
                assert 'object-delete' in call_positional[1]  # path

                # Verify the request has the expected data format
                data = call_kwargs['data']
                assert 'resource_type' in data
                assert 'resource_pk' in data
                assert data['resource_pk'] == str(inventory.pk)

                # ResourceAPIClient handles authentication internally - we just need to verify
                # it went through the proper client methods that would add auth headers


@pytest.mark.django_db
def test_sync_request_timeout_handling(inventory, enable_reverse_sync):  # noqa: F811
    """
    Test that sync handles request timeouts gracefully.
    """
    with enable_reverse_sync():
        with override_settings(RESOURCE_SERVER={'URL': 'http://gateway.example.com', 'SECRET_KEY': 'test-secret'}):
            with patch('ansible_base.resource_registry.rest_client.ResourceAPIClient._make_request') as mock_request:
                # Simulate timeout
                import requests

                mock_request.side_effect = requests.exceptions.Timeout("Request timed out")

                from ansible_base.rbac.sync import maybe_reverse_sync_object_deletion

                # Should handle timeout without raising
                try:
                    maybe_reverse_sync_object_deletion(inventory)
                except requests.exceptions.Timeout:
                    pytest.fail("Sync should handle timeouts gracefully")


@pytest.mark.django_db
def test_sync_url_construction(inventory, enable_reverse_sync):  # noqa: F811
    """
    Test that the sync URL is constructed correctly for the Gateway service.
    This verifies the endpoint routing works properly.
    """
    with enable_reverse_sync():
        with override_settings(RESOURCE_SERVER={'URL': 'http://gateway.example.com:8080', 'SECRET_KEY': 'test-secret'}):
            with patch('ansible_base.resource_registry.rest_client.ResourceAPIClient._make_request') as mock_request:
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {'deleted_count': 0}
                mock_request.return_value = mock_response

                from ansible_base.rbac.sync import maybe_reverse_sync_object_deletion

                maybe_reverse_sync_object_deletion(inventory)

                # Verify URL construction
                call_args = mock_request.call_args
                call_positional = call_args[0]  # Positional arguments

                # Should be a POST request to the create endpoint
                assert call_positional[0] == 'post'  # method

                # Should include object-delete endpoint
                assert 'object-delete' in call_positional[1]  # path
