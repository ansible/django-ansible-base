import weakref
from unittest.mock import MagicMock, patch

import pytest
from django.apps import apps
from django.db.models.signals import pre_delete
from django.test.utils import override_settings
from rest_framework.exceptions import ValidationError

from ansible_base.lib.utils.response import get_relative_url
from ansible_base.rbac.models import ObjectRole, RoleDefinition, RoleEvaluation, RoleEvaluationUUID, RoleTeamAssignment, RoleUserAssignment
from ansible_base.rbac.permission_registry import permission_registry
from ansible_base.rbac.triggers import _defer_rbac_cache, dab_post_migrate, defer_rbac_cache, post_migration_rbac_setup
from test_app.models import ExampleEvent, Inventory, Organization, Team, User


@pytest.mark.django_db
def test_post_migrate_signals():
    mck = MagicMock()
    # corresponds to docs/apps/rbac/for_app_developers.md, Post-migrate Actions
    dab_post_migrate.connect(mck.ad_hoc_func, dispatch_uid="my_logic")
    post_migration_rbac_setup(apps.get_app_config('dab_rbac'))
    mck.ad_hoc_func.assert_called_once_with(sender=apps.get_app_config('dab_rbac'), signal=dab_post_migrate)


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


def gfk_filter(obj):
    "Test helper method, expects to be called before permissions are assigned"
    ct = permission_registry.content_type_model.objects.get_for_model(obj)
    gfk = {'object_id': obj.pk, 'content_type_id': ct.pk}
    # No roles are assigned in the starting state, this is a design objective
    assert not RoleEvaluation.objects.filter(**gfk).exists(), obj
    return gfk


@pytest.mark.django_db
@pytest.mark.parametrize('what_to_delete', ['user', 'org', 'object'])
def test_delete_signals_object(organization, inventory, rando, inv_rd, what_to_delete):
    user_id = rando.id
    inv_gfk = gfk_filter(inventory)
    org_gfk = gfk_filter(organization)

    assignment = inv_rd.give_permission(rando, inventory)

    assert RoleEvaluation.objects.filter(**org_gfk).count() == 0
    assert RoleEvaluation.objects.filter(**inv_gfk).count() == 2

    if what_to_delete == 'user':
        rando.delete()
    if what_to_delete == 'org':
        organization.delete()
    else:
        inventory.delete()

    assert not RoleEvaluation.objects.filter(**inv_gfk).exists()
    assert not RoleEvaluation.objects.filter(**org_gfk).exists()
    assert not RoleUserAssignment.objects.filter(user_id=user_id).exists()
    assert not ObjectRole.objects.filter(id=assignment.object_role_id).exists()


@pytest.mark.django_db
@pytest.mark.parametrize('what_to_delete', ['user', 'org', 'object'])
@pytest.mark.parametrize('cache_org', [True, False])
def test_delete_signals_organization(organization, inventory, rando, org_inv_change_rd, what_to_delete, cache_org):
    user_id = rando.id
    inv_gfk = gfk_filter(inventory)
    org_gfk = gfk_filter(organization)

    with override_settings(ANSIBLE_BASE_CACHE_PARENT_PERMISSIONS=cache_org):
        assignment = org_inv_change_rd.give_permission(rando, organization)
        assert RoleEvaluation.objects.filter(**org_gfk).count() == (4 if cache_org else 2)
        assert RoleEvaluation.objects.filter(**inv_gfk).count() == 2

        if what_to_delete == 'user':
            rando.delete()
        if what_to_delete == 'org':
            organization.delete()
        else:
            inventory.delete()

        assert not RoleEvaluation.objects.filter(**inv_gfk).exists()
        if what_to_delete == 'object':
            # The user and org still exist, so the membership should still exist
            assert RoleUserAssignment.objects.filter(user_id=user_id).count() == 1
            assert ObjectRole.objects.filter(id=assignment.object_role_id).count() == 1
            assert RoleEvaluation.objects.filter(**org_gfk).count() == (4 if cache_org else 2)
        else:
            assert not RoleUserAssignment.objects.filter(user_id=user_id).exists()
            assert not ObjectRole.objects.filter(id=assignment.object_role_id).exists()
            assert not RoleEvaluation.objects.filter(**org_gfk).exists()


@pytest.mark.django_db
@pytest.mark.parametrize('what_to_delete', ['team', 'org', 'object'])
def test_delete_signals_team_object(organization, inventory, team, inv_rd, what_to_delete):
    team_id = team.id
    inv_gfk = gfk_filter(inventory)
    org_gfk = gfk_filter(organization)
    assignment = inv_rd.give_permission(team, inventory)

    if what_to_delete == 'team':
        team.delete()
    if what_to_delete == 'org':
        organization.delete()
    else:
        inventory.delete()

    assert not RoleTeamAssignment.objects.filter(team_id=team_id).exists()
    assert not ObjectRole.objects.filter(id=assignment.object_role_id).exists()
    assert not RoleEvaluation.objects.filter(**inv_gfk).exists()
    assert not RoleEvaluation.objects.filter(**org_gfk).exists()


@pytest.mark.django_db
@pytest.mark.parametrize('what_to_delete', ['team', 'org', 'object'])
def test_delete_signals_team_organization(organization, inventory, team, org_inv_rd, what_to_delete):
    inv_gfk = gfk_filter(inventory)
    org_gfk = gfk_filter(organization)
    team_id = team.id
    assignment = org_inv_rd.give_permission(team, organization)

    if what_to_delete == 'team':
        team.delete()
    if what_to_delete == 'org':
        organization.delete()
    else:
        inventory.delete()

    if what_to_delete == 'object':
        assert RoleTeamAssignment.objects.filter(team_id=team_id).count() == 1  # team still has org role
        assert ObjectRole.objects.filter(id=assignment.object_role_id).count() == 1
        assert RoleEvaluation.objects.filter(**org_gfk).count() == 2
    else:
        assert not RoleTeamAssignment.objects.filter(team_id=team_id).exists()
        assert not ObjectRole.objects.filter(id=assignment.object_role_id).exists()
        assert not RoleEvaluation.objects.filter(**org_gfk).exists()

    assert not RoleEvaluation.objects.filter(**inv_gfk).exists()


@pytest.mark.django_db
def test_defer_rbac_cache_produces_correct_evaluations(organization, inventory, rando, org_inv_rd):
    """Calling give_permission inside defer_rbac_cache should produce
    the same RoleEvaluation entries as calling it without deferral."""
    inv_gfk = gfk_filter(inventory)
    org_gfk = gfk_filter(organization)

    with defer_rbac_cache():
        org_inv_rd.give_permission(rando, organization)
        # During deferral, evaluations should not yet exist
        assert not RoleEvaluation.objects.filter(**inv_gfk).exists()

    # After the context manager exits, evaluations should be flushed
    assert RoleEvaluation.objects.filter(**org_gfk).exists()
    assert RoleEvaluation.objects.filter(**inv_gfk).exists()
    assert rando.has_obj_perm(inventory, 'change')


@pytest.mark.django_db
def test_defer_rbac_cache_multiple_assignments(organization, rando, inv_rd):
    """Multiple give_permission calls inside defer_rbac_cache should
    all produce correct evaluations after the context exits."""
    second_org = Organization.objects.create(name='second-org')
    inv1 = Inventory.objects.create(name='inv1', organization=organization)
    inv2 = Inventory.objects.create(name='inv2', organization=second_org)

    with defer_rbac_cache():
        inv_rd.give_permission(rando, inv1)
        inv_rd.give_permission(rando, inv2)

    assert rando.has_obj_perm(inv1, 'change')
    assert rando.has_obj_perm(inv2, 'change')


@pytest.mark.django_db
def test_defer_rbac_cache_can_be_nested():
    """Nesting defer_rbac_cache should be a no-op -- the outermost
    caller owns the flush lifecycle."""
    with defer_rbac_cache():
        with defer_rbac_cache():
            pass  # should not raise


@pytest.mark.django_db
def test_defer_rbac_cache_nested_flush_only_on_outer_exit(organization, inventory, rando, org_inv_rd):
    """When defer_rbac_cache is nested, flush should only happen when
    the outermost context exits, not the inner one."""
    inv_gfk = gfk_filter(inventory)

    with defer_rbac_cache():
        org_inv_rd.give_permission(rando, organization)
        with defer_rbac_cache():
            pass  # inner exit should NOT flush
        # Still inside outer -- evaluations should not exist yet
        assert not RoleEvaluation.objects.filter(**inv_gfk).exists()

    # After outer exits, evaluations should be flushed
    assert RoleEvaluation.objects.filter(**inv_gfk).exists()
    assert rando.has_obj_perm(inventory, 'change')


@pytest.mark.django_db
def test_defer_rbac_cache_empty_block(inventory):
    """An empty defer_rbac_cache block should not trigger any
    recomputation — it should be a no-op."""
    from unittest.mock import patch

    with patch('ansible_base.rbac.triggers.compute_object_role_permissions') as mock_compute:
        with defer_rbac_cache():
            pass

    mock_compute.assert_not_called()


@pytest.mark.django_db
def test_defer_rbac_cache_without_context_manager(organization, inventory, rando, org_inv_rd):
    """Without defer_rbac_cache, behavior is unchanged — evaluations
    are created immediately."""
    inv_gfk = gfk_filter(inventory)

    org_inv_rd.give_permission(rando, organization)

    assert RoleEvaluation.objects.filter(**inv_gfk).exists()
    assert rando.has_obj_perm(inventory, 'change')


@pytest.mark.django_db
def test_defer_rbac_cache_with_team_assignment(organization, team, rando, org_team_member_rd):
    """defer_rbac_cache should also defer and flush team membership
    recomputation (the team_ids path)."""
    with defer_rbac_cache():
        org_team_member_rd.give_permission(rando, organization)

    assert rando.has_obj_perm(team, 'member_team')


@pytest.mark.django_db
def test_team_delete_orphan_cleanup_runs_once(team, inventory, inv_rd):
    """When a team with a role assignment is deleted (creating an orphan
    ObjectRole), verify that the orphan cleanup query runs exactly once."""
    inv_rd.give_permission(team, inventory)

    with patch.object(ObjectRole.objects, 'filter', wraps=ObjectRole.objects.filter) as mock_filter:
        team.delete()

    orphan_calls = [c for c in mock_filter.call_args_list if c.kwargs.get('users__isnull') is True and c.kwargs.get('teams__isnull') is True]
    assert len(orphan_calls) == 1


@pytest.mark.django_db
def test_defer_rbac_cache_defers_team_delete_recomputation(organization, team, org_team_member_rd):
    """Inside defer_rbac_cache, compute_team_member_roles and
    compute_object_role_permissions are NOT called during the block,
    but ARE called when the context exits."""
    # A survivor team ensures stashed_recompute_team_ids is non-empty
    Team.objects.create(name='survivor-team', organization=organization)
    # Give the team a role with team_permission so delete populates both
    # deferred team_ids and object_roles
    org_team_member_rd.give_permission(team, organization)

    with (
        patch('ansible_base.rbac.triggers.compute_team_member_roles') as mock_team,
        patch('ansible_base.rbac.triggers.compute_object_role_permissions') as mock_obj,
    ):
        with defer_rbac_cache():
            team.delete()
            mock_team.assert_not_called()
            mock_obj.assert_not_called()
        mock_team.assert_called_once()
        mock_obj.assert_called_once()


@pytest.mark.django_db
def test_defer_rbac_cache_defers_orphan_cleanup_on_team_delete(team, inventory, inv_rd):
    """Inside defer_rbac_cache, the orphan ObjectRole cleanup does NOT
    run inside the block, but DOES run once when the context exits."""
    inv_rd.give_permission(team, inventory)

    with patch.object(ObjectRole.objects, 'filter', wraps=ObjectRole.objects.filter) as mock_filter:
        with defer_rbac_cache():
            team.delete()
            orphan_calls_during = [c for c in mock_filter.call_args_list if c.kwargs.get('users__isnull') is True and c.kwargs.get('teams__isnull') is True]
            assert len(orphan_calls_during) == 0

        orphan_calls_after = [c for c in mock_filter.call_args_list if c.kwargs.get('users__isnull') is True and c.kwargs.get('teams__isnull') is True]
        assert len(orphan_calls_after) == 1


@pytest.mark.django_db
@pytest.mark.parametrize('use_defer', [True, False], ids=['deferred', 'immediate'])
def test_defer_rbac_cache_delete_produces_correct_cleanup(rando, inv_rd, use_defer):
    """Org deletion with multiple teams produces correct cleanup both
    with defer_rbac_cache (deferred path) and without (immediate path),
    confirming the non-deferred path is unchanged."""
    from contextlib import nullcontext

    org = Organization.objects.create(name='test-org-cleanup')
    team1 = Team.objects.create(name='team-cleanup-1', organization=org)
    team2 = Team.objects.create(name='team-cleanup-2', organization=org)
    inv1 = Inventory.objects.create(name='inv-cleanup-1', organization=org)
    inv2 = Inventory.objects.create(name='inv-cleanup-2', organization=org)

    ct_inv = permission_registry.content_type_model.objects.get_for_model(inv1)
    ct_org = permission_registry.content_type_model.objects.get_for_model(org)
    inv1_gfk = {'object_id': inv1.pk, 'content_type_id': ct_inv.pk}
    inv2_gfk = {'object_id': inv2.pk, 'content_type_id': ct_inv.pk}
    org_gfk = {'object_id': org.pk, 'content_type_id': ct_org.pk}

    # Teams get inventory roles (creates ObjectRoles that become orphans
    # when teams are deleted via cascade)
    inv_rd.give_permission(team1, inv1)
    inv_rd.give_permission(team2, inv2)
    # User gets a direct inventory role to verify user permissions are cleaned up
    inv_rd.give_permission(rando, inv1)

    assert rando.has_obj_perm(inv1, 'change')

    team1_id, team2_id = team1.id, team2.id

    if use_defer:
        with defer_rbac_cache():
            org.delete()
    else:
        with patch('ansible_base.rbac.triggers.defer_rbac_cache', nullcontext):
            org.delete()

    # All RoleEvaluations for the org and its inventories are gone
    assert not RoleEvaluation.objects.filter(**org_gfk).exists()
    assert not RoleEvaluation.objects.filter(**inv1_gfk).exists()
    assert not RoleEvaluation.objects.filter(**inv2_gfk).exists()
    # All ObjectRoles for the deleted teams are gone
    assert not RoleTeamAssignment.objects.filter(team_id__in=[team1_id, team2_id]).exists()
    # No orphan ObjectRoles remain
    assert not ObjectRole.objects.filter(users__isnull=True, teams__isnull=True).exists()
    # The user no longer has permissions on any deleted objects
    assert not RoleUserAssignment.objects.filter(user_id=rando.id).exists()


@pytest.mark.django_db
def test_defer_rbac_cache_multiple_team_deletes_single_flush(organization, org_team_member_rd):
    """Inside defer_rbac_cache, deleting multiple teams individually results
    in compute_team_member_roles being called only once (in the flush),
    not once per team deletion."""
    team1 = Team.objects.create(name='team-flush-1', organization=organization)
    team2 = Team.objects.create(name='team-flush-2', organization=organization)
    # A survivor team ensures stashed_recompute_team_ids is non-empty
    Team.objects.create(name='survivor-team', organization=organization)

    # Give both teams roles with team_permission so deletes populate deferred team_ids
    org_team_member_rd.give_permission(team1, organization)
    org_team_member_rd.give_permission(team2, organization)

    with patch('ansible_base.rbac.triggers.compute_team_member_roles') as mock_team, patch('ansible_base.rbac.triggers.compute_object_role_permissions'):
        with defer_rbac_cache():
            team1.delete()
            team2.delete()
            mock_team.assert_not_called()
        mock_team.assert_called_once()


# --- Auto-wrapping tests (connect_rbac_signals) ---


@pytest.mark.django_db
def test_registered_model_delete_activates_defer(organization, inventory, rando, inv_rd):
    """Delete a registered model instance and verify that _defer_rbac_cache
    was active during the delete signal (the auto-wrapping took effect)."""
    inv_rd.give_permission(rando, inventory)

    defer_active_during_signal = []

    def record_defer_state(sender, instance, **kwargs):
        defer_active_during_signal.append(_defer_rbac_cache.active)

    pre_delete.connect(record_defer_state, sender=Inventory)
    try:
        inventory.delete()
    finally:
        pre_delete.disconnect(record_defer_state, sender=Inventory)

    assert len(defer_active_during_signal) == 1
    assert defer_active_during_signal[0] is True


@pytest.mark.django_db
def test_cascading_delete_activates_defer_once(organization, org_team_member_rd):
    """Delete an org that has teams and inventories.  The org's delete()
    enters defer_rbac_cache; bulk pre-cascade cleanup handles all RBAC
    work before Django's cascade fires.  Since all teams are being
    deleted (no survivors outside the org), compute_team_member_roles
    is not called at all -- there are no teams left to recompute."""
    team1 = Team.objects.create(name='cascade-t1', organization=organization)
    team2 = Team.objects.create(name='cascade-t2', organization=organization)
    Team.objects.create(name='cascade-survivor', organization=organization)
    Inventory.objects.create(name='cascade-inv1', organization=organization)
    Inventory.objects.create(name='cascade-inv2', organization=organization)

    org_team_member_rd.give_permission(team1, organization)
    org_team_member_rd.give_permission(team2, organization)

    with patch('ansible_base.rbac.triggers.compute_team_member_roles') as mock_ctmr, patch('ansible_base.rbac.triggers.compute_object_role_permissions'):
        organization.delete()

    # Bulk pre-cascade cleanup handles everything; all teams are being deleted
    # so there are no team IDs that need recomputation
    mock_ctmr.assert_not_called()


@pytest.mark.django_db
def test_org_cascade_delete_correct_end_state(rando, inv_rd):
    """Functional test (no mocking).  Create an org with 3 teams,
    3 inventories, and role assignments on each.  Delete the org
    (which auto-wraps in defer).  Verify all evaluations, assignments,
    and ObjectRoles are cleaned up."""
    org = Organization.objects.create(name='cascade-functional-org')
    teams = [Team.objects.create(name=f'cf-team-{i}', organization=org) for i in range(3)]
    inventories = [Inventory.objects.create(name=f'cf-inv-{i}', organization=org) for i in range(3)]

    ct_inv = permission_registry.content_type_model.objects.get_for_model(Inventory)
    ct_org = permission_registry.content_type_model.objects.get_for_model(Organization)

    # Assign inventory roles to teams and give rando a direct role
    for team, inv in zip(teams, inventories):
        inv_rd.give_permission(team, inv)
    inv_rd.give_permission(rando, inventories[0])

    team_ids = [t.id for t in teams]
    inv_ids = [i.id for i in inventories]
    org_pk = org.pk

    org.delete()

    # All evaluations for org and inventories are gone
    assert not RoleEvaluation.objects.filter(content_type_id=ct_org.pk, object_id=org_pk).exists()
    for inv_id in inv_ids:
        assert not RoleEvaluation.objects.filter(content_type_id=ct_inv.pk, object_id=inv_id).exists()

    # All team assignments are gone
    assert not RoleTeamAssignment.objects.filter(team_id__in=team_ids).exists()

    # No orphan ObjectRoles remain
    assert not ObjectRole.objects.filter(users__isnull=True, teams__isnull=True).exists()

    # User no longer has any assignments to deleted objects
    assert not RoleUserAssignment.objects.filter(user_id=rando.id).exists()


@pytest.mark.django_db
def test_delete_wrapping_preserves_return_value(organization):
    """Call instance.delete() on a registered model and verify it returns
    the standard Django delete tuple (count, {model_label: count}).
    The wrapping should be transparent."""
    inv = Inventory.objects.create(name='return-val-inv', organization=organization)
    result = inv.delete()

    assert isinstance(result, tuple)
    assert len(result) == 2
    count, details = result
    assert isinstance(count, int)
    assert count >= 1
    assert isinstance(details, dict)


@pytest.mark.django_db
@pytest.mark.parametrize(
    'model_cls',
    [Inventory, Organization, Team],
    ids=['Inventory', 'Organization', 'Team'],
)
def test_delete_wrapping_preserves_method_metadata(model_cls):
    """Verify that the wrapped delete() method has the same __name__
    and __doc__ as the original (via functools.wraps)."""
    assert model_cls.delete.__name__ == 'delete'
    # functools.wraps sets __wrapped__ to the original function
    assert hasattr(model_cls.delete, '__wrapped__')


# --- Re-entrant defer tests ---


@pytest.mark.django_db
def test_manual_defer_wrapping_org_delete(rando, inv_rd):
    """Explicitly wrap an org delete in defer_rbac_cache().  Since
    connect_rbac_signals already wraps delete(), this creates a nested
    entry.  Verify no RuntimeError and correct end state."""
    org = Organization.objects.create(name='manual-defer-org')
    inv = Inventory.objects.create(name='manual-defer-inv', organization=org)
    inv_rd.give_permission(rando, inv)

    ct_inv = permission_registry.content_type_model.objects.get_for_model(Inventory)

    with defer_rbac_cache():
        org.delete()  # auto-wrapped delete enters defer again (nested / re-entrant)

    # All evaluations and assignments cleaned up
    assert not RoleEvaluation.objects.filter(content_type_id=ct_inv.pk, object_id=inv.pk).exists()
    assert not RoleUserAssignment.objects.filter(user_id=rando.id).exists()


@pytest.mark.django_db
def test_reentrant_defer_exception_in_inner(organization, inventory, rando, org_inv_rd):
    """Inside outer defer_rbac_cache, enter inner defer_rbac_cache and
    raise an exception.  The inner exit is a no-op even on exception;
    the outer finally still flushes correctly."""
    inv_gfk = gfk_filter(inventory)

    with defer_rbac_cache():
        org_inv_rd.give_permission(rando, organization)

        def _raise_in_inner_defer():
            with defer_rbac_cache():
                raise RuntimeError('boom')

        with pytest.raises(RuntimeError):
            _raise_in_inner_defer()

        # Still inside outer -- no flush yet
        assert not RoleEvaluation.objects.filter(**inv_gfk).exists()

    # After outer exits, evaluations should be flushed
    assert RoleEvaluation.objects.filter(**inv_gfk).exists()
    assert rando.has_obj_perm(inventory, 'change')


# --- Negative test ---


@pytest.mark.django_db
def test_non_registered_model_delete_no_wrapping():
    """Verify that a model NOT registered in the permission registry
    does NOT have its delete() wrapped with defer_rbac_cache.  Creating
    and deleting a non-registered model should never activate defer."""
    # ExampleEvent is explicitly not registered in the permission registry
    assert ExampleEvent not in permission_registry._registry
    assert not hasattr(ExampleEvent.delete, '__wrapped__')

    event = ExampleEvent.objects.create(name='unregistered-event')

    defer_active_during_signal = []

    def record_defer_state(sender, instance, **kwargs):
        defer_active_during_signal.append(_defer_rbac_cache.active)

    pre_delete.connect(record_defer_state, sender=ExampleEvent)
    try:
        event.delete()
    finally:
        pre_delete.disconnect(record_defer_state, sender=ExampleEvent)

    assert len(defer_active_during_signal) == 1
    assert defer_active_during_signal[0] is False


# --- Edge case tests ---


@pytest.mark.django_db
def test_non_team_delete_skips_team_recomputation(inventory, rando, inv_rd):
    """Deleting a non-team registered object (inventory) should not
    trigger the team branch of rbac_post_delete_remove_object_roles.
    ObjectRole and RoleEvaluation cleanup should still happen."""
    inv_gfk = gfk_filter(inventory)
    assignment = inv_rd.give_permission(rando, inventory)

    with (
        patch('ansible_base.rbac.triggers.compute_team_member_roles') as mock_team,
        patch('ansible_base.rbac.triggers.compute_object_role_permissions') as mock_obj,
    ):
        inventory.delete()

    mock_team.assert_not_called()
    mock_obj.assert_not_called()
    assert not RoleEvaluation.objects.filter(**inv_gfk).exists()
    assert not ObjectRole.objects.filter(id=assignment.object_role_id).exists()


@pytest.mark.django_db
def test_team_delete_no_assignments_no_orphan_cleanup(organization):
    """Deleting a team with no role assignments should complete without
    error. The orphan cleanup query runs but deleted_count is 0, so no
    orphan-related log message should be emitted."""
    team = Team.objects.create(name='empty-team', organization=organization)

    with patch('ansible_base.rbac.triggers.logger') as mock_logger:
        team.delete()

    orphan_info_calls = [c for c in mock_logger.info.call_args_list if 'orphan' in str(c).lower()]
    assert len(orphan_info_calls) == 0


@pytest.mark.django_db
def test_defer_rbac_cache_discards_on_exception(organization, inventory, rando, org_inv_rd):
    """When an exception is raised inside defer_rbac_cache, the deferred
    compute calls should NOT run -- evaluations should not exist after a
    rollback because the underlying DB state is invalid."""
    inv_gfk = gfk_filter(inventory)

    def _grant_and_raise():
        with defer_rbac_cache():
            org_inv_rd.give_permission(rando, organization)
            raise RuntimeError('deliberate test exception')

    with pytest.raises(RuntimeError, match='deliberate'):
        _grant_and_raise()

    assert not RoleEvaluation.objects.filter(**inv_gfk).exists()
    assert not rando.has_obj_perm(inventory, 'change')


@pytest.mark.django_db
def test_defer_rbac_cache_discards_state_on_exception():
    """After an exception in defer_rbac_cache, all thread-local state
    (active, team_ids, object_roles) should be reset to initial values."""

    def _raise_with_state():
        with defer_rbac_cache():
            _defer_rbac_cache.team_ids.update({1, 2, 3})
            _defer_rbac_cache.object_roles.add(MagicMock())
            raise RuntimeError('boom')

    with pytest.raises(RuntimeError, match='boom'):
        _raise_with_state()

    assert _defer_rbac_cache.active is False
    assert _defer_rbac_cache.team_ids == set()
    assert _defer_rbac_cache.object_roles == set()
    assert _defer_rbac_cache.skip_post_delete_rbac is False


@pytest.mark.django_db
@pytest.mark.parametrize(
    'has_inventory',
    [False, True],
    ids=['no-children', 'with-inventory'],
)
def test_org_delete_no_teams(rando, inv_rd, has_inventory):
    """Deleting an org with no teams should complete without error,
    clean up all evaluations, and never trigger team-related
    recomputation. Parameterized with and without child inventories."""
    org = Organization.objects.create(name='no-team-org')
    org_gfk = gfk_filter(org)

    assignment = None
    inv_gfk = None
    if has_inventory:
        inv = Inventory.objects.create(name='inv-in-org', organization=org)
        inv_gfk = gfk_filter(inv)
        assignment = inv_rd.give_permission(rando, inv)

    with patch('ansible_base.rbac.triggers.compute_team_member_roles') as mock_team:
        org.delete()

    mock_team.assert_not_called()
    assert not RoleEvaluation.objects.filter(**org_gfk).exists()
    if has_inventory:
        assert not RoleEvaluation.objects.filter(**inv_gfk).exists()
        assert not ObjectRole.objects.filter(id=assignment.object_role_id).exists()
        assert not RoleUserAssignment.objects.filter(user_id=rando.id).exists()


# --- Unit-perf regression tests ---


@pytest.mark.django_db
@pytest.mark.parametrize('num_teams', [1, 5, 10])
def test_defer_rbac_cache_compute_calls_constant_with_team_count(num_teams, org_team_member_rd):
    """Regardless of how many teams are in the deleted org, bulk
    pre-cascade cleanup handles RBAC work before the cascade fires.
    Since all teams are children of the deleted org, no team membership
    recomputation is needed (compute_team_member_roles is not called).
    compute_object_role_permissions is called at most once for any
    indirectly affected roles."""
    org = Organization.objects.create(name='perf-test-org')
    Team.objects.create(name='survivor-team', organization=org)

    teams = [Team.objects.create(name=f'perf-team-{i}', organization=org) for i in range(num_teams)]
    for team in teams:
        org_team_member_rd.give_permission(team, org)

    with (
        patch('ansible_base.rbac.triggers.compute_team_member_roles') as mock_team,
        patch('ansible_base.rbac.triggers.compute_object_role_permissions') as mock_obj,
    ):
        with defer_rbac_cache():
            org.delete()

    # All teams are being deleted, so no team membership recomputation needed
    assert mock_team.call_count == 0
    assert mock_obj.call_count <= 1


@pytest.mark.django_db
@pytest.mark.parametrize('num_teams', [1, 5, 10])
def test_defer_rbac_cache_orphan_cleanup_constant_with_team_count(num_teams, inv_rd):
    """Regardless of how many teams are deleted, orphan cleanup should
    run exactly once when using defer_rbac_cache (O(1) not O(N))."""
    org = Organization.objects.create(name='orphan-perf-org')
    teams = [Team.objects.create(name=f'orphan-team-{i}', organization=org) for i in range(num_teams)]
    for team in teams:
        inv = Inventory.objects.create(name=f'inv-for-{team.name}', organization=org)
        inv_rd.give_permission(team, inv)

    with patch.object(ObjectRole.objects, 'filter', wraps=ObjectRole.objects.filter) as mock_filter:
        with defer_rbac_cache():
            org.delete()

    orphan_calls = [c for c in mock_filter.call_args_list if c.kwargs.get('users__isnull') is True and c.kwargs.get('teams__isnull') is True]
    assert len(orphan_calls) == 1


@pytest.mark.django_db
def test_without_defer_compute_calls_scale_with_teams(org_team_member_rd):
    """Without defer_rbac_cache, compute_team_member_roles is called once
    per team deletion -- O(N). This baseline proves the deferral
    optimization actually changes behavior."""
    from contextlib import nullcontext

    org = Organization.objects.create(name='baseline-org')
    teams = [Team.objects.create(name=f'baseline-team-{i}', organization=org) for i in range(3)]
    for team in teams:
        org_team_member_rd.give_permission(team, org)

    with (
        patch('ansible_base.rbac.triggers.defer_rbac_cache', nullcontext),
        patch('ansible_base.rbac.triggers.compute_team_member_roles') as mock_team,
        patch('ansible_base.rbac.triggers.compute_object_role_permissions'),
    ):
        org.delete()

    assert mock_team.call_count == 3


@pytest.mark.django_db
@pytest.mark.parametrize('num_children', [1, 5, 10])
def test_defer_rbac_cache_compute_calls_constant_with_child_count(num_children, rando, inv_rd, org_team_member_rd):
    """Regardless of how many child objects (inventories) exist in an org,
    bulk pre-cascade cleanup handles RBAC work before the cascade.
    Since all teams are children of the deleted org, no team membership
    recomputation is needed.  compute_object_role_permissions is called
    at most once for any indirectly affected roles."""
    org = Organization.objects.create(name='child-perf-org')
    team = Team.objects.create(name='child-perf-team', organization=org)
    Team.objects.create(name='child-survivor', organization=org)
    org_team_member_rd.give_permission(team, org)

    for i in range(num_children):
        inv = Inventory.objects.create(name=f'child-inv-{i}', organization=org)
        inv_rd.give_permission(rando, inv)

    with (
        patch('ansible_base.rbac.triggers.compute_team_member_roles') as mock_team,
        patch('ansible_base.rbac.triggers.compute_object_role_permissions') as mock_obj,
    ):
        with defer_rbac_cache():
            org.delete()

    # All teams are being deleted, so no team membership recomputation needed
    assert mock_team.call_count == 0
    assert mock_obj.call_count <= 1


# --- Bulk pre-cascade cleanup tests ---


@pytest.mark.django_db
def test_bulk_pre_cascade_skips_signal_handler(organization, inv_rd, rando):
    """When an org with children is deleted, the bulk pre-cascade cleanup
    runs and sets skip_post_delete_rbac=True.  The per-object signal
    handler should be skipped for all cascaded children."""
    inv = Inventory.objects.create(name='bulk-inv', organization=organization)
    Team.objects.create(name='bulk-team', organization=organization)
    inv_rd.give_permission(rando, inv)

    signal_states = []

    def tracking_handler(instance, *args, **kwargs):
        signal_states.append((instance._meta.model_name, _defer_rbac_cache.skip_post_delete_rbac))

    from django.db.models.signals import post_delete as pd_signal

    # Connect our tracking handler for all registered models
    for cls in permission_registry._registry:
        pd_signal.connect(tracking_handler, sender=cls, dispatch_uid=f'track-{cls._meta.model_name}')

    try:
        organization.delete()
    finally:
        for cls in permission_registry._registry:
            pd_signal.disconnect(tracking_handler, sender=cls, dispatch_uid=f'track-{cls._meta.model_name}')

    # Signals fired for cascaded children, and every handler saw skip=True
    assert len(signal_states) > 0
    assert all(skip for _, skip in signal_states), f"Expected all skip=True, got: {signal_states}"


@pytest.mark.django_db
def test_bulk_pre_cascade_leaf_model_no_skip(inventory, rando, inv_rd):
    """Deleting a leaf model (no RBAC-registered children) should NOT
    set the skip flag.  The signal handler should run normally."""
    inv_rd.give_permission(rando, inventory)

    from ansible_base.rbac.triggers import _defer_rbac_cache

    skip_states = []

    def capture_skip(instance, *args, **kwargs):
        skip_states.append(_defer_rbac_cache.skip_post_delete_rbac)

    from django.db.models.signals import post_delete as pd_signal

    pd_signal.connect(capture_skip, sender=Inventory, dispatch_uid='capture-skip')
    try:
        inventory.delete()
    finally:
        pd_signal.disconnect(capture_skip, sender=Inventory, dispatch_uid='capture-skip')

    # For leaf models, bulk cleanup returns early and does NOT set the skip flag
    assert len(skip_states) == 1
    assert skip_states[0] is False


@pytest.mark.django_db
def test_bulk_pre_cascade_reduces_query_count(rando, inv_rd, org_team_member_rd):
    """Verify that the per-team query overhead during org deletion is
    lower with bulk pre-cascade cleanup than without it.

    Django's cascade mechanism and pre_delete signals still generate
    per-object queries, so we cannot achieve O(1) total queries.  But
    the RBAC-specific work (ObjectRole/RoleEvaluation cleanup, team
    recomputation) is batched into bulk queries, significantly reducing
    the per-team overhead compared to the old per-signal approach."""
    from contextlib import nullcontext

    from django.db import connection, reset_queries
    from django.test.utils import override_settings

    num_teams = 10

    def setup_and_delete(use_bulk):
        """Create an org with teams and inventories, then delete it.
        Returns the query count during the delete operation."""
        org = Organization.objects.create(name=f'qc-org-{"bulk" if use_bulk else "signal"}')
        teams = [Team.objects.create(name=f'qc-t-{i}', organization=org) for i in range(num_teams)]
        for team in teams:
            org_team_member_rd.give_permission(team, org)
        for i in range(3):
            inv = Inventory.objects.create(name=f'qc-inv-{i}', organization=org)
            inv_rd.give_permission(rando, inv)

        reset_queries()
        if use_bulk:
            org.delete()  # uses bulk pre-cascade cleanup
        else:
            with patch('ansible_base.rbac.triggers.defer_rbac_cache', nullcontext):
                org.delete()  # falls back to per-signal handler
        return len(connection.queries)

    with override_settings(DEBUG=True):
        bulk_queries = setup_and_delete(use_bulk=True)
        signal_queries = setup_and_delete(use_bulk=False)

    # Bulk approach should use fewer queries than per-signal approach
    assert bulk_queries < signal_queries, f'Expected bulk ({bulk_queries}) < signal ({signal_queries}) queries'


@pytest.mark.django_db
def test_bulk_pre_cascade_standalone_team_delete(organization, inv_rd):
    """Deleting a standalone team (not via org cascade) should NOT use
    bulk cleanup (teams have no RBAC-registered children).  The signal
    handler should run normally and clean up correctly."""
    team = Team.objects.create(name='standalone-team', organization=organization)
    inv = Inventory.objects.create(name='standalone-inv', organization=organization)
    inv_rd.give_permission(team, inv)

    team_id = team.id
    obj_role_id = (
        ObjectRole.objects.filter(
            content_type=permission_registry.content_type_model.objects.get_for_model(Inventory),
            object_id=inv.pk,
        )
        .first()
        .id
    )

    team.delete()

    # Team assignments cleaned up
    assert not RoleTeamAssignment.objects.filter(team_id=team_id).exists()
    # ObjectRole orphan cleaned up
    assert not ObjectRole.objects.filter(id=obj_role_id).exists()
    # Inventory still exists (not cascade-deleted)
    assert Inventory.objects.filter(id=inv.id).exists()


@pytest.mark.django_db
def test_bulk_pre_cascade_no_children_noop(organization):
    """Deleting an org with no children should not error and the bulk
    cleanup should be a no-op (no children found)."""
    # Remove all children first
    Team.objects.filter(organization=organization).delete()
    Inventory.objects.filter(organization=organization).delete()

    # This should not raise
    organization.delete()

    assert not Organization.objects.filter(id=organization.id).exists()


# --- Raw SQL Delete Safety Guardrails ---


def _get_signal_receivers(signal, model):
    """Return a list of (dispatch_uid, receiver_name) for signal handlers
    connected to *model*.

    Django stores the sender in the key tuple as id(sender) when
    dispatch_uid is set, or as a weakref otherwise.  The receiver itself
    is stored as a weakref.ref to the actual function."""
    model_id = id(model)
    results = []
    for entry in signal.receivers:
        key = entry[0]
        receiver = entry[1]
        dispatch_uid = key[0]
        sender_ref = key[1]

        # Match sender: Django uses id(sender) for dispatch_uid registrations
        if isinstance(sender_ref, int):
            if sender_ref != model_id:
                continue
        elif isinstance(sender_ref, weakref.ref):
            if sender_ref() is not model:
                continue
        else:
            continue

        # Dereference the receiver (stored as weakref.ref)
        actual_receiver = receiver() if isinstance(receiver, weakref.ref) else receiver
        recv_name = getattr(actual_receiver, '__name__', repr(actual_receiver))
        results.append((dispatch_uid, recv_name))
    return results


@pytest.mark.django_db
class TestRawSQLDeleteSafetyIntrospection:
    """CI guardrails: verify that raw SQL delete in _bulk_delete_and_accumulate_sync
    is safe by asserting no unexpected signal handlers are connected to the
    models it bypasses."""

    # The ONLY expected pre_delete handler on the assignment models is the
    # activitystream_delete handler from AuditableModel.  Raw SQL delete
    # bypasses this but manually calls _log_audit_entry for the same effect.
    _EXPECTED_ASSIGNMENT_PRE_DELETE_UIDS = {
        # Pattern: dab_activitystream_{ModelName}_delete
        'dab_activitystream_RoleUserAssignment_delete',
        'dab_activitystream_RoleTeamAssignment_delete',
    }

    @pytest.mark.parametrize(
        'model,expected_uid',
        [
            (RoleUserAssignment, 'dab_activitystream_RoleUserAssignment_delete'),
            (RoleTeamAssignment, 'dab_activitystream_RoleTeamAssignment_delete'),
        ],
        ids=['RoleUserAssignment', 'RoleTeamAssignment'],
    )
    def test_assignment_pre_delete_only_activitystream(self, model, expected_uid):
        """Assert that the only pre_delete handler on assignment models is
        activitystream_delete.  Raw SQL delete bypasses all Django signals;
        if a new handler is added, this test fails to alert the developer
        to update the bypass code in _bulk_delete_and_accumulate_sync."""
        from django.db.models.signals import pre_delete

        receivers = _get_signal_receivers(pre_delete, model)
        uids = {uid for uid, _ in receivers}
        assert uids == {expected_uid}, (
            f"Unexpected pre_delete handlers on {model.__name__}: {uids}. "
            f"Raw SQL delete in _bulk_delete_and_accumulate_sync bypasses Django signals. "
            f"If you added a new handler, update the bypass code to replicate its effect."
        )

    @pytest.mark.parametrize(
        'model',
        [RoleUserAssignment, RoleTeamAssignment],
        ids=['RoleUserAssignment', 'RoleTeamAssignment'],
    )
    def test_assignment_no_post_delete_handlers(self, model):
        """Assignment models must have no post_delete handlers.
        Raw SQL delete skips all signals; a new post_delete handler
        would silently never fire for bulk deletes."""
        from django.db.models.signals import post_delete

        receivers = _get_signal_receivers(post_delete, model)
        assert receivers == [], f"Unexpected post_delete handlers on {model.__name__}: {receivers}. " f"Raw SQL delete bypasses all Django signals."

    @pytest.mark.parametrize(
        'model',
        [ObjectRole, RoleEvaluation, RoleEvaluationUUID],
        ids=['ObjectRole', 'RoleEvaluation', 'RoleEvaluationUUID'],
    )
    def test_no_activity_stream_signals(self, model):
        """ObjectRole, RoleEvaluation, and RoleEvaluationUUID do NOT inherit
        AuditableModel and should have no activitystream signal handlers."""
        from django.db.models.signals import post_delete, pre_delete

        for sig_name, sig in [('pre_delete', pre_delete), ('post_delete', post_delete)]:
            receivers = _get_signal_receivers(sig, model)
            activitystream_receivers = [(uid, name) for uid, name in receivers if 'activitystream' in uid]
            assert activitystream_receivers == [], (
                f"{model.__name__} has unexpected activitystream {sig_name} handlers: "
                f"{activitystream_receivers}. ObjectRole and RoleEvaluation models "
                f"should NOT inherit AuditableModel."
            )


@pytest.mark.django_db
class TestObjectRoleFKCascadeConstraints:
    """Verify that all FK fields pointing to ObjectRole use on_delete=CASCADE.
    The raw SQL delete in _bulk_delete_and_accumulate_sync deletes children
    explicitly in bottom-up order, relying on these being CASCADE relationships.
    If someone changes one to SET_NULL or PROTECT, the raw SQL delete would
    leave orphaned rows or break entirely."""

    def test_all_related_objects_use_cascade(self):
        """Every model with an FK to ObjectRole must use on_delete=CASCADE."""
        from django.db import models

        for related in ObjectRole._meta.related_objects:
            assert related.on_delete == models.CASCADE, (
                f"{related.related_model.__name__}.{related.field.name} uses "
                f"on_delete={related.on_delete.__name__} instead of CASCADE. "
                f"Raw SQL delete in _bulk_delete_and_accumulate_sync deletes "
                f"children in bottom-up order and relies on CASCADE semantics."
            )

    def test_expected_related_models(self):
        """The set of models with FK to ObjectRole must be exactly the set
        we handle in _bulk_delete_and_accumulate_sync.  If a new model adds
        an FK to ObjectRole, this test fails so the developer knows to add
        a DELETE statement for it in the raw SQL path."""
        expected_related = {
            'RoleUserAssignment',
            'RoleTeamAssignment',
            'RoleEvaluation',
            'RoleEvaluationUUID',
        }
        actual_related = {rel.related_model.__name__ for rel in ObjectRole._meta.related_objects}
        assert actual_related == expected_related, (
            f"Models with FK to ObjectRole changed. Expected: {expected_related}, "
            f"got: {actual_related}. Update _bulk_delete_and_accumulate_sync "
            f"to handle the new/removed model."
        )


@pytest.mark.django_db
class TestRBACModelsNotSwappable:
    """RoleUserAssignment, RoleTeamAssignment, ObjectRole, and RoleEvaluation
    must be concrete DAB models, not abstract or swappable.  The raw SQL
    delete hardcodes their table names; swappable or abstract models would
    break the bypass."""

    @pytest.mark.parametrize(
        'model',
        [RoleUserAssignment, RoleTeamAssignment, ObjectRole, RoleEvaluation, RoleEvaluationUUID],
        ids=['RoleUserAssignment', 'RoleTeamAssignment', 'ObjectRole', 'RoleEvaluation', 'RoleEvaluationUUID'],
    )
    def test_model_is_concrete(self, model):
        assert not model._meta.abstract, f"{model.__name__} must not be abstract"
        assert not getattr(model._meta, 'swappable', None), f"{model.__name__} must not be swappable"


@pytest.mark.django_db
class TestCascadeSizeCheck:
    """Tests for _check_cascade_size which guards against excessively large
    cascade deletes that would consume too much memory for audit logging."""

    def test_under_limit_passes(self, organization, team, rando, inv_rd):
        """Org with small RBAC data deletes without error when limit is high."""
        inv = Inventory.objects.create(name='small-inv', organization=organization)
        inv_rd.give_permission(rando, inv)
        # Default limit is 50_000 which is way above what we create here
        organization.delete()
        assert not Organization.objects.filter(id=organization.id).exists()

    @override_settings(ANSIBLE_BASE_RBAC_CASCADE_DELETE_CHILD_OBJECT_LIMIT=5)
    def test_over_limit_raises_validation_error(self, organization, team, rando, inv_rd):
        """With a low limit setting, ValidationError is raised before any
        data is deleted."""
        # Create enough RBAC data to exceed the limit of 5
        for i in range(4):
            inv = Inventory.objects.create(name=f'limit-inv-{i}', organization=organization)
            inv_rd.give_permission(rando, inv)

        with pytest.raises(ValidationError, match='exceeds the limit'):
            organization.delete()
        # Org still exists because the delete was rejected
        assert Organization.objects.filter(id=organization.id).exists()

    @override_settings(ANSIBLE_BASE_RBAC_CASCADE_DELETE_CHILD_OBJECT_LIMIT=0)
    def test_zero_limit_disables_check(self, organization, rando, inv_rd):
        """Setting limit to 0 disables the check entirely, allowing
        arbitrarily large cascade deletes."""
        for i in range(10):
            inv = Inventory.objects.create(name=f'nolimit-inv-{i}', organization=organization)
            inv_rd.give_permission(rando, inv)
        # Should not raise even with many children
        organization.delete()
        assert not Organization.objects.filter(id=organization.id).exists()

    @override_settings(ANSIBLE_BASE_RBAC_CASCADE_DELETE_CHILD_OBJECT_LIMIT=5)
    def test_error_message_includes_counts(self, organization, rando, inv_rd):
        """The error message includes the cascade count and the configured limit."""
        for i in range(4):
            inv = Inventory.objects.create(name=f'msg-inv-{i}', organization=organization)
            inv_rd.give_permission(rando, inv)

        with pytest.raises(ValidationError) as exc_info:
            organization.delete()

        error_msg = str(exc_info.value.detail)
        assert 'limit of 5' in error_msg
        assert 'cascade-delete' in error_msg

    @override_settings(ANSIBLE_BASE_RBAC_CASCADE_DELETE_CHILD_OBJECT_LIMIT=5)
    def test_cascade_limit_returns_http_400(self, admin_api_client, organization, rando, inv_rd):
        """Verify that the cascade size limit surfaces as HTTP 400 (not 500)
        through a real API DELETE request.  This validates that DRF's
        exception handler properly catches the ValidationError raised deep
        in the _check_cascade_size call chain."""
        for i in range(4):
            inv = Inventory.objects.create(name=f'api-inv-{i}', organization=organization)
            inv_rd.give_permission(rando, inv)

        url = get_relative_url('organization-detail', kwargs={'pk': organization.pk})
        response = admin_api_client.delete(url)

        assert response.status_code == 400, f"Expected 400, got {response.status_code}: {response.data}"
        assert 'exceeds the limit' in str(response.data)
        # Org must still exist (transaction rolled back)
        assert Organization.objects.filter(id=organization.id).exists()


@pytest.mark.django_db
class TestRawSQLDeleteFunctional:
    """Functional tests for _bulk_delete_and_accumulate_sync to verify that
    the raw SQL path cleans up all RBAC data correctly."""

    def test_raw_sql_delete_cleans_all_rbac_data(self, organization, team, rando, inv_rd):
        """After org delete with raw SQL path, all ObjectRoles, assignments,
        and evaluations are cleaned up."""
        inv = Inventory.objects.create(name='raw-sql-inv', organization=organization)
        inv_rd.give_permission(rando, inv)
        inv_rd.give_permission(team, inv)

        user_id = rando.id
        team_id = team.id
        ct_inv = permission_registry.content_type_model.objects.get_for_model(inv)
        inv_filter = {'object_id': inv.pk, 'content_type_id': ct_inv.pk}

        organization.delete()

        assert not ObjectRole.objects.filter(**inv_filter).exists()
        assert not RoleEvaluation.objects.filter(**inv_filter).exists()
        assert not RoleUserAssignment.objects.filter(user_id=user_id).exists()
        assert not RoleTeamAssignment.objects.filter(team_id=team_id).exists()

    def test_raw_sql_delete_emits_audit_log_entries(self, organization, team, rando, inv_rd):
        """After delete, audit log entries are emitted for deleted assignments
        via _log_audit_entry (not signals)."""
        inv = Inventory.objects.create(name='audit-inv', organization=organization)
        inv_rd.give_permission(rando, inv)
        inv_rd.give_permission(team, inv)

        with patch('ansible_base.activitystream.signals._log_audit_entry') as mock_log:
            organization.delete()

        # At least one audit entry per assignment type
        assert mock_log.call_count >= 2, f"Expected at least 2 audit log calls (1 RUA + 1 RTA), got {mock_log.call_count}"
        # Verify all calls used operation='delete'
        for call in mock_log.call_args_list:
            assert call.kwargs.get('operation') == 'delete'


class TestRawSQLDeleteObjectRoles:
    """Unit tests for _raw_sql_delete_object_roles helper."""

    @pytest.mark.django_db
    def test_deletes_object_roles_and_all_children(self, organization, team, rando, inv_rd):
        """Create ObjectRoles with assignments, call the function, verify all rows deleted."""
        from django.db import connection

        from ansible_base.rbac.triggers import _raw_sql_delete_object_roles

        inv = Inventory.objects.create(name='sql-del-inv', organization=organization)
        inv_rd.give_permission(rando, inv)
        inv_rd.give_permission(team, inv)

        ct_inv = permission_registry.content_type_model.objects.get_for_model(inv)
        object_role_ids = list(ObjectRole.objects.filter(content_type=ct_inv, object_id=inv.pk).values_list('id', flat=True))
        assert len(object_role_ids) > 0

        # Verify child rows exist before deletion
        assert RoleUserAssignment.objects.filter(object_role_id__in=object_role_ids).exists()
        assert RoleTeamAssignment.objects.filter(object_role_id__in=object_role_ids).exists()
        assert RoleEvaluation.objects.filter(role_id__in=object_role_ids).exists()

        _raw_sql_delete_object_roles(object_role_ids, connection)

        # All rows should be gone
        assert not ObjectRole.objects.filter(id__in=object_role_ids).exists()
        assert not RoleUserAssignment.objects.filter(object_role_id__in=object_role_ids).exists()
        assert not RoleTeamAssignment.objects.filter(object_role_id__in=object_role_ids).exists()
        assert not RoleEvaluation.objects.filter(role_id__in=object_role_ids).exists()
        assert not RoleEvaluationUUID.objects.filter(role_id__in=object_role_ids).exists()

    @pytest.mark.django_db
    def test_raw_sql_delete_object_roles_empty_list(self):
        """Calling _raw_sql_delete_object_roles with an empty list should
        return immediately without executing any SQL."""
        from django.db import connection

        from ansible_base.rbac.triggers import _raw_sql_delete_object_roles

        # Should not raise or execute any SQL
        _raw_sql_delete_object_roles([], connection)

    @pytest.mark.django_db
    def test_single_object_role_user_only(self, organization, rando, inv_rd):
        """Delete ObjectRoles that have only user assignments (no team assignments)."""
        from django.db import connection

        from ansible_base.rbac.triggers import _raw_sql_delete_object_roles

        inv = Inventory.objects.create(name='user-only-inv', organization=organization)
        inv_rd.give_permission(rando, inv)

        ct_inv = permission_registry.content_type_model.objects.get_for_model(inv)
        object_role_ids = list(ObjectRole.objects.filter(content_type=ct_inv, object_id=inv.pk).values_list('id', flat=True))
        assert len(object_role_ids) > 0
        assert RoleUserAssignment.objects.filter(object_role_id__in=object_role_ids).exists()
        assert not RoleTeamAssignment.objects.filter(object_role_id__in=object_role_ids).exists()

        _raw_sql_delete_object_roles(object_role_ids, connection)

        assert not ObjectRole.objects.filter(id__in=object_role_ids).exists()
        assert not RoleUserAssignment.objects.filter(object_role_id__in=object_role_ids).exists()
        assert not RoleEvaluation.objects.filter(role_id__in=object_role_ids).exists()


class TestRawSQLDeleteParentEvaluations:
    """Unit tests for _raw_sql_delete_parent_evaluations helper."""

    @pytest.mark.django_db
    def test_deletes_evaluations_for_parent_objects(self, organization, rando, org_inv_change_rd):
        """Create RoleEvaluations for objects, call the function, verify deleted."""
        from django.db import connection

        from ansible_base.rbac.triggers import _raw_sql_delete_parent_evaluations

        inv = Inventory.objects.create(name='parent-eval-inv', organization=organization)
        org_inv_change_rd.give_permission(rando, organization)

        ct_inv = permission_registry.content_type_model.objects.get_for_model(inv)
        assert RoleEvaluation.objects.filter(content_type_id=ct_inv.id, object_id=inv.pk).exists()

        _raw_sql_delete_parent_evaluations([(ct_inv, {inv.pk})], connection)

        assert not RoleEvaluation.objects.filter(content_type_id=ct_inv.id, object_id=inv.pk).exists()

    @pytest.mark.django_db
    def test_skips_empty_pk_lists(self):
        """Entries with empty pk sets should be skipped without error."""
        from django.db import connection

        from ansible_base.rbac.triggers import _raw_sql_delete_parent_evaluations

        ct = permission_registry.content_type_model.objects.get_for_model(Organization)
        # Should not raise
        _raw_sql_delete_parent_evaluations([(ct, set())], connection)

    @pytest.mark.django_db
    def test_multiple_content_types(self, organization, rando, org_inv_change_rd, inv_rd):
        """Handles multiple content types in a single call."""
        from django.db import connection

        from ansible_base.rbac.triggers import _raw_sql_delete_parent_evaluations

        inv1 = Inventory.objects.create(name='multi-ct-inv1', organization=organization)
        inv2 = Inventory.objects.create(name='multi-ct-inv2', organization=organization)
        org_inv_change_rd.give_permission(rando, organization)

        ct_inv = permission_registry.content_type_model.objects.get_for_model(Inventory)
        assert RoleEvaluation.objects.filter(content_type_id=ct_inv.id, object_id=inv1.pk).exists()
        assert RoleEvaluation.objects.filter(content_type_id=ct_inv.id, object_id=inv2.pk).exists()

        _raw_sql_delete_parent_evaluations([(ct_inv, {inv1.pk, inv2.pk})], connection)

        assert not RoleEvaluation.objects.filter(content_type_id=ct_inv.id, object_id=inv1.pk).exists()
        assert not RoleEvaluation.objects.filter(content_type_id=ct_inv.id, object_id=inv2.pk).exists()


class TestEmitAuditForDeletedAssignments:
    """Unit tests for _emit_audit_for_deleted_assignments helper."""

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        'assignment_type,row_key',
        [
            ('rua', 'user_id'),
            ('rta', 'team_id'),
        ],
        ids=['user_assignment', 'team_assignment'],
    )
    def test_calls_log_audit_entry_with_correct_args(self, assignment_type, row_key):
        """Pass in .values() dicts, mock _log_audit_entry, verify called with correct args."""
        from ansible_base.rbac.triggers import _emit_audit_for_deleted_assignments

        row = {'id': 42, row_key: 7, 'object_role_id': 99, 'role_definition_id': 3}
        user_assignment_rows = [row] if assignment_type == 'rua' else []
        team_assignment_rows = [row] if assignment_type == 'rta' else []

        with patch('ansible_base.activitystream.signals._log_audit_entry') as mock_log:
            _emit_audit_for_deleted_assignments(user_assignment_rows, team_assignment_rows)

        mock_log.assert_called_once()
        call_kwargs = mock_log.call_args.kwargs
        assert call_kwargs['operation'] == 'delete'
        assert 'removed_fields' in call_kwargs['changes']
        obj = call_kwargs['content_object']
        assert obj.pk == 42
        assert obj.id == 42
        assert obj.audit_log_enabled is True

    @pytest.mark.django_db
    def test_empty_lists_is_noop(self):
        """Empty row lists should not call _log_audit_entry."""
        from ansible_base.rbac.triggers import _emit_audit_for_deleted_assignments

        with patch('ansible_base.activitystream.signals._log_audit_entry') as mock_log:
            _emit_audit_for_deleted_assignments([], [])

        mock_log.assert_not_called()

    @pytest.mark.django_db
    def test_handles_import_error_gracefully(self):
        """When activity stream is not installed, ImportError is silently caught."""
        from ansible_base.rbac.triggers import _emit_audit_for_deleted_assignments

        row = {'id': 1, 'user_id': 2, 'object_role_id': 3, 'role_definition_id': 4}

        # Patch the import inside _emit_audit_for_deleted_assignments to raise ImportError
        import builtins

        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == 'ansible_base.activitystream.signals':
                raise ImportError('activity stream not installed')
            return original_import(name, *args, **kwargs)

        with patch.object(builtins, '__import__', side_effect=mock_import):
            # Should not raise -- ImportError is caught internally
            _emit_audit_for_deleted_assignments([row], [])

    @pytest.mark.django_db
    def test_multiple_rows_both_types(self):
        """Multiple rows for both assignment types are all processed."""
        from ansible_base.rbac.triggers import _emit_audit_for_deleted_assignments

        user_assignment_rows = [
            {'id': 1, 'user_id': 10, 'object_role_id': 100, 'role_definition_id': 5},
            {'id': 2, 'user_id': 11, 'object_role_id': 101, 'role_definition_id': 6},
        ]
        team_assignment_rows = [
            {'id': 3, 'team_id': 20, 'object_role_id': 102, 'role_definition_id': 7},
        ]

        with patch('ansible_base.activitystream.signals._log_audit_entry') as mock_log:
            _emit_audit_for_deleted_assignments(user_assignment_rows, team_assignment_rows)

        assert mock_log.call_count == 3
        # All calls should be delete operations
        for call in mock_log.call_args_list:
            assert call.kwargs['operation'] == 'delete'

    @pytest.mark.django_db
    def test_str_on_reconstructed_instance_does_not_crash(self, organization, rando, inv_rd):
        """Reconstructed instances from _emit_audit_for_deleted_assignments
        must produce a safe __str__ without accessing FK fields."""
        from ansible_base.rbac.triggers import _emit_audit_for_deleted_assignments

        inv = Inventory.objects.create(name='str-test-inv', organization=organization)
        assignment = inv_rd.give_permission(rando, inv)
        # Capture real .values() data
        user_rows = list(RoleUserAssignment.objects.filter(id=assignment.id).values())
        assert len(user_rows) == 1

        str_results = []

        def capturing_log(content_object, **kwargs):
            str_results.append(str(content_object))

        with patch('ansible_base.activitystream.signals._log_audit_entry', side_effect=capturing_log):
            _emit_audit_for_deleted_assignments(user_rows, [])

        assert len(str_results) == 1
        assert 'RoleUserAssignment' in str_results[0]
        assert str(user_rows[0]['id']) in str_results[0]


class TestEmailPolicySignal:
    """Tests for the pre_save signal that prevents unauthorized email
    changes across all services."""

    @pytest.mark.django_db
    def test_superuser_can_change_any_email(self):
        admin = User.objects.create(username='admin-su', is_superuser=True)
        alice = User.objects.create(username='alice', email='alice@example.com')
        with patch('crum.get_current_user', return_value=admin):
            alice.email = 'alice-new@example.com'
            alice.save()
        alice.refresh_from_db()
        assert alice.email == 'alice-new@example.com'

    @pytest.mark.django_db
    def test_regular_user_cannot_change_own_email(self):
        alice = User.objects.create(username='alice', email='alice@example.com')
        with patch('crum.get_current_user', return_value=alice):
            alice.email = 'hacked@evil.com'
            with pytest.raises(ValidationError) as exc_info:
                alice.save()
            assert 'email' in exc_info.value.detail
        alice.refresh_from_db()
        assert alice.email == 'alice@example.com'

    @pytest.mark.django_db
    def test_org_admin_can_change_member_email(self, organization):
        org_admin_rd = RoleDefinition.objects.managed.org_admin
        org_member_rd = RoleDefinition.objects.managed.org_member
        org_admin = User.objects.create(username='org-admin')
        member = User.objects.create(username='member', email='member@example.com')
        org_admin_rd.give_permission(org_admin, organization)
        org_member_rd.give_permission(member, organization)

        with patch('crum.get_current_user', return_value=org_admin):
            member.email = 'member-new@example.com'
            member.save()
        member.refresh_from_db()
        assert member.email == 'member-new@example.com'

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        'crum_user',
        [None, 'anonymous'],
        ids=['no-user', 'anonymous-user'],
    )
    def test_no_authenticated_user_allows_email_change(self, crum_user):
        """System operations (management commands, forward-sync) and
        pre-authentication contexts (JWT auth where CRUM returns
        AnonymousUser) should always be allowed."""
        from django.contrib.auth.models import AnonymousUser

        if crum_user == 'anonymous':
            crum_user = AnonymousUser()

        alice = User.objects.create(username='alice', email='alice@example.com')
        with patch('crum.get_current_user', return_value=crum_user):
            alice.email = 'alice-synced@example.com'
            alice.save()
        alice.refresh_from_db()
        assert alice.email == 'alice-synced@example.com'

    @pytest.mark.django_db
    def test_same_email_is_not_blocked(self):
        alice = User.objects.create(username='alice', email='alice@example.com')
        with patch('crum.get_current_user', return_value=alice):
            alice.email = 'alice@example.com'
            alice.save()
        alice.refresh_from_db()
        assert alice.email == 'alice@example.com'

    @pytest.mark.django_db
    def test_new_user_creation_is_not_blocked(self):
        alice = User.objects.create(username='alice', email='alice@example.com')
        with patch('crum.get_current_user', return_value=alice):
            bob = User.objects.create(username='bob', email='bob@example.com')
        bob.refresh_from_db()
        assert bob.email == 'bob@example.com'

    @pytest.mark.django_db
    @pytest.mark.parametrize(
        'requesting_user_type,expected_email',
        [
            ('superuser', 'changed@example.com'),
            ('regular', 'original@example.com'),
        ],
        ids=['superuser-allowed', 'regular-blocked'],
    )
    def test_email_change_by_user_type(self, requesting_user_type, expected_email):
        target = User.objects.create(username='target', email='original@example.com')
        if requesting_user_type == 'superuser':
            requestor = User.objects.create(username='requestor', is_superuser=True)
        else:
            requestor = User.objects.create(username='requestor')

        with patch('crum.get_current_user', return_value=requestor):
            target.email = 'changed@example.com'
            if requesting_user_type == 'regular':
                with pytest.raises(ValidationError):
                    target.save()
            else:
                target.save()
        target.refresh_from_db()
        assert target.email == expected_email

    @pytest.mark.django_db
    def test_update_fields_without_email_is_not_blocked(self):
        """When save(update_fields=...) excludes email, the signal
        should not fire even if instance.email was modified in memory."""
        alice = User.objects.create(username='alice', email='alice@example.com')
        with patch('crum.get_current_user', return_value=alice):
            alice.email = 'hacked@evil.com'
            alice.first_name = 'Alice'
            alice.save(update_fields=['first_name'])
        alice.refresh_from_db()
        assert alice.first_name == 'Alice'

    @pytest.mark.django_db
    def test_email_reverted_on_blocked_save(self):
        """Verify the in-memory email is reverted when the signal
        rejects the change, so the caller has a consistent state."""
        alice = User.objects.create(username='alice', email='alice@example.com')
        with patch('crum.get_current_user', return_value=alice):
            alice.email = 'hacked@evil.com'
            with pytest.raises(ValidationError):
                alice.save()
        assert alice.email == 'alice@example.com'

    def test_email_enforcement_signals_registered_by_default(self):
        """Verify that email enforcement signals are registered when
        EMAIL_ENFORCEMENT_VIA_SERIALIZER is False (the default)."""
        from django.db.models.signals import post_init, pre_save

        assert not User.EMAIL_ENFORCEMENT_VIA_SERIALIZER
        pre_save_uids = {r[0][0] for r in pre_save.receivers}
        post_init_uids = {r[0][0] for r in post_init.receivers}
        assert 'permission-registry-enforce-email' in pre_save_uids
        assert 'permission-registry-stash-email' in post_init_uids
