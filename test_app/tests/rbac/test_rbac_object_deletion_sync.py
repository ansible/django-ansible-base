"""
Unit tests for AAP-51985: Cross-Service RBAC Cleanup for Object Deletion

Tests the enhanced rbac_post_delete_remove_object_roles function that:
1. Uses bulk delete return values instead of inefficient .exists() queries
2. Conditionally triggers cross-service sync only when object assignments existed
3. Handles both regular resource deletion and team deletion cases
"""

from unittest.mock import MagicMock, patch

import pytest
from django.test.utils import override_settings

from test_app.models import Inventory

# Make reverse sync fixtures available
from test_app.tests.resource_registry.conftest import enable_reverse_sync  # noqa: F401


@pytest.mark.django_db
def test_bulk_delete_return_value_optimization(inventory, rando, inv_rd):
    """
    Test that rbac_post_delete_remove_object_roles uses bulk delete return values
    instead of .exists() queries for performance optimization.
    """
    # Create role assignment so deletion will find something
    inv_rd.give_permission(rando, inventory)

    # Mock ObjectRole.objects.filter().delete() to verify return value is used
    with patch('ansible_base.rbac.models.ObjectRole.objects.filter') as mock_filter:
        mock_queryset = mock_filter.return_value
        # Simulate bulk delete returning (count, details)
        mock_queryset.delete.return_value = (2, {'test_app.ObjectRole': 2})

        # Mock the sync function to verify it gets called
        with patch('ansible_base.rbac.sync.maybe_reverse_sync_object_deletion') as mock_sync:
            # Delete the inventory - this should trigger our enhanced signal
            inventory.delete()

            # Verify delete was called (our code uses the return value)
            mock_queryset.delete.assert_called_once()

            # Verify sync was called because deleted_count > 0
            mock_sync.assert_called_once_with(inventory)


@pytest.mark.django_db
def test_no_sync_when_no_object_assignments(inventory):
    """
    Test performance optimization: when no object-level assignments exist,
    sync should be skipped entirely (fast path for 90%+ deletions).
    """
    # No role assignments created - inventory has no object-level permissions

    with patch('ansible_base.rbac.models.ObjectRole.objects.filter') as mock_filter:
        mock_queryset = mock_filter.return_value
        # Simulate bulk delete finding nothing to delete
        mock_queryset.delete.return_value = (0, {})

        with patch('ansible_base.rbac.sync.maybe_reverse_sync_object_deletion') as mock_sync:
            # Delete inventory
            inventory.delete()

            # Verify sync was NOT called because deleted_count == 0
            mock_sync.assert_not_called()


@pytest.mark.django_db
def test_sync_triggered_with_object_assignments(inventory, rando, inv_rd, enable_reverse_sync):  # noqa: F811
    """
    Test that sync is triggered when object-level assignments existed.
    This is the rare case where cross-service cleanup is needed.
    """
    # Create role assignment to simulate object-level permissions
    inv_rd.give_permission(rando, inventory)

    with enable_reverse_sync():
        with override_settings(RESOURCE_SERVER={'URL': 'http://example.invalid', 'SECRET_KEY': 'test-secret-key'}):
            with patch('ansible_base.resource_registry.rest_client.ResourceAPIClient._make_request') as mock_make_request:
                # Mock successful sync response
                mock_response = MagicMock()
                mock_response.status_code = 200
                mock_response.json.return_value = {'message': 'Deleted 1 role assignments for test_app.inventory 123', 'deleted_count': 1}
                mock_make_request.return_value = mock_response

                # Delete inventory - should trigger sync
                inventory.delete()

                # Verify sync API was called
                assert mock_make_request.called, "Cross-service sync should have been attempted"


@pytest.mark.django_db
def test_team_deletion_special_case(team, rando, member_rd):
    """
    Test team deletion behavior which has additional complexity.
    Teams trigger extra cleanup for orphaned object roles.
    """
    # Give user team membership
    member_rd.give_permission(rando, team)

    # Mock the team-specific orphaned role cleanup
    with patch('ansible_base.rbac.models.ObjectRole.objects.filter') as mock_filter:
        mock_queryset = mock_filter.return_value

        # Simulate team deletion finding object assignments
        mock_queryset.delete.return_value = (2, {'test_app.ObjectRole': 2})

        with patch('ansible_base.rbac.sync.maybe_reverse_sync_object_deletion') as mock_sync:
            # Delete team
            team.delete()

            # Verify sync was called because team deletion found object assignments
            mock_sync.assert_called_once_with(team)


@pytest.mark.django_db
def test_sync_failure_graceful_handling(inventory, rando, inv_rd):
    """
    Test that local deletion continues even if cross-service sync fails.
    This ensures robust behavior when Gateway is unavailable.
    """
    # Create assignment
    inv_rd.give_permission(rando, inventory)

    # Mock sync to raise exception
    with patch('ansible_base.rbac.sync.maybe_reverse_sync_object_deletion') as mock_sync:
        mock_sync.side_effect = Exception("Gateway unavailable")

        # Mock logger to verify exception is logged
        with patch('ansible_base.rbac.triggers.logger') as mock_logger:
            # Delete should succeed despite sync failure
            inventory.delete()

            # Verify sync was attempted
            mock_sync.assert_called_once()

            # Verify exception was logged
            mock_logger.exception.assert_called_once()

            # Verify local cleanup still happened (inventory is gone)
            assert not Inventory.objects.filter(id=inventory.id).exists()


@pytest.mark.django_db
def test_sync_import_failure_handling(inventory, rando, inv_rd):
    """
    Test graceful handling when sync module import fails.
    This addresses the case where django-ansible-base is missing from Controller.
    """
    # Create assignment to trigger sync path
    inv_rd.give_permission(rando, inventory)

    # Mock import failure for the sync module specifically - patch where it's imported in triggers.py
    with patch('ansible_base.rbac.sync.maybe_reverse_sync_object_deletion', side_effect=ImportError("No module named 'ansible_base'")):

        with patch('ansible_base.rbac.triggers.logger') as mock_logger:
            # Delete should succeed despite import failure
            inventory.delete()

            # Verify exception was logged
            mock_logger.exception.assert_called_once()

            # Verify local deletion still succeeded
            assert not Inventory.objects.filter(id=inventory.id).exists()


@pytest.mark.django_db
def test_multiple_assignment_types_bulk_cleanup(inventory, rando, team, inv_rd):
    """
    Test that both user and team assignments are handled in bulk cleanup.
    This verifies the efficiency of single API call for all assignment types.
    """
    # Create both user and team assignments on the same inventory
    inv_rd.give_permission(rando, inventory)
    inv_rd.give_permission(team, inventory)

    with patch('ansible_base.rbac.models.ObjectRole.objects.filter') as mock_filter:
        mock_queryset = mock_filter.return_value
        # Simulate finding multiple assignments (both user and team)
        mock_queryset.delete.return_value = (3, {'test_app.RoleUserAssignment': 1, 'test_app.RoleTeamAssignment': 1, 'test_app.ObjectRole': 1})

        with patch('ansible_base.rbac.sync.maybe_reverse_sync_object_deletion') as mock_sync:
            inventory.delete()

            # Verify sync was called once (bulk operation)
            mock_sync.assert_called_once_with(inventory)
