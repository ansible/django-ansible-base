import logging
from collections import OrderedDict
from unittest.mock import Mock, patch

import pytest
from django.test import RequestFactory
from jwt.exceptions import ExpiredSignatureError, InvalidSignatureError, PyJWKClientConnectionError
from rest_framework.request import Request

from ansible_base.authentication.authenticator_plugins.oauth_bearer import AuthenticatorPlugin
from ansible_base.authentication.bearer_authentication import (
    BearerAuthentication,
    BearerAuthenticationResult,
    BearerTokenValidationError,
    ScopedBearerToken,
)

PLUGIN_LOGGER = "ansible_base.authentication.authenticator_plugins.oauth_bearer"
AUDIT_LOGGER = "ansible_base.auth_audit"


def _routing_claims(configuration):
    return {"iss": configuration["ISSUER_URL"], "aud": configuration["AUDIENCE"]}


def _request(token="signed-token"):
    return Request(RequestFactory().get("/", HTTP_AUTHORIZATION=f"Bearer {token}"))


def _plugin_authenticate(plugin, token, decode_side_effect, signing_key=None):
    """Run the plugin with a deterministic decode sequence and a mocked JWKS client."""
    signing_key = signing_key or Mock(key="public-key", _jwk_data={"kid": "test-key"})
    with (
        patch("ansible_base.authentication.authenticator_plugins.oauth_bearer.CachedJWKClient") as jwk_client,
        patch("ansible_base.authentication.authenticator_plugins.oauth_bearer.decode", side_effect=decode_side_effect),
    ):
        jwk_client.return_value.get_signing_key_from_jwt.return_value = signing_key
        jwk_client.return_value.refresh_signing_key_from_jwt.return_value = signing_key
        return plugin.authenticate(token=token)


@pytest.mark.django_db
def test_routing_decline_is_logged_with_provider_name(oauth_bearer_authenticator, caplog):
    """A token another provider owns is declined with a debug line naming this authenticator (TC-2 items 1 and 9)."""
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)

    with caplog.at_level(logging.DEBUG, logger=PLUGIN_LOGGER):
        assert plugin.authenticate(token="opaque-non-jwt-token") is None

    assert f"does not match authenticator {oauth_bearer_authenticator.name}" in caplog.text


@pytest.mark.django_db
def test_successful_authentication_emits_audit_event_with_user_provider_and_timestamp(caplog):
    """A successful login writes one INFO audit record with the user, provider identity and a timestamp (TC-2 item 2)."""
    user = Mock(username="external-user")
    plugin = Mock()
    plugin.authenticate.return_value = BearerAuthenticationResult(user=user, auth=ScopedBearerToken(scopes=frozenset()))

    with (
        patch.object(BearerAuthentication, "_api_authentication_backends", return_value=OrderedDict({7: plugin})),
        caplog.at_level(logging.INFO, logger=AUDIT_LOGGER),
    ):
        authenticated_user, _ = BearerAuthentication().authenticate(_request())

    assert authenticated_user is user
    events = [record for record in caplog.records if record.name == AUDIT_LOGGER]
    assert len(events) == 1
    event = events[0]
    assert event.levelno == logging.INFO
    assert event.created > 0
    assert "external-user" in event.getMessage()
    assert '"7"' in event.getMessage()


@pytest.mark.django_db
def test_expired_token_logs_reason_without_the_token_value(oauth_bearer_authenticator, caplog):
    """An expired token logs its reason at debug level and never the credential (TC-2 item 3)."""
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)
    token = "expired-token-value"
    claims = _routing_claims(oauth_bearer_authenticator.configuration)
    signing_errors = [claims, ExpiredSignatureError("expired")]

    with caplog.at_level(logging.DEBUG, logger=PLUGIN_LOGGER):
        with pytest.raises(BearerTokenValidationError) as exc:
            _plugin_authenticate(plugin, token, signing_errors)

    assert exc.value.reason == "expired"
    assert f"token expired for authenticator {oauth_bearer_authenticator.name}" in caplog.text
    assert token not in caplog.text


@pytest.mark.django_db
def test_invalid_signature_logs_troubleshooting_context_without_the_token_value(oauth_bearer_authenticator, caplog):
    """A signature that survives one key refresh logs the refresh attempt and never the credential (TC-2 item 4)."""
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)
    token = "unsigned-token-value"
    claims = _routing_claims(oauth_bearer_authenticator.configuration)
    signing_errors = [claims, InvalidSignatureError("bad signature")]

    with caplog.at_level(logging.DEBUG, logger=PLUGIN_LOGGER):
        with pytest.raises(BearerTokenValidationError) as exc:
            _plugin_authenticate(plugin, token, signing_errors)

    assert exc.value.reason == "invalid"
    assert f"signature failed for authenticator {oauth_bearer_authenticator.name}" in caplog.text
    assert "refreshing signing key" in caplog.text
    assert token not in caplog.text


@pytest.mark.django_db
def test_unavailable_jwks_logs_a_warning_and_maps_to_provider_unavailable(oauth_bearer_authenticator, caplog):
    """An unreachable JWKS endpoint logs a warning with the provider name and a safe failure reason (TC-2 item 5)."""
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)
    token = "unavailable-token-value"

    with (
        patch("ansible_base.authentication.authenticator_plugins.oauth_bearer.CachedJWKClient") as jwk_client,
        patch("ansible_base.authentication.authenticator_plugins.oauth_bearer.decode", return_value=_routing_claims(oauth_bearer_authenticator.configuration)),
        caplog.at_level(logging.DEBUG, logger=PLUGIN_LOGGER),
    ):
        jwk_client.return_value.get_signing_key_from_jwt.side_effect = PyJWKClientConnectionError("connection refused")
        with pytest.raises(BearerTokenValidationError) as exc:
            plugin.authenticate(token=token)

    assert exc.value.reason == "provider_unavailable"
    assert f"OAuth Bearer JWKS endpoint is unavailable for authenticator {oauth_bearer_authenticator.name}" in caplog.text
    assert token not in caplog.text


@pytest.mark.django_db
@pytest.mark.parametrize("reason", ["invalid", "expired", "provider_unavailable"])
def test_failure_detail_is_generic_and_carries_no_internal_detail(oauth_bearer_authenticator, reason):
    """Client-visible failure text names neither the provider, its endpoints, nor the credential (TC-2 item 8)."""
    failure = BearerTokenValidationError(reason)
    exposed_text = " ".join(filter(None, [str(failure), failure.detail, failure.error_description or ""]))

    assert exposed_text
    for internal in (oauth_bearer_authenticator.name, oauth_bearer_authenticator.configuration["JWKS_URI"], "signed-token-value"):
        assert internal not in exposed_text


@pytest.mark.django_db
def test_debug_logging_can_be_raised_for_troubleshooting(oauth_bearer_authenticator, caplog):
    """Raising the plugin logger to DEBUG surfaces the validation trail for one login (TC-2 items 1 and 9)."""
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)
    claims = {
        **_routing_claims(oauth_bearer_authenticator.configuration),
        "sub": "subject",
        "email": "user@example.com",
        "scope": "read",
    }

    with (
        caplog.at_level(logging.DEBUG, logger=PLUGIN_LOGGER),
        patch(
            "ansible_base.authentication.authenticator_plugins.oauth_bearer.get_or_create_authenticator_user", return_value=(Mock(is_active=True), Mock(), True)
        ),
        patch("ansible_base.authentication.authenticator_plugins.oauth_bearer.is_system_user", return_value=False),
        patch("ansible_base.authentication.authenticator_plugins.oauth_bearer.update_user_claims"),
    ):
        _plugin_authenticate(plugin, "signed-token-value", [claims, claims])

    assert f"Validating external OAuth token against authenticator {oauth_bearer_authenticator.name}" in caplog.text
    assert f"OAuth Bearer JWT validated for authenticator {oauth_bearer_authenticator.name}" in caplog.text
    assert "signed-token-value" not in caplog.text
