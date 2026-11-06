import json
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from django.core.cache import cache
from jwt.exceptions import PyJWKClientConnectionError

from ansible_base.authentication.authenticator_plugins.oauth_bearer import AuthenticatorPlugin
from ansible_base.authentication.bearer_authentication import BearerTokenValidationError

PLUGIN = "ansible_base.authentication.authenticator_plugins.oauth_bearer"
JWK_CLIENT = "ansible_base.authentication.jwk_client.PyJWKClient"


def _keypair(kid):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update({"kid": kid, "alg": "RS256", "use": "sig"})
    return key, jwk


def _token(configuration, key, kid):
    claims = {
        "iss": configuration["ISSUER_URL"],
        "aud": configuration["AUDIENCE"],
        "sub": "subject",
        "email": "cached@example.com",
        "scope": "read",
        "exp": int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp()),
    }
    return jwt.encode(claims, key, algorithm="RS256", headers={"kid": kid})


def _authenticate(plugin, token):
    with ExitStack() as stack:
        stack.enter_context(patch(f"{PLUGIN}.get_or_create_authenticator_user", return_value=(Mock(username="cached-user"), Mock(), True)))
        stack.enter_context(patch(f"{PLUGIN}.update_user_claims", side_effect=lambda user, *_args, **_kwargs: user))
        return plugin.authenticate(token=token)


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
def test_authenticate_populates_the_cache(oauth_bearer_authenticator):
    """A successful login stores the provider key set in the shared cache (TC-5 item 8)."""
    key, jwk = _keypair("k1")
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)

    with patch(f"{JWK_CLIENT}.fetch_data", return_value={"keys": [jwk]}):
        assert _authenticate(plugin, _token(oauth_bearer_authenticator.configuration, key, "k1")) is not None

    configuration = oauth_bearer_authenticator.configuration
    jwk_client = plugin._build_jwk_client(configuration["JWKS_URI"], configuration)
    assert cache.get(jwk_client._jwk_set_cache_key) == {"keys": [jwk]}


@pytest.mark.django_db
def test_blocked_provider_fails_then_recovers_when_the_cache_is_empty(oauth_bearer_authenticator):
    """With an empty cache a blocked provider is a safe failure; restoring it resumes authentication (TC-5 items 10 and 11)."""
    key, jwk = _keypair("k1")
    token = _token(oauth_bearer_authenticator.configuration, key, "k1")
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)

    with patch(f"{JWK_CLIENT}.fetch_data", side_effect=[{"keys": [jwk]}, PyJWKClientConnectionError("down"), {"keys": [jwk]}]) as fetch_data:
        assert _authenticate(plugin, token) is not None

        cache.clear()
        with pytest.raises(BearerTokenValidationError) as failure:
            _authenticate(plugin, token)
        assert failure.value.reason == "provider_unavailable"

        cache.clear()
        assert _authenticate(plugin, token) is not None

    assert fetch_data.call_count == 3


@pytest.mark.django_db
def test_removed_key_rejects_old_tokens_and_accepts_the_current_key(oauth_bearer_authenticator):
    """After rotation, a token signed by the removed key is rejected while a current-key token works (TC-5 item 14)."""
    old_key, old_jwk = _keypair("old")
    new_key, new_jwk = _keypair("new")
    configuration = oauth_bearer_authenticator.configuration
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)

    with patch(f"{JWK_CLIENT}.fetch_data", side_effect=[{"keys": [old_jwk]}, {"keys": [new_jwk]}, {"keys": [new_jwk]}]):
        assert _authenticate(plugin, _token(configuration, old_key, "old")) is not None

        cache.clear()
        with pytest.raises(BearerTokenValidationError):
            _authenticate(plugin, _token(configuration, old_key, "old"))

        assert _authenticate(plugin, _token(configuration, new_key, "new")) is not None


@pytest.mark.django_db
def test_repeated_invalid_signatures_refresh_at_most_once(oauth_bearer_authenticator):
    """A storm of invalid signatures stays within the refresh cooldown instead of hammering the provider (TC-5 item 15)."""
    _, jwk = _keypair("k1")
    configuration = oauth_bearer_authenticator.configuration
    token = _token(configuration, _keypair("other")[0], "k1")
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)

    with patch(f"{JWK_CLIENT}.fetch_data", return_value={"keys": [jwk]}) as fetch_data:
        for _ in range(100):
            with pytest.raises(BearerTokenValidationError):
                _authenticate(plugin, token)

    assert fetch_data.call_count <= 2
