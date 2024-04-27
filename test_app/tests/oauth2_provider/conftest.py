from datetime import datetime, timezone

import pytest
from oauthlib.common import generate_token

from ansible_base.oauth2_provider.models import OAuth2AccessToken, OAuth2Application


@pytest.fixture
def oauth2_application(randname):
    return OAuth2Application.objects.create(
        name=randname("OAuth2 Application"),
        description="Test OAuth2 Application",
        redirect_uris="http://example.com/callback",
        authorization_grant_type="authorization-code",
        client_type="confidential",
    )


@pytest.fixture
def oauth2_admin_access_token(oauth2_application, admin_user):
    return OAuth2AccessToken.objects.get_or_create(
        user=admin_user,
        application=oauth2_application,
        description="Test Access Token",
        # This has to be timezone aware
        expires=datetime(2088, 1, 1, tzinfo=timezone.utc),
        token=generate_token(),
    )[0]
