import logging
from datetime import datetime, timezone
from unittest import mock

import pytest
from oauthlib.common import generate_token

from ansible_base.oauth2_provider.models import OAuth2AccessToken, OAuth2RefreshToken


@pytest.mark.django_db
def test_oauth2_revoke_access_then_refresh_token(oauth2_admin_access_token):
    token = oauth2_admin_access_token[0]
    refresh_token = oauth2_admin_access_token[0].refresh_token
    assert OAuth2AccessToken.objects.count() == 1
    assert OAuth2RefreshToken.objects.count() == 1

    token.revoke()
    assert OAuth2AccessToken.objects.count() == 0
    assert OAuth2RefreshToken.objects.count() == 1
    assert not refresh_token.revoked

    refresh_token.revoke()
    assert OAuth2AccessToken.objects.count() == 0
    assert OAuth2RefreshToken.objects.count() == 1


@pytest.mark.django_db
def test_oauth2_revoke_refresh_token(oauth2_admin_access_token):
    refresh_token = oauth2_admin_access_token[0].refresh_token
    assert OAuth2AccessToken.objects.count() == 1
    assert OAuth2RefreshToken.objects.count() == 1

    refresh_token.revoke()
    assert OAuth2AccessToken.objects.count() == 0
    # the same OAuth2RefreshToken is recycled
    new_refresh_token = OAuth2RefreshToken.objects.all().first()
    assert refresh_token == new_refresh_token
    assert new_refresh_token.revoked


@pytest.mark.django_db
@mock.patch("ansible_base.oauth2_provider.models.access_token.logger")
def test_oauth2_access_token_creation_logs_with_application(mock_logger, oauth2_application_password, admin_user):
    """Test that OAuth2AccessToken creation logs with application name."""
    application, _secret = oauth2_application_password

    # Create an access token with an application
    token = OAuth2AccessToken.objects.create(
        user=admin_user,
        application=application,
        token=generate_token(),
        scope='write',
        expires=datetime(2088, 1, 1, tzinfo=timezone.utc),
    )

    # Verify the logger was called with the correct message
    mock_logger.log.assert_called_once_with(
        logging.INFO, f"Created OAuth2 access token {token.pk} for user '{admin_user.username}' with application '{application.name}' and scope 'write'"
    )

    # Verify the token was created
    assert OAuth2AccessToken.objects.filter(pk=token.pk).exists()


@pytest.mark.django_db
@mock.patch("ansible_base.oauth2_provider.models.access_token.logger")
def test_oauth2_access_token_creation_logs_without_application(mock_logger, admin_user):
    """Test that OAuth2AccessToken creation logs for personal access tokens."""
    # Create a personal access token (no application)
    token = OAuth2AccessToken.objects.create(
        user=admin_user,
        application=None,
        token=generate_token(),
        scope='read',
        expires=datetime(2088, 1, 1, tzinfo=timezone.utc),
    )

    # Verify the logger was called with personal access token message
    mock_logger.log.assert_called_once_with(
        logging.INFO, f"Created OAuth2 access token {token.pk} for user '{admin_user.username}' with application 'N/A (Personal Access Token)' and scope 'read'"
    )

    # Verify the token was created
    assert OAuth2AccessToken.objects.filter(pk=token.pk).exists()


@pytest.mark.django_db
@mock.patch("ansible_base.oauth2_provider.models.refresh_token.logger")
def test_oauth2_refresh_token_creation_logs(mock_logger, oauth2_application_password, admin_user):
    """Test that OAuth2RefreshToken creation logs with access token reference."""
    application, _secret = oauth2_application_password

    # Create an access token first
    access_token = OAuth2AccessToken.objects.create(
        user=admin_user,
        application=application,
        token=generate_token(),
        scope='write',
        expires=datetime(2088, 1, 1, tzinfo=timezone.utc),
    )

    # Create a refresh token linked to the access token
    refresh_token = OAuth2RefreshToken.objects.create(
        user=admin_user,
        application=application,
        token=generate_token(),
        access_token=access_token,
    )

    # Verify the logger was called with the correct message
    mock_logger.log.assert_called_once_with(
        logging.INFO, f"Created OAuth2 refresh token {refresh_token.pk} for user '{admin_user.username}' linked to access token {access_token.pk}"
    )

    # Verify the refresh token was created
    assert OAuth2RefreshToken.objects.filter(pk=refresh_token.pk).exists()
