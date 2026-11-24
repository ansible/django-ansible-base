import copy
import json
import logging
import ssl
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import jwt
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from django.core.cache import cache
from jwt.exceptions import PyJWKClientConnectionError

from ansible_base.authentication.authenticator_plugins.oidc import AuthenticatorPlugin
from ansible_base.lib.utils.response import get_relative_url

FETCH_DATA = "ansible_base.authentication.jwk_client.PyJWKClient.fetch_data"
JWKS_URI = "https://idp.example.com/keys"
OIDC_LOGGER = "ansible_base.authentication.authenticator_plugins.oidc"


def _plugin_messages(caplog):
    """Return messages logged by the OIDC plugin, ignoring unrelated loggers."""
    return [record.getMessage() for record in caplog.records if record.name == OIDC_LOGGER]


def _plugin_warnings(caplog):
    """Return warning-or-higher messages logged by the OIDC plugin."""
    return [record.getMessage() for record in caplog.records if record.name == OIDC_LOGGER and record.levelno >= logging.WARNING]


def _keypair(kid):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update({"kid": kid, "alg": "RS256", "use": "sig"})
    return key, jwk


def _ec_keypair(kid):
    """Return a P-256 key and a JWK that omits ``alg``; PyJWT must infer ES256."""
    key = ec.generate_private_key(ec.SECP256R1())
    jwk = json.loads(jwt.algorithms.ECAlgorithm.to_jwk(key.public_key()))
    jwk.update({"kid": kid})
    return key, jwk


def _write_ca_certificate(path, common_name="internal-ca"):
    """Write a self-signed CA certificate and return its subject common name."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, common_name)])
    now = datetime.now(timezone.utc)
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    return common_name


def _loaded_ca_names(ssl_context):
    return {value for certificate in ssl_context.get_ca_certs() for rdn in certificate["subject"] for _type, value in rdn}


def _token(key, kid=None, algorithm="RS256"):
    claims = {"sub": "oidc-user", "exp": datetime.now(timezone.utc) + timedelta(minutes=5)}
    headers = {"kid": kid} if kid else None
    return jwt.encode(claims, key, algorithm=algorithm, headers=headers)


def _plugin(authenticator, **configuration_overrides):
    authenticator.configuration = {
        **authenticator.configuration,
        "JWKS_URI": JWKS_URI,
        **configuration_overrides,
    }
    return AuthenticatorPlugin(database_instance=authenticator)


def _next_version(authenticator):
    """Return an unsaved copy that models the authenticator after a later save."""
    newer = copy.copy(authenticator)
    newer.modified = authenticator.modified + timedelta(seconds=1)
    return newer


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
def test_find_valid_key_reuses_shared_cache_across_plugin_instances(oidc_authenticator):
    """Two workers resolving the same authenticator share one cached JWKS fetch."""
    key, jwk = _keypair("k1")
    token = _token(key, "k1")
    first_worker = _plugin(oidc_authenticator)
    second_worker = _plugin(oidc_authenticator)

    with patch(FETCH_DATA, return_value={"keys": [jwk]}) as fetch_data:
        assert first_worker.find_valid_key(token)["kid"] == "k1"
        assert second_worker.find_valid_key(token)["kid"] == "k1"

    assert fetch_data.call_count == 1


@pytest.mark.django_db
def test_find_valid_key_does_not_share_keys_between_authenticators(oidc_authenticator):
    """Each authenticator resolves keys from its own JWKS URI (AAP-101982 reproduction)."""
    first_key, first_jwk = _keypair("first")
    second_key, second_jwk = _keypair("second")
    documents = {
        "https://first-idp.example.com/keys": {"keys": [first_jwk]},
        "https://second-idp.example.com/keys": {"keys": [second_jwk]},
    }
    other_authenticator = copy.copy(oidc_authenticator)
    other_authenticator.pk = oidc_authenticator.pk + 1

    first_plugin = _plugin(oidc_authenticator, JWKS_URI="https://first-idp.example.com/keys")
    second_plugin = _plugin(other_authenticator, JWKS_URI="https://second-idp.example.com/keys")

    def fetch_for_uri(client):
        return documents[client.uri]

    with patch(FETCH_DATA, autospec=True, side_effect=fetch_for_uri) as fetch_data:
        assert first_plugin.find_valid_key(_token(first_key, "first"))["kid"] == "first"
        assert second_plugin.find_valid_key(_token(second_key, "second"))["kid"] == "second"

    assert [call.args[0].uri for call in fetch_data.call_args_list] == list(documents)
    first_client = first_plugin._jwk_client()
    second_client = second_plugin._jwk_client()
    assert first_client._jwk_set_cache_key != second_client._jwk_set_cache_key
    assert [key["kid"] for key in cache.get(first_client._jwk_set_cache_key)["keys"]] == ["first"]
    assert [key["kid"] for key in cache.get(second_client._jwk_set_cache_key)["keys"]] == ["second"]


@pytest.mark.django_db
def test_find_valid_key_isolates_configuration_versions(oidc_authenticator):
    """Saving an authenticator moves it to a cache namespace with no prior keys."""
    key, jwk = _keypair("k1")
    token = _token(key, "k1")
    before_save = _plugin(oidc_authenticator)
    after_save = _plugin(_next_version(oidc_authenticator))

    with patch(FETCH_DATA, return_value={"keys": [jwk]}) as fetch_data:
        assert before_save.find_valid_key(token)["kid"] == "k1"
        assert after_save.find_valid_key(token)["kid"] == "k1"

    assert fetch_data.call_count == 2


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("cache_timeout", "expected_fetches"),
    [
        pytest.param(3600, 1, id="cached"),
        pytest.param(0, 2, id="cache-disabled"),
    ],
)
def test_find_valid_key_honors_configured_cache_timeout(oidc_authenticator, cache_timeout, expected_fetches):
    key, jwk = _keypair("k1")
    token = _token(key, "k1")
    plugin = _plugin(oidc_authenticator, JWKS_CACHE_TIMEOUT=cache_timeout)

    with patch(FETCH_DATA, return_value={"keys": [jwk]}) as fetch_data:
        assert plugin.find_valid_key(token)["kid"] == "k1"
        assert plugin.find_valid_key(token)["kid"] == "k1"

    assert fetch_data.call_count == expected_fetches


@pytest.mark.django_db
def test_jwk_client_uses_configured_cache_and_url_timeouts(oidc_authenticator):
    plugin = _plugin(oidc_authenticator, JWKS_CACHE_TIMEOUT=1234, JWKS_URL_TIMEOUT=42)

    client = plugin._jwk_client()

    assert client.cache_timeout == 1234
    assert client.timeout == 42


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("verify_ssl", "ca_bundle_is_default"),
    [
        pytest.param(True, True, id="verify-ssl"),
        pytest.param(False, False, id="skip-ssl-verification"),
    ],
)
def test_jwk_client_honors_verify_ssl(oidc_authenticator, monkeypatch, verify_ssl, ca_bundle_is_default):
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
    client = _plugin(oidc_authenticator, VERIFY_SSL=verify_ssl)._jwk_client()

    if ca_bundle_is_default:
        assert client.ssl_context is None
    else:
        assert client.ssl_context is not None
        assert client.ssl_context.verify_mode == ssl.CERT_NONE


@pytest.mark.django_db
@pytest.mark.parametrize("variable", ["REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE"])
def test_jwk_client_trusts_the_configured_ca_bundle(oidc_authenticator, monkeypatch, tmp_path, variable):
    """The requests-based fetch honored these variables; the JWKS fetch must keep doing so."""
    ca_file = tmp_path / "internal-ca.pem"
    common_name = _write_ca_certificate(ca_file)
    monkeypatch.delenv("REQUESTS_CA_BUNDLE", raising=False)
    monkeypatch.delenv("CURL_CA_BUNDLE", raising=False)
    monkeypatch.setenv(variable, str(ca_file))

    client = _plugin(oidc_authenticator)._jwk_client()

    assert client.ssl_context is not None
    assert client.ssl_context.verify_mode == ssl.CERT_REQUIRED
    assert common_name in _loaded_ca_names(client.ssl_context)


@pytest.mark.django_db
def test_jwk_client_ignores_the_ca_bundle_when_verification_is_disabled(oidc_authenticator, monkeypatch, tmp_path):
    ca_file = tmp_path / "internal-ca.pem"
    _write_ca_certificate(ca_file)
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(ca_file))

    client = _plugin(oidc_authenticator, VERIFY_SSL=False)._jwk_client()

    assert client.ssl_context.verify_mode == ssl.CERT_NONE


@pytest.mark.django_db
def test_decode_and_validate_id_token_uses_the_shared_jwks_cache(oidc_authenticator):
    """social-auth-core consumes the key returned by find_valid_key without its process-local cache."""
    key, jwk = _keypair("k1")
    plugin = _plugin(oidc_authenticator, ID_TOKEN_ISSUER="https://issuer.example.com")
    id_token = jwt.encode(
        {
            "iss": "https://issuer.example.com",
            "sub": "oidc-user",
            "aud": "12345",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
            "iat": datetime.now(timezone.utc),
        },
        key,
        algorithm="RS256",
        headers={"kid": "k1"},
    )

    with patch(FETCH_DATA, return_value={"keys": [jwk]}) as fetch_data:
        claims = plugin.decode_and_validate_id_token(id_token, "access-token")

    assert claims["sub"] == "oidc-user"
    assert fetch_data.call_count == 1


@pytest.mark.django_db
def test_find_valid_key_refreshes_for_a_rotated_key(oidc_authenticator):
    old_key, old_jwk = _keypair("k1")
    new_key, new_jwk = _keypair("k2")
    plugin = _plugin(oidc_authenticator)

    with patch(FETCH_DATA, side_effect=[{"keys": [old_jwk]}, {"keys": [old_jwk, new_jwk]}]) as fetch_data:
        assert plugin.find_valid_key(_token(old_key, "k1"))["kid"] == "k1"
        assert plugin.find_valid_key(_token(new_key, "k2"))["kid"] == "k2"

    assert fetch_data.call_count == 2


@pytest.mark.django_db
def test_find_valid_key_refreshes_when_the_cached_key_stops_verifying(oidc_authenticator):
    """A provider that reuses a kid across rotations is refreshed after a signature failure."""
    old_key, old_jwk = _keypair("k1")
    replacement_key, replacement_jwk = _keypair("k1")
    plugin = _plugin(oidc_authenticator)

    with patch(FETCH_DATA, side_effect=[{"keys": [old_jwk]}, {"keys": [replacement_jwk]}]) as fetch_data:
        assert plugin.find_valid_key(_token(old_key, "k1"))["kid"] == "k1"
        assert plugin.find_valid_key(_token(replacement_key, "k1"))["kid"] == "k1"

    assert fetch_data.call_count == 2


@pytest.mark.django_db
def test_find_valid_key_does_not_fall_back_to_stale_keys_when_refresh_fails(oidc_authenticator):
    old_key, old_jwk = _keypair("k1")
    new_key, _new_jwk = _keypair("k2")
    plugin = _plugin(oidc_authenticator)

    with patch(FETCH_DATA, side_effect=[{"keys": [old_jwk]}, PyJWKClientConnectionError("provider unavailable")]) as fetch_data:
        assert plugin.find_valid_key(_token(old_key, "k1"))["kid"] == "k1"
        assert plugin.find_valid_key(_token(new_key, "k2")) is None

    assert fetch_data.call_count == 2


@pytest.mark.django_db
def test_find_valid_key_rejects_a_key_a_refresh_removed(oidc_authenticator):
    """A key the provider stops publishing cannot validate while its cache entry is still warm."""
    old_key, old_jwk = _keypair("k1")
    new_key, new_jwk = _keypair("k2")
    plugin = _plugin(oidc_authenticator, JWKS_URL_TIMEOUT=1)

    with patch(FETCH_DATA, side_effect=[{"keys": [old_jwk]}, {"keys": [new_jwk]}]) as fetch_data:
        assert plugin.find_valid_key(_token(old_key, "k1"))["kid"] == "k1"
        assert plugin.find_valid_key(_token(new_key, "k2"))["kid"] == "k2"
        assert plugin.find_valid_key(_token(old_key, "k1")) is None

    assert fetch_data.call_count == 2


@pytest.mark.django_db
@pytest.mark.parametrize("kid", ["k1", None], ids=["with-kid", "without-kid"])
def test_find_valid_key_warns_when_the_provider_is_unavailable(oidc_authenticator, caplog, kid):
    """An unreachable JWKS endpoint is reported once, at warning, without a refresh attempt."""
    key, _jwk = _keypair("k1")
    plugin = _plugin(oidc_authenticator)

    with patch(FETCH_DATA, side_effect=PyJWKClientConnectionError("provider unavailable")) as fetch_data:
        with caplog.at_level(logging.DEBUG, logger=OIDC_LOGGER):
            assert plugin.find_valid_key(_token(key, kid)) is None

    assert fetch_data.call_count == 1
    assert len(_plugin_warnings(caplog)) == 1
    assert "JWKS endpoint is unavailable" in _plugin_warnings(caplog)[0]


@pytest.mark.django_db
def test_find_valid_key_warns_when_the_provider_is_unavailable_during_refresh(oidc_authenticator, caplog):
    """A reused kid whose key changed forces our refresh, which reports the outage."""
    old_key, old_jwk = _keypair("k1")
    replacement_key, _replacement_jwk = _keypair("k1")
    plugin = _plugin(oidc_authenticator)

    with patch(FETCH_DATA, side_effect=[{"keys": [old_jwk]}, PyJWKClientConnectionError("provider unavailable")]) as fetch_data:
        assert plugin.find_valid_key(_token(old_key, "k1"))["kid"] == "k1"
        caplog.clear()
        with caplog.at_level(logging.DEBUG, logger=OIDC_LOGGER):
            assert plugin.find_valid_key(_token(replacement_key, "k1")) is None

    assert fetch_data.call_count == 2
    assert len(_plugin_warnings(caplog)) == 1
    assert "unavailable during refresh" in _plugin_warnings(caplog)[0]


@pytest.mark.django_db
def test_find_valid_key_logs_a_token_rejection_at_debug(oidc_authenticator, caplog):
    """A kid the provider does not issue is a rejected token, not a provider outage."""
    provider_key, provider_jwk = _keypair("k1")
    unknown_key, _unknown_jwk = _keypair("k2")
    plugin = _plugin(oidc_authenticator, JWKS_URL_TIMEOUT=1)

    with patch(FETCH_DATA, return_value={"keys": [provider_jwk]}) as fetch_data:
        assert plugin.find_valid_key(_token(provider_key, "k1"))["kid"] == "k1"
        caplog.clear()
        with caplog.at_level(logging.DEBUG, logger=OIDC_LOGGER):
            assert plugin.find_valid_key(_token(unknown_key, "k2")) is None

    assert fetch_data.call_count == 2
    assert _plugin_warnings(caplog) == []
    assert any("Unable to refresh JWKS keys" in message for message in _plugin_messages(caplog))


@pytest.mark.django_db
def test_find_valid_key_logs_a_refresh_cooldown_at_debug(oidc_authenticator, caplog):
    """Cooldown rejections must not read like provider outages."""
    provider_key, provider_jwk = _keypair("k1")
    unknown_key, _unknown_jwk = _keypair("k2")
    plugin = _plugin(oidc_authenticator, JWKS_URL_TIMEOUT=1)

    with patch(FETCH_DATA, return_value={"keys": [provider_jwk]}) as fetch_data:
        assert plugin.find_valid_key(_token(provider_key, "k1"))["kid"] == "k1"
        assert plugin.find_valid_key(_token(unknown_key, "k2")) is None
        caplog.clear()
        with caplog.at_level(logging.DEBUG, logger=OIDC_LOGGER):
            assert plugin.find_valid_key(_token(unknown_key, "k2")) is None

    assert fetch_data.call_count == 2
    assert _plugin_warnings(caplog) == []
    assert any("cooldown" in message for message in _plugin_messages(caplog))


@pytest.mark.django_db
def test_find_valid_key_rejects_a_removed_key_after_cache_expiry_when_refresh_fails(oidc_authenticator):
    """An expired cache entry is never repopulated from stale process-local keys."""
    key, jwk = _keypair("k1")
    token = _token(key, "k1")
    plugin = _plugin(oidc_authenticator)

    unavailable = PyJWKClientConnectionError("provider unavailable")
    with patch(FETCH_DATA, side_effect=[{"keys": [jwk]}, unavailable, unavailable]):
        assert plugin.find_valid_key(token)["kid"] == "k1"
        client = plugin._jwk_client()
        cache.delete(client._jwk_set_cache_key)
        cache.delete(client._signing_key_cache_key("k1"))
        assert plugin.find_valid_key(token) is None


@pytest.mark.django_db
def test_find_valid_key_rejects_a_key_the_refresh_does_not_replace(oidc_authenticator):
    provider_key, provider_jwk = _keypair("k1")
    unrelated_key, _unrelated_jwk = _keypair("other")
    plugin = _plugin(oidc_authenticator)

    with patch(FETCH_DATA, return_value={"keys": [provider_jwk]}) as fetch_data:
        assert plugin.find_valid_key(_token(unrelated_key, "k1")) is None

    assert fetch_data.call_count == 2


@pytest.mark.django_db
def test_find_valid_key_infers_algorithm_when_the_jwk_omits_alg(oidc_authenticator):
    key, jwk = _ec_keypair("ec1")
    plugin = _plugin(oidc_authenticator)

    with patch(FETCH_DATA, return_value={"keys": [jwk]}):
        found = plugin.find_valid_key(_token(key, "ec1", algorithm="ES256"))

    assert found["kid"] == "ec1"
    assert found["alg"] == "ES256"


@pytest.mark.django_db
def test_find_valid_key_supports_tokens_without_a_kid(oidc_authenticator):
    key, jwk = _keypair("k1")
    plugin = _plugin(oidc_authenticator)

    with patch(FETCH_DATA, return_value={"keys": [jwk]}) as fetch_data:
        assert plugin.find_valid_key(_token(key))["kid"] == "k1"

    assert fetch_data.call_count == 1


@pytest.mark.django_db
def test_find_valid_key_refreshes_tokens_without_a_kid(oidc_authenticator):
    old_key, old_jwk = _keypair("k1")
    new_key, new_jwk = _keypair("k2")
    plugin = _plugin(oidc_authenticator)

    with patch(FETCH_DATA, side_effect=[{"keys": [old_jwk]}, {"keys": [old_jwk, new_jwk]}]) as fetch_data:
        assert plugin.find_valid_key(_token(new_key))["kid"] == "k2"

    assert fetch_data.call_count == 2


@pytest.mark.django_db
def test_find_valid_key_without_kid_does_not_fall_back_to_stale_keys(oidc_authenticator):
    old_key, old_jwk = _keypair("k1")
    new_key, _new_jwk = _keypair("k2")
    plugin = _plugin(oidc_authenticator)

    with patch(FETCH_DATA, side_effect=[{"keys": [old_jwk]}, PyJWKClientConnectionError("provider unavailable")]):
        assert plugin.find_valid_key(_token(new_key)) is None


@pytest.mark.django_db
def test_find_valid_key_rejects_malformed_tokens(oidc_authenticator):
    assert _plugin(oidc_authenticator).find_valid_key("not-a-token") is None


@pytest.mark.parametrize(
    "instance",
    [
        pytest.param(None, id="no-database-instance"),
        pytest.param(SimpleNamespace(), id="unsaved-instance"),
        pytest.param(SimpleNamespace(pk=1, modified=None), id="instance-without-timestamp"),
    ],
)
def test_jwks_cache_namespace_requires_a_persisted_version(instance):
    plugin = AuthenticatorPlugin()
    plugin.database_instance = instance

    assert plugin._jwks_cache_namespace() is None


@pytest.mark.parametrize(
    ("id_token", "key"),
    [
        pytest.param("not-a-jwt", {"kty": "RSA", "kid": "k1", "alg": "RS256"}, id="malformed-token"),
        pytest.param("header.payload.signature", {"kty": "unsupported", "kid": "k1", "alg": "RS256"}, id="unusable-key"),
    ],
)
def test_signature_matches_rejects_unusable_input(id_token, key):
    assert AuthenticatorPlugin._signature_matches(id_token, key) is False


@pytest.mark.django_db
def test_find_valid_key_without_kid_returns_none_when_no_key_matches(oidc_authenticator):
    provider_key, provider_jwk = _keypair("k1")
    unrelated_key, _unrelated_jwk = _keypair("other")
    plugin = _plugin(oidc_authenticator)

    with patch(FETCH_DATA, return_value={"keys": [provider_jwk]}):
        assert plugin.find_valid_key(_token(unrelated_key)) is None


def _create_payload(configuration):
    return {
        "name": "Test OIDC Authenticator",
        "enabled": True,
        "create_objects": True,
        "remove_users": True,
        "type": "ansible_base.authentication.authenticator_plugins.oidc",
        "configuration": configuration,
    }


@pytest.mark.django_db
def test_oidc_jwks_configuration_defaults(admin_api_client, oidc_configuration):
    response = admin_api_client.post(get_relative_url("authenticator-list"), data=_create_payload(oidc_configuration), format="json")

    assert response.status_code == 201, response.data
    assert response.data["configuration"]["JWKS_CACHE_TIMEOUT"] == 3600
    assert response.data["configuration"]["JWKS_URL_TIMEOUT"] == 5


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field", "value", "expected_status"),
    [
        pytest.param("JWKS_CACHE_TIMEOUT", 0, 201, id="cache-timeout-zero-disables-caching"),
        pytest.param("JWKS_CACHE_TIMEOUT", -1, 400, id="cache-timeout-negative"),
        pytest.param("JWKS_URL_TIMEOUT", 0, 400, id="url-timeout-zero"),
        pytest.param("JWKS_URL_TIMEOUT", 300, 201, id="url-timeout-maximum"),
        pytest.param("JWKS_URL_TIMEOUT", 301, 400, id="url-timeout-above-maximum"),
    ],
)
def test_oidc_jwks_configuration_validation(admin_api_client, oidc_configuration, field, value, expected_status):
    configuration = {**oidc_configuration, field: value}

    response = admin_api_client.post(get_relative_url("authenticator-list"), data=_create_payload(configuration), format="json")

    assert response.status_code == expected_status, response.data
