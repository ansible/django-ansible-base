"""an object whose parent is reassigned before its first save is a create, not a move."""

from unittest.mock import patch

import pytest

from ansible_base.rbac import permission_registry, triggers
from ansible_base.rbac.caching import recompute_all_role_evaluations
from ansible_base.rbac.models import ObjectRole, RoleEvaluation
from ansible_base.rbac.remote import GenericObject
from ansible_base.rbac.triggers import defer_rbac_computations
from test_app.models import Inventory, Organization


def _evaluation_rows():
    return set(RoleEvaluation.objects.values_list("role_id", "codename", "content_type_id", "object_id"))


@pytest.mark.django_db
def test_create_does_not_recompute_constructed_parent(rando, org_inv_rd):
    """Roles on the parent the object was constructed with, but not saved with, are not recomputed."""
    org_a = Organization.objects.create(name='org-a')
    org_b = Organization.objects.create(name='org-b')
    org_inv_rd.give_permission(rando, org_a)
    org_inv_rd.give_permission(rando, org_b)
    role_a = ObjectRole.objects.get(role_definition=org_inv_rd, object_id=org_a.pk)
    role_b = ObjectRole.objects.get(role_definition=org_inv_rd, object_id=org_b.pk)

    inv = Inventory(name='inv', organization=org_a)
    inv.organization = org_b
    with patch('ansible_base.rbac.triggers.recompute_role_evaluations_for_created', wraps=triggers.recompute_role_evaluations_for_created) as mock_recompute:
        inv.save()

    mock_recompute.assert_called_once()
    assert set(mock_recompute.call_args.args[0]) == {role_b}
    assert role_a not in mock_recompute.call_args.args[0]
    org_ct = permission_registry.content_type_model.objects.get_for_model(Organization)
    assert list(mock_recompute.call_args.kwargs['target_parents']) == [GenericObject(org_ct.id, org_b.pk)]
    assert rando.has_obj_perm(inv, 'change_inventory')
    after = _evaluation_rows()
    recompute_all_role_evaluations()
    assert _evaluation_rows() == after


def _create_inventory(organization, constructed_with, deferred):
    def create():
        inv = Inventory(name='inv', organization=constructed_with)
        inv.organization = organization
        inv.save()
        return inv

    if deferred:
        with defer_rbac_computations():
            return create()
    return create()


@pytest.mark.django_db
@pytest.mark.parametrize('deferred', [False, True], ids=['immediate', 'deferred'])
def test_save_after_create_is_not_a_move(rando, org_inv_rd, deferred):
    """After a create with a reassigned parent, saving the same instance again without a parent change is not a move."""
    org_a = Organization.objects.create(name='org-a')
    org_b = Organization.objects.create(name='org-b')
    org_inv_rd.give_permission(rando, org_b)
    inv = _create_inventory(org_b, constructed_with=org_a, deferred=deferred)

    with patch('ansible_base.rbac.triggers.post_save_update_obj_permissions') as mock_update:
        inv.save()
    mock_update.assert_not_called()
    assert rando.has_obj_perm(inv, 'change_inventory')


@pytest.mark.django_db
@pytest.mark.parametrize('deferred', [False, True], ids=['immediate', 'deferred'])
@pytest.mark.parametrize('reassigned', [False, True], ids=['constructed', 'reassigned'])
def test_move_after_create_still_moves_grants(rando, org_inv_rd, deferred, reassigned):
    """A real parent change after create still takes the old organization's grant away."""
    org_a = Organization.objects.create(name='org-a')
    org_b = Organization.objects.create(name='org-b')
    org_inv_rd.give_permission(rando, org_a)

    inv = _create_inventory(org_a, constructed_with=org_b if reassigned else org_a, deferred=deferred)
    assert rando.has_obj_perm(inv, 'change_inventory')

    inv.organization = org_b
    inv.save()

    assert not rando.has_obj_perm(inv, 'change_inventory')
    after = _evaluation_rows()
    recompute_all_role_evaluations()
    assert _evaluation_rows() == after
