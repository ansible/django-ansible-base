#  Copyright 2024 Red Hat, Inc.
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.

import pytest

from ansible_base.rbac import permission_registry


@pytest.mark.django_db
def test_add_user_to_team_relationship(team, rando, inventory, inv_rd, member_rd):
    inv_rd.give_permission(team, inventory)
    assert not rando.has_obj_perm(team, 'member_team')
    assert not rando.has_obj_perm(inventory, 'change_inventory')

    team.tracked_users.add(rando)
    assert rando.has_obj_perm(team, 'member_team')
    assert rando.has_obj_perm(inventory, 'change_inventory')

    team.tracked_users.clear()
    assert not rando.has_obj_perm(team, 'member_team')
    assert not rando.has_obj_perm(inventory, 'change_inventory')


@pytest.mark.django_db
def test_add_user_to_tracked_role(team, rando, member_rd):
    assert not rando.has_obj_perm(team, 'member_team')

    member_rd.give_permission(rando, team)
    assert rando in team.tracked_users.all()

    member_rd.remove_permission(rando, team)
    assert rando not in team.tracked_users.all()


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
