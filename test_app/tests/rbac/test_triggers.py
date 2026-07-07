from unittest.mock import MagicMock, patch

import pytest
from django.apps import apps
from django.test.utils import override_settings
from rest_framework.exceptions import ValidationError

from ansible_base.rbac.models import ObjectRole, RoleDefinition, RoleEvaluation, RoleTeamAssignment, RoleUserAssignment
from ansible_base.rbac.permission_registry import permission_registry
from ansible_base.rbac.triggers import dab_post_migrate, defer_rbac_cache, post_migration_rbac_setup
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


def test_defer_rbac_cache_cannot_be_nested():
    """Nesting defer_rbac_cache should raise a RuntimeError."""
    with defer_rbac_cache():
        with pytest.raises(RuntimeError, match="cannot be nested"):
            with defer_rbac_cache():
                pass


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
