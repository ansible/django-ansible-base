import pytest

from ansible_base.rbac.models import RoleUserAssignment


@pytest.mark.django_db
def test_load_assignment_list(rando, inventory, inv_rd, global_inv_rd):
    assignment = inv_rd.give_permission(rando, inventory)
    global_inv_rd.give_global_permission(rando)
    assert assignment.id in [asmt.id for asmt in RoleUserAssignment.objects.only('id')]


@pytest.mark.django_db
def test_load_assignment_property(rando, inventory, inv_rd, global_inv_rd):
    assignment = inv_rd.give_permission(rando, inventory)
    global_inv_rd.give_global_permission(rando)
    assert str(assignment.object_id) in [asmt.object_id for asmt in RoleUserAssignment.objects.only('object_id')]
