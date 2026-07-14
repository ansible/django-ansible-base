"""
Unit tests for AAP-51985: Cross-Service RBAC Cleanup for Object Deletion

Tests the enhanced delete() wrapping and rbac_post_delete_remove_object_roles:
1. delete() is wrapped with defer_rbac_cache() via connect_rbac_signals
2. For parent models, _bulk_pre_cascade_rbac_cleanup runs pre-cascade cleanup
3. For leaf models, the post_delete signal handler runs but defers sync
4. Cross-service sync uses the batch API in the deferred path

To exercise the signal handler's direct (non-deferred) sync path, patch
``defer_rbac_cache`` with ``nullcontext`` so the handler runs without deferral.
"""

from contextlib import nullcontext
from unittest.mock import MagicMock, patch

import pytest
from django.test.utils import override_settings

from ansible_base.rbac.models import ObjectRole
from ansible_base.rbac.permission_registry import permission_registry
from test_app.models import Inventory

# Make reverse sync fixtures available
from test_app.tests.resource_registry.conftest import enable_reverse_sync  # noqa: F401


@pytest.mark.django_db
def test_bulk_delete_return_value_optimization(inventory, rando, inv_rd):
    """
    Test that deleting an object with role assignments correctly cleans up
    those ObjectRoles.  The wrapped delete() with defer_rbac_cache handles
    cleanup efficiently via bulk operations.
    """
    inv_rd.give_permission(rando, inventory)
    inv_pk = inventory.pk
    ct = permission_registry.content_type_model.objects.get_for_model(Inventory)

    # Verify assignments exist before deletion
    assert ObjectRole.objects.filter(content_type=ct, object_id=inv_pk).exists()

    inventory.delete()

    # Verify object roles are cleaned up
    assert not ObjectRole.objects.filter(content_type=ct, object_id=inv_pk).exists()
    assert not Inventory.objects.filter(pk=inv_pk).exists()


@pytest.mark.django_db
def test_no_sync_when_no_object_assignments(inventory):
    """
    Test performance optimization: when no object-level assignments exist,
    sync should be skipped entirely (fast path for 90%+ deletions).
    Uses nullcontext to bypass defer_rbac_cache so the signal handler's
    direct sync path is exercised.
    """
    # No role assignments created - inventory has no object-level permissions
    with patch('ansible_base.rbac.triggers.defer_rbac_cache', nullcontext):
        with patch('ansible_base.rbac.sync.maybe_reverse_sync_object_deletion') as mock_sync:
            inventory.delete()

            # Verify sync was NOT called because no assignments existed
            mock_sync.assert_not_called()


@pytest.mark.django_db
def test_sync_triggered_with_object_assignments(inventory, rando, inv_rd, enable_reverse_sync):  # noqa: F811
    """
    Test that sync is triggered when object-level assignments existed.
    Uses nullcontext to bypass defer_rbac_cache so the signal handler's
    direct sync path is exercised.
    """
    inv_rd.give_permission(rando, inventory)

    with enable_reverse_sync():
        with override_settings(RESOURCE_SERVER={'URL': 'http://example.invalid', 'SECRET_KEY': 'test-secret-key'}):
            with patch('ansible_base.rbac.triggers.defer_rbac_cache', nullcontext):
                with patch('ansible_base.resource_registry.rest_client.ResourceAPIClient._make_request') as mock_make_request:
                    mock_response = MagicMock()
                    mock_response.status_code = 200
                    mock_response.json.return_value = {
                        'message': 'Deleted 1 role assignments',
                        'deleted_count': 1,
                    }
                    mock_make_request.return_value = mock_response

                    inventory.delete()

                    assert mock_make_request.called, "Cross-service sync should have been attempted"


@pytest.mark.django_db
def test_team_deletion_special_case(team, rando, member_rd):
    """
    Test team deletion correctly cleans up team-specific object roles,
    including orphaned roles from team membership.
    """
    member_rd.give_permission(rando, team)
    team_pk = team.pk
    team_cls = type(team)
    ct = permission_registry.content_type_model.objects.get_for_model(team_cls)

    # Verify assignments exist before deletion
    assert ObjectRole.objects.filter(content_type=ct, object_id=team_pk).exists()

    team.delete()

    # Verify object roles for this team are cleaned up
    assert not ObjectRole.objects.filter(content_type=ct, object_id=team_pk).exists()


@pytest.mark.django_db
def test_sync_failure_graceful_handling(inventory, rando, inv_rd):
    """
    Test that local deletion continues even if cross-service sync fails.
    Uses nullcontext to exercise the signal handler's direct sync path.
    """
    inv_rd.give_permission(rando, inventory)

    with patch('ansible_base.rbac.triggers.defer_rbac_cache', nullcontext):
        with patch('ansible_base.rbac.sync.maybe_reverse_sync_object_deletion') as mock_sync:
            mock_sync.side_effect = Exception("Gateway unavailable")

            with patch('ansible_base.rbac.triggers.logger') as mock_logger:
                inventory.delete()

                mock_sync.assert_called_once()
                mock_logger.exception.assert_called_once()
                assert not Inventory.objects.filter(id=inventory.id).exists()


@pytest.mark.django_db
def test_sync_import_failure_handling(inventory, rando, inv_rd):
    """
    Test graceful handling when sync module import fails.
    Uses nullcontext to exercise the signal handler's direct sync path.
    """
    inv_rd.give_permission(rando, inventory)

    with patch('ansible_base.rbac.triggers.defer_rbac_cache', nullcontext):
        with patch(
            'ansible_base.rbac.sync.maybe_reverse_sync_object_deletion',
            side_effect=ImportError("No module named 'ansible_base'"),
        ):
            with patch('ansible_base.rbac.triggers.logger') as mock_logger:
                inventory.delete()

                mock_logger.exception.assert_called_once()
                assert not Inventory.objects.filter(id=inventory.id).exists()


@pytest.mark.django_db
def test_multiple_assignment_types_bulk_cleanup(inventory, rando, team, inv_rd):
    """
    Test that both user and team assignments are handled during deletion.
    Verifies the efficiency of the deferred cleanup path.
    """
    inv_rd.give_permission(rando, inventory)
    inv_rd.give_permission(team, inventory)
    inv_pk = inventory.pk
    ct = permission_registry.content_type_model.objects.get_for_model(Inventory)

    # Verify assignments exist (user and team share the same ObjectRole
    # since they use the same role definition)
    assert ObjectRole.objects.filter(content_type=ct, object_id=inv_pk).count() >= 1

    inventory.delete()

    # Verify all object roles are cleaned up
    assert not ObjectRole.objects.filter(content_type=ct, object_id=inv_pk).exists()
    assert not Inventory.objects.filter(pk=inv_pk).exists()
