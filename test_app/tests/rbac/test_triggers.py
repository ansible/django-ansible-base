import pytest
from django.contrib.contenttypes.models import ContentType

from ansible_base.rbac.models import ObjectRole, RoleEvaluation, RoleTeamAssignment, RoleUserAssignment
from test_app.models import Inventory, Organization


@pytest.mark.django_db
def test_change_parent_field(team, rando, inventory, org_inv_rd, member_rd):
    member_rd.give_permission(rando, team)
    org_inv_rd.give_permission(team, inventory.organization)
    assert rando.has_obj_perm(inventory, 'change')

    inventory.organization = Organization.objects.create(name='new-org')
    inventory.save()

    assert not rando.has_obj_perm(inventory, 'change')


@pytest.mark.django_db
def test_change_parent_field_with_only(team, rando, inventory, org_inv_rd, member_rd):
    member_rd.give_permission(rando, team)
    org_inv_rd.give_permission(team, inventory.organization)
    assert rando.has_obj_perm(inventory, 'change')

    inv_copy = Inventory.objects.only('id').get(id=inventory.id)
    assert 'organization_id' not in inv_copy.__dict__  # signal should not undermine .only

    inv_copy.organization = Organization.objects.create(name='new-org')
    inv_copy.save()

    assert not rando.has_obj_perm(inv_copy, 'change')


@pytest.mark.django_db
def test_perform_unrelated_update(inventory):
    """
    Signals should not trigger queries of permission related fields are not changed
    """
    inv_copy = Inventory.objects.only('id', 'name').get(id=inventory.id)
    assert 'organization_id' not in inv_copy.__dict__

    inv_copy.name = 'new inventory name'
    inv_copy.save()

    assert 'organization_id' not in inv_copy.__dict__


@pytest.mark.django_db
@pytest.mark.parametrize('what_to_delete', ['user', 'object'])
def test_delete_signals(organization, inventory, rando, inv_rd, what_to_delete):
    assignment = inv_rd.give_permission(rando, inventory)
    inv_id = inventory.id
    user_id = rando.id
    inv_ct = ContentType.objects.get_for_model(inventory)
    if what_to_delete == 'user':
        rando.delete()
    else:
        organization.delete()
    assert not RoleUserAssignment.objects.filter(user_id=user_id).exists()
    assert not ObjectRole.objects.filter(id=assignment.object_role_id).exists()
    assert not RoleEvaluation.objects.filter(content_type_id=inv_ct.id, object_id=inv_id).exists()


@pytest.mark.django_db
@pytest.mark.parametrize('what_to_delete', ['team', 'object'])
def test_delete_signals_team(organization, inventory, team, inv_rd, what_to_delete):
    assignment = inv_rd.give_permission(team, inventory)
    inv_id = inventory.id
    team_id = team.id
    inv_ct = ContentType.objects.get_for_model(inventory)
    if what_to_delete == 'team':
        team.delete()
    else:
        organization.delete()
    assert not RoleTeamAssignment.objects.filter(team_id=team_id).exists()
    assert not ObjectRole.objects.filter(id=assignment.object_role_id).exists()
    assert not RoleEvaluation.objects.filter(content_type_id=inv_ct.id, object_id=inv_id).exists()
