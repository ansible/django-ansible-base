"""
Tests for bulk_remove_permissions chunking (AAP-90162).

These tests verify that bulk removal with forced small batch sizes works correctly,
ensuring the chunking logic handles splits properly without losing data or correctness.
"""

import pytest
from unittest.mock import patch

import ansible_base.rbac.pipeline as rbac_pipeline
from ansible_base.rbac import permission_registry
from ansible_base.rbac.models import RoleDefinition, RoleTeamAssignment, RoleUserAssignment
from ansible_base.rbac.pipeline import bulk_give_permissions, bulk_remove_permissions
from test_app.models import Inventory, Organization, User


@pytest.mark.django_db
def test_bulk_remove_permissions_with_forced_small_chunks():
    """
    Verify that bulk_remove_permissions works correctly when chunked into small batches.

    Passes fetch_batch_size=5 so 36 triples require 8 fetch batches, exercising the
    chunking path without creating hundreds of rows for CI.
    """
    org = Organization.objects.create(name='test_org')
    inventories = [Inventory.objects.create(name=f'inv_{i}', organization=org) for i in range(6)]
    users = [User.objects.create(username=f'user_{i}') for i in range(6)]

    inv_change_rd = RoleDefinition.objects.create_from_permissions(
        name='Inventory Change Role',
        permissions=['change_inventory', 'view_inventory'],
        content_type=permission_registry.content_type_model.objects.get_for_model(Inventory),
    )

    permission_triples = [(inv_change_rd, user, inv) for user in users for inv in inventories]
    assert len(permission_triples) == 36

    created_assignments = bulk_give_permissions(user_permissions=permission_triples)
    assert len(created_assignments) == 36
    assert RoleUserAssignment.objects.filter(role_definition=inv_change_rd).count() == 36

    bulk_remove_permissions(user_permissions=permission_triples, fetch_batch_size=5)

    assert RoleUserAssignment.objects.filter(role_definition=inv_change_rd).count() == 0
    assert RoleTeamAssignment.objects.filter(role_definition=inv_change_rd).count() == 0


@pytest.mark.django_db
def test_resolved_assignment_equality_ignores_parent_reference():
    """
    ResolvedAssignment equality is defined by (actor, role_definition, content_type, object_id).
    Two instances with the same uniqueness key but different parent_reference must compare equal
    so dict.fromkeys() collapses them before chunking — otherwise the same DB row is fetched
    from multiple batches with batch_size=1 and returned twice.
    """
    from ansible_base.rbac.pipeline import ResolvedAssignment, _find_assignments_chunked, _lookup_object_roles

    org = Organization.objects.create(name='test_org')
    inv = Inventory.objects.create(name='inv', organization=org)
    user = User.objects.create(username='user')

    rd = RoleDefinition.objects.create_from_permissions(
        name='Inventory Change Role',
        permissions=['change_inventory', 'view_inventory'],
        content_type=permission_registry.content_type_model.objects.get_for_model(Inventory),
    )
    bulk_give_permissions(user_permissions=[(rd, user, inv)])

    ct = permission_registry.content_type_model.objects.get_for_model(Inventory)
    object_id = str(inv.pk)

    # Artificially construct two ResolvedAssignments with the same DB uniqueness key but
    # differing parent_reference (as would occur with RemoteObject inputs).
    # The old NamedTuple approach would not deduplicate these; the class-level __eq__/__hash__
    # ensures dict.fromkeys() collapses them to one before chunking.
    ra1 = ResolvedAssignment(rd, user, ct, object_id, 'ref_a')
    ra2 = ResolvedAssignment(rd, user, ct, object_id, 'ref_b')
    assert ra1 == ra2, "same DB uniqueness key must compare equal regardless of parent_reference"

    resolved = [ra1, ra2]
    lookup = _lookup_object_roles(resolved)
    results = _find_assignments_chunked(resolved, lookup, RoleUserAssignment, 'user_id', batch_size=1)

    assert len(results) == 1, f"Expected 1 result after dedup, got {len(results)}"


@pytest.mark.django_db
def test_bulk_remove_permissions_dedup_across_chunks():
    """
    Verify that duplicate triples are deduplicated before chunking so the same DB row is
    never fetched twice and remove_assignments receives exactly one copy.

    With fetch_batch_size=1, five identical triples would each become their own batch if not
    deduped first; _find_assignments_chunked collapses them to one unique triple up front.
    """
    org = Organization.objects.create(name='test_org')
    inv = Inventory.objects.create(name='inv', organization=org)
    user = User.objects.create(username='user')

    rd = RoleDefinition.objects.create_from_permissions(
        name='Inventory Change Role',
        permissions=['change_inventory', 'view_inventory'],
        content_type=permission_registry.content_type_model.objects.get_for_model(Inventory),
    )

    bulk_give_permissions(user_permissions=[(rd, user, inv)])
    assert RoleUserAssignment.objects.filter(role_definition=rd).count() == 1

    duplicated_triples = [(rd, user, inv)] * 5

    with patch('ansible_base.rbac.pipeline.remove_assignments',
               wraps=rbac_pipeline.remove_assignments) as mock_ra:
        bulk_remove_permissions(user_permissions=duplicated_triples, fetch_batch_size=1)

    received = mock_ra.call_args.kwargs['user_assignments']
    assert len(received) == 1, f"Expected 1 deduplicated assignment, got {len(received)}"
    assert RoleUserAssignment.objects.filter(role_definition=rd).count() == 0


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
