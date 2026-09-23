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
    # Create test data
    org = Organization.objects.create(name='test_org')
    # Create 40 inventories and 40 users to get 1600 triples (will chunk at 999)
    inventories = [Inventory.objects.create(name=f'inv_{i}', organization=org) for i in range(40)]
    users = [User.objects.create(username=f'user_{i}') for i in range(40)]

    # Create a role definition
    inv_change_rd = RoleDefinition.objects.create_from_permissions(
        name='Inventory Change Role',
        permissions=['change_inventory', 'view_inventory'],
        content_type=permission_registry.content_type_model.objects.get_for_model(Inventory),
    )

    # Create 1600 assignments (40 * 40)
    permission_triples = [(inv_change_rd, user, inv) for user in users for inv in inventories]
    assert len(permission_triples) == 1600

    # Give all permissions
    created_assignments = bulk_give_permissions(user_permissions=permission_triples)
    assert len(created_assignments) == 1600
    assert RoleUserAssignment.objects.filter(role_definition=inv_change_rd).count() == 1600

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
    inventories = [Inventory.objects.create(name=f'inv_{i}', organization=org) for i in range(30)]
    users = [User.objects.create(username=f'user_{i}') for i in range(30)]

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

    # Create ~1200 mixed assignments (global + object-scoped)
    permission_triples = []

    # 30 global assignments (user -> global role, no object)
    for user in users:
        permission_triples.append((global_rd, user, None))

    # 900 object-scoped assignments (30 users * 30 inventories)
    for user in users:
        for inv in inventories:
            permission_triples.append((inv_change_rd, user, inv))

    assert len(permission_triples) == 930  # 30 + 900

    # Give all permissions
    created_assignments = bulk_give_permissions(user_permissions=permission_triples)
    assert len(created_assignments) == 930

    # Verify they exist before removal
    assert RoleUserAssignment.objects.filter(role_definition=global_rd).count() == 30
    assert RoleUserAssignment.objects.filter(role_definition=inv_change_rd).count() == 900

    # Remove all assignments
    bulk_remove_permissions(user_permissions=permission_triples)

    # Verify all were removed
    assert RoleUserAssignment.objects.filter(role_definition=global_rd).count() == 0
    assert RoleUserAssignment.objects.filter(role_definition=inv_change_rd).count() == 0


@pytest.mark.django_db
def test_bulk_remove_permissions_empty_input():
    """Verify that empty input is handled correctly."""
    bulk_remove_permissions()  # Should not raise
    assert True
