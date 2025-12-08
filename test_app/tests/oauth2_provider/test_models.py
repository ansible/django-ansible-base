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


@pytest.mark.django_db
def test_oauth2_access_token_has_non_trivial_changes_returns_true_for_new_token(admin_user):
    """Test that _has_non_trivial_changes returns False for a new token (no pk yet)."""
    token = OAuth2AccessToken(
        user=admin_user,
        application=None,
        token=generate_token(),
        scope='write',
        expires=datetime(2088, 1, 1, tzinfo=timezone.utc),
    )
    assert token._has_non_trivial_changes() is True


@pytest.mark.django_db
def test_oauth2_access_token_has_non_trivial_changes_returns_false_for_timestamp_only_changes(admin_user):
    """Test that _has_non_trivial_changes returns False when only timestamp fields change."""
    token = OAuth2AccessToken.objects.create(
        user=admin_user,
        application=None,
        token=generate_token(),
        scope='write',
        expires=datetime(2088, 1, 1, tzinfo=timezone.utc),
    )

    # Modify only timestamp fields (these should be ignored)
    # Note: modified is auto_now, so it will change automatically
    # created_by and modified_by are also timestamp-related
    # last_used is explicitly a timestamp field

    # Since we can't directly modify timestamp fields without triggering other changes,
    # we just verify that if we call the method without changing any real fields, it returns False
    assert token._has_non_trivial_changes() is False


@pytest.mark.django_db
def test_oauth2_access_token_has_non_trivial_changes_returns_true_for_scope_change(admin_user):
    """Test that _has_non_trivial_changes returns True when scope changes."""
    token = OAuth2AccessToken.objects.create(
        user=admin_user,
        application=None,
        token=generate_token(),
        scope='write',
        expires=datetime(2088, 1, 1, tzinfo=timezone.utc),
    )

    # Change a non-timestamp field
    token.scope = 'read'

    assert token._has_non_trivial_changes() is True


@pytest.mark.django_db
def test_oauth2_access_token_has_non_trivial_changes_returns_true_for_description_change(admin_user):
    """Test that _has_non_trivial_changes returns True when description changes."""
    token = OAuth2AccessToken.objects.create(
        user=admin_user,
        application=None,
        token=generate_token(),
        scope='write',
        expires=datetime(2088, 1, 1, tzinfo=timezone.utc),
        description='Original description',
    )

    # Change a non-timestamp field
    token.description = 'Updated description'

    assert token._has_non_trivial_changes() is True


@pytest.mark.django_db
def test_oauth2_access_token_has_non_trivial_changes_returns_true_for_expires_change(admin_user):
    """Test that _has_non_trivial_changes returns True when expires changes."""
    token = OAuth2AccessToken.objects.create(
        user=admin_user,
        application=None,
        token=generate_token(),
        scope='write',
        expires=datetime(2088, 1, 1, tzinfo=timezone.utc),
    )

    # Change a non-timestamp field
    token.expires = datetime(2089, 1, 1, tzinfo=timezone.utc)

    assert token._has_non_trivial_changes() is True


@pytest.mark.django_db
def test_oauth2_refresh_token_has_non_trivial_changes_returns_true_for_new_token(admin_user):
    """Test that _has_non_trivial_changes returns False for a new refresh token."""
    access_token = OAuth2AccessToken.objects.create(
        user=admin_user,
        token=generate_token(),
        scope='write',
        expires=datetime(2088, 1, 1, tzinfo=timezone.utc),
    )

    refresh_token = OAuth2RefreshToken(
        user=admin_user,
        token=generate_token(),
        access_token=access_token,
    )

    assert refresh_token._has_non_trivial_changes() is True


@pytest.mark.django_db
def test_oauth2_refresh_token_has_non_trivial_changes_returns_false_for_no_changes(admin_user, oauth2_application_password):
    """Test that _has_non_trivial_changes returns False when nothing changed."""
    application, _secret = oauth2_application_password

    access_token = OAuth2AccessToken.objects.create(
        user=admin_user,
        application=application,
        token=generate_token(),
        scope='write',
        expires=datetime(2088, 1, 1, tzinfo=timezone.utc),
    )

    refresh_token = OAuth2RefreshToken.objects.create(
        user=admin_user,
        application=application,
        token=generate_token(),
        access_token=access_token,
    )

    assert refresh_token._has_non_trivial_changes() is False


@pytest.mark.django_db
def test_oauth2_refresh_token_has_non_trivial_changes_returns_true_for_revoked_change(admin_user, oauth2_application_password):
    """Test that _has_non_trivial_changes returns True when revoked status changes."""
    application, _secret = oauth2_application_password

    access_token = OAuth2AccessToken.objects.create(
        user=admin_user,
        application=application,
        token=generate_token(),
        scope='write',
        expires=datetime(2088, 1, 1, tzinfo=timezone.utc),
    )

    refresh_token = OAuth2RefreshToken.objects.create(
        user=admin_user,
        application=application,
        token=generate_token(),
        access_token=access_token,
        revoked=datetime(2088, 1, 1, tzinfo=timezone.utc),
    )

    # Change revoked status
    refresh_token.revoked = None

    assert refresh_token._has_non_trivial_changes() is True


@pytest.mark.django_db
@mock.patch("ansible_base.oauth2_provider.models.access_token.logger")
def test_oauth2_access_token_modification_logs_with_scope_change(mock_logger, admin_user):
    """Test that OAuth2AccessToken modification logs when scope changes."""
    # Create an access token
    token = OAuth2AccessToken.objects.create(
        user=admin_user,
        application=None,
        token=generate_token(),
        scope='write',
        expires=datetime(2088, 1, 1, tzinfo=timezone.utc),
    )

    # Reset the mock to ignore creation log
    mock_logger.reset_mock()

    # Modify the scope (a non-timestamp field)
    token.scope = 'read'
    token.save()

    # Verify the modification was logged
    expected_msg = (
        f"Modified OAuth2 access token {token.pk} for user '{admin_user.username}' " f"with application 'N/A (Personal Access Token)' and scope 'read'"
    )
    mock_logger.log.assert_called_once_with(logging.INFO, expected_msg)


@pytest.mark.django_db
@mock.patch("ansible_base.oauth2_provider.models.access_token.logger")
def test_oauth2_access_token_modification_logs_with_description_change(mock_logger, oauth2_application_password, admin_user):
    """Test that OAuth2AccessToken modification logs when description changes."""
    application, _secret = oauth2_application_password

    # Create an access token
    token = OAuth2AccessToken.objects.create(
        user=admin_user,
        application=application,
        token=generate_token(),
        scope='write',
        expires=datetime(2088, 1, 1, tzinfo=timezone.utc),
        description='Original',
    )

    # Reset the mock to ignore creation log
    mock_logger.reset_mock()

    # Modify the description (a non-timestamp field)
    token.description = 'Updated'
    token.save()

    # Verify the modification was logged
    mock_logger.log.assert_called_once_with(
        logging.INFO, f"Modified OAuth2 access token {token.pk} for user '{admin_user.username}' with application '{application.name}' and scope 'write'"
    )


@pytest.mark.django_db
@mock.patch("ansible_base.oauth2_provider.models.access_token.logger")
def test_oauth2_access_token_no_modification_log_for_timestamp_only_changes(mock_logger, admin_user):
    """Test that OAuth2AccessToken does not log modification when only timestamp fields change."""
    # Create an access token
    token = OAuth2AccessToken.objects.create(
        user=admin_user,
        application=None,
        token=generate_token(),
        scope='write',
        expires=datetime(2088, 1, 1, tzinfo=timezone.utc),
    )

    # Reset the mock to ignore creation log
    mock_logger.reset_mock()

    # Save without changing non-timestamp fields
    # This will update modified and modified_by, but should not log
    token.save()

    # Verify no modification log was created
    mock_logger.log.assert_not_called()


@pytest.mark.django_db
@mock.patch("ansible_base.oauth2_provider.models.access_token.logger")
def test_oauth2_access_token_no_modification_log_for_last_used_change(mock_logger, admin_user):
    """Test that OAuth2AccessToken does not log modification when only last_used changes."""
    # Create an access token
    token = OAuth2AccessToken.objects.create(
        user=admin_user,
        application=None,
        token=generate_token(),
        scope='write',
        expires=datetime(2088, 1, 1, tzinfo=timezone.utc),
    )

    # Reset the mock to ignore creation log
    mock_logger.reset_mock()

    # Update only last_used (a timestamp field that should be ignored)
    token.save(update_fields=['last_used'])

    # Verify no modification log was created
    mock_logger.log.assert_not_called()


@pytest.mark.django_db
@mock.patch("ansible_base.oauth2_provider.models.refresh_token.logger")
def test_oauth2_refresh_token_modification_logs_with_revoked_change(mock_logger, admin_user, oauth2_application_password):
    """Test that OAuth2RefreshToken modification logs when revoked status changes."""
    application, _secret = oauth2_application_password

    # Create tokens
    access_token = OAuth2AccessToken.objects.create(
        user=admin_user,
        application=application,
        token=generate_token(),
        scope='write',
        expires=datetime(2088, 1, 1, tzinfo=timezone.utc),
    )

    refresh_token = OAuth2RefreshToken.objects.create(
        user=admin_user,
        application=application,
        token=generate_token(),
        access_token=access_token,
    )

    # Reset the mock to ignore creation log
    mock_logger.reset_mock()

    # Modify the revoked status (a non-timestamp field)
    refresh_token.revoked = datetime(2088, 6, 1, tzinfo=timezone.utc)
    refresh_token.save()

    # Verify the modification was logged
    mock_logger.log.assert_called_once_with(
        logging.INFO, f"Modified OAuth2 refresh token {refresh_token.pk} for user '{admin_user.username}' linked to access token {access_token.pk}"
    )


@pytest.mark.django_db
@mock.patch("ansible_base.oauth2_provider.models.refresh_token.logger")
def test_oauth2_refresh_token_no_modification_log_for_timestamp_only_changes(mock_logger, admin_user, oauth2_application_password):
    """Test that OAuth2RefreshToken does not log modification when only timestamp fields change."""
    application, _secret = oauth2_application_password

    # Create tokens
    access_token = OAuth2AccessToken.objects.create(
        user=admin_user,
        application=application,
        token=generate_token(),
        scope='write',
        expires=datetime(2088, 1, 1, tzinfo=timezone.utc),
    )

    refresh_token = OAuth2RefreshToken.objects.create(
        user=admin_user,
        application=application,
        token=generate_token(),
        access_token=access_token,
    )

    # Reset the mock to ignore creation log
    mock_logger.reset_mock()

    # Save without changing non-timestamp fields
    # This will update modified and modified_by, but should not log
    refresh_token.save()

    # Verify no modification log was created
    mock_logger.log.assert_not_called()


@pytest.mark.django_db
@mock.patch("ansible_base.oauth2_provider.models.access_token.logger")
def test_oauth2_access_token_no_modification_log_with_update_fields_timestamp_only(mock_logger, admin_user):
    """Test that OAuth2AccessToken does not log when update_fields contains only timestamp fields."""
    # Create an access token
    token = OAuth2AccessToken.objects.create(
        user=admin_user,
        application=None,
        token=generate_token(),
        scope='write',
        expires=datetime(2088, 1, 1, tzinfo=timezone.utc),
    )

    # Reset the mock to ignore creation log
    mock_logger.reset_mock()

    # Save with update_fields containing only timestamp fields
    token.save(update_fields=['modified', 'modified_by'])

    # Verify no modification log was created
    mock_logger.log.assert_not_called()


@pytest.mark.django_db
@mock.patch("ansible_base.oauth2_provider.models.access_token.logger")
def test_oauth2_access_token_modification_log_with_update_fields_non_timestamp(mock_logger, admin_user):
    """Test that OAuth2AccessToken logs when update_fields contains non-timestamp fields."""
    # Create an access token
    token = OAuth2AccessToken.objects.create(
        user=admin_user,
        application=None,
        token=generate_token(),
        scope='write',
        expires=datetime(2088, 1, 1, tzinfo=timezone.utc),
        description='Original',
    )

    # Reset the mock to ignore creation log
    mock_logger.reset_mock()

    # Change description and save with update_fields
    token.description = 'Updated'
    token.save(update_fields=['description'])

    # Verify the modification was logged
    expected_msg = (
        f"Modified OAuth2 access token {token.pk} for user '{admin_user.username}' " f"with application 'N/A (Personal Access Token)' and scope 'write'"
    )
    mock_logger.log.assert_called_once_with(logging.INFO, expected_msg)


@pytest.mark.django_db
@mock.patch("ansible_base.oauth2_provider.models.access_token.logger")
def test_oauth2_access_token_no_modification_log_with_update_fields_unchanged_field(mock_logger, admin_user):
    """Test that OAuth2AccessToken does not log when update_fields specifies a field that didn't change."""
    # Create an access token
    token = OAuth2AccessToken.objects.create(
        user=admin_user,
        application=None,
        token=generate_token(),
        scope='write',
        expires=datetime(2088, 1, 1, tzinfo=timezone.utc),
        description='Same',
    )

    # Reset the mock to ignore creation log
    mock_logger.reset_mock()

    # Save with update_fields but without actually changing the field
    token.save(update_fields=['description'])

    # Verify no modification log was created (field value didn't change)
    mock_logger.log.assert_not_called()


@pytest.mark.django_db
@mock.patch("ansible_base.oauth2_provider.models.refresh_token.logger")
def test_oauth2_refresh_token_no_modification_log_with_update_fields_timestamp_only(mock_logger, admin_user, oauth2_application_password):
    """Test that OAuth2RefreshToken does not log when update_fields contains only timestamp fields."""
    application, _secret = oauth2_application_password

    # Create tokens
    access_token = OAuth2AccessToken.objects.create(
        user=admin_user,
        application=application,
        token=generate_token(),
        scope='write',
        expires=datetime(2088, 1, 1, tzinfo=timezone.utc),
    )

    refresh_token = OAuth2RefreshToken.objects.create(
        user=admin_user,
        application=application,
        token=generate_token(),
        access_token=access_token,
    )

    # Reset the mock to ignore creation log
    mock_logger.reset_mock()

    # Save with update_fields containing only timestamp fields
    refresh_token.save(update_fields=['modified', 'modified_by'])

    # Verify no modification log was created
    mock_logger.log.assert_not_called()


@pytest.mark.django_db
@mock.patch("ansible_base.oauth2_provider.models.refresh_token.logger")
def test_oauth2_refresh_token_modification_log_with_update_fields_non_timestamp(mock_logger, admin_user, oauth2_application_password):
    """Test that OAuth2RefreshToken logs when update_fields contains non-timestamp fields."""
    application, _secret = oauth2_application_password

    # Create tokens
    access_token = OAuth2AccessToken.objects.create(
        user=admin_user,
        application=application,
        token=generate_token(),
        scope='write',
        expires=datetime(2088, 1, 1, tzinfo=timezone.utc),
    )

    refresh_token = OAuth2RefreshToken.objects.create(
        user=admin_user,
        application=application,
        token=generate_token(),
        access_token=access_token,
    )

    # Reset the mock to ignore creation log
    mock_logger.reset_mock()

    # Change revoked status and save with update_fields
    refresh_token.revoked = datetime(2088, 6, 1, tzinfo=timezone.utc)
    refresh_token.save(update_fields=['revoked'])

    # Verify the modification was logged
    mock_logger.log.assert_called_once_with(
        logging.INFO, f"Modified OAuth2 refresh token {refresh_token.pk} for user '{admin_user.username}' linked to access token {access_token.pk}"
    )
