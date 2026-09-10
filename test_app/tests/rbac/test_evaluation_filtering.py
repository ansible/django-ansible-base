# claude-opus-4-6
"""Tests for the object_pk/object_ct_id filtering optimization in needed_cache_updates."""

from unittest.mock import patch

import pytest

from ansible_base.rbac.models import ObjectRole, RoleEvaluation
from ansible_base.rbac.permission_registry import permission_registry
from ansible_base.rbac.prefetch import TypesPrefetch
from test_app.models import Inventory


def _inv_ct_id():
    return permission_registry.content_type_model.objects.get_for_model(Inventory).id


@pytest.mark.django_db
def test_needed_cache_updates_filtered_returns_only_target_object(rando, organization, org_inv_rd):
    """When object_pk and object_ct_id are given, needed_cache_updates
    should only return evaluation entries for that specific object."""
    Inventory.objects.create(name='inv1', organization=organization)
    Inventory.objects.create(name='inv2', organization=organization)

    org_inv_rd.give_permission(rando, organization)
    org_role = ObjectRole.objects.get(
        role_definition=org_inv_rd,
        object_id=organization.pk,
    )

    # Full recompute should find nothing to change (already up to date)
    to_delete, to_add = org_role.needed_cache_updates()
    assert len(to_add) == 0
    assert len(to_delete) == 0

    # Create a new inventory - the signal handles it, but let's test the method directly
    inv3 = Inventory.objects.create(name='inv3', organization=organization)

    # Delete the evaluations for inv3 so needed_cache_updates has something to find
    RoleEvaluation.objects.filter(role=org_role, object_id=inv3.pk).delete()

    # Filtered call should only report adds for inv3
    to_delete, to_add = org_role.needed_cache_updates(object_pk=inv3.pk, object_ct_id=_inv_ct_id())
    assert len(to_delete) == 0
    assert len(to_add) > 0
    assert all(entry.object_id == inv3.pk for entry in to_add)


@pytest.mark.django_db
def test_filtered_evaluation_count_is_small(rando, organization, org_inv_rd):
    """With many inventories, filtered needed_cache_updates should log a small
    evaluation count, not the total for the whole org role."""
    for i in range(200):
        Inventory.objects.create(name=f'inv-{i}', organization=organization)

    org_inv_rd.give_permission(rando, organization)
    org_role = ObjectRole.objects.get(
        role_definition=org_inv_rd,
        object_id=organization.pk,
    )

    # Total evaluations for this role should be large (200 inventories * permissions + org perms)
    total_evals = org_role.permission_partials.count()
    assert total_evals > 200

    # Create one more inventory and delete its evals to simulate needing an update
    new_inv = Inventory.objects.create(name='inv-new', organization=organization)
    RoleEvaluation.objects.filter(role=org_role, object_id=new_inv.pk).delete()

    logged = {}
    with patch.object(ObjectRole, '_log_partials_count', side_effect=lambda count, label, *a: logged.update({label: count})):
        org_role.needed_cache_updates(object_pk=new_inv.pk, object_ct_id=_inv_ct_id())

    # The existing evaluation count should be 0 since we deleted them
    existing_label = f'existing evaluation (object_pk={new_inv.pk})'
    assert logged[existing_label] == 0
    # Expected evaluations should be scoped to just the one inventory's permissions
    # org_inv_rd grants change_inventory + view_inventory, so we expect a small number
    assert logged['expected evaluation'] < total_evals
    assert logged['expected evaluation'] <= 10


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


@pytest.mark.django_db
def test_filtered_evaluations_fewer_than_unfiltered(rando, organization, org_inv_rd):
    """Filtered needed_cache_updates should load fewer evaluation entries
    than unfiltered when there are many inventories."""
    for i in range(50):
        Inventory.objects.create(name=f'inv-{i}', organization=organization)

    org_inv_rd.give_permission(rando, organization)
    org_role = ObjectRole.objects.get(
        role_definition=org_inv_rd,
        object_id=organization.pk,
    )

    inv_ct_id = _inv_ct_id()
    target_inv = Inventory.objects.first()

    unfiltered = {}
    with patch.object(ObjectRole, '_log_partials_count', side_effect=lambda count, label, *a: unfiltered.update({label: count})):
        org_role.needed_cache_updates()

    filtered = {}
    with patch.object(ObjectRole, '_log_partials_count', side_effect=lambda count, label, *a: filtered.update({label: count})):
        org_role.needed_cache_updates(object_pk=target_inv.pk, object_ct_id=inv_ct_id)

    # Filtered should load far fewer existing evaluation entries
    existing_filtered_label = f'existing evaluation (object_pk={target_inv.pk})'
    assert filtered[existing_filtered_label] < unfiltered['existing evaluation (full)']
    assert filtered['expected evaluation'] < unfiltered['expected evaluation']


@pytest.mark.django_db
def test_needed_cache_updates_requires_both_pk_and_ct(rando, organization, org_inv_rd):
    """Passing object_pk without object_ct_id (or vice versa) must raise ValueError."""
    org_inv_rd.give_permission(rando, organization)
    org_role = ObjectRole.objects.get(role_definition=org_inv_rd, object_id=organization.pk)

    with pytest.raises(ValueError):
        org_role.needed_cache_updates(object_pk=1)
    with pytest.raises(ValueError):
        org_role.needed_cache_updates(object_ct_id=1)


@pytest.mark.django_db
def test_expected_direct_permissions_requires_both_pk_and_ct(rando, organization, org_inv_rd):
    """Passing object_pk without object_ct_id (or vice versa) must raise ValueError."""
    org_inv_rd.give_permission(rando, organization)
    org_role = ObjectRole.objects.get(role_definition=org_inv_rd, object_id=organization.pk)

    types_prefetch = TypesPrefetch.from_db()
    with pytest.raises(ValueError):
        org_role.expected_direct_permissions(types_prefetch, object_pk=1)
    with pytest.raises(ValueError):
        org_role.expected_direct_permissions(types_prefetch, object_ct_id=1)
