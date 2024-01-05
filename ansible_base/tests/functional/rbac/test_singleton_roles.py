import pytest


@pytest.mark.django_db
def test_user_singleton_role(rando, inventory, inv_rd):
    inv_rd.give_global_permission(rando)
    assert rando.has_obj_perm(inventory, 'change_inventory')
    assert rando.singleton_permissions() == {'change_inventory', 'view_inventory'}

    inv_rd.remove_global_permission(rando)
    assert not rando.has_obj_perm(inventory, 'change_inventory')
    assert rando.singleton_permissions() == set()


@pytest.mark.django_db
def test_singleton_role_via_team(rando, organization, team, inventory, inv_rd, member_rd):
    member_role = member_rd.give_permission(rando, organization)
    assert list(member_role.provides_teams.all()) == [team]

    inv_rd.give_global_permission(team)
    assert rando.has_obj_perm(inventory, 'change_inventory')
    assert rando.singleton_permissions() == {'change_inventory', 'view_inventory'}

    inv_rd.remove_global_permission(team)
    assert not rando.has_obj_perm(inventory, 'change_inventory')
    assert rando.singleton_permissions() == set()
