import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import override_settings

from ansible_base.rbac.policies import can_change_user, visible_users
from test_app.models import User


@pytest.mark.django_db
def test_org_admin_can_not_change_superuser(org_admin_rd, organization):
    org_admin = User.objects.create(username='org-admin')
    org_admin_rd.give_permission(org_admin, organization)

    admin = User.objects.create(username='new-superuser', is_superuser=True)
    assert not can_change_user(org_admin, admin)


@pytest.mark.django_db
def test_unrelated_can_not_change_user():
    alice = User.objects.create(username='alice')
    bob = User.objects.create(username='bob')

    for first, second in [(alice, bob), (bob, alice)]:
        assert not can_change_user(first, second)


@pytest.mark.django_db
def test_superuser_can_change_new_user(admin_user):
    alice = User.objects.create(username='alice')
    assert can_change_user(admin_user, alice)


@pytest.mark.django_db
def test_user_can_manage_themselves():
    """Default can_self_edit=True allows self-edit."""
    alice = User.objects.create(username='alice')
    assert can_change_user(alice, alice)


@pytest.mark.django_db
def test_user_cannot_manage_themselves_when_self_edit_disabled():
    """can_self_edit=False blocks self-edit when ALLOW_USER_EMAIL_SELF_EDIT is off (default)."""
    alice = User.objects.create(username='alice')
    assert not can_change_user(alice, alice, can_self_edit=False)


@pytest.mark.django_db
@override_settings(ALLOW_USER_EMAIL_SELF_EDIT=True)
def test_self_edit_setting_overrides_can_self_edit_false():
    """ALLOW_USER_EMAIL_SELF_EDIT=True allows self-edit even when can_self_edit=False."""
    alice = User.objects.create(username='alice')
    assert can_change_user(alice, alice, can_self_edit=False)


@pytest.mark.django_db
def test_superuser_can_manage_themselves_even_when_self_edit_disabled(admin_user):
    assert can_change_user(admin_user, admin_user, can_self_edit=False)


@pytest.mark.django_db
def test_org_admin_can_manage_themselves_when_self_edit_disabled(org_admin_rd, organization):
    alice = User.objects.create(username='alice')
    org_admin_rd.give_permission(alice, organization)
    assert can_change_user(alice, alice, can_self_edit=False)


@pytest.mark.django_db
def test_org_member_cannot_manage_themselves_when_self_edit_disabled(org_member_rd, organization):
    alice = User.objects.create(username='alice')
    org_member_rd.give_permission(alice, organization)
    assert not can_change_user(alice, alice, can_self_edit=False)


@pytest.mark.django_db
@override_settings(ALLOW_USER_EMAIL_SELF_EDIT=True)
def test_org_member_can_self_edit_when_setting_enabled(org_member_rd, organization):
    """With ALLOW_USER_EMAIL_SELF_EDIT=True, even can_self_edit=False is overridden."""
    alice = User.objects.create(username='alice')
    org_member_rd.give_permission(alice, organization)
    assert can_change_user(alice, alice)
    assert can_change_user(alice, alice, can_self_edit=False)


@pytest.mark.django_db
@override_settings(ALLOW_USER_EMAIL_SELF_EDIT=True)
def test_setting_does_not_affect_other_user_changes():
    """ALLOW_USER_EMAIL_SELF_EDIT only controls self-edit, not editing other users."""
    alice = User.objects.create(username='alice')
    bob = User.objects.create(username='bob')
    assert not can_change_user(alice, bob)


@pytest.mark.django_db
@override_settings(ALLOW_USER_EMAIL_SELF_EDIT=True, MANAGE_ORGANIZATION_AUTH=False)
def test_self_edit_setting_requires_manage_org_auth():
    """ALLOW_USER_EMAIL_SELF_EDIT should not bypass the MANAGE_ORGANIZATION_AUTH gate."""
    alice = User.objects.create(username='alice')
    assert not can_change_user(alice, alice)


@pytest.mark.django_db
@override_settings(MANAGE_ORGANIZATION_AUTH=False)
def test_org_admin_cannot_change_email_when_manage_org_auth_disabled(org_admin_rd, org_member_rd, organization):
    """Org admins cannot change their own or others' email when MANAGE_ORGANIZATION_AUTH is off."""
    org_admin = User.objects.create(username='org-admin')
    member = User.objects.create(username='member')
    org_admin_rd.give_permission(org_admin, organization)
    org_member_rd.give_permission(member, organization)
    assert not can_change_user(org_admin, org_admin, can_self_edit=False)
    assert not can_change_user(org_admin, member, can_self_edit=False)
    assert not can_change_user(org_admin, org_admin)
    assert not can_change_user(org_admin, member)


@pytest.mark.django_db
def test_none_request_user_returns_false():
    alice = User.objects.create(username='alice')
    assert not can_change_user(None, alice)


@pytest.mark.django_db
def test_none_target_user_returns_false():
    alice = User.objects.create(username='alice')
    assert not can_change_user(alice, None)


def test_both_none_returns_false():
    assert not can_change_user(None, None)


@pytest.mark.django_db
@override_settings(MANAGE_ORGANIZATION_AUTH=False)
def test_non_superuser_cannot_change_user_when_manage_org_auth_disabled():
    alice = User.objects.create(username='alice')
    bob = User.objects.create(username='bob')
    assert not can_change_user(alice, bob)
    assert not can_change_user(alice, alice)
    assert not can_change_user(alice, alice, can_self_edit=False)


@pytest.mark.django_db
@override_settings(MANAGE_ORGANIZATION_AUTH=False)
def test_superuser_can_still_change_user_when_manage_org_auth_disabled(admin_user):
    alice = User.objects.create(username='alice')
    assert can_change_user(admin_user, alice)
    assert can_change_user(admin_user, admin_user)


@pytest.mark.django_db
def test_update_fields_bypass_vector(org_member_rd, organization):
    """Partial save(update_fields=['first_name']) followed by full save must still enforce email policy."""
    from crum import impersonate
    from rest_framework.exceptions import ValidationError

    unprivileged = User.objects.create(username='unprivileged-user')

    target = User.objects.create(username='target-user', email='original@example.com')
    org_member_rd.give_permission(target, organization)

    with impersonate(unprivileged):
        target.first_name = 'Updated'
        target.save(update_fields=['first_name'])

        target.email = 'hacked@example.com'
        with pytest.raises(ValidationError):
            target.save()

    target.refresh_from_db()
    assert target.email == 'original@example.com'
    assert target.first_name == 'Updated'


@pytest.mark.django_db
def test_deferred_only_load_enforces_email_policy(org_member_rd, organization):
    """User loaded via .only('id') must still enforce email policy."""
    from crum import impersonate
    from rest_framework.exceptions import ValidationError

    member = User.objects.create(username='deferred-member', email='original@example.com')
    org_member_rd.give_permission(member, organization)

    deferred = User.objects.only('id', 'username').get(pk=member.pk)
    with impersonate(deferred):
        deferred.email = 'hacked@example.com'
        with pytest.raises(ValidationError):
            deferred.save()

    member.refresh_from_db()
    assert member.email == 'original@example.com'


@pytest.mark.django_db
def test_visible_users_anonymous_user():
    User.objects.create(username='alice')
    User.objects.create(username='bob', is_superuser=True)

    qs = visible_users(AnonymousUser())
    assert not qs.exists()
