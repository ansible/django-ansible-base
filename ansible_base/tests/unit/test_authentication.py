from collections import OrderedDict
from unittest import mock
from unittest.mock import MagicMock

import ldap
import pytest
from rest_framework.serializers import ValidationError

from ansible_base.authenticator_plugins.ldap import AuthenticatorPlugin, LDAPSettings, validate_ldap_filter


@pytest.fixture
def ldap_settings(ldap_configuration):
    return LDAPSettings(defaults=ldap_configuration)


def test_ldap_validate_connection_options_newctx_comes_last(ldap_configuration):
    ldap_configuration["CONNECTION_OPTIONS"]["OPT_X_TLS_NEWCTX"] = 0
    ldap_configuration["CONNECTION_OPTIONS"]["OPT_X_TLS_PACKAGE"] = "GnuTLS"
    settings = LDAPSettings(defaults=ldap_configuration)
    assert settings.CONNECTION_OPTIONS[ldap.OPT_X_TLS_NEWCTX] == 0
    assert isinstance(settings.CONNECTION_OPTIONS, OrderedDict)
    last_key = next(reversed(settings.CONNECTION_OPTIONS))
    assert last_key == ldap.OPT_X_TLS_NEWCTX


def test_ldap_validate_ldap_filter(ldap_configuration, ldap_settings):
    """
    Ensure we handle invalid subfilters correctly.

    validate_ldap_filter should return False if the overall filter is invalid.
    """
    invalid_filter = "(&(cn=%(user)s)(objectClass=posixAccount)(invalid))"
    with pytest.raises(ValidationError) as e:
        validate_ldap_filter(invalid_filter, 'foo')
    assert e.value.args[0] == 'Invalid filter: (invalid)'


@pytest.mark.django_db
@mock.patch("ansible_base.authenticator_plugins.ldap.logger")
def test_AuthenticatorPlugin_authenticate_authenticator_disabled(logger, ldap_authenticator, ldap_settings):
    """
    Ensure we handle disabled authenticators correctly in AuthenticatorPlugin.authenticate.

    Normally we cannot hit this case (thus we cannot write a functional test for it), because
    we filter for enabled authenticators only. But perhaps in the future we will
    call this differently, so it's worth keeping the safeguard in place.

    This tests that safeguard.
    """
    ldap_authenticator.enabled = False
    ldap_authenticator.save()
    backend = AuthenticatorPlugin(database_instance=ldap_authenticator)
    request = MagicMock()
    assert backend.authenticate(request, username="foo", password="bar") is None
    logger.info.assert_called_with(f"LDAP authenticator {ldap_authenticator.name} is disabled, skipping")


@pytest.mark.django_db
@mock.patch("ansible_base.authenticator_plugins.ldap.logger")
def test_AuthenticatorPlugin_authenticate_no_authenticator(logger):
    """
    Test how AuthenticatorPlugin.authenticate handles no authenticator.
    """
    backend = AuthenticatorPlugin(database_instance=None)
    request = MagicMock()
    assert backend.authenticate(request, username="foo", password="bar") is None
    logger.error.assert_called_with("AuthenticatorPlugin was missing an authenticator")


@pytest.mark.django_db
@mock.patch("ansible_base.authenticator_plugins.ldap.LDAPBackend.authenticate", return_value=None)
@pytest.mark.parametrize(
    "extra_settings, newctx_value",
    [
        ({}, None),
        ({"CONNECTION_OPTIONS": {"OPT_X_TLS_REQUIRE_CERT": True}, "START_TLS": True}, 0),
        ({"CONNECTION_OPTIONS": {"OPT_X_TLS_REQUIRE_CERT": True}, "START_TLS": False}, None),
        ({"CONNECTION_OPTIONS": {"OPT_X_TLS_REQUIRE_CERT": False}, "START_TLS": True}, 0),
        ({"CONNECTION_OPTIONS": {"OPT_X_TLS_REQUIRE_CERT": False}, "START_TLS": False}, None),
        ({"CONNECTION_OPTIONS": {}, "START_TLS": False}, None),
        ({"CONNECTION_OPTIONS": {}, "START_TLS": True}, None),
        ({"CONNECTION_OPTIONS": {"OPT_X_TLS_REQUIRE_CERT": True, "OPT_X_TLS_NEWCTX": 1}, "START_TLS": True}, 0),
        ({"CONNECTION_OPTIONS": {"OPT_X_TLS_REQUIRE_CERT": True, "OPT_X_TLS_NEWCTX": 1}, "START_TLS": False}, 1),
    ],
    ids=[
        "START_TLS not specified",
        "START_TLS enabled, OPT_X_TLS_REQUIRE_CERT enabled",
        "START_TLS disabled, OPT_X_TLS_REQUIRE_CERT enabled",
        "START_TLS enabled, OPT_X_TLS_REQUIRE_CERT disabled",
        "START_TLS disabled, OPT_X_TLS_REQUIRE_CERT disabled",
        "START_TLS disabled, no OPT_X_TLS_REQUIRE_CERT",
        "START_TLS enabled, no OPT_X_TLS_REQUIRE_CERT",
        "Existing OPT_X_TLS_NEWCTX gets forced to 0 (START_TLS enabled)",
        "Existing OPT_X_TLS_NEWCTX gets preserved (START_TLS disabled)",
    ],
)
def test_AuthenticatorPlugin_authenticate_start_tls(authenticate, ldap_authenticator, extra_settings, newctx_value, shut_up_logging):
    """
    Ensure we force OPT_X_TLS_NEWCTX to 0 (only) when START_TLS is enabled.

    Conditions:
    - START_TLS enabled in settings
    - OPT_X_TLS_REQUIRE_CERT enabled in settings.CONNECTION_OPTIONS
    """
    ldap_authenticator.configuration.update(extra_settings)
    ldap_authenticator.save()
    # settings = LDAPSettings(defaults=ldap_authenticator.configuration)
    backend = AuthenticatorPlugin(database_instance=ldap_authenticator)
    request = MagicMock()
    assert backend.authenticate(request, username="foo", password="bar") is None
    if newctx_value is not None:
        assert backend.settings.CONNECTION_OPTIONS[ldap.OPT_X_TLS_NEWCTX] == newctx_value
    else:
        assert ldap.OPT_X_TLS_NEWCTX not in backend.settings.CONNECTION_OPTIONS
