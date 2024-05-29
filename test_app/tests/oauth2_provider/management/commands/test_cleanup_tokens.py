# Python
import datetime
from io import StringIO

import pytest

# Django
from django.core.management import call_command

from ansible_base.oauth2_provider.models import OAuth2AccessToken, OAuth2RefreshToken


def attempt_cleanup(expected_access_tokens_deleted, expected_refresh_tokens_deleted):
    with StringIO() as out, StringIO() as err:
        current_access_tokens = OAuth2AccessToken.objects.count()
        current_refresh_tokens = OAuth2RefreshToken.objects.count()

        call_command("cleanup_tokens", verbosity=1, stdout=out, stderr=err)

        err_lines = err.getvalue().split("\n")

        assert f"Expired OAuth 2 Access Tokens deleted: {expected_access_tokens_deleted}" in err_lines
        assert f"Expired OAuth 2 Refresh Tokens deleted: {expected_refresh_tokens_deleted}" in err_lines

        assert OAuth2AccessToken.objects.count() == current_access_tokens - expected_access_tokens_deleted
        assert OAuth2RefreshToken.objects.count() == current_refresh_tokens - expected_refresh_tokens_deleted


@pytest.mark.django_db
class TestCleanupTokensCommand:
    def test_cleanup_expired_tokens(self, oauth2_admin_access_token):
        assert OAuth2AccessToken.objects.count() == 1
        assert OAuth2RefreshToken.objects.count() == 1

        attempt_cleanup(0, 0)

        # Manually expire admin token
        oauth2_admin_access_token.expires = datetime.datetime.fromtimestamp(0)
        oauth2_admin_access_token.save()

        attempt_cleanup(1, 1)
