import hashlib
from datetime import datetime, timezone

import pytest
from oauthlib.common import generate_token

from ansible_base.lib.testing.fixtures import copy_fixture
from ansible_base.lib.utils.hashing import hash_string
from ansible_base.lib.utils.response import get_relative_url
from ansible_base.oauth2_provider.models import OAuth2AccessToken, OAuth2Application

__all__ = [  # noqa: F822, the additional _pat_X are unknown so we need this here
    'oauth2_application',
    'oauth2_application_password',
    'oauth2_admin_access_token',
    'oauth2_user_pat',
    'oauth2_user_pat_1',
    'oauth2_user_pat_2',
    'oauth2_user_pat_3',
    'oauth2_user_application_token',
    'oauth2_user_application_token_1',
    'oauth2_user_application_token_2',
    'oauth2_user_application_token_3',
]


@pytest.fixture
def oauth2_application(randname):
    """
    Creates an OAuth2 application with a random name and returns
    both the application and its client secret.
    """
    app = OAuth2Application(
        name=randname("OAuth2 Application"),
        description="Test OAuth2 Application",
        redirect_uris="https://example.com/callback",
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
        redirect_uris="https://example.com/callback",
        authorization_grant_type="password",
        client_type="confidential",
    )
    # Store this before it gets hashed
    secret = app.client_secret
    app.save()
    return (app, secret)


@pytest.fixture
def oauth2_admin_access_token(oauth2_application, admin_api_client, admin_user):
    """
    3-tuple with (token object with hashed token, plaintext token, plaintext_refresh_token)
    """
    url = get_relative_url('token-list')
    response = admin_api_client.post(url, {'application': oauth2_application[0].pk})
    assert response.status_code == 201

    plaintext_token = response.data['token']
    plaintext_refresh_token = response.data['refresh_token']
    hashed_token = hash_string(plaintext_token, hasher=hashlib.sha256, algo="sha256")
    token = OAuth2AccessToken.objects.get(token=hashed_token)
    return (token, plaintext_token, plaintext_refresh_token)


@copy_fixture(copies=3)
@pytest.fixture
def oauth2_user_pat(user, randname):
    return OAuth2AccessToken.objects.get_or_create(
        user=user,
        description=randname("Personal Access Token for 'user'"),
        # This has to be timezone aware
        expires=datetime(2088, 1, 1, tzinfo=timezone.utc),
        token=generate_token(),
    )[0]


@copy_fixture(copies=3)
@pytest.fixture
def oauth2_user_application_token(user, randname, oauth2_application):
    return OAuth2AccessToken.objects.get_or_create(
        user=user,
        description=randname("Application Access Token for 'user'"),
        # This has to be timezone aware
        expires=datetime(2088, 1, 1, tzinfo=timezone.utc),
        token=generate_token(),
        application=oauth2_application[0],
    )[0]
