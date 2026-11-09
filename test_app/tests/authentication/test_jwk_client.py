import hashlib
from unittest.mock import Mock, call, patch

import jwt
import pytest
from django.core.cache import cache
from jwt.exceptions import PyJWKClientError, PyJWKError

from ansible_base.authentication.jwk_client import (
    CachedJWKClient,
    JWKSFetchTimeoutError,
    _JWKSRetry,
)


def _token(kid="key-id"):
    return jwt.encode({"sub": "subject"}, "not-used", algorithm="HS256", headers={"kid": kid})


def _jwk_document(kid="key-id"):
    return {"keys": [{"kty": "oct", "k": "c2VjcmV0", "kid": kid, "alg": "HS256"}]}


def test_jwks_retry_preserves_its_timeout_error_message():
    assert str(_JWKSRetry(PyJWKClientError("refresh cooldown timed out"))) == "refresh cooldown timed out"


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


def test_cached_jwk_client_with_zero_lifespan_ignores_existing_signing_key_cache():
    uri = "https://issuer.example.com/keys"
    cached_client = CachedJWKClient(uri, lifespan=123)
    no_cache_client = CachedJWKClient(uri, lifespan=0)
    token = _token()
    cached_key = {"kty": "RSA", "kid": "key-id"}
    fetched_key = Mock(_jwk_data={"kty": "RSA", "kid": "key-id"})
    cache.set(cached_client._signing_key_cache_key("key-id"), cached_key, timeout=cached_client.cache_timeout)

    with (
        patch("ansible_base.authentication.jwk_client.cache.get") as cache_get,
        patch("ansible_base.authentication.jwk_client.cache.set") as cache_set,
        patch(
            "ansible_base.authentication.jwk_client.PyJWKClient.get_signing_key_from_jwt",
            return_value=fetched_key,
        ) as get_signing_key,
    ):
        assert no_cache_client.get_signing_key_from_jwt(token) is fetched_key

    cache_get.assert_not_called()
    cache_set.assert_not_called()
    get_signing_key.assert_called_once_with(token)
    assert cache.get(cached_client._signing_key_cache_key("key-id")) == cached_key


def test_cached_jwk_client_rejects_tokens_without_a_kid():
    client = CachedJWKClient("https://issuer.example.com/keys")
    token = jwt.encode({"sub": "subject"}, "not-used", algorithm="HS256")
    with pytest.raises(PyJWKClientError, match="missing kid"):
        client.get_signing_key_from_jwt(token)


@pytest.mark.parametrize(
    ("timeout", "expected_wait", "expected_lease"),
    [(1, 1, 2), (30, 30, 31)],
)
def test_cached_jwk_client_uses_jwks_timeout_for_fetch_coordination(timeout, expected_wait, expected_lease):
    client = CachedJWKClient("https://issuer.example.com/keys", timeout=timeout)

    assert client.fetch_wait_seconds == expected_wait
    assert client.fetch_lease_seconds == expected_lease


def test_cached_jwk_client_invalidates_known_entries_for_a_cache_namespace():
    with patch("ansible_base.authentication.jwk_client.cache.delete_many") as delete_many:
        CachedJWKClient.invalidate_cache_namespace("authenticator:7:version-one")

    namespace = hashlib.sha256(b"authenticator:7:version-one").hexdigest()
    delete_many.assert_called_once_with((f"jwk_set:{namespace}", f"jwks_refresh:{namespace}", f"jwks_fetch:{namespace}"))


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


def test_cached_jwk_client_does_not_reuse_jwk_set_when_cache_namespace_changes():
    uri = "https://issuer.example.com/keys"
    first_client = CachedJWKClient(uri, cache_namespace="authenticator:1:version-one")
    second_client = CachedJWKClient(uri, cache_namespace="authenticator:1:version-two")
    document = {"keys": []}

    with (
        patch("ansible_base.authentication.jwk_client.PyJWKClient.fetch_data", return_value=document) as fetch_data,
        patch("ansible_base.authentication.jwk_client.PyJWKSet.from_dict", return_value=Mock()),
    ):
        first_client.get_jwk_set()
        second_client.get_jwk_set()

    assert first_client._cache_namespace != second_client._cache_namespace
    assert fetch_data.call_count == 2


def test_cached_jwk_client_with_zero_lifespan_ignores_existing_jwk_set_cache():
    uri = "https://issuer.example.com/keys"
    cached_client = CachedJWKClient(uri, lifespan=123)
    no_cache_client = CachedJWKClient(uri, lifespan=0)
    cached_document = _jwk_document("cached-key")
    fetched_document = _jwk_document("fetched-key")
    cache.set(cached_client._jwk_set_cache_key, cached_document, timeout=cached_client.cache_timeout)

    with (
        patch("ansible_base.authentication.jwk_client.cache.get") as cache_get,
        patch("ansible_base.authentication.jwk_client.cache.add") as cache_add,
        patch("ansible_base.authentication.jwk_client.cache.set") as cache_set,
        patch("ansible_base.authentication.jwk_client.PyJWKClient.fetch_data", return_value=fetched_document) as fetch_data,
    ):
        jwk_set = no_cache_client.get_jwk_set()

    cache_get.assert_not_called()
    cache_add.assert_not_called()
    cache_set.assert_not_called()
    fetch_data.assert_called_once_with()
    assert [key.key_id for key in jwk_set.keys] == ["fetched-key"]
    assert cache.get(cached_client._jwk_set_cache_key) == cached_document


def test_cached_jwk_client_with_zero_lifespan_does_not_use_cache_during_key_refresh():
    client = CachedJWKClient("https://issuer.example.com/keys", lifespan=0)
    signing_key = Mock(_jwk_data={"kty": "RSA", "kid": "key-id"})

    with (
        patch("ansible_base.authentication.jwk_client.cache.get") as cache_get,
        patch("ansible_base.authentication.jwk_client.cache.delete") as cache_delete,
        patch("ansible_base.authentication.jwk_client.cache.set") as cache_set,
        patch.object(client, "get_signing_keys", return_value=[signing_key]) as get_signing_keys,
        patch.object(client, "match_kid", return_value=signing_key) as match_kid,
    ):
        assert client.refresh_signing_key_from_jwt(_token()) is signing_key

    cache_get.assert_not_called()
    cache_delete.assert_not_called()
    cache_set.assert_not_called()
    get_signing_keys.assert_called_once_with(refresh=True)
    match_kid.assert_called_once_with([signing_key], "key-id")


def test_cached_jwk_client_with_zero_lifespan_rejects_an_unknown_key_without_cache_access():
    client = CachedJWKClient("https://issuer.example.com/keys", lifespan=0)
    token = _token()

    with (
        patch("ansible_base.authentication.jwk_client.cache.get") as cache_get,
        patch("ansible_base.authentication.jwk_client.cache.delete") as cache_delete,
        patch("ansible_base.authentication.jwk_client.cache.set") as cache_set,
        patch.object(client, "get_signing_keys", return_value=[]),
    ):
        with pytest.raises(PyJWKClientError, match="Unable to find a signing key"):
            client.refresh_signing_key_from_jwt(token)

    cache_get.assert_not_called()
    cache_delete.assert_not_called()
    cache_set.assert_not_called()


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


def test_cached_jwk_client_times_out_second_forced_refresh_during_cooldown():
    client = CachedJWKClient("https://issuer.example.com/keys")
    document = {"keys": []}
    with (
        patch("ansible_base.authentication.jwk_client.PyJWKClient.fetch_data", return_value=document) as fetch_data,
        patch("ansible_base.authentication.jwk_client.PyJWKSet.from_dict", return_value=Mock()),
    ):
        client.get_jwk_set(refresh=True)
        with (
            patch("ansible_base.authentication.jwk_client.time.monotonic", side_effect=[0, client.fetch_wait_seconds]),
            patch("ansible_base.authentication.jwk_client.time.sleep"),
            pytest.raises(PyJWKClientError, match="refresh cooldown"),
        ):
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


def test_cached_jwk_client_reuses_jwk_set_populated_by_the_fetch_lock_owner():
    client = CachedJWKClient("https://issuer.example.com/keys")
    document = {"keys": []}
    cache.set(client._fetch_lock_key, "other-request", timeout=client.fetch_lease_seconds)

    def complete_peer_fetch(_delay):
        cache.set(client._jwk_set_cache_key, document, timeout=client.cache_timeout)

    with (
        patch("ansible_base.authentication.jwk_client.random.uniform", return_value=0.01),
        patch("ansible_base.authentication.jwk_client.time.sleep", side_effect=complete_peer_fetch),
        patch("ansible_base.authentication.jwk_client.PyJWKClient.fetch_data") as fetch_data,
        patch("ansible_base.authentication.jwk_client.PyJWKSet.from_dict", return_value=Mock()) as from_dict,
    ):
        client.get_jwk_set()

    fetch_data.assert_not_called()
    from_dict.assert_called_once_with(document)


def test_cached_jwk_client_does_not_read_a_jwk_document_when_caching_is_disabled():
    client = CachedJWKClient("https://issuer.example.com/keys", lifespan=0)

    with patch("ansible_base.authentication.jwk_client.cache.get") as cache_get:
        assert client._cached_jwk_document() is None

    cache_get.assert_not_called()


def test_cached_jwk_client_parses_an_available_cached_jwk_set():
    client = CachedJWKClient("https://issuer.example.com/keys")
    cache.set(client._jwk_set_cache_key, _jwk_document("cached-key"), timeout=client.cache_timeout)

    assert [key.key_id for key in client._cached_jwk_set().keys] == ["cached-key"]


def test_cached_jwk_client_returns_an_updated_cached_jwk_set_only_after_a_peer_change():
    client = CachedJWKClient("https://issuer.example.com/keys")
    original_document = _jwk_document("old-key")
    cache.set(client._jwk_set_cache_key, original_document, timeout=client.cache_timeout)

    assert client._updated_cached_jwk_set(original_document) is None

    rotated_document = _jwk_document("rotated-key")
    cache.set(client._jwk_set_cache_key, rotated_document, timeout=client.cache_timeout)

    assert [key.key_id for key in client._updated_cached_jwk_set(original_document).keys] == ["rotated-key"]


def test_cached_jwk_client_ignores_an_expired_jwk_set_while_waiting_for_a_forced_refresh():
    client = CachedJWKClient("https://issuer.example.com/keys")
    document = _jwk_document("old-key")
    cache.set(client._jwk_set_cache_key, document, timeout=client.cache_timeout)
    cache.delete(client._jwk_set_cache_key)

    assert client._updated_cached_jwk_set(document) is None


def test_cached_jwk_client_selects_reusable_keys_for_normal_and_forced_requests():
    client = CachedJWKClient("https://issuer.example.com/keys")
    original_document = _jwk_document("old-key")
    rotated_document = _jwk_document("rotated-key")
    cache.set(client._jwk_set_cache_key, original_document, timeout=client.cache_timeout)

    assert [key.key_id for key in client._reusable_cached_jwk_set(False, None).keys] == ["old-key"]
    assert client._reusable_cached_jwk_set(True, original_document) is None

    cache.set(client._jwk_set_cache_key, rotated_document, timeout=client.cache_timeout)

    assert [key.key_id for key in client._reusable_cached_jwk_set(True, original_document).keys] == ["rotated-key"]


def test_cached_jwk_client_reuses_jwk_set_published_during_forced_refresh_wait():
    """A refresh waiter must use a peer's rotated JWKS rather than waiting for cooldown expiry."""
    client = CachedJWKClient("https://issuer.example.com/keys")
    old_document = _jwk_document("old-key")
    new_document = _jwk_document("rotated-key")
    cache.set(client._jwk_set_cache_key, old_document, timeout=client.cache_timeout)
    cache.set(client._refresh_lock_key, True, timeout=client.forced_refresh_cooldown)

    def publish_peer_jwk_set(_delay):
        cache.set(client._jwk_set_cache_key, new_document, timeout=client.cache_timeout)

    with (
        patch("ansible_base.authentication.jwk_client.random.uniform", return_value=0.01),
        patch("ansible_base.authentication.jwk_client.time.sleep", side_effect=publish_peer_jwk_set),
        patch("ansible_base.authentication.jwk_client.PyJWKClient.fetch_data") as fetch_data,
    ):
        jwk_set = client.get_jwk_set(refresh=True)

    assert [key.key_id for key in jwk_set.keys] == ["rotated-key"]
    fetch_data.assert_not_called()


def test_cached_jwk_client_reuses_jwk_set_published_before_forced_refresh_lock_acquisition():
    """A refresh owner must not fetch again when another worker publishes keys before it gets the lock."""
    client = CachedJWKClient("https://issuer.example.com/keys")
    old_document = _jwk_document("old-key")
    new_document = _jwk_document("rotated-key")
    cache.set(client._jwk_set_cache_key, old_document, timeout=client.cache_timeout)

    def acquire_refresh_lock_after_peer_publish(_use_locks):
        cache.set(client._jwk_set_cache_key, new_document, timeout=client.cache_timeout)

    with (
        patch.object(client, "_set_refresh_lock", side_effect=acquire_refresh_lock_after_peer_publish),
        patch("ansible_base.authentication.jwk_client.PyJWKClient.fetch_data") as fetch_data,
    ):
        jwk_set = client.get_jwk_set(refresh=True)

    assert [key.key_id for key in jwk_set.keys] == ["rotated-key"]
    fetch_data.assert_not_called()


def test_cached_jwk_client_raises_availability_error_when_fetch_lock_owner_does_not_finish():
    client = CachedJWKClient("https://issuer.example.com/keys")
    cache.set(client._fetch_lock_key, "other-request", timeout=client.fetch_lease_seconds)

    with (
        patch("ansible_base.authentication.jwk_client.time.monotonic", side_effect=[0, client.fetch_wait_seconds]),
        patch("ansible_base.authentication.jwk_client.time.sleep"),
        pytest.raises(JWKSFetchTimeoutError, match="Timed out waiting"),
    ):
        client.get_jwk_set()


def test_cached_jwk_client_exponentially_backs_off_fetch_retries():
    with (
        patch("ansible_base.authentication.jwk_client.time.monotonic", return_value=0),
        patch("ansible_base.authentication.jwk_client.random.uniform", side_effect=[0.02, 0.04]) as uniform,
        patch("ansible_base.authentication.jwk_client.time.sleep") as sleep,
    ):
        CachedJWKClient._sleep_before_jwk_set_retry(1, retry_count=0, timeout_error=PyJWKClientError("timeout"))
        CachedJWKClient._sleep_before_jwk_set_retry(1, retry_count=1, timeout_error=PyJWKClientError("timeout"))

    assert uniform.call_args_list == [call(0.01, 0.02), call(0.02, 0.04)]
    assert sleep.call_args_list == [call(0.02), call(0.04)]


def test_cached_jwk_client_caps_fetch_retry_exponent_before_it_overflows():
    """Long bounded waits retain the maximum backoff without calculating an enormous power."""
    with (
        patch("ansible_base.authentication.jwk_client.time.monotonic", return_value=0),
        patch("ansible_base.authentication.jwk_client.random.uniform", return_value=0.25) as uniform,
        patch("ansible_base.authentication.jwk_client.time.sleep") as sleep,
    ):
        CachedJWKClient._sleep_before_jwk_set_retry(1, retry_count=10000, timeout_error=PyJWKClientError("timeout"))

    uniform.assert_called_once_with(0.125, 0.25)
    sleep.assert_called_once_with(0.25)


def test_cached_jwk_client_waits_for_an_active_fetch_before_forced_refresh():
    client = CachedJWKClient("https://issuer.example.com/keys")
    document = {"keys": []}
    cache.set(client._fetch_lock_key, "other-request", timeout=client.fetch_lease_seconds)

    def complete_peer_fetch(_delay):
        cache.delete(client._fetch_lock_key)

    with (
        patch("ansible_base.authentication.jwk_client.random.uniform", return_value=0.01),
        patch("ansible_base.authentication.jwk_client.time.sleep", side_effect=complete_peer_fetch),
        patch("ansible_base.authentication.jwk_client.PyJWKClient.fetch_data", return_value=document) as fetch_data,
        patch("ansible_base.authentication.jwk_client.PyJWKSet.from_dict", return_value=Mock()),
    ):
        client.get_jwk_set(refresh=True)

    fetch_data.assert_called_once_with()


def test_cached_jwk_client_waits_for_refresh_cooldown_before_forced_refresh():
    client = CachedJWKClient("https://issuer.example.com/keys")
    document = {"keys": []}
    cache.set(client._refresh_lock_key, True, timeout=client.forced_refresh_cooldown)

    def expire_refresh_cooldown(_delay):
        cache.delete(client._refresh_lock_key)

    with (
        patch("ansible_base.authentication.jwk_client.random.uniform", return_value=0.01),
        patch("ansible_base.authentication.jwk_client.time.sleep", side_effect=expire_refresh_cooldown),
        patch("ansible_base.authentication.jwk_client.PyJWKClient.fetch_data", return_value=document) as fetch_data,
        patch("ansible_base.authentication.jwk_client.PyJWKSet.from_dict", return_value=Mock()),
    ):
        client.get_jwk_set(refresh=True)

    fetch_data.assert_called_once_with()


def test_cached_jwk_client_raises_availability_error_when_forced_refresh_wait_expires():
    client = CachedJWKClient("https://issuer.example.com/keys")
    cache.set(client._fetch_lock_key, "other-request", timeout=client.fetch_lease_seconds)

    with (
        patch("ansible_base.authentication.jwk_client.time.monotonic", side_effect=[0, client.fetch_wait_seconds]),
        patch("ansible_base.authentication.jwk_client.time.sleep"),
        pytest.raises(JWKSFetchTimeoutError, match="Timed out waiting"),
    ):
        client.get_jwk_set(refresh=True)


def test_cached_jwk_client_does_not_release_a_replaced_fetch_lease():
    client = CachedJWKClient("https://issuer.example.com/keys")
    document = {"keys": []}

    def replace_fetch_lease():
        cache.set(client._fetch_lock_key, "new-owner", timeout=client.fetch_lease_seconds)
        return document

    with (
        patch("ansible_base.authentication.jwk_client.PyJWKClient.fetch_data", side_effect=replace_fetch_lease),
        patch("ansible_base.authentication.jwk_client.PyJWKSet.from_dict", return_value=Mock()),
    ):
        client.get_jwk_set()

    assert cache.get(client._fetch_lock_key) == "new-owner"


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

    with pytest.raises(PyJWKClientError, match="refresh is on cooldown"):
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
            side_effect=[[], PyJWKClientError("JWKS refresh is on cooldown")],
        ),
    ):
        with pytest.raises(PyJWKClientError, match="refresh is on cooldown"):
            client.get_signing_key("missing")
