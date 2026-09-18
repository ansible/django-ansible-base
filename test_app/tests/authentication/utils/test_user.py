from unittest import mock

import pytest

from ansible_base.authentication.models import AuthenticatorUser
from ansible_base.authentication.utils.user import can_user_change_password, normalize_and_get_email


@pytest.mark.parametrize(
    "authenticators,expected_result",
    [
        (None, False),
        ([], True),
        (["system"], False),
        (["system", "local", "ldap"], False),
        (["local"], True),
        (["ldap"], False),
        (["ldap", "saml"], False),
        (["saml", "local"], True),
        (["custom"], False),
        (["custom", "local"], True),
    ],
)
def test_can_user_change_password(
    authenticators, expected_result, system_user, random_user, local_authenticator, ldap_authenticator, custom_authenticator, saml_authenticator
):
    if authenticators is None:
        user = None
    else:
        if 'system' in authenticators:
            user = system_user
        else:
            user = random_user

        for authenticator in authenticators:
            if authenticator == 'local':
                AuthenticatorUser.objects.get_or_create(uid=random_user.username, user=random_user, provider=local_authenticator)
            elif authenticator == 'ldap':
                AuthenticatorUser.objects.get_or_create(uid=random_user.username, user=random_user, provider=ldap_authenticator)
            elif authenticator == 'custom':
                AuthenticatorUser.objects.get_or_create(uid=random_user.username, user=random_user, provider=custom_authenticator)
            elif authenticator == 'saml':
                AuthenticatorUser.objects.get_or_create(uid=random_user.username, user=random_user, provider=saml_authenticator)

    assert can_user_change_password(user) == expected_result


def test_can_user_change_password_import_error(local_authenticator, random_user):
    AuthenticatorUser.objects.get_or_create(uid=random_user.username, user=random_user, provider=local_authenticator)
    with mock.patch('ansible_base.authentication.utils.user.get_authenticator_plugin', side_effect=ImportError("Test Exception")):
        assert can_user_change_password(random_user) is False


@pytest.mark.parametrize(
    "email_input,expected",
    [
        # Valid emails pass through
        ("user@example.com", "user@example.com"),
        ("User@Example.COM", "user@example.com"),
        ("  user@example.com  ", "user@example.com"),
        (["user@example.com"], "user@example.com"),
        # Invalid emails are rejected (returns None)
        ("not-an-email", None),
        ("justausername", None),
        ("user@", None),
        ("@example.com", None),
        # Empty/None inputs
        ("", None),
        (None, None),
        ([], None),
        # Non-string types
        (123, None),
        ({}, None),
        # List with invalid email
        (["not-an-email"], None),
        ([""], None),
    ],
)
def test_normalize_and_get_email(email_input, expected):
    """Test that normalize_and_get_email validates email format and rejects invalid addresses."""
    assert normalize_and_get_email(email_input) == expected


def test_normalize_and_get_email_logs_warning_for_invalid(caplog):
    """Test that an invalid email from an authenticator logs a warning."""
    import logging

    with caplog.at_level(logging.WARNING, logger='ansible_base.authentication.utils.user'):
        result = normalize_and_get_email("not-a-valid-email")
    assert result is None
    assert "Rejecting invalid email address" in caplog.text
    assert "not-a-valid-email" in caplog.text
