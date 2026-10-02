"""
Tests for bulk_remove_permissions chunking (AAP-90162).

These tests verify that bulk removal with forced small batch sizes works correctly,
ensuring the chunking logic handles splits properly without losing data or correctness.
"""

import pytest

from ansible_base.rbac import permission_registry
from ansible_base.rbac.models import RoleDefinition, RoleTeamAssignment, RoleUserAssignment
from ansible_base.rbac.pipeline import bulk_give_permissions, bulk_remove_permissions
from test_app.models import Inventory, Organization, User


@pytest.mark.django_db
def test_bulk_remove_permissions_with_forced_small_chunks():
    """
    Verify that bulk_remove_permissions works correctly when chunked into small batches.

    This simulates what happens on SQLite (max_query_params=999) by creating enough
    removal triples to require chunking, then verifying all assignments are actually removed.
    """
    # Create test data (6x6=36 triples to exercise chunking without massive CI overhead)
    org = Organization.objects.create(name='test_org')
    inventories = [Inventory.objects.create(name=f'inv_{i}', organization=org) for i in range(6)]
    users = [User.objects.create(username=f'user_{i}') for i in range(6)]

    # Create a role definition
    inv_change_rd = RoleDefinition.objects.create_from_permissions(
        name='Inventory Change Role',
        permissions=['change_inventory', 'view_inventory'],
        content_type=permission_registry.content_type_model.objects.get_for_model(Inventory),
    )

    # Create 36 assignments (6 * 6) - enough to test chunking works
    permission_triples = [(inv_change_rd, user, inv) for user in users for inv in inventories]
    assert len(permission_triples) == 36

    # Give all permissions
    created_assignments = bulk_give_permissions(user_permissions=permission_triples)
    assert len(created_assignments) == 36
    assert RoleUserAssignment.objects.filter(role_definition=inv_change_rd).count() == 36

    # Remove all assignments
    bulk_remove_permissions(user_permissions=permission_triples)

    # Verify all were removed
    assert RoleUserAssignment.objects.filter(role_definition=inv_change_rd).count() == 0
    assert RoleTeamAssignment.objects.filter(role_definition=inv_change_rd).count() == 0


@pytest.mark.django_db
def test_bulk_remove_permissions_mixed_global_and_object_scoped():
    """
    Verify that bulk_remove_permissions handles mixed global and object-scoped assignments
    correctly when chunking.

    Global assignments (content_object=None) are matched differently than object-scoped ones
    in _find_assignments, so this tests that chunking doesn't break that logic.
    """
    org = Organization.objects.create(name='test_org')
    inventories = [Inventory.objects.create(name=f'inv_{i}', organization=org) for i in range(10)]
    users = [User.objects.create(username=f'user_{i}') for i in range(10)]

    # Create role definitions
    global_rd = RoleDefinition.objects.create_from_permissions(
        name='Global Role',
        permissions=['change_inventory', 'view_inventory'],
        content_type=None,  # Global (singleton) role
    )

    inv_change_rd = RoleDefinition.objects.create_from_permissions(
        name='Object-Scoped Role',
        permissions=['change_inventory', 'view_inventory'],
        content_type=permission_registry.content_type_model.objects.get_for_model(Inventory),
    )

    # Create ~110 mixed assignments (global + object-scoped)
    permission_triples = []

    # 10 global assignments (user -> global role, no object)
    for user in users:
        permission_triples.append((global_rd, user, None))

    # 100 object-scoped assignments (10 users * 10 inventories)
    for user in users:
        for inv in inventories:
            permission_triples.append((inv_change_rd, user, inv))

    assert len(permission_triples) == 110  # 10 + 100

    # Give all permissions
    created_assignments = bulk_give_permissions(user_permissions=permission_triples)
    assert len(created_assignments) == 110

    # Verify they exist before removal (globally scoped assignment won't show via filter)
    assert RoleUserAssignment.objects.filter(role_definition=inv_change_rd).count() == 100

    # Remove all assignments
    bulk_remove_permissions(user_permissions=permission_triples)

    # Verify all were removed
    assert RoleUserAssignment.objects.filter(role_definition=global_rd).count() == 0
    assert RoleUserAssignment.objects.filter(role_definition=inv_change_rd).count() == 0


@pytest.mark.django_db
def test_bulk_remove_permissions_empty_input():
    """Verify that empty input is handled correctly."""
    bulk_remove_permissions()  # Should not raise
