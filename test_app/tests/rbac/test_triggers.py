from unittest.mock import MagicMock, patch

import pytest
from django.apps import apps
from django.test.utils import override_settings
from rest_framework.exceptions import ValidationError

from ansible_base.rbac.models import ObjectRole, RoleDefinition, RoleEvaluation, RoleTeamAssignment, RoleUserAssignment
from ansible_base.rbac.permission_registry import permission_registry
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
def test_defer_rbac_computations_discards_on_exception(organization, rando, org_inv_rd):
    """On exception, deferred data should be discarded without flushing."""
    org_inv_rd.give_permission(rando, organization)

    with pytest.raises(RuntimeError, match="deliberate"):
        with defer_rbac_computations():
            inv = Inventory.objects.create(name='error-inv', organization=organization)
            raise RuntimeError("deliberate")

    assert not rando.has_obj_perm(inv, 'change')


@pytest.mark.django_db
def test_api_delete_uses_deferral_context_managers(admin_api_client, organization, rando, org_inv_rd):
    """DELETE via the API should use defer_rbac_computations, verified by
    checking that the context manager is active when the post_delete
    signal fires during the cascade."""
    from django.db.models.signals import post_delete

    from ansible_base.rbac.triggers import _defer_rbac

    org_inv_rd.give_permission(rando, organization)
    for i in range(3):
        Inventory.objects.create(name=f'defer-api-inv-{i}', organization=organization)

    was_active = []

    def check_defer(sender, instance, **kwargs):
        was_active.append(_defer_rbac.active)

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

    with patch('ansible_base.rbac.triggers.compute_object_role_permissions') as mock_compute:
        with defer_rbac_computations():
            pass

    mock_compute.assert_not_called()


@pytest.mark.django_db
def test_defer_rbac_computations_give_permission_raises_after_stash(organization, rando, org_inv_rd):
    """give_permission raises after resources have been created/deleted inside the CM."""
    with defer_rbac_computations():
        Inventory.objects.create(name='stash-trigger', organization=organization)
        with pytest.raises(RuntimeError, match="give_permission cannot be called"):
            org_inv_rd.give_permission(rando, organization)


@pytest.mark.django_db
def test_defer_rbac_computations_give_permission_ok_before_stash(organization, rando, org_inv_rd):
    """give_permission is allowed inside the CM before any data is stashed."""
    with defer_rbac_computations():
        org_inv_rd.give_permission(rando, organization)
    assert rando.has_obj_perm(organization, 'view')


@pytest.mark.django_db
def test_defer_rbac_computations_remove_permission_raises_after_stash(organization, rando, org_inv_rd):
    """remove_permission raises after resources have been created/deleted inside the CM."""
    org_inv_rd.give_permission(rando, organization)
    with defer_rbac_computations():
        Inventory.objects.create(name='stash-trigger', organization=organization)
        with pytest.raises(RuntimeError, match="remove_permission cannot be called"):
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
