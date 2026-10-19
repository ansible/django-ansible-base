import hashlib
from unittest.mock import Mock, patch

import jwt
import pytest
from django.core.cache import cache
from jwt.exceptions import PyJWKClientError, PyJWKError

from ansible_base.authentication.jwk_client import CachedJWKClient


def _token(kid="key-id"):
    return jwt.encode({"sub": "subject"}, "not-used", algorithm="HS256", headers={"kid": kid})


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


def test_cached_jwk_client_caches_signing_key_by_uri_and_kid():
    client = CachedJWKClient("https://issuer.example.com/keys", lifespan=123)
    signing_key = Mock(_jwk_data={"kty": "RSA", "kid": "key-id"})
    cached_key = Mock()

    with patch(
        "ansible_base.authentication.jwk_client.PyJWKClient.get_signing_key_from_jwt",
        return_value=signing_key,
    ) as get_signing_key, patch(
        "ansible_base.authentication.jwk_client.PyJWK.from_dict",
        return_value=cached_key,
    ) as from_dict:
        assert client.get_signing_key_from_jwt(_token()) is signing_key
        assert client.get_signing_key_from_jwt(_token()) is cached_key

    get_signing_key.assert_called_once()
    from_dict.assert_called_once_with(signing_key._jwk_data)


def test_cached_jwk_client_rejects_tokens_without_a_kid():
    client = CachedJWKClient("https://issuer.example.com/keys")
    token = jwt.encode({"sub": "subject"}, "not-used", algorithm="HS256")
    with pytest.raises(PyJWKClientError, match="missing kid"):
        client.get_signing_key_from_jwt(token)


def test_cached_jwk_client_discards_invalid_cached_jwk_and_refetches():
    client = CachedJWKClient("https://issuer.example.com/keys")
    token = _token()
    cache_identifier = hashlib.sha256(b"key-id").hexdigest()
    cache_key = f"external_oauth_jwk:{client._cache_namespace}:{cache_identifier}"
    cache.set(cache_key, {"not": "a JWK"})
    signing_key = Mock(_jwk_data={"kty": "RSA", "kid": "key-id"})

    with patch("ansible_base.authentication.jwk_client.PyJWK.from_dict", side_effect=PyJWKError("bad key")), patch(
        "ansible_base.authentication.jwk_client.PyJWKClient.get_signing_key_from_jwt",
        return_value=signing_key,
    ) as get_signing_key:
        assert client.get_signing_key_from_jwt(token) is signing_key

    get_signing_key.assert_called_once_with(token)


def test_cached_jwk_client_reuses_jwk_set_across_instances():
    first_client = CachedJWKClient("https://issuer.example.com/keys")
    second_client = CachedJWKClient("https://issuer.example.com/keys")
    jwk_set = Mock()
    document = {"keys": []}

    with patch(
        "ansible_base.authentication.jwk_client.PyJWKClient.fetch_data",
        return_value=document,
    ) as fetch_data, patch(
        "ansible_base.authentication.jwk_client.PyJWKSet.from_dict",
        return_value=jwk_set,
    ):
        assert first_client.get_jwk_set() is jwk_set
        assert second_client.get_jwk_set() is jwk_set

    fetch_data.assert_called_once_with()


def test_cached_jwk_client_refreshes_once_for_unknown_kid():
    client = CachedJWKClient("https://issuer.example.com/keys")
    refreshed_key = Mock()
    with patch.object(client, "get_signing_keys", side_effect=[[], [refreshed_key]]) as get_keys, patch.object(
        client, "match_kid", side_effect=[None, refreshed_key]
    ):
        assert client.get_signing_key("missing") is refreshed_key
    assert get_keys.call_args_list[1].kwargs == {"refresh": True}


def test_cached_jwk_client_throttles_repeated_unknown_kid_refreshes():
    client = CachedJWKClient("https://issuer.example.com/keys")
    with patch.object(client, "get_signing_keys", return_value=[]), patch.object(client, "match_kid", return_value=None), patch.object(
        client, "get_jwk_set", side_effect=PyJWKClientError("refresh is already in progress")
    ):
        with pytest.raises(PyJWKClientError, match="missing"):
            client.get_signing_key("missing")
