import pytest
from django.test import RequestFactory, override_settings
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from ansible_base.lib.serializers.mixins import EmailAdminOnlyMixin, ExternalAuthPasswordMixin
from test_app.models import User
from test_app.serializers import UserSerializer


class EmailTestSerializer(EmailAdminOnlyMixin, serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['email']


class PasswordTestSerializer(ExternalAuthPasswordMixin, serializers.ModelSerializer):
    """Minimal serializer isolating ExternalAuthPasswordMixin's own no-op
    guard from UserSerializer's unrelated field configuration (which, as a
    plain ModelSerializer, rejects blank password at the field level before
    validate_password ever runs)."""

    class Meta:
        model = User
        fields = ['password']
        extra_kwargs = {'password': {'required': False, 'allow_blank': True}}


def _make_request(user):
    request = RequestFactory().patch('/api/v1/users/')
    request.user = user
    return request


class TestEmailAdminOnlyMixin:

    @pytest.mark.django_db
    def test_regular_user_cannot_change_own_email(self):
        alice = User.objects.create(username='alice', email='alice@example.com')
        serializer = EmailTestSerializer(alice, context={'request': _make_request(alice)})
        with pytest.raises(PermissionDenied):
            serializer.validate_email('newemail@example.com')

    @pytest.mark.django_db
    def test_superuser_can_change_any_email(self):
        admin = User.objects.create(username='admin', is_superuser=True)
        alice = User.objects.create(username='alice', email='alice@example.com')
        serializer = EmailTestSerializer(alice, context={'request': _make_request(admin)})
        assert serializer.validate_email('newemail@example.com') == 'newemail@example.com'

    @pytest.mark.django_db
    def test_same_email_is_allowed(self):
        alice = User.objects.create(username='alice', email='alice@example.com')
        serializer = EmailTestSerializer(alice, context={'request': _make_request(alice)})
        assert serializer.validate_email('alice@example.com') == 'alice@example.com'

    @pytest.mark.django_db
    def test_new_user_email_is_allowed(self):
        alice = User.objects.create(username='alice')
        serializer = EmailTestSerializer(instance=None, context={'request': _make_request(alice)})
        assert serializer.validate_email('new@example.com') == 'new@example.com'

    @pytest.mark.django_db
    def test_no_request_context_is_allowed(self):
        alice = User.objects.create(username='alice', email='alice@example.com')
        serializer = EmailTestSerializer(alice, context={})
        assert serializer.validate_email('newemail@example.com') == 'newemail@example.com'

    @pytest.mark.django_db
    def test_org_admin_can_change_member_email(self, org_admin_rd, org_member_rd, organization):
        org_admin = User.objects.create(username='org-admin')
        member = User.objects.create(username='member', email='member@example.com')
        org_admin_rd.give_permission(org_admin, organization)
        org_member_rd.give_permission(member, organization)
        serializer = EmailTestSerializer(member, context={'request': _make_request(org_admin)})
        assert serializer.validate_email('updated@example.com') == 'updated@example.com'

    @pytest.mark.django_db
    @override_settings(ALLOW_USER_EMAIL_SELF_EDIT=True)
    def test_self_edit_allowed_when_setting_enabled(self):
        alice = User.objects.create(username='alice', email='alice@example.com')
        serializer = EmailTestSerializer(alice, context={'request': _make_request(alice)})
        assert serializer.validate_email('newemail@example.com') == 'newemail@example.com'

    @pytest.mark.django_db
    def test_regular_user_cannot_change_other_user_email(self):
        alice = User.objects.create(username='alice')
        bob = User.objects.create(username='bob', email='bob@example.com')
        serializer = EmailTestSerializer(bob, context={'request': _make_request(alice)})
        with pytest.raises(PermissionDenied):
            serializer.validate_email('hacked@example.com')

    @pytest.mark.django_db
    @override_settings(ALLOW_USER_EMAIL_SELF_EDIT=True)
    def test_setting_does_not_allow_changing_other_user_email(self):
        alice = User.objects.create(username='alice')
        bob = User.objects.create(username='bob', email='bob@example.com')
        serializer = EmailTestSerializer(bob, context={'request': _make_request(alice)})
        with pytest.raises(PermissionDenied):
            serializer.validate_email('hacked@example.com')


class TestUsernameAdminOnlyMixin:

    @pytest.mark.django_db
    def test_regular_user_cannot_change_own_username(self):
        alice = User.objects.create(username='alice')
        serializer = UserSerializer(alice, data={'username': 'renamed'}, context={'request': _make_request(alice)}, partial=True)

        with pytest.raises(PermissionDenied):
            serializer.is_valid(raise_exception=True)

    @pytest.mark.django_db
    @override_settings(ALLOW_USER_USERNAME_SELF_EDIT=True)
    def test_regular_user_can_change_own_username_when_setting_enabled(self):
        alice = User.objects.create(username='alice')
        serializer = UserSerializer(alice, data={'username': 'renamed'}, context={'request': _make_request(alice)}, partial=True)

        assert serializer.is_valid(raise_exception=True)

    @pytest.mark.django_db
    def test_superuser_can_change_another_users_username(self):
        admin = User.objects.create(username='admin', is_superuser=True)
        alice = User.objects.create(username='alice')
        serializer = UserSerializer(alice, data={'username': 'renamed'}, context={'request': _make_request(admin)}, partial=True)

        assert serializer.is_valid(raise_exception=True)

    @pytest.mark.django_db
    def test_unchanged_username_is_allowed(self):
        alice = User.objects.create(username='alice')
        serializer = UserSerializer(alice, data={'username': 'alice'}, context={'request': _make_request(alice)}, partial=True)

        assert serializer.is_valid(raise_exception=True)

    @pytest.mark.django_db
    def test_username_change_without_request_context_is_allowed(self):
        alice = User.objects.create(username='alice')
        serializer = UserSerializer(alice, data={'username': 'renamed'}, context={}, partial=True)

        assert serializer.is_valid(raise_exception=True)


class TestIsActiveAdminOnlyMixin:

    @pytest.mark.django_db
    def test_regular_user_cannot_change_own_is_active(self):
        alice = User.objects.create(username='alice', is_active=True)
        serializer = UserSerializer(alice, data={'is_active': False}, context={'request': _make_request(alice)}, partial=True)

        with pytest.raises(PermissionDenied):
            serializer.is_valid(raise_exception=True)

    @pytest.mark.django_db
    def test_superuser_can_change_another_users_is_active(self):
        admin = User.objects.create(username='admin', is_superuser=True)
        alice = User.objects.create(username='alice', is_active=True)
        serializer = UserSerializer(alice, data={'is_active': False}, context={'request': _make_request(admin)}, partial=True)

        assert serializer.is_valid(raise_exception=True)

    @pytest.mark.django_db
    def test_unchanged_is_active_is_allowed_alongside_other_self_edits(self):
        """The Ansible UI resubmits is_active at its current value on every save
        regardless of what the user actually changed. Without this no-op, every
        self-edit of any field (e.g. first_name) would be rejected."""
        alice = User.objects.create(username='alice', is_active=True)
        serializer = UserSerializer(alice, data={'is_active': True, 'first_name': 'Alice'}, context={'request': _make_request(alice)}, partial=True)

        assert serializer.is_valid(raise_exception=True)

    @pytest.mark.django_db
    def test_is_active_change_without_request_context_is_allowed(self):
        alice = User.objects.create(username='alice', is_active=True)
        serializer = UserSerializer(alice, data={'is_active': False}, context={}, partial=True)

        assert serializer.is_valid(raise_exception=True)

    @pytest.mark.django_db
    @override_settings(ALLOW_USER_EMAIL_SELF_EDIT=True)
    def test_email_self_edit_setting_does_not_allow_self_is_active_change(self):
        """Regression guard: enabling email self-edit must not incidentally
        unlock is_active self-edit, since they share can_change_user but must
        use distinct self_edit_setting names."""
        alice = User.objects.create(username='alice', is_active=True)
        serializer = UserSerializer(alice, data={'is_active': False}, context={'request': _make_request(alice)}, partial=True)

        with pytest.raises(PermissionDenied):
            serializer.is_valid(raise_exception=True)


class TestExternalAuthPasswordMixin:

    def test_allows_password_when_authentication_app_not_installed(self):
        """ansible_base.authentication is an optional app; the User model only
        gains the authenticator_users reverse accessor when it's installed.
        Deployments without it must not crash on password changes."""
        from types import SimpleNamespace

        mixin = ExternalAuthPasswordMixin()
        mixin.instance = SimpleNamespace()  # no authenticator_users attribute

        assert mixin.validate_password('NewSecurePass1!') == 'NewSecurePass1!'

    @pytest.mark.django_db
    def test_user_with_no_authenticator_association_can_set_password(self):
        alice = User.objects.create(username='alice')
        serializer = UserSerializer(alice, data={'password': 'NewSecurePass1!'}, context={'request': _make_request(alice)}, partial=True)

        assert serializer.is_valid(raise_exception=True)

    @pytest.mark.django_db
    def test_local_authenticator_user_can_set_own_password(self, local_authenticator):
        from ansible_base.authentication.models import AuthenticatorUser

        alice = User.objects.create(username='alice')
        AuthenticatorUser.objects.create(provider=local_authenticator, user=alice)
        serializer = UserSerializer(alice, data={'password': 'NewSecurePass1!'}, context={'request': _make_request(alice)}, partial=True)

        assert serializer.is_valid(raise_exception=True)

    @pytest.mark.django_db
    def test_external_authenticator_user_cannot_set_own_password(self, custom_authenticator):
        from ansible_base.authentication.models import AuthenticatorUser

        alice = User.objects.create(username='alice')
        AuthenticatorUser.objects.create(provider=custom_authenticator, user=alice)
        serializer = UserSerializer(alice, data={'password': 'NewSecurePass1!'}, context={'request': _make_request(alice)}, partial=True)

        with pytest.raises(PermissionDenied):
            serializer.is_valid(raise_exception=True)

    @pytest.mark.django_db
    def test_admin_cannot_set_password_for_external_authenticator_user(self, custom_authenticator):
        """The block is independent of can_change_user and applies regardless
        of requester -- an admin editing an externally-authenticated user
        through the same reused form must also be blocked."""
        from ansible_base.authentication.models import AuthenticatorUser

        admin = User.objects.create(username='admin', is_superuser=True)
        alice = User.objects.create(username='alice')
        AuthenticatorUser.objects.create(provider=custom_authenticator, user=alice)
        serializer = UserSerializer(alice, data={'password': 'NewSecurePass1!'}, context={'request': _make_request(admin)}, partial=True)

        with pytest.raises(PermissionDenied):
            serializer.is_valid(raise_exception=True)

    @pytest.mark.django_db
    def test_user_with_mixed_authenticators_cannot_set_password(self, local_authenticator, custom_authenticator):
        """A user linked to both a local and a non-local authenticator is
        still treated as externally authenticated."""
        from ansible_base.authentication.models import AuthenticatorUser

        alice = User.objects.create(username='alice')
        AuthenticatorUser.objects.create(provider=local_authenticator, user=alice)
        AuthenticatorUser.objects.create(provider=custom_authenticator, user=alice)
        serializer = UserSerializer(alice, data={'password': 'NewSecurePass1!'}, context={'request': _make_request(alice)}, partial=True)

        with pytest.raises(PermissionDenied):
            serializer.is_valid(raise_exception=True)

    @pytest.mark.django_db
    def test_blank_password_is_allowed(self, custom_authenticator):
        """The Ansible UI omits password from the payload entirely when
        unchanged (DRF partial-update skips absent fields naturally), but
        ExternalAuthPasswordMixin's own no-op on falsy values guards other API
        clients/serializers that configure password as allow_blank and send an
        empty string instead of omitting the key. Uses an externally-authenticated
        user to prove the no-op happens before the external-auth check, not
        because the check happened to pass."""
        from ansible_base.authentication.models import AuthenticatorUser

        alice = User.objects.create(username='alice')
        AuthenticatorUser.objects.create(provider=custom_authenticator, user=alice)
        serializer = PasswordTestSerializer(alice, data={'password': ''}, partial=True)

        assert serializer.is_valid(raise_exception=True)

    @pytest.mark.django_db
    def test_new_user_password_is_allowed(self):
        """A brand-new user has no authenticator associations yet to check against."""
        admin = User.objects.create(username='admin', is_superuser=True)
        serializer = UserSerializer(data={'username': 'alice', 'password': 'NewSecurePass1!'}, context={'request': _make_request(admin)})

        assert serializer.is_valid(raise_exception=True)
