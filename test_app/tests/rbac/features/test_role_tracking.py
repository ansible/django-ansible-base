import pytest

from ansible_base.rbac import permission_registry


@pytest.mark.django_db
def test_add_user_to_team_relationship(team, rando, inventory, inv_rd, member_rd):
    inv_rd.give_permission(team, inventory)
    assert not rando.has_obj_perm(team, 'member_team')
    assert not rando.has_obj_perm(inventory, 'change_inventory')

    team.users.add(rando)
    assert rando.has_obj_perm(team, 'member_team')
    assert rando.has_obj_perm(inventory, 'change_inventory')

    team.users.clear()
    assert not rando.has_obj_perm(team, 'member_team')
    assert not rando.has_obj_perm(inventory, 'change_inventory')


@pytest.mark.django_db
def test_add_user_to_tracked_role(team, rando, member_rd):
    assert not rando.has_obj_perm(team, 'member_team')

    member_rd.give_permission(rando, team)
    assert rando in team.users.all()

    member_rd.remove_permission(rando, team)
    assert rando not in team.users.all()


@pytest.mark.django_db
def test_add_team_to_tracked_relationship(rando, organization, member_rd):
    child_team = permission_registry.team_model.objects.create(name='child-team', organization=organization)
    parent_team = permission_registry.team_model.objects.create(name='parent-team', organization=organization)
    member_rd.give_permission(rando, parent_team)
    assert not rando.has_obj_perm(child_team, 'member')

    child_team.team_parents.add(parent_team)
    assert rando.has_obj_perm(child_team, 'member')

    child_team.team_parents.clear()
    assert not rando.has_obj_perm(child_team, 'member')


@pytest.mark.django_db
def test_add_team_to_tracked_role(rando, organization, member_rd):
    child_team = permission_registry.team_model.objects.create(name='child-team', organization=organization)
    parent_team = permission_registry.team_model.objects.create(name='parent-team', organization=organization)
    member_rd.give_permission(rando, parent_team)
    assert not rando.has_obj_perm(child_team, 'member')

    member_rd.give_permission(parent_team, child_team)
    assert parent_team in child_team.team_parents.all()

    member_rd.remove_permission(parent_team, child_team)
    assert parent_team not in child_team.team_parents.all()


@pytest.mark.django_db
@pytest.mark.parametrize("reverse", [True, False])
def test_add_organization_member_to_relationship(rando, organization, org_member_rd, reverse):
    assert not rando.has_obj_perm(organization, 'member')

    if reverse:
        rando.member_of_organizations.add(organization)
    else:
        organization.users.add(rando)

    assert org_member_rd.object_roles.count() == 1
    object_role = org_member_rd.object_roles.first()
    assert rando in object_role.users.all()
    assert rando.has_obj_perm(organization, 'member')
