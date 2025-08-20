from unittest.mock import MagicMock, patch

import pytest

from ansible_base.rbac.models import RoleDefinition
from ansible_base.rbac.remote import RemoteObject
from ansible_base.resource_registry.rest_client import ResourceAPIClient
from test_app.models import Inventory, User

pytestmark = pytest.mark.django_db


class TestRestClientRemoteObjects:
    """Test ResourceAPIClient handling of RemoteObject instances."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock ResourceAPIClient for testing."""
        client = ResourceAPIClient("http://test.com", "/api/v1/", jwt_user_id="test-user")
        return client

    @pytest.fixture
    def mock_role_definition(self):
        """Create a mock role definition."""
        rd = MagicMock(spec=RoleDefinition)
        rd.name = "test-role"
        return rd

    @pytest.fixture
    def mock_user(self):
        """Create a mock user with resource."""
        user = MagicMock(spec=User)
        user._meta.model_name = "user"
        user.resource.ansible_id = "test-user-id"
        return user

    def test_sync_unassignment_with_remote_object(self, mock_client, mock_role_definition, mock_user, foo_type):
        """Test that sync_unassignment handles RemoteObject instances correctly."""
        # Create a RemoteObject
        remote_obj = RemoteObject(content_type=foo_type, object_id=42)

        # Mock the _sync_assignment method
        with patch.object(mock_client, '_sync_assignment') as mock_sync:
            mock_client.sync_unassignment(mock_role_definition, mock_user, remote_obj)

            # Verify _sync_assignment was called with correct data
            mock_sync.assert_called_once()
            call_args, call_kwargs = mock_sync.call_args
            data_dict = call_args[0]  # First positional argument (data dict)
            giving_flag = call_kwargs.get('giving', True)  # Should be False for unassignment

            assert data_dict['role_definition'] == "test-role"
            assert data_dict['user_ansible_id'] == "test-user-id"
            assert data_dict['object_id'] == '42'  # RemoteObject.object_id converted to string
            assert giving_flag is False  # Should be False for unassignment

    def test_sync_unassignment_with_none_content_object(self, mock_client, mock_role_definition, mock_user):
        """Test that sync_unassignment handles None content_object correctly."""
        with patch.object(mock_client, '_sync_assignment') as mock_sync:
            mock_client.sync_unassignment(mock_role_definition, mock_user, None)

            # Verify _sync_assignment was called with object_id as None
            mock_sync.assert_called_once()
            call_args, call_kwargs = mock_sync.call_args
            data_dict = call_args[0]

            assert data_dict['role_definition'] == "test-role"
            assert data_dict['user_ansible_id'] == "test-user-id"
            assert data_dict['object_id'] is None

    def test_sync_unassignment_with_regular_model(self, mock_client, mock_role_definition, mock_user):
        """Test that sync_unassignment handles regular Django models correctly."""
        # Create a mock inventory object
        inventory = MagicMock(spec=Inventory)

        with patch.object(mock_client, '_sync_assignment') as mock_sync:
            # Mock the content type lookup
            with patch('ansible_base.resource_registry.rest_client.apps.get_model') as mock_get_model:
                mock_ct_cls = MagicMock()
                mock_ct = MagicMock()
                mock_ct.service = "test-service"
                mock_ct.api_slug = "test.inventory"
                mock_ct_cls.objects.get_for_model.return_value = mock_ct
                mock_get_model.return_value = mock_ct_cls

                mock_client.sync_unassignment(mock_role_definition, mock_user, inventory)

                # Verify get_for_model was called to get content type
                mock_ct_cls.objects.get_for_model.assert_called_once_with(inventory)

                # Verify _sync_assignment was called
                mock_sync.assert_called_once()
                call_args, _ = mock_sync.call_args
                data_dict = call_args[0]

                assert data_dict['role_definition'] == "test-role"
                assert data_dict['user_ansible_id'] == "test-user-id"

    def test_sync_unassignment_with_team_actor(self, mock_client, mock_role_definition, foo_type):
        """Test that sync_unassignment works with team actors."""
        # Create a mock team
        team = MagicMock()
        team._meta.model_name = "team"
        team.resource.ansible_id = "test-team-id"

        remote_obj = RemoteObject(content_type=foo_type, object_id=42)

        with patch.object(mock_client, '_sync_assignment') as mock_sync:
            mock_client.sync_unassignment(mock_role_definition, team, remote_obj)

            # Verify _sync_assignment was called with team_ansible_id
            mock_sync.assert_called_once()
            call_args, _ = mock_sync.call_args
            data_dict = call_args[0]

            assert data_dict['role_definition'] == "test-role"
            assert data_dict['team_ansible_id'] == "test-team-id"
            assert data_dict['object_id'] == '42'

    def test_isinstance_check_for_remote_object(self, foo_type):
        """Test that isinstance check correctly identifies RemoteObject instances."""
        remote_obj = RemoteObject(content_type=foo_type, object_id=42)
        regular_obj = MagicMock(spec=Inventory)

        # Test that RemoteObject is correctly identified
        assert isinstance(remote_obj, RemoteObject)
        assert not isinstance(regular_obj, RemoteObject)

        # Test that object_id is accessible
        assert remote_obj.object_id == 42
