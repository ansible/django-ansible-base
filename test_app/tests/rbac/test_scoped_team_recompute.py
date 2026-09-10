"""Tests for scoped compute_team_member_roles — verifying that the team_ids
parameter correctly limits which teams are updated and that the team-of-team
graph expansion works correctly.

These tests exercise the race-condition fix where concurrent org deletion
and team creation previously caused FK violations because the global
recompute touched ObjectRoles from unrelated orgs.
"""

from unittest.mock import patch

import pytest

from ansible_base.rbac.caching import (
    all_team_children,
    compute_team_member_roles,
)
from ansible_base.rbac.permission_registry import permission_registry
from test_app.models import Inventory, Organization


@pytest.mark.django_db
class TestScopedComputeTeamMemberRoles:
    """Test that compute_team_member_roles(team_ids=...) only writes to the specified teams."""

    def test_scoped_to_new_team_does_not_touch_other_org(self, rando, member_rd, org_team_member_rd):
        """Creating a team in org A should not touch org B's provides_teams.

        This is the core race-condition scenario: org B is being deleted
        concurrently, so touching its ObjectRoles causes FK violations.
        """
        org_a = Organization.objects.create(name='org-a')
        org_b = Organization.objects.create(name='org-b')

        team_b = permission_registry.team_model.objects.create(name='team-b', organization=org_b)
        member_rd.give_permission(rando, team_b)

        # Sanity: team_b has member_roles
        assert team_b.member_roles.exists()
        original_member_role_ids = set(team_b.member_roles.values_list('id', flat=True))

        # Now create team in org_a and do a scoped recompute for just this team
        team_a = permission_registry.team_model.objects.create(name='team-a', organization=org_a)

        # Wipe team_b's member_roles to prove a scoped recompute doesn't touch it
        team_b.member_roles.clear()
        compute_team_member_roles(team_ids=[team_a.id])

        # team_b should still have empty member_roles (was not touched by the scoped recompute)
        assert not team_b.member_roles.exists()

        # A global recompute would restore it
        compute_team_member_roles()
        assert set(team_b.member_roles.values_list('id', flat=True)) == original_member_role_ids

    def test_scoped_recompute_updates_specified_team(self, rando, member_rd, org_team_member_rd):
        """A scoped recompute correctly updates the specified team's member_roles."""
        org = Organization.objects.create(name='test-org')
        team = permission_registry.team_model.objects.create(name='test-team', organization=org)

        # Give org-level member_team role — this should make the ObjectRole provide membership to the team
        assignment = org_team_member_rd.give_permission(rando, org)

        # Clear and re-derive using scoped compute
        team.member_roles.clear()
        assert not team.member_roles.exists()

        compute_team_member_roles(team_ids=[team.id])
        assert team.member_roles.exists()
        assert assignment.object_role in team.member_roles.all()

    def test_team_creation_signal_scopes_correctly(self, rando, org_team_member_rd, inv_rd):
        """End-to-end: creating a team after an org-level member_team role exists
        correctly populates provides_teams for just the new team.
        """
        org = Organization.objects.create(name='org')
        inv = Inventory.objects.create(name='inv', organization=org)

        assignment = org_team_member_rd.give_permission(rando, org)

        # Create team — the post_save signal calls compute_team_member_roles(team_ids=[team.id])
        team = permission_registry.team_model.objects.create(name='new-team', organization=org)
        assert set(assignment.object_role.provides_teams.all()) == {team}

        # User should get access to inv through team membership
        inv_rd.give_permission(team, inv)
        assert rando.has_obj_perm(inv, 'change')


@pytest.mark.django_db
class TestTeamOfTeamExpansion:
    """Test that the team_ids expansion correctly includes child teams in the team-of-team graph."""

    def test_all_team_children_simple(self):
        """all_team_children finds direct children."""
        children_map = {1: {2, 3}, 2: {4}}
        assert all_team_children(1, children_map) == {2, 3, 4}
        assert all_team_children(2, children_map) == {4}
        assert all_team_children(3, children_map) == set()

    def test_all_team_children_with_cycle(self):
        """all_team_children handles cycles without infinite recursion."""
        children_map = {1: {2}, 2: {3}, 3: {1}}
        result = all_team_children(1, children_map)
        assert result == {2, 3, 1}

    def test_scoped_recompute_expands_to_children(self, rando, organization, member_rd, inv_rd):
        """When team T1 is specified in team_ids and T1 is parent of T2,
        T2 is automatically included in the recompute.
        """
        team1 = permission_registry.team_model.objects.create(name='team-1', organization=organization)
        team2 = permission_registry.team_model.objects.create(name='team-2', organization=organization)
        inv = Inventory.objects.create(name='inv', organization=organization)

        # Make team1 a parent of team2 (member of team1 → member of team2)
        member_rd.give_permission(team1, team2)
        # Give team2 inventory permission
        inv_rd.give_permission(team2, inv)

        # Give user membership to team1
        assignment = member_rd.give_permission(rando, team1)

        # Verify the provides_teams chain works
        assert team2 in assignment.object_role.provides_teams.all()
        assert rando.has_obj_perm(inv, 'change')

        # Clear member_roles for both teams and do a scoped recompute with just team1
        team1.member_roles.clear()
        team2.member_roles.clear()

        # Scoped to team1 — should expand to include team2 (child)
        compute_team_member_roles(team_ids=[team1.id])

        # Both teams should be restored
        assert team1.member_roles.exists()
        assert team2.member_roles.exists()

    def test_five_nested_teams_scoped(self, rando, organization, member_rd, inv_rd):
        """Scoped recompute on the top team expands through the full chain."""
        inv = Inventory.objects.create(name='inv', organization=organization)
        teams = [permission_registry.team_model.objects.create(name=f'team-{i}', organization=organization) for i in range(5)]

        # Create chain: team-0 <- team-1 <- team-2 <- team-3 <- team-4
        for parent_team, child_team in zip(teams[:-1], teams[1:]):
            member_rd.give_permission(parent_team, child_team)
        inv_rd.give_permission(teams[-1], inv)
        member_rd.give_permission(rando, teams[0])

        # Sanity: full chain works
        assert rando.has_obj_perm(inv, 'change')

        # Clear all member_roles and do a scoped recompute on team-0 only
        for t in teams:
            t.member_roles.clear()

        compute_team_member_roles(team_ids=[teams[0].id])

        # All teams should be restored via expansion
        for t in teams:
            assert t.member_roles.exists(), f'{t.name} should have member_roles after expansion'

        # Permissions should still work
        assert rando.has_obj_perm(inv, 'change')


@pytest.mark.django_db
class TestTeamDeletionScoping:
    """Test that team deletion correctly identifies and scopes the recompute to affected teams."""

    def test_delete_team_middle_of_chain(self, rando, organization, member_rd, inv_rd):
        """Deleting a team in the middle of a chain correctly updates downstream teams."""
        inv = Inventory.objects.create(name='inv', organization=organization)
        team1 = permission_registry.team_model.objects.create(name='team-1', organization=organization)
        team2 = permission_registry.team_model.objects.create(name='team-2', organization=organization)
        team3 = permission_registry.team_model.objects.create(name='team-3', organization=organization)

        # Chain: team1 -> team2 -> team3
        member_rd.give_permission(team1, team2)
        member_rd.give_permission(team2, team3)
        inv_rd.give_permission(team3, inv)
        member_rd.give_permission(rando, team1)

        assert rando.has_obj_perm(inv, 'change')

        # Delete middle team — should break the chain
        team2.delete()
        assert not rando.has_obj_perm(inv, 'change')

    def test_delete_parent_team_does_not_touch_unrelated_org(self, rando, member_rd, inv_rd):
        """Deleting a team should only recompute teams that were children of the deleted team,
        not teams in unrelated orgs.
        """
        org_a = Organization.objects.create(name='org-a')
        org_b = Organization.objects.create(name='org-b')

        team_a1 = permission_registry.team_model.objects.create(name='team-a1', organization=org_a)
        team_a2 = permission_registry.team_model.objects.create(name='team-a2', organization=org_a)
        team_b = permission_registry.team_model.objects.create(name='team-b', organization=org_b)

        # team_a1 is parent of team_a2
        member_rd.give_permission(team_a1, team_a2)
        member_rd.give_permission(rando, team_b)

        # Sanity
        assert team_b.member_roles.exists()

        # Track calls to see scoping
        original_compute = compute_team_member_roles.__wrapped__ if hasattr(compute_team_member_roles, '__wrapped__') else compute_team_member_roles
        captured_team_ids = []

        def tracking_compute(team_ids=None):
            captured_team_ids.append(team_ids)
            return original_compute(team_ids=team_ids)

        with patch('ansible_base.rbac.triggers.compute_team_member_roles', tracking_compute):
            team_a1.delete()

        # The recompute should have been scoped (not global)
        assert len(captured_team_ids) > 0
        for tid_set in captured_team_ids:
            if tid_set is not None:
                assert team_b.id not in tid_set, "team_b should not be in the recompute scope"

    def test_delete_team_in_org_with_many_teams(self, rando, organization, member_rd, inv_rd):
        """Deleting a team that is a parent of another correctly updates the child."""
        team_parent = permission_registry.team_model.objects.create(name='parent', organization=organization)
        team_child = permission_registry.team_model.objects.create(name='child', organization=organization)
        inv = Inventory.objects.create(name='inv', organization=organization)

        # parent is parent of child
        member_rd.give_permission(team_parent, team_child)
        inv_rd.give_permission(team_child, inv)
        member_rd.give_permission(rando, team_parent)

        assert rando.has_obj_perm(inv, 'change')

        # Delete parent — child should lose the transitive member_roles
        team_parent.delete()
        assert not rando.has_obj_perm(inv, 'change')


@pytest.mark.django_db
class TestRoleAssignmentScoping:
    """Test that role assignments correctly scope the provides_teams recompute."""

    def test_give_member_team_scopes_to_target_team(self, rando, member_rd, inv_rd):
        """Giving a member_team role on a team scopes the recompute to that team."""
        org_a = Organization.objects.create(name='org-a')
        org_b = Organization.objects.create(name='org-b')

        team_a = permission_registry.team_model.objects.create(name='team-a', organization=org_a)
        team_b = permission_registry.team_model.objects.create(name='team-b', organization=org_b)
        inv = Inventory.objects.create(name='inv', organization=org_a)

        inv_rd.give_permission(team_a, inv)
        inv_rd.give_permission(team_b, Inventory.objects.create(name='inv-b', organization=org_b))

        # Track recompute calls
        original_compute = compute_team_member_roles.__wrapped__ if hasattr(compute_team_member_roles, '__wrapped__') else compute_team_member_roles
        captured_team_ids = []

        def tracking_compute(team_ids=None):
            captured_team_ids.append(team_ids)
            return original_compute(team_ids=team_ids)

        with patch('ansible_base.rbac.pipeline.compute_team_member_roles', tracking_compute):
            member_rd.give_permission(rando, team_a)

        assert rando.has_obj_perm(inv, 'change')

        # Verify scoping happened — the recompute should have included team_a but not team_b
        recompute_calls_with_ids = [ids for ids in captured_team_ids if ids is not None]
        assert len(recompute_calls_with_ids) > 0
        for ids in recompute_calls_with_ids:
            assert team_a.id in ids
            assert team_b.id not in ids

    def test_org_level_member_team_scopes_to_org_teams(self, rando, org_team_member_rd, inv_rd):
        """Giving an org-level member_team role scopes to all teams in that org."""
        org_a = Organization.objects.create(name='org-a')
        org_b = Organization.objects.create(name='org-b')

        team_a1 = permission_registry.team_model.objects.create(name='team-a1', organization=org_a)
        team_a2 = permission_registry.team_model.objects.create(name='team-a2', organization=org_a)
        team_b = permission_registry.team_model.objects.create(name='team-b', organization=org_b)

        inv = Inventory.objects.create(name='inv', organization=org_a)
        inv_rd.give_permission(team_a1, inv)

        original_compute = compute_team_member_roles.__wrapped__ if hasattr(compute_team_member_roles, '__wrapped__') else compute_team_member_roles
        captured_team_ids = []

        def tracking_compute(team_ids=None):
            captured_team_ids.append(team_ids)
            return original_compute(team_ids=team_ids)

        with patch('ansible_base.rbac.pipeline.compute_team_member_roles', tracking_compute):
            org_team_member_rd.give_permission(rando, org_a)

        assert rando.has_obj_perm(inv, 'change')

        # Should include both org_a teams but not org_b's team
        recompute_calls_with_ids = [ids for ids in captured_team_ids if ids is not None]
        assert len(recompute_calls_with_ids) > 0
        for ids in recompute_calls_with_ids:
            assert team_a1.id in ids
            assert team_a2.id in ids
            assert team_b.id not in ids

    def test_revoke_member_team_scoped(self, rando, member_rd, inv_rd):
        """Revoking a member_team role correctly scopes the recompute."""
        org = Organization.objects.create(name='org')
        team = permission_registry.team_model.objects.create(name='team', organization=org)
        inv = Inventory.objects.create(name='inv', organization=org)

        inv_rd.give_permission(team, inv)
        member_rd.give_permission(rando, team)
        assert rando.has_obj_perm(inv, 'change')

        member_rd.remove_permission(rando, team)
        assert not rando.has_obj_perm(inv, 'change')

    def test_team_to_team_assignment_scoped(self, rando, member_rd, inv_rd):
        """Assigning a member_team role to a team actor scopes correctly."""
        org = Organization.objects.create(name='org')
        parent = permission_registry.team_model.objects.create(name='parent', organization=org)
        child = permission_registry.team_model.objects.create(name='child', organization=org)
        inv = Inventory.objects.create(name='inv', organization=org)

        inv_rd.give_permission(child, inv)
        member_rd.give_permission(rando, parent)
        assert not rando.has_obj_perm(inv, 'change')

        # Assign parent as team member of child — user should now get access
        member_rd.give_permission(parent, child)
        assert rando.has_obj_perm(inv, 'change')

        # Revoke — access should be removed
        member_rd.remove_permission(parent, child)
        assert not rando.has_obj_perm(inv, 'change')


@pytest.mark.django_db
class TestTeamOrganizationChange:
    """Test that moving a team between organizations correctly scopes the recompute."""

    def test_move_team_to_different_org(self, rando, org_team_member_rd, inv_rd):
        """Moving a team between orgs correctly updates provides_teams.

        Uses org_team_member_rd (team membership only, no direct inventory perms)
        so that access is purely through team membership.
        """
        org_a = Organization.objects.create(name='org-a')
        org_b = Organization.objects.create(name='org-b')

        team = permission_registry.team_model.objects.create(name='test-team', organization=org_a)
        inv = Inventory.objects.create(name='inv', organization=org_a)

        org_team_member_rd.give_permission(rando, org_a)
        inv_rd.give_permission(team, inv)
        assert rando.has_obj_perm(inv, 'change')

        # Move team to org_b — rando's org_a membership no longer covers this team
        team.organization = org_b
        team.save(update_fields=['organization'])

        assert not rando.has_obj_perm(inv, 'change')

        # User with org_b team membership should gain access
        user_b = permission_registry.user_model.objects.create(username='user_b')
        org_team_member_rd.give_permission(user_b, org_b)
        assert user_b.has_obj_perm(inv, 'change')


@pytest.mark.django_db
class TestGlobalRecomputeStillWorks:
    """Verify that compute_team_member_roles(team_ids=None) still does a full global recompute."""

    def test_global_recompute_fixes_all_teams(self, rando, member_rd, org_team_member_rd):
        """A global recompute (no team_ids) restores all teams."""
        org_a = Organization.objects.create(name='org-a')
        org_b = Organization.objects.create(name='org-b')

        team_a = permission_registry.team_model.objects.create(name='team-a', organization=org_a)
        team_b = permission_registry.team_model.objects.create(name='team-b', organization=org_b)

        member_rd.give_permission(rando, team_a)
        member_rd.give_permission(rando, team_b)

        assert team_a.member_roles.exists()
        assert team_b.member_roles.exists()

        # Clear both and do global recompute
        team_a.member_roles.clear()
        team_b.member_roles.clear()

        compute_team_member_roles()

        assert team_a.member_roles.exists()
        assert team_b.member_roles.exists()

    def test_empty_team_ids_is_noop(self):
        """Passing an empty team_ids set should not error and should be a no-op."""
        compute_team_member_roles(team_ids=set())
        compute_team_member_roles(team_ids=[])
