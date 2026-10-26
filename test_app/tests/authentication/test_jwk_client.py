import hashlib
from unittest.mock import Mock, patch

import jwt
import pytest
from django.core.cache import cache
from jwt.exceptions import PyJWKClientError, PyJWKError

from ansible_base.authentication.jwk_client import CachedJWKClient


def _token(kid="key-id"):
    return jwt.encode({"sub": "subject"}, "not-used", algorithm="HS256", headers={"kid": kid})


def _jwk_document(kid="key-id"):
    return {"keys": [{"kty": "oct", "k": "c2VjcmV0", "kid": kid, "alg": "HS256"}]}


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


def test_cached_jwk_client_caches_signing_key_by_uri_and_kid():
    client = CachedJWKClient("https://issuer.example.com/keys", lifespan=123)
    signing_key = Mock(_jwk_data={"kty": "RSA", "kid": "key-id"})
    cached_key = Mock()

    with (
        patch(
            "ansible_base.authentication.jwk_client.PyJWKClient.get_signing_key_from_jwt",
            return_value=signing_key,
        ) as get_signing_key,
        patch(
            "ansible_base.authentication.jwk_client.PyJWK.from_dict",
            return_value=cached_key,
        ) as from_dict,
    ):
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
    cache_key = f"jwk:{client._cache_namespace}:{cache_identifier}"
    cache.set(cache_key, {"not": "a JWK"})
    signing_key = Mock(_jwk_data={"kty": "RSA", "kid": "key-id"})

    with (
        patch("ansible_base.authentication.jwk_client.PyJWK.from_dict", side_effect=PyJWKError("bad key")),
        patch(
            "ansible_base.authentication.jwk_client.PyJWKClient.get_signing_key_from_jwt",
            return_value=signing_key,
        ) as get_signing_key,
    ):
        assert client.get_signing_key_from_jwt(token) is signing_key

    get_signing_key.assert_called_once_with(token)


def test_cached_jwk_client_reuses_jwk_set_across_instances():
    first_client = CachedJWKClient("https://issuer.example.com/keys")
    second_client = CachedJWKClient("https://issuer.example.com/keys")
    jwk_set = Mock()
    document = {"keys": []}

    with (
        patch(
            "ansible_base.authentication.jwk_client.PyJWKClient.fetch_data",
            return_value=document,
        ) as fetch_data,
        patch(
            "ansible_base.authentication.jwk_client.PyJWKSet.from_dict",
            return_value=jwk_set,
        ),
    ):
        assert first_client.get_jwk_set() is jwk_set
        assert second_client.get_jwk_set() is jwk_set

    fetch_data.assert_called_once_with()


def test_cached_jwk_client_only_caches_a_parser_validated_jwk_set():
    client = CachedJWKClient("https://issuer.example.com/keys")
    document = _jwk_document()

    with patch("ansible_base.authentication.jwk_client.PyJWKClient.fetch_data", return_value=document) as fetch_data:
        jwk_set = client.get_jwk_set()

    assert [key.key_id for key in jwk_set.keys] == ["key-id"]
    assert cache.get(client._jwk_set_cache_key) == document
    fetch_data.assert_called_once_with()


@pytest.mark.parametrize("document", [{"error": "temporarily unavailable"}, {"keys": []}, {"keys": [{"kty": "invalid"}]}])
def test_cached_jwk_client_does_not_cache_an_unusable_jwk_set(document):
    client = CachedJWKClient("https://issuer.example.com/keys")

    with patch("ansible_base.authentication.jwk_client.PyJWKClient.fetch_data", return_value=document):
        with pytest.raises(PyJWKClientError, match="unusable key set"):
            client.get_jwk_set()

    assert cache.get(client._jwk_set_cache_key) is None


def test_cached_jwk_client_recovers_after_an_unusable_jwk_set_response():
    client = CachedJWKClient("https://issuer.example.com/keys")
    document = _jwk_document()

    with patch(
        "ansible_base.authentication.jwk_client.PyJWKClient.fetch_data",
        side_effect=[{"error": "temporarily unavailable"}, document],
    ) as fetch_data:
        with pytest.raises(PyJWKClientError, match="unusable key set"):
            client.get_jwk_set()
        jwk_set = client.get_jwk_set()

    assert [key.key_id for key in jwk_set.keys] == ["key-id"]
    assert cache.get(client._jwk_set_cache_key) == document
    assert fetch_data.call_count == 2


def test_cached_jwk_client_preserves_a_valid_jwk_set_when_forced_refresh_is_unusable():
    client = CachedJWKClient("https://issuer.example.com/keys")
    document = _jwk_document()
    cache.set(client._jwk_set_cache_key, document)

    with patch("ansible_base.authentication.jwk_client.PyJWKClient.fetch_data", return_value={"error": "temporarily unavailable"}):
        with pytest.raises(PyJWKClientError, match="unusable key set"):
            client.get_jwk_set(refresh=True)

    assert cache.get(client._jwk_set_cache_key) == document


def test_cached_jwk_client_disables_pyjwt_per_instance_jwk_set_cache():
    client = CachedJWKClient("https://issuer.example.com/keys")

    assert client.jwk_set_cache is None


def test_cached_jwk_client_uses_cached_jwk_set_when_provider_is_unavailable():
    first_client = CachedJWKClient("https://issuer.example.com/keys")
    second_client = CachedJWKClient("https://issuer.example.com/keys")
    jwk_set = Mock()
    document = {"keys": []}

    with (
        patch(
            "ansible_base.authentication.jwk_client.PyJWKClient.fetch_data",
            side_effect=[document, PyJWKClientError("provider unavailable")],
        ) as fetch_data,
        patch(
            "ansible_base.authentication.jwk_client.PyJWKSet.from_dict",
            return_value=jwk_set,
        ),
    ):
        assert first_client.get_jwk_set() is jwk_set
        assert second_client.get_jwk_set() is jwk_set

    fetch_data.assert_called_once_with()


def test_cached_jwk_client_scopes_jwk_set_cache_by_provider_uri():
    first_client = CachedJWKClient("https://issuer.example.com/keys-one")
    second_client = CachedJWKClient("https://issuer.example.com/keys-two")
    documents = [{"keys": []}, {"keys": []}]

    with (
        patch(
            "ansible_base.authentication.jwk_client.PyJWKClient.fetch_data",
            side_effect=documents,
        ) as fetch_data,
        patch(
            "ansible_base.authentication.jwk_client.PyJWKSet.from_dict",
            return_value=Mock(),
        ),
    ):
        first_client.get_jwk_set()
        second_client.get_jwk_set()

    assert fetch_data.call_count == 2


def test_cached_jwk_client_blocks_second_forced_refresh_during_cooldown():
    client = CachedJWKClient("https://issuer.example.com/keys")
    document = {"keys": []}
    with (
        patch("ansible_base.authentication.jwk_client.PyJWKClient.fetch_data", return_value=document) as fetch_data,
        patch("ansible_base.authentication.jwk_client.PyJWKSet.from_dict", return_value=Mock()),
    ):
        client.get_jwk_set(refresh=True)
        with pytest.raises(PyJWKClientError, match="refresh is already in progress"):
            client.get_jwk_set(refresh=True)

    assert client.forced_refresh_cooldown == 60
    fetch_data.assert_called_once_with()


def test_cached_jwk_client_allows_every_forced_refresh_when_cooldown_is_disabled():
    with patch("ansible_base.authentication.jwk_client.get_setting", return_value=0):
        client = CachedJWKClient("https://issuer.example.com/keys")
    document = {"keys": []}

    with (
        patch("ansible_base.authentication.jwk_client.PyJWKClient.fetch_data", return_value=document) as fetch_data,
        patch("ansible_base.authentication.jwk_client.PyJWKSet.from_dict", return_value=Mock()),
    ):
        client.get_jwk_set(refresh=True)
        client.get_jwk_set(refresh=True)

    assert fetch_data.call_count == 2


@pytest.mark.parametrize("configured_value", [None, -1, 86401, "60"])
def test_cached_jwk_client_uses_default_for_invalid_refresh_cooldown(configured_value):
    with patch("ansible_base.authentication.jwk_client.get_setting", return_value=configured_value):
        client = CachedJWKClient("https://issuer.example.com/keys")

    assert client.forced_refresh_cooldown == 60


def test_cached_jwk_client_rejects_a_non_object_jwk_set():
    client = CachedJWKClient("https://issuer.example.com/keys")
    with patch("ansible_base.authentication.jwk_client.PyJWKClient.fetch_data", return_value=[]):
        with pytest.raises(PyJWKClientError, match="did not return a JSON object"):
            client.get_jwk_set()


def test_cached_jwk_client_rejects_a_second_jwk_fetch_while_the_first_is_locked():
    client = CachedJWKClient("https://issuer.example.com/keys")
    cache.set(client._fetch_lock_key, True, timeout=client.forced_refresh_cooldown)

    with pytest.raises(PyJWKClientError, match="fetch is already in progress"):
        client.get_jwk_set()


def test_cached_jwk_client_refreshes_and_caches_a_signing_key():
    client = CachedJWKClient("https://issuer.example.com/keys")
    signing_key = Mock(_jwk_data={"kty": "RSA", "kid": "key-id"})

    with (
        patch.object(client, "get_signing_keys", return_value=[signing_key]),
        patch.object(client, "match_kid", return_value=signing_key),
    ):
        assert client.refresh_signing_key_from_jwt(_token()) is signing_key

    assert cache.get(client._signing_key_cache_key("key-id")) == signing_key._jwk_data


def test_cached_jwk_client_rejects_refresh_without_a_key_id():
    client = CachedJWKClient("https://issuer.example.com/keys")
    token = jwt.encode({"sub": "subject"}, "not-used", algorithm="HS256")

    with pytest.raises(PyJWKClientError, match="missing kid"):
        client.refresh_signing_key_from_jwt(token)


def test_cached_jwk_client_keeps_a_cached_signing_key_when_refresh_is_in_cooldown():
    client = CachedJWKClient("https://issuer.example.com/keys")
    token = _token()
    cached_key = {"kty": "RSA", "kid": "key-id"}
    cache.set(client._signing_key_cache_key("key-id"), cached_key)
    cache.set(client._refresh_lock_key, True, timeout=client.forced_refresh_cooldown)

    with pytest.raises(PyJWKClientError, match="refresh is already in progress"):
        client.refresh_signing_key_from_jwt(token)

    assert cache.get(client._signing_key_cache_key("key-id")) == cached_key


def test_cached_jwk_client_delegates_unknown_kid_refresh_to_pyjwt():
    client = CachedJWKClient("https://issuer.example.com/keys")
    refreshed_key = Mock()
    with (
        patch.object(client, "get_signing_keys", side_effect=[[], [refreshed_key]]) as get_keys,
        patch.object(client, "match_kid", side_effect=[None, refreshed_key]),
    ):
        assert client.get_signing_key("missing") is refreshed_key
    assert get_keys.call_args_list[1].kwargs == {"refresh": True}


def test_cached_jwk_client_rejects_unknown_kid_when_shared_refresh_is_throttled():
    client = CachedJWKClient("https://issuer.example.com/keys")
    with (
        patch.object(client, "match_kid", return_value=None),
        patch.object(
            client,
            "get_signing_keys",
            side_effect=[[], PyJWKClientError("JWKS refresh is already in progress")],
        ),
    ):
        with pytest.raises(PyJWKClientError, match="refresh is already in progress"):
            client.get_signing_key("missing")
