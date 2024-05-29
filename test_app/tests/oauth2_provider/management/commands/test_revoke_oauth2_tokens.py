# Python
import datetime
from io import StringIO

import pytest

# Django
from django.core.management import call_command
from django.core.management.base import CommandError

from ansible_base.oauth2_provider.models import OAuth2AccessToken, OAuth2RefreshToken


@pytest.mark.django_db
class TestOAuth2RevokeCommand:
    def test_non_existing_user(self, randname):
        with StringIO() as out:
            fake_username = randname("user")
            arg = '--user=' + fake_username
            with pytest.raises(CommandError) as excinfo:
                call_command('revoke_oauth2_tokens', arg, stdout=out)
            assert 'A user with that username does not exist' in str(excinfo.value)

    def test_revoke_all_access_tokens(self, oauth2_admin_access_token, oauth2_user_application_token):
        with StringIO() as out:
            assert OAuth2AccessToken.objects.count() == 2
            call_command('revoke_oauth2_tokens', stdout=out)
            assert OAuth2AccessToken.objects.count() == 0

    def test_revoke_access_token_for_user(self, oauth2_admin_access_token, oauth2_user_application_token):
        with StringIO() as out:
            admin_username = oauth2_admin_access_token.user.username
            user_username = oauth2_user_application_token.user.username

            assert OAuth2AccessToken.objects.count() == 2
            assert OAuth2RefreshToken.objects.count() == 1
            for r in OAuth2RefreshToken.objects.all():
                assert r.revoked is None

            call_command('revoke_oauth2_tokens', f'--user={admin_username}', stdout=out)
            assert OAuth2AccessToken.objects.count() == 1
            for r in OAuth2RefreshToken.objects.all():
                assert r.revoked is None

            call_command('revoke_oauth2_tokens', f'--user={admin_username}', "--all", stdout=out)
            assert OAuth2AccessToken.objects.count() == 1
            for r in OAuth2RefreshToken.objects.all():
                assert r.revoked is not None
                assert isinstance(r.revoked, datetime.datetime)

            call_command('revoke_oauth2_tokens', f'--user={user_username}', stdout=out)
            assert OAuth2AccessToken.objects.count() == 0

    def test_revoke_all_refresh_tokens(self, oauth2_admin_access_token):
        with StringIO() as out:
            assert OAuth2AccessToken.objects.count() == 1
            assert OAuth2RefreshToken.objects.count() == 1

            call_command('revoke_oauth2_tokens', stdout=out)
            assert OAuth2AccessToken.objects.count() == 0
            assert OAuth2RefreshToken.objects.count() == 1
            for r in OAuth2RefreshToken.objects.all():
                assert r.revoked is None

            call_command('revoke_oauth2_tokens', '--all', stdout=out)
            assert OAuth2RefreshToken.objects.count() == 1
            for r in OAuth2RefreshToken.objects.all():
                assert r.revoked is not None
                assert isinstance(r.revoked, datetime.datetime)
