import pytest
from django.test import RequestFactory, override_settings
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from ansible_base.lib.serializers.mixins import EmailAdminOnlyMixin
from test_app.models import User


class EmailTestSerializer(EmailAdminOnlyMixin, serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['email']


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
    @override_settings(ALLOW_USER_SELF_EDIT=True)
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
    @override_settings(ALLOW_USER_SELF_EDIT=True)
    def test_setting_does_not_allow_changing_other_user_email(self):
        alice = User.objects.create(username='alice')
        bob = User.objects.create(username='bob', email='bob@example.com')
        serializer = EmailTestSerializer(bob, context={'request': _make_request(alice)})
        with pytest.raises(PermissionDenied):
            serializer.validate_email('hacked@example.com')
