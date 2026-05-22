from unittest.mock import patch

import pytest

from ansible_base.rbac.models import RoleEvaluation
from ansible_base.rbac.triggers import _deferred_evaluation, defer_role_evaluation, update_after_assignment
from test_app.models import Inventory


@pytest.mark.django_db
class TestDeferRoleEvaluation:
    def test_deferred_state_starts_disabled(self):
        assert _deferred_evaluation.enabled is False
        assert _deferred_evaluation.object_roles == set()
        assert _deferred_evaluation.needs_team_recompute is False

    def test_context_manager_enables_and_restores(self):
        assert _deferred_evaluation.enabled is False
        with defer_role_evaluation():
            assert _deferred_evaluation.enabled is True
        assert _deferred_evaluation.enabled is False

    @patch('ansible_base.rbac.triggers.compute_object_role_permissions')
    @patch('ansible_base.rbac.triggers.compute_team_member_roles')
    def test_context_manager_nesting(self, mock_teams, mock_perms):
        assert _deferred_evaluation.enabled is False
        with defer_role_evaluation():
            assert _deferred_evaluation.enabled is True
            _deferred_evaluation.object_roles.add("outer_role")
            with defer_role_evaluation():
                assert _deferred_evaluation.enabled is True
                assert _deferred_evaluation.object_roles == set()
            assert _deferred_evaluation.enabled is True
            assert "outer_role" in _deferred_evaluation.object_roles
        assert _deferred_evaluation.enabled is False

    def test_context_manager_restores_on_exception(self):
        assert _deferred_evaluation.enabled is False
        with pytest.raises(RuntimeError):
            with defer_role_evaluation():
                assert _deferred_evaluation.enabled is True
                raise RuntimeError("test")
        assert _deferred_evaluation.enabled is False

    @patch('ansible_base.rbac.triggers.compute_object_role_permissions')
    @patch('ansible_base.rbac.triggers.compute_team_member_roles')
    def test_update_after_assignment_defers_when_enabled(self, mock_teams, mock_perms):
        mock_role = object()
        with defer_role_evaluation():
            update_after_assignment(False, {mock_role})
            assert mock_role in _deferred_evaluation.object_roles
            assert _deferred_evaluation.needs_team_recompute is False

    def test_update_after_assignment_defers_team_recompute(self):
        with defer_role_evaluation():
            update_after_assignment(True, set())
            assert _deferred_evaluation.needs_team_recompute is True

    @patch('ansible_base.rbac.triggers.compute_object_role_permissions')
    @patch('ansible_base.rbac.triggers.compute_team_member_roles')
    def test_update_after_assignment_accumulates(self, mock_teams, mock_perms):
        role_a = object()
        role_b = object()
        with defer_role_evaluation():
            update_after_assignment(False, {role_a})
            update_after_assignment(True, {role_b})
            assert role_a in _deferred_evaluation.object_roles
            assert role_b in _deferred_evaluation.object_roles
            assert _deferred_evaluation.needs_team_recompute is True

    @patch('ansible_base.rbac.triggers.compute_object_role_permissions')
    @patch('ansible_base.rbac.triggers.compute_team_member_roles')
    def test_update_after_assignment_calls_directly_when_not_deferred(self, mock_teams, mock_perms):
        mock_roles = {object()}
        update_after_assignment(True, mock_roles)
        mock_teams.assert_called_once()
        mock_perms.assert_called_once_with(object_roles=mock_roles)

    @patch('ansible_base.rbac.triggers.compute_object_role_permissions')
    @patch('ansible_base.rbac.triggers.compute_team_member_roles')
    def test_deferred_batch_executes_on_exit(self, mock_teams, mock_perms):
        role_a = object()
        role_b = object()
        with defer_role_evaluation():
            update_after_assignment(True, {role_a})
            update_after_assignment(False, {role_b})
            mock_teams.assert_not_called()
            mock_perms.assert_not_called()

        mock_teams.assert_called_once()
        mock_perms.assert_called_once()
        called_roles = mock_perms.call_args[1]['object_roles']
        assert role_a in called_roles
        assert role_b in called_roles

    @patch('ansible_base.rbac.triggers.compute_object_role_permissions')
    @patch('ansible_base.rbac.triggers.compute_team_member_roles')
    def test_deferred_skips_team_recompute_when_not_needed(self, mock_teams, mock_perms):
        with defer_role_evaluation():
            update_after_assignment(False, {object()})

        mock_teams.assert_not_called()
        mock_perms.assert_called_once()

    @patch('ansible_base.rbac.triggers.compute_object_role_permissions')
    @patch('ansible_base.rbac.triggers.compute_team_member_roles')
    def test_deferred_skips_all_when_empty(self, mock_teams, mock_perms):
        with defer_role_evaluation():
            pass

        mock_teams.assert_not_called()
        mock_perms.assert_not_called()

    def test_give_permission_batches_evaluations(self, inv_rd, rando, inventory, organization):
        """Integration test: give_permission under defer batches RoleEvaluation writes."""
        inv2 = Inventory.objects.create(name='inv-2', organization=organization)

        with defer_role_evaluation():
            inv_rd.give_permission(rando, inventory)
            inv_rd.give_permission(rando, inv2)

        assert rando.has_obj_perm(inventory, 'change')
        assert rando.has_obj_perm(inv2, 'change')
        assert RoleEvaluation.objects.filter(object_id=inventory.pk).exists()
        assert RoleEvaluation.objects.filter(object_id=inv2.pk).exists()

    def test_remove_permission_batches_evaluations(self, inv_rd, rando, inventory, organization):
        """Integration test: remove_permission under defer cleans up correctly."""
        inv_rd.give_permission(rando, inventory)
        assert rando.has_obj_perm(inventory, 'change')

        with defer_role_evaluation():
            inv_rd.remove_permission(rando, inventory)

        assert not rando.has_obj_perm(inventory, 'change')

    def test_mixed_give_remove_under_defer(self, inv_rd, rando, inventory, organization):
        """Integration test: mixed operations produce correct final state."""
        inv2 = Inventory.objects.create(name='inv-mix-2', organization=organization)
        inv_rd.give_permission(rando, inventory)

        with defer_role_evaluation():
            inv_rd.give_permission(rando, inv2)
            inv_rd.remove_permission(rando, inventory)

        assert not rando.has_obj_perm(inventory, 'change')
        assert rando.has_obj_perm(inv2, 'change')
