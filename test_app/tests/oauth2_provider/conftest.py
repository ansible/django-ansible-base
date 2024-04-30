from datetime import datetime, timezone

import pytest
from oauthlib.common import generate_token

from ansible_base.oauth2_provider.models import OAuth2AccessToken, OAuth2Application


@pytest.fixture
def oauth2_application(randname):
    """
    Creates an OAuth2 application with a random name and returns
    both the application and its client secret.
    """
    app = OAuth2Application(
        name=randname("OAuth2 Application"),
        description="Test OAuth2 Application",
        redirect_uris="http://example.com/callback",
        authorization_grant_type="authorization-code",
        client_type="confidential",
    )
    # Store this before it gets hashed
    secret = app.client_secret
    app.save()
    return (app, secret)


@pytest.fixture
def oauth2_application_password(randname):
    """
    Creates an OAuth2 application with a random name and returns
    both the application and its client secret.
    """
    app = OAuth2Application(
        name=randname("OAuth2 Application"),
        description="Test OAuth2 Application",
        redirect_uris="http://example.com/callback",
        authorization_grant_type="password",
        client_type="confidential",
    )
    # Store this before it gets hashed
    secret = app.client_secret
    app.save()
    return (app, secret)


@pytest.fixture
def oauth2_admin_access_token(oauth2_application, admin_user):
    return OAuth2AccessToken.objects.get_or_create(
        user=admin_user,
        application=oauth2_application[0],
        description="Test Access Token",
        # This has to be timezone aware
        expires=datetime(2088, 1, 1, tzinfo=timezone.utc),
        token=generate_token(),
    )[0]
