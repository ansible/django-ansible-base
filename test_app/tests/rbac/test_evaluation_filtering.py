# claude-opus-4-6
"""Tests for needed_cache_updates and the create signal that narrows the recompute to the new object."""

import pytest

from ansible_base.rbac.models import ObjectRole
from test_app.models import Inventory


@pytest.mark.django_db
def test_unfiltered_still_works(rando, organization, org_inv_rd):
    """Calling needed_cache_updates without filtering should still work correctly."""
    Inventory.objects.create(name='inv1', organization=organization)

    org_inv_rd.give_permission(rando, organization)
    org_role = ObjectRole.objects.get(
        role_definition=org_inv_rd,
        object_id=organization.pk,
    )

    to_delete, to_add = org_role.needed_cache_updates()
    assert len(to_add) == 0
    assert len(to_delete) == 0


@pytest.mark.django_db
def test_signal_passes_filter_on_create(rando, organization, org_inv_rd):
    """Creating an inventory should trigger the optimized path and produce correct permissions."""
    org_inv_rd.give_permission(rando, organization)

    inv = Inventory.objects.create(name='signal-test-inv', organization=organization)

    # Verify the signal-driven update created the right evaluations
    assert rando.has_obj_perm(inv, 'change_inventory')
    assert rando.has_obj_perm(inv, 'view_inventory')
