from unittest.mock import MagicMock, patch

import pytest
from django.apps import apps
from django.test.utils import override_settings
from rest_framework.exceptions import ValidationError

from ansible_base.rbac.caching import compute_team_member_roles
from ansible_base.rbac.models import ObjectRole, RoleDefinition, RoleEvaluation, RoleTeamAssignment, RoleUserAssignment
from ansible_base.rbac.permission_registry import permission_registry
from ansible_base.rbac.pipeline import bulk_give_permissions, bulk_remove_permissions
from ansible_base.rbac.triggers import dab_post_migrate, defer_rbac_computations, post_migration_rbac_setup
from test_app.models import Inventory, Organization, User


@pytest.mark.django_db
def test_post_migrate_signals():
    mck = MagicMock()
    # corresponds to docs/apps/rbac/for_app_developers.md, Post-migrate Actions
    dab_post_migrate.connect(mck.ad_hoc_func, dispatch_uid="my_logic")
    post_migration_rbac_setup(apps.get_app_config('dab_rbac'))
    mck.ad_hoc_func.assert_called_once_with(sender=apps.get_app_config('dab_rbac'), signal=dab_post_migrate)


@pytest.mark.django_db
def test_post_migrate_skips_recompute_when_no_migrations_applied():
    """post_migration_rbac_setup should skip recompute when the plan kwarg
    is an empty list, meaning no migrations were actually applied."""
    with (
        patch('ansible_base.rbac.triggers.compute_team_member_roles') as mock_team,
        patch('ansible_base.rbac.triggers.recompute_all_role_evaluations') as mock_obj,
    ):
        post_migration_rbac_setup(apps.get_app_config('dab_rbac'), plan=[])

    mock_team.assert_not_called()
    mock_obj.assert_not_called()


@pytest.mark.django_db
def test_post_migrate_runs_recompute_when_plan_has_entries():
    """post_migration_rbac_setup should call recompute functions when the
    plan kwarg contains migration entries."""
    with (
        patch('ansible_base.rbac.triggers.compute_team_member_roles') as mock_team,
        patch('ansible_base.rbac.triggers.recompute_all_role_evaluations') as mock_obj,
    ):
        post_migration_rbac_setup(apps.get_app_config('dab_rbac'), plan=[('fake_migration',)])

    mock_team.assert_called_once()
    mock_obj.assert_called_once()


@pytest.mark.django_db
def test_cleanup_orphaned_object_roles(organization, inv_rd):
    """cleanup_orphaned_object_roles deletes ObjectRoles with no assignments."""
    from ansible_base.rbac.caching import cleanup_orphaned_object_roles

    inv = Inventory.objects.create(name='orphan-test-inv', organization=organization)
    inv_rd.give_permission(User.objects.create(username='orphan-user'), inv)
    obj_role = ObjectRole.objects.get(role_definition=inv_rd, object_id=inv.pk)

    # Remove the assignment — ObjectRole is now orphaned
    obj_role.users.clear()
    assert not obj_role.users.exists()
    assert not obj_role.teams.exists()

    deleted = cleanup_orphaned_object_roles()
    assert deleted >= 1
    assert not ObjectRole.objects.filter(pk=obj_role.pk).exists()


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


def _defer_rbac_with_exception(organization):
    """Helper to ensure only one throwing invocation inside pytest.raises."""
    with defer_rbac_computations():
        Inventory.objects.create(name='error-inv', organization=organization)
        raise RuntimeError("deliberate")


@pytest.mark.django_db
def test_defer_rbac_computations_flushes_on_exception(organization, rando, org_inv_rd):
    """On exception, deferred data should still be flushed so RBAC stays consistent."""
    org_inv_rd.give_permission(rando, organization)

    with pytest.raises(RuntimeError, match="deliberate"):
        _defer_rbac_with_exception(organization)

    inv = Inventory.objects.get(name='error-inv')
    assert rando.has_obj_perm(inv, 'change')


@pytest.mark.django_db
def test_api_delete_uses_deferral_context_managers(admin_api_client, organization, rando, org_inv_rd):
    """DELETE via the API should use defer_rbac_computations, verified by
    checking that the context manager is active when the post_delete
    signal fires during the cascade."""
    from django.db.models.signals import post_delete

    from ansible_base.rbac.caching import defer_rbac_state

    org_inv_rd.give_permission(rando, organization)
    for i in range(3):
        Inventory.objects.create(name=f'defer-api-inv-{i}', organization=organization)

    was_active = []

    def check_defer(sender, instance, **kwargs):
        was_active.append(defer_rbac_state.active)

    post_delete.connect(check_defer, sender=Inventory)
    try:
        response = admin_api_client.delete(f'/api/v1/organizations/{organization.pk}/')
    finally:
        post_delete.disconnect(check_defer, sender=Inventory)

    assert response.status_code == 204
    assert len(was_active) == 3
    assert all(was_active), "defer_rbac_computations should have been active during delete"
    assert not Organization.objects.filter(pk=organization.pk).exists()


@pytest.mark.django_db
def test_defer_rbac_computations_defers_resource_creation(organization, rando, org_inv_rd):
    """Creating a child resource inside defer_rbac_computations should defer
    RoleEvaluation updates until the context manager exits."""
    org_inv_rd.give_permission(rando, organization)

    with defer_rbac_computations():
        inv = Inventory.objects.create(name='deferred-inv', organization=organization)
        inv_gfk = gfk_filter(inv)
        # During deferral, evaluations for the new inventory should not exist
        assert not RoleEvaluation.objects.filter(**inv_gfk).exists()

    # After exit, evaluations should be flushed
    assert RoleEvaluation.objects.filter(**inv_gfk).exists()
    assert rando.has_obj_perm(inv, 'change')


@pytest.mark.django_db
def test_defer_rbac_computations_multiple_resources(organization, rando, org_inv_rd):
    """Multiple resource creations inside defer_rbac_computations should
    all produce correct evaluations after the context exits."""
    second_org = Organization.objects.create(name='second-org')
    org_inv_rd.give_permission(rando, organization)
    org_inv_rd.give_permission(rando, second_org)

    with defer_rbac_computations():
        inv1 = Inventory.objects.create(name='inv1', organization=organization)
        inv2 = Inventory.objects.create(name='inv2', organization=second_org)

    assert rando.has_obj_perm(inv1, 'change')
    assert rando.has_obj_perm(inv2, 'change')


@pytest.mark.django_db
def test_defer_rbac_computations_cannot_be_nested():
    """Nesting defer_rbac_computations should raise a RuntimeError."""
    with defer_rbac_computations():
        with pytest.raises(RuntimeError, match="cannot be nested"):
            with defer_rbac_computations():
                pass


@pytest.mark.django_db
def test_defer_rbac_computations_empty_block(inventory):
    """An empty defer_rbac_computations block should not trigger any
    recomputation."""
    from unittest.mock import patch

    with patch('ansible_base.rbac.triggers.recompute_role_evaluations') as mock_compute:
        with defer_rbac_computations():
            pass

    mock_compute.assert_not_called()


@pytest.mark.django_db
def test_defer_rbac_computations_give_permission_raises_after_stash(organization, rando, org_inv_rd):
    """give_permission raises after resources are stashed because RoleEvaluation is stale."""
    with defer_rbac_computations():
        Inventory.objects.create(name='stash-trigger', organization=organization)
        with pytest.raises(RuntimeError, match="Permission assignment/removal cannot be called"):
            org_inv_rd.give_permission(rando, organization)


@pytest.mark.django_db
def test_defer_rbac_computations_give_permission_ok_before_stash(organization, rando, org_inv_rd):
    """give_permission is allowed inside the CM before any data is stashed."""
    with defer_rbac_computations():
        org_inv_rd.give_permission(rando, organization)
    assert rando.has_obj_perm(organization, 'view')


@pytest.mark.django_db
def test_defer_rbac_computations_remove_permission_raises_after_stash(organization, rando, org_inv_rd):
    """remove_permission raises after resources are stashed because RoleEvaluation is stale."""
    org_inv_rd.give_permission(rando, organization)
    with defer_rbac_computations():
        Inventory.objects.create(name='stash-trigger', organization=organization)
        with pytest.raises(RuntimeError, match="Permission assignment/removal cannot be called"):
            org_inv_rd.remove_permission(rando, organization)


@pytest.mark.django_db
def test_defer_rbac_computations_has_obj_perm_raises_after_stash(organization, rando, org_inv_rd):
    """has_obj_perm raises after data is stashed because evaluations are stale."""
    org_inv_rd.give_permission(rando, organization)
    with defer_rbac_computations():
        Inventory.objects.create(name='stash-trigger', organization=organization)
        with pytest.raises(RuntimeError, match="has_obj_perm cannot be called"):
            rando.has_obj_perm(organization, 'view')


@pytest.mark.django_db
def test_defer_rbac_computations_has_obj_perm_ok_before_stash(organization, rando, org_inv_rd):
    """has_obj_perm is allowed inside the CM before any data is stashed."""
    org_inv_rd.give_permission(rando, organization)
    with defer_rbac_computations():
        assert rando.has_obj_perm(organization, 'view')


@pytest.mark.django_db
def test_without_defer_evaluations_are_immediate(organization, inventory, rando, org_inv_rd):
    """Without defer_rbac_computations, evaluations are created immediately."""
    inv_gfk = gfk_filter(inventory)

    org_inv_rd.give_permission(rando, organization)

    assert RoleEvaluation.objects.filter(**inv_gfk).exists()
    assert rando.has_obj_perm(inventory, 'change')


@pytest.mark.django_db
@override_settings(ANSIBLE_BASE_ALLOW_CUSTOM_TEAM_ROLES=True)
def test_defer_rbac_computations_delete_team_direct_role(rando):
    """Delete a team that has a direct team-scoped role assigned to a user.
    The ObjectRole and RoleEvaluation should be cleaned up."""
    from test_app.models import Organization, Team

    org = Organization.objects.create(name='defer-team-org')
    team = Team.objects.create(name='defer-team', organization=org)
    team_ct = permission_registry.content_type_model.objects.get_for_model(Team)

    view_team_rd = RoleDefinition.objects.create_from_permissions(
        permissions=['view_team'],
        name='view-team-rd',
        content_type=team_ct,
    )
    view_team_rd.give_permission(rando, team)
    assert rando.has_obj_perm(team, 'view')
    assert ObjectRole.objects.filter(role_definition=view_team_rd, object_id=team.pk, content_type=team_ct).exists()
    assert RoleEvaluation.objects.filter(codename='view_team', object_id=team.pk, content_type_id=team_ct.pk).exists()

    with defer_rbac_computations():
        team.delete()

    assert not ObjectRole.objects.filter(role_definition=view_team_rd, object_id=team.pk, content_type=team_ct).exists()
    assert not RoleEvaluation.objects.filter(codename='view_team', object_id=team.pk, content_type_id=team_ct.pk).exists()


@pytest.mark.django_db
@override_settings(ANSIBLE_BASE_ALLOW_CUSTOM_TEAM_ROLES=True)
def test_defer_rbac_computations_delete_team_via_org_role(rando):
    """An org-scoped role gives view_team on teams in the org.
    Deleting the team should remove the RoleEvaluation for that team."""
    from test_app.models import Organization, Team

    org = Organization.objects.create(name='defer-org-team-org')
    team = Team.objects.create(name='defer-org-team', organization=org)
    org_ct = permission_registry.content_type_model.objects.get_for_model(Organization)
    team_ct = permission_registry.content_type_model.objects.get_for_model(Team)

    org_view_team_rd = RoleDefinition.objects.create_from_permissions(
        permissions=['view_organization', 'view_team'],
        name='org-view-team-rd',
        content_type=org_ct,
    )
    assignment = org_view_team_rd.give_permission(rando, org)
    assert rando.has_obj_perm(team, 'view')
    assert RoleEvaluation.objects.filter(codename='view_team', object_id=team.pk, content_type_id=team_ct.pk).exists()

    with defer_rbac_computations():
        team.delete()

    assert not RoleEvaluation.objects.filter(codename='view_team', object_id=team.pk, content_type_id=team_ct.pk).exists()
    # The org-level ObjectRole should still exist (org not deleted)
    assert ObjectRole.objects.filter(id=assignment.object_role_id).exists()


@pytest.mark.django_db
@override_settings(ANSIBLE_BASE_ALLOW_CUSTOM_TEAM_ROLES=True)
def test_defer_rbac_computations_delete_org_cleans_team_role(rando):
    """An org-scoped role gives view_team on teams in the org.
    Deleting the org should clean up both the ObjectRole and RoleEvaluations."""
    from test_app.models import Organization, Team

    org = Organization.objects.create(name='defer-org-del-org')
    team = Team.objects.create(name='defer-org-del-team', organization=org)
    org_ct = permission_registry.content_type_model.objects.get_for_model(Organization)
    team_ct = permission_registry.content_type_model.objects.get_for_model(Team)

    org_view_team_rd = RoleDefinition.objects.create_from_permissions(
        permissions=['view_organization', 'view_team'],
        name='org-view-team-rd-2',
        content_type=org_ct,
    )
    assignment = org_view_team_rd.give_permission(rando, org)
    assert rando.has_obj_perm(team, 'view')
    assert RoleEvaluation.objects.filter(codename='view_team', object_id=team.pk, content_type_id=team_ct.pk).exists()

    with defer_rbac_computations():
        org.delete()

    assert not ObjectRole.objects.filter(id=assignment.object_role_id).exists()
    assert not RoleEvaluation.objects.filter(codename='view_team', object_id=team.pk, content_type_id=team_ct.pk).exists()
    assert not RoleEvaluation.objects.filter(codename='view_organization', object_id=org.pk, content_type_id=org_ct.pk).exists()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "scenario",
    [
        pytest.param("rollback", id="skips_flush_on_rollback"),
        pytest.param("flush_error", id="suppresses_flush_exception"),
    ],
)
def test_defer_rbac_error_handling_paths(organization, rando, org_inv_rd, scenario):
    """Rollback and flush-error paths in defer_rbac_computations exception handler."""
    org_inv_rd.give_permission(rando, organization)

    def _create_and_raise():
        with defer_rbac_computations():
            Inventory.objects.create(name=f'{scenario}-inv', organization=organization)
            raise RuntimeError("deliberate")

    if scenario == "rollback":
        with patch('ansible_base.rbac.triggers.connection') as mock_conn:
            mock_conn.in_atomic_block = True
            mock_conn.needs_rollback = True
            with pytest.raises(RuntimeError, match="deliberate"):
                _create_and_raise()
    else:
        with patch('ansible_base.rbac.triggers._flush_rbac', side_effect=RuntimeError("flush error")):
            with pytest.raises(RuntimeError, match="deliberate"):
                _create_and_raise()


@pytest.mark.django_db
def test_defer_rbac_computations_team_creation():
    """Creating a Team inside defer_rbac_computations processes team IDs in the flush."""
    from test_app.models import Team

    org = Organization.objects.create(name='defer-team-create-org')

    with patch('ansible_base.rbac.triggers.compute_team_member_roles', wraps=compute_team_member_roles) as mock_ctmr:
        with defer_rbac_computations():
            team = Team.objects.create(name='deferred-team', organization=org)

        mock_ctmr.assert_called_once()
        assert team.id in mock_ctmr.call_args.kwargs['team_ids']


@pytest.mark.django_db
class TestBulkGivePermissions:
    """Tests for bulk_give_permissions."""

    def test_multiple_users_single_rd(self, organization, rando, org_inv_rd):
        second_user = User.objects.create(username='second-user')
        bulk_give_permissions(
            user_permissions=[
                (org_inv_rd, rando, organization),
                (org_inv_rd, second_user, organization),
            ]
        )
        assert rando.has_obj_perm(organization, 'view')
        assert second_user.has_obj_perm(organization, 'view')

    def test_multiple_objects_single_rd(self, organization, inv_rd):
        inv1 = Inventory.objects.create(name='bulk-inv1', organization=organization)
        inv2 = Inventory.objects.create(name='bulk-inv2', organization=organization)
        user = User.objects.create(username='bulk-user')
        bulk_give_permissions(user_permissions=[(inv_rd, user, inv1), (inv_rd, user, inv2)])
        assert user.has_obj_perm(inv1, 'change')
        assert user.has_obj_perm(inv2, 'change')

    def test_multi_rd_user_assignments(self, organization, rando, org_inv_rd):
        from test_app.models import Team

        member_rd = RoleDefinition.objects.managed.team_member
        team = Team.objects.create(name='bulk-team', organization=organization)
        bulk_give_permissions(
            user_permissions=[
                (org_inv_rd, rando, organization),
                (member_rd, rando, team),
            ]
        )
        assert rando.has_obj_perm(organization, 'view')
        assert rando.has_obj_perm(team, 'member_team')

    def test_multi_rd_with_teams(self, organization, team, inv_rd):
        inv = Inventory.objects.create(name='multi-rd-inv', organization=organization)
        user = User.objects.create(username='multi-rd-user')
        member_rd = RoleDefinition.objects.managed.team_member
        bulk_give_permissions(
            user_permissions=[(member_rd, user, team)],
            team_permissions=[(inv_rd, team, inv)],
        )
        assert user.has_obj_perm(team, 'member_team')
        assert ObjectRole.objects.filter(role_definition=inv_rd, object_id=inv.pk, teams=team).exists()

    def test_evaluations_correct(self, organization, rando, org_inv_rd):
        inv = Inventory.objects.create(name='eval-inv', organization=organization)
        bulk_give_permissions(user_permissions=[(org_inv_rd, rando, organization)])
        assert rando.has_obj_perm(inv, 'change')
        assert RoleEvaluation.objects.filter(codename='change_inventory', object_id=inv.pk).exists()

    def test_idempotent(self, organization, rando, org_inv_rd):
        bulk_give_permissions(user_permissions=[(org_inv_rd, rando, organization)])
        bulk_give_permissions(user_permissions=[(org_inv_rd, rando, organization)])
        assert RoleUserAssignment.objects.filter(user=rando, role_definition=org_inv_rd).count() == 1

    def test_empty_is_noop(self):
        bulk_give_permissions()

    def test_return_no_cross_product(self, organization, inv_rd):
        """Return value must contain only the requested assignments, not cross-product extras."""
        inv1 = Inventory.objects.create(name='xp-inv1', organization=organization)
        inv2 = Inventory.objects.create(name='xp-inv2', organization=organization)
        user1 = User.objects.create(username='xp-user1')
        user2 = User.objects.create(username='xp-user2')

        # Pre-existing: user1 has inv2 (not part of the bulk call)
        inv_rd.give_permission(user1, inv2)

        assignments = bulk_give_permissions(
            user_permissions=[
                (inv_rd, user1, inv1),
                (inv_rd, user2, inv2),
            ]
        )
        returned_pairs = {(a.user_id, a.object_id) for a in assignments}
        assert returned_pairs == {
            (user1.pk, str(inv1.pk)),
            (user2.pk, str(inv2.pk)),
        }, f"Cross-product leak: got {returned_pairs}"

    def test_audit_no_cross_product(self, organization, inv_rd):
        """Audit logging must not fire for pre-existing assignments outside the batch."""
        inv1 = Inventory.objects.create(name='audit-xp-inv1', organization=organization)
        inv2 = Inventory.objects.create(name='audit-xp-inv2', organization=organization)
        user1 = User.objects.create(username='audit-xp-user1')
        user2 = User.objects.create(username='audit-xp-user2')

        inv_rd.give_permission(user1, inv2)

        with patch('ansible_base.rbac.pipeline._audit_log_created') as mock_audit:
            bulk_give_permissions(
                user_permissions=[
                    (inv_rd, user1, inv1),
                    (inv_rd, user2, inv2),
                ],
                fire_signals_on_create=False,
            )
            args = mock_audit.call_args
            db_assignments = args[0][0]
            existing_pks = args[0][1]
            new_assignments = [a for a in db_assignments if a.pk not in existing_pks]
            new_pairs = {(a.user_id, a.object_id) for a in new_assignments}
            assert (user1.pk, str(inv2.pk)) not in new_pairs, "Pre-existing assignment leaked into new set"


@pytest.mark.django_db
class TestBulkRemovePermissions:
    """Tests for the classmethod bulk_remove_permissions."""

    def test_removes_assignments(self, organization, rando, org_inv_rd):
        org_inv_rd.give_permission(rando, organization)
        assert rando.has_obj_perm(organization, 'view')
        bulk_remove_permissions(user_permissions=[(org_inv_rd, rando, organization)])
        assert not rando.has_obj_perm(organization, 'view')

    def test_orphans_object_role(self, organization, rando, org_inv_rd):
        org_inv_rd.give_permission(rando, organization)
        or_count_before = ObjectRole.objects.count()
        bulk_remove_permissions(user_permissions=[(org_inv_rd, rando, organization)])
        assert ObjectRole.objects.count() < or_count_before

    def test_keeps_other_users(self, organization, org_inv_rd):
        user1 = User.objects.create(username='keep-user1')
        user2 = User.objects.create(username='keep-user2')
        bulk_give_permissions(
            user_permissions=[
                (org_inv_rd, user1, organization),
                (org_inv_rd, user2, organization),
            ]
        )
        bulk_remove_permissions(user_permissions=[(org_inv_rd, user1, organization)])
        assert not user1.has_obj_perm(organization, 'view')
        assert user2.has_obj_perm(organization, 'view')

    def test_multi_rd_removal(self, organization, rando, org_inv_rd):
        from test_app.models import Team

        member_rd = RoleDefinition.objects.managed.team_member
        team = Team.objects.create(name='rm-team', organization=organization)
        org_inv_rd.give_permission(rando, organization)
        member_rd.give_permission(rando, team)
        assert rando.has_obj_perm(organization, 'view')
        assert rando.has_obj_perm(team, 'member_team')
        bulk_remove_permissions(
            user_permissions=[
                (org_inv_rd, rando, organization),
                (member_rd, rando, team),
            ]
        )
        assert not rando.has_obj_perm(organization, 'view')
        assert not rando.has_obj_perm(team, 'member_team')

    def test_empty_is_noop(self):
        bulk_remove_permissions()

    def test_team_removal_revokes_inherited_permissions(self, organization, team, inv_rd):
        """Removing a team assignment must revoke permissions inherited through the team."""
        inv = Inventory.objects.create(name='team-rm-inv', organization=organization)
        user = User.objects.create(username='team-rm-user')
        member_rd = RoleDefinition.objects.managed.team_member
        member_rd.give_permission(user, team)
        inv_rd.give_permission(team, inv)
        assert user.has_obj_perm(inv, 'change')

        bulk_remove_permissions(team_permissions=[(inv_rd, team, inv)])
        assert not user.has_obj_perm(inv, 'change')

    def test_team_removal_no_stale_object_roles(self, organization, inv_rd):
        """Removing a team assignment must not leave RoleEvaluation rows
        pointing to deleted ObjectRoles when signal handlers cause
        additional ObjectRole deletions.

        Regression test: bulk_remove_permissions added team ancestor roles to
        the surviving set, then orphaned.delete() fired signal handlers that
        deleted some of those ancestor ObjectRoles. The stale in-memory
        references caused compute_object_role_permissions to create
        RoleEvaluation rows with dangling FK references.
        """
        from django.db.models.signals import post_delete

        from test_app.models import Team

        inv = Inventory.objects.create(name='stale-or-inv', organization=organization)
        team = Team.objects.create(name='stale-or-team', organization=organization)
        user = User.objects.create(username='stale-or-user')
        member_rd = RoleDefinition.objects.managed.team_member
        member_rd.give_permission(user, team)
        inv_rd.give_permission(team, inv)
        assert user.has_obj_perm(inv, 'change')

        # The member ObjectRole is what bulk_ancestor_roles will add to surviving
        member_obj_role = ObjectRole.objects.get(
            role_definition=member_rd,
            content_type_id=permission_registry.content_type_model.objects.get_for_model(team).pk,
            object_id=team.pk,
        )

        # Simulate downstream signal handlers (like AWX's) that delete
        # additional ObjectRoles during orphaned.delete() cascade.
        def delete_ancestor_role(sender, instance, **kwargs):
            if instance.pk == member_obj_role.pk:
                return
            ObjectRole.objects.filter(pk=member_obj_role.pk).delete()

        post_delete.connect(delete_ancestor_role, sender=ObjectRole)
        try:
            bulk_remove_permissions(team_permissions=[(inv_rd, team, inv)])
        finally:
            post_delete.disconnect(delete_ancestor_role, sender=ObjectRole)

        # Every RoleEvaluation must reference an existing ObjectRole
        orphaned_evals = RoleEvaluation.objects.exclude(role_id__in=ObjectRole.objects.values_list('id', flat=True))
        assert not orphaned_evals.exists(), (
            f"Found {orphaned_evals.count()} RoleEvaluation rows pointing to " f"deleted ObjectRoles: {list(orphaned_evals.values_list('role_id', flat=True))}"
        )

    def test_team_removal_no_cross_product(self, organization, inv_rd):
        """Removing team assignments must not affect unrelated team-object pairs."""
        from test_app.models import Team

        inv1 = Inventory.objects.create(name='team-xp-inv1', organization=organization)
        inv2 = Inventory.objects.create(name='team-xp-inv2', organization=organization)
        team1 = Team.objects.create(name='team-xp-t1', organization=organization)
        team2 = Team.objects.create(name='team-xp-t2', organization=organization)
        member_rd = RoleDefinition.objects.managed.team_member
        user = User.objects.create(username='team-xp-user')
        member_rd.give_permission(user, team1)
        member_rd.give_permission(user, team2)

        bulk_give_permissions(
            team_permissions=[
                (inv_rd, team1, inv1),
                (inv_rd, team1, inv2),
                (inv_rd, team2, inv1),
                (inv_rd, team2, inv2),
            ]
        )
        assert user.has_obj_perm(inv1, 'change')
        assert user.has_obj_perm(inv2, 'change')

        bulk_remove_permissions(team_permissions=[(inv_rd, team1, inv1)])
        assert RoleTeamAssignment.objects.filter(team=team1, role_definition=inv_rd, object_id=inv2.pk).exists()
        assert RoleTeamAssignment.objects.filter(team=team2, role_definition=inv_rd, object_id=inv1.pk).exists()
        assert RoleTeamAssignment.objects.filter(team=team2, role_definition=inv_rd, object_id=inv2.pk).exists()
        assert user.has_obj_perm(inv2, 'change')


@pytest.mark.django_db
class TestBulkRemotePermissions:
    """Tests for bulk operations with RemoteObject content objects."""

    @pytest.fixture
    def foo_type(self):
        org_ct = permission_registry.content_type_model.objects.get_for_model(Organization)
        return permission_registry.content_type_model.objects.create(service='foo', model='foo', app_label='foo', parent_content_type=org_ct)

    @pytest.fixture
    def foo_rd(self, foo_type):
        from ansible_base.rbac.models import DABPermission

        perm = DABPermission.objects.create(codename='foo_foo', content_type=foo_type)
        return RoleDefinition.objects.create_from_permissions(name='Bulk foo role', permissions=[perm.api_slug], content_type=foo_type)

    def test_bulk_give_remote_permission(self, rando, foo_type, foo_rd):
        from ansible_base.rbac.remote import RemoteObject

        a_foo = RemoteObject(content_type=foo_type, object_id=42)
        bulk_give_permissions(user_permissions=[(foo_rd, rando, a_foo)])
        assert rando.has_obj_perm(a_foo, 'foo')

    def test_bulk_give_remote_with_parent_reference(self, rando, foo_type, foo_rd, organization):
        from ansible_base.rbac.remote import RemoteObject

        a_foo = RemoteObject(content_type=foo_type, object_id=42, parent_reference=organization.pk)
        bulk_give_permissions(user_permissions=[(foo_rd, rando, a_foo)])
        obj_role = ObjectRole.objects.get(role_definition=foo_rd, object_id='42')
        assert str(obj_role.parent_reference) == str(organization.pk)

    def test_bulk_remove_remote_permission(self, rando, foo_type, foo_rd):
        from ansible_base.rbac.remote import RemoteObject

        a_foo = RemoteObject(content_type=foo_type, object_id=42)
        foo_rd.give_permission(rando, a_foo)
        assert rando.has_obj_perm(a_foo, 'foo')
        bulk_remove_permissions(user_permissions=[(foo_rd, rando, a_foo)])
        assert not rando.has_obj_perm(a_foo, 'foo')
        assert not ObjectRole.objects.filter(role_definition=foo_rd, object_id='42').exists()

    def test_bulk_mixed_local_and_remote(self, rando, organization, foo_type, foo_rd, org_inv_rd):
        from ansible_base.rbac.remote import RemoteObject

        a_foo = RemoteObject(content_type=foo_type, object_id=42)
        bulk_give_permissions(
            user_permissions=[
                (foo_rd, rando, a_foo),
                (org_inv_rd, rando, organization),
            ]
        )
        assert rando.has_obj_perm(a_foo, 'foo')
        assert rando.has_obj_perm(organization, 'view')


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


@pytest.mark.django_db
class TestPermissionQueryCount:
    """Profile query counts for give_permission / remove_permission."""

    @override_settings(DEBUG=True)
    def test_give_permission_user_query_count(self, rando, organization, org_admin_rd):
        from django.db import connection

        connection.queries_log.clear()
        before = len(connection.queries)
        org_admin_rd.give_permission(rando, organization)
        count = len(connection.queries) - before
        print(f"\ngive_permission (user+org): {count} queries")

    @override_settings(DEBUG=True)
    def test_remove_permission_user_query_count(self, rando, organization, org_admin_rd):
        from django.db import connection

        org_admin_rd.give_permission(rando, organization)
        connection.queries_log.clear()
        before = len(connection.queries)
        org_admin_rd.remove_permission(rando, organization)
        count = len(connection.queries) - before
        print(f"\nremove_permission (user+org): {count} queries")

    @override_settings(DEBUG=True)
    def test_give_permission_team_query_count(self, team, inventory, inv_rd):
        from django.db import connection

        connection.queries_log.clear()
        before = len(connection.queries)
        inv_rd.give_permission(team, inventory)
        count = len(connection.queries) - before
        print(f"\ngive_permission (team+inv): {count} queries")

    @override_settings(DEBUG=True)
    def test_remove_permission_team_query_count(self, team, inventory, inv_rd):
        from django.db import connection

        inv_rd.give_permission(team, inventory)
        connection.queries_log.clear()
        before = len(connection.queries)
        inv_rd.remove_permission(team, inventory)
        count = len(connection.queries) - before
        print(f"\nremove_permission (team+inv): {count} queries")
