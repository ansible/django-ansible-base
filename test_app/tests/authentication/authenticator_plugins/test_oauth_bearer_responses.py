from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest
from jwt.exceptions import ExpiredSignatureError, InvalidSignatureError, PyJWKClientConnectionError

from ansible_base.authentication.bearer_authentication import get_api_authentication_backends
from ansible_base.lib.utils.response import get_relative_url

PLUGIN = "ansible_base.authentication.authenticator_plugins.oauth_bearer"
TOKEN = "external-token-value"


def _claims(configuration):
    return {
        "iss": configuration["ISSUER_URL"],
        "aud": configuration["AUDIENCE"],
        "sub": "subject",
        "email": "unmapped@example.com",
        "scope": "read",
        "exp": int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp()),
    }


def _login(client, decode_effect, jwk_error=None, provision_result=None):
    """Log in through a real API request with the plugin's network and provisioning edges stubbed."""
    get_api_authentication_backends.cache_clear()
    try:
        with ExitStack() as stack:
            jwk_client = stack.enter_context(patch(f"{PLUGIN}.CachedJWKClient"))
            stack.enter_context(patch(f"{PLUGIN}.decode", side_effect=decode_effect))
            if provision_result is not None:
                stack.enter_context(patch(f"{PLUGIN}.get_or_create_authenticator_user", return_value=provision_result))
            if jwk_error is not None:
                jwk_client.return_value.get_signing_key_from_jwt.side_effect = jwk_error
            else:
                jwk_client.return_value.get_signing_key_from_jwt.return_value = Mock(key="public-key")
            return client.get(get_relative_url("user-me"), headers={"Authorization": f"Bearer {TOKEN}"})
    finally:
        get_api_authentication_backends.cache_clear()


def _expired(configuration):
    return [_claims(configuration), ExpiredSignatureError("expired")]


def _invalid(configuration):
    return [_claims(configuration), InvalidSignatureError("bad signature")]


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("case", "expected_detail"),
    [
        pytest.param("expired", "Bearer token has expired.", id="expired"),
        pytest.param("invalid-signature", "Invalid Bearer token.", id="invalid-signature"),
        pytest.param("jwks-unavailable", "Authentication service unavailable.", id="jwks-unavailable"),
        pytest.param("unmapped-user", "Invalid Bearer token.", id="unmapped-user"),
    ],
)
def test_external_oauth_failures_return_a_generic_401_without_leaking_detail(oauth_bearer_authenticator, unauthenticated_api_client, case, expected_detail):
    """Every external failure is a generic 401 with a Bearer challenge and no internal detail (TC-10 items 1, 2, 3, 6, 7)."""
    configuration = oauth_bearer_authenticator.configuration
    kwargs = {
        "expired": {"decode_effect": _expired(configuration)},
        "invalid-signature": {"decode_effect": _invalid(configuration)},
        "jwks-unavailable": {"decode_effect": [_claims(configuration)] * 2, "jwk_error": PyJWKClientConnectionError("connection refused")},
        "unmapped-user": {"decode_effect": [_claims(configuration), _claims(configuration)], "provision_result": (None, None, False)},
    }[case]

    response = _login(unauthenticated_api_client, **kwargs)

    assert response.status_code == 401
    assert response["WWW-Authenticate"].startswith('Bearer realm="api", error="invalid_token"')
    body = response.content.decode()
    assert expected_detail in body
    leaked = [TOKEN, oauth_bearer_authenticator.name, configuration["JWKS_URI"], "unmapped@example.com", "Traceback"]
    for internal in leaked:
        assert internal not in body
        for value in response.headers.values():
            assert internal not in value
