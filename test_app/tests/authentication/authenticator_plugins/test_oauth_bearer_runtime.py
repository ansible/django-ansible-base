from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from ansible_base.authentication.authenticator_plugins.oauth_bearer import AuthenticatorPlugin
from ansible_base.authentication.bearer_authentication import BearerTokenValidationError


def _claims(configuration, **overrides):
    claims = {
        "iss": configuration["ISSUER_URL"],
        "aud": configuration["AUDIENCE"],
        "sub": "subject",
        "email": "user@example.com",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    claims.update(overrides)
    return claims


def _routing_claims(configuration):
    """Return the unverified claims used to select this configured provider."""
    return {"iss": configuration["ISSUER_URL"], "aud": configuration["AUDIENCE"]}


def _authenticate_signed_token(plugin, token, public_key):
    with (
        patch("ansible_base.authentication.authenticator_plugins.oauth_bearer.CachedJWKClient") as jwk_client,
        patch(
            "ansible_base.authentication.authenticator_plugins.oauth_bearer.get_or_create_authenticator_user",
            return_value=(Mock(is_active=False), Mock(), False),
        ) as get_or_create,
    ):
        # A repeated key after a signature failure proves a refreshed JWKS did
        # not change. The plugin must decline the token without retrying it.
        signing_key = Mock(key=public_key, _jwk_data={"kid": "test-key"})
        jwk_client.return_value.get_signing_key_from_jwt.return_value = signing_key
        jwk_client.return_value.refresh_signing_key_from_jwt.return_value = signing_key
        try:
            result = plugin.authenticate(token=token)
        except BearerTokenValidationError:
            result = None
    return result, get_or_create


@pytest.mark.django_db
def test_oauth_bearer_plugin_validates_token_and_updates_claims(oauth_bearer_authenticator):
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)
    token = "signed-token"
    signing_key = Mock(key="public-key")
    user = Mock(is_active=True, username="external-user")
    claims = {
        **_routing_claims(oauth_bearer_authenticator.configuration),
        "email": "user@example.com",
        "sub": "subject",
        "groups": ["operators", 3],
        "scope": "read",
    }

    with (
        patch("ansible_base.authentication.authenticator_plugins.oauth_bearer.CachedJWKClient") as jwk_client,
        patch(
            "ansible_base.authentication.authenticator_plugins.oauth_bearer.decode",
            return_value=claims,
        ) as decode_token,
        patch(
            "ansible_base.authentication.authenticator_plugins.oauth_bearer.get_or_create_authenticator_user",
            return_value=(user, Mock(), True),
        ) as get_or_create,
        patch(
            "ansible_base.authentication.authenticator_plugins.oauth_bearer.is_system_user",
            return_value=False,
        ),
        patch(
            "ansible_base.authentication.authenticator_plugins.oauth_bearer.update_user_claims",
            return_value=user,
        ) as update_claims,
    ):
        jwk_client.return_value.get_signing_key_from_jwt.return_value = signing_key
        result = plugin.authenticate(token=token)

    assert result.user == user
    assert result.auth.scopes == frozenset({"read"})

    jwk_client.assert_called_once_with(
        oauth_bearer_authenticator.configuration["JWKS_URI"],
        lifespan=oauth_bearer_authenticator.configuration["JWKS_CACHE_TIMEOUT"],
        timeout=oauth_bearer_authenticator.configuration["JWKS_URL_TIMEOUT"],
        ssl_context=None,
    )
    assert decode_token.call_count == 2
    assert decode_token.call_args_list[1].kwargs == {
        "key": signing_key.key,
        "algorithms": oauth_bearer_authenticator.configuration["ALLOWED_ALGORITHMS"],
        "audience": oauth_bearer_authenticator.configuration["AUDIENCE"],
        "issuer": oauth_bearer_authenticator.configuration["ISSUER_URL"],
        "options": {"require": ["exp"]},
        "leeway": 0,
    }
    get_or_create.assert_called_once_with(
        uid="user@example.com",
        email="user@example.com",
        authenticator=oauth_bearer_authenticator,
        user_details={"email": "user@example.com"},
        extra_data=claims,
    )
    update_claims.assert_called_once_with(user, oauth_bearer_authenticator, ["operators"], attrs=claims)


@pytest.mark.django_db
def test_oauth_bearer_plugin_defaults_missing_clock_skew_for_existing_configurations(oauth_bearer_authenticator):
    """Authenticators saved before this setting existed retain zero expiry grace."""
    configuration = dict(oauth_bearer_authenticator.configuration)
    configuration.pop("JWT_CLOCK_SKEW_TOLERANCE_SECONDS")
    signing_key = Mock(key="public-key")

    with patch("ansible_base.authentication.authenticator_plugins.oauth_bearer.decode", return_value={}) as decode_token:
        AuthenticatorPlugin._decode_validated_token("token", signing_key, configuration)

    assert decode_token.call_args.kwargs["leeway"] == 0


@pytest.mark.parametrize(
    "configuration,claims,expected_scopes",
    [
        ({}, {}, set()),
        ({}, {"scope": "profile email"}, set()),
        ({}, {"scope": "read"}, {"read"}),
        ({}, {"scope": "write"}, {"read", "write"}),
        ({}, {"scope": ["profile", "write"]}, {"read", "write"}),
        (
            {"SCOPE_ATTRIBUTE_NAME": "scp", "READ_SCOPE_NAME": "gateway.read", "WRITE_SCOPE_NAME": "gateway.write"},
            {"scp": "openid gateway.read"},
            {"read"},
        ),
        (
            {"SCOPE_ATTRIBUTE_NAME": "scp", "READ_SCOPE_NAME": "gateway.read", "WRITE_SCOPE_NAME": "gateway.write"},
            {"scp": "openid gateway.write"},
            {"read", "write"},
        ),
        (
            {"SCOPE_ATTRIBUTE_NAME": "scp", "WRITE_SCOPE_NAME": "gateway.write"},
            {"scope": "write", "scp": "openid"},
            set(),
        ),
    ],
)
@pytest.mark.django_db
def test_oauth_bearer_plugin_maps_configured_token_scopes_to_read_write(oauth_bearer_authenticator, configuration, claims, expected_scopes):
    """Only configured read/write token scopes grant authorization; write implies read."""
    oauth_bearer_authenticator.configuration.update(configuration)
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)

    with patch("ansible_base.authentication.authenticator_plugins.oauth_bearer.logger") as logger:
        assert plugin._read_write_scopes(claims) == frozenset(expected_scopes)

    logger.debug.assert_called_once_with(
        f"OAuth Bearer authenticator {oauth_bearer_authenticator.name} mapped scope claim "
        f"{configuration.get('SCOPE_ATTRIBUTE_NAME', 'scope')} to API scopes {sorted(expected_scopes)}"
    )


@pytest.mark.django_db
def test_oauth_bearer_plugin_defaults_missing_optional_configuration_for_existing_configurations(oauth_bearer_authenticator):
    """Legacy authenticator records use schema defaults for settings added after creation."""
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)
    configuration = dict(oauth_bearer_authenticator.configuration)
    for setting in ("ALLOWED_ALGORITHMS", "VERIFY_SSL", "JWKS_CACHE_TIMEOUT", "JWKS_URL_TIMEOUT", "GROUPS_CLAIM"):
        configuration.pop(setting)

    signing_key = Mock(key="public-key")
    user = Mock(is_active=True, username="external-user")
    claims = {"email": "user@example.com", "sub": "subject", "groups": ["operators"]}
    with (
        patch("ansible_base.authentication.authenticator_plugins.oauth_bearer.decode", return_value={}) as decode_token,
        patch("ansible_base.authentication.authenticator_plugins.oauth_bearer.CachedJWKClient") as jwk_client,
        patch(
            "ansible_base.authentication.authenticator_plugins.oauth_bearer.get_or_create_authenticator_user",
            return_value=(user, Mock(), True),
        ),
        patch("ansible_base.authentication.authenticator_plugins.oauth_bearer.is_system_user", return_value=False),
        patch("ansible_base.authentication.authenticator_plugins.oauth_bearer.update_user_claims", return_value=user) as update_claims,
    ):
        AuthenticatorPlugin._decode_validated_token("token", signing_key, configuration)
        plugin._build_jwk_client(configuration["JWKS_URI"], configuration)
        assert plugin._user_from_claims(claims, configuration) == user

    assert decode_token.call_args.kwargs["algorithms"] == ["RS256"]
    assert decode_token.call_args.kwargs["audience"] == configuration["AUDIENCE"]
    assert decode_token.call_args.kwargs["issuer"] == configuration["ISSUER_URL"]
    jwk_client.assert_called_once_with(configuration["JWKS_URI"], lifespan=3600, timeout=30, ssl_context=None)
    update_claims.assert_called_once_with(user, oauth_bearer_authenticator, ["operators"], attrs=claims)


@pytest.mark.django_db
@pytest.mark.parametrize("setting", ("ISSUER_URL", "AUDIENCE"))
def test_oauth_bearer_plugin_does_not_route_tokens_when_required_configuration_is_missing(oauth_bearer_authenticator, setting):
    """Missing required legacy configuration cannot select this JWT validator."""
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)
    configuration = dict(oauth_bearer_authenticator.configuration)
    configuration.pop(setting)

    with patch(
        "ansible_base.authentication.authenticator_plugins.oauth_bearer.decode",
        return_value=_routing_claims(oauth_bearer_authenticator.configuration),
    ):
        assert plugin._matches_token_routing_claims("token", configuration) is False


@pytest.mark.django_db
@pytest.mark.parametrize("setting", ("JWKS_URI", "CLAIM_LIST"))
def test_oauth_bearer_plugin_rejects_missing_required_runtime_configuration(oauth_bearer_authenticator, setting):
    """Missing required legacy configuration is rejected without a KeyError."""
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)
    configuration = dict(oauth_bearer_authenticator.configuration)
    configuration.pop(setting)

    if setting == "JWKS_URI":
        plugin.database_instance.configuration = configuration
        with patch.object(plugin, "_matches_token_routing_claims", return_value=True), pytest.raises(BearerTokenValidationError):
            plugin.authenticate(token="token")
    else:
        with pytest.raises(BearerTokenValidationError):
            plugin._user_from_claims({"email": "user@example.com"}, configuration)


@pytest.mark.django_db
def test_oauth_bearer_plugin_uses_first_usable_claim_list_value_for_uid(oauth_bearer_authenticator):
    """The ordered CLAIM_LIST selects the uid passed to authenticator-user provisioning."""
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)
    plugin.database_instance.configuration["CLAIM_LIST"] = ["preferred_username", "email"]
    user = Mock(is_active=True, username="external-user")
    claims = {
        **_routing_claims(plugin.database_instance.configuration),
        "preferred_username": "first-claim-wins",
        "email": "user@example.com",
        "groups": [],
    }

    with (
        patch("ansible_base.authentication.authenticator_plugins.oauth_bearer.CachedJWKClient") as jwk_client,
        patch(
            "ansible_base.authentication.authenticator_plugins.oauth_bearer.decode",
            side_effect=[_routing_claims(plugin.database_instance.configuration), claims],
        ),
        patch(
            "ansible_base.authentication.authenticator_plugins.oauth_bearer.get_or_create_authenticator_user",
            return_value=(user, Mock(), True),
        ) as get_or_create,
        patch("ansible_base.authentication.authenticator_plugins.oauth_bearer.is_system_user", return_value=False),
        patch("ansible_base.authentication.authenticator_plugins.oauth_bearer.update_user_claims", return_value=user),
    ):
        jwk_client.return_value.get_signing_key_from_jwt.return_value = Mock(key="public-key")
        result = plugin.authenticate(token="token")

    assert result.user == user
    assert get_or_create.call_args.kwargs["uid"] == "first-claim-wins"


@pytest.mark.django_db
def test_oauth_bearer_plugin_maps_azp_service_principal_through_user_claims(oauth_bearer_authenticator):
    """An azp-first service principal provisions an identity and applies normal authenticator maps."""
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)
    plugin.database_instance.configuration["CLAIM_LIST"] = ["azp", "email"]
    user = Mock(is_active=True, username="gateway-service")
    claims = {
        **_routing_claims(plugin.database_instance.configuration),
        "azp": "gateway-service",
        "email": "service@example.com",
        "groups": ["service-accounts"],
    }

    with (
        patch("ansible_base.authentication.authenticator_plugins.oauth_bearer.CachedJWKClient") as jwk_client,
        patch(
            "ansible_base.authentication.authenticator_plugins.oauth_bearer.decode",
            side_effect=[_routing_claims(plugin.database_instance.configuration), claims],
        ),
        patch(
            "ansible_base.authentication.authenticator_plugins.oauth_bearer.get_or_create_authenticator_user",
            return_value=(user, Mock(), True),
        ) as get_or_create,
        patch("ansible_base.authentication.authenticator_plugins.oauth_bearer.is_system_user", return_value=False),
        patch(
            "ansible_base.authentication.authenticator_plugins.oauth_bearer.update_user_claims",
            return_value=user,
        ) as update_claims,
    ):
        jwk_client.return_value.get_signing_key_from_jwt.return_value = Mock(key="public-key")
        result = plugin.authenticate(token="token")

    assert result.user == user
    assert get_or_create.call_args.kwargs["uid"] == "gateway-service"
    update_claims.assert_called_once_with(user, oauth_bearer_authenticator, ["service-accounts"], attrs=claims)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "token,database_instance",
    [(None, True), ("token", False)],
)
def test_oauth_bearer_plugin_requires_token_and_database_instance(oauth_bearer_authenticator, token, database_instance):
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator if database_instance else None)
    assert plugin.authenticate(token=token) is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    "claims",
    [
        {"iss": "https://another.example.com/issuer", "aud": "api://aap-example"},
        {"iss": "https://login.example.com/tenant/v2.0", "aud": "another-client"},
        {"iss": "https://login.example.com/tenant/v2.0", "aud": ["another-client", 42]},
    ],
)
def test_oauth_bearer_plugin_skips_jwks_for_tokens_owned_by_another_provider(oauth_bearer_authenticator, claims):
    """Routing claims reject foreign tokens before any JWKS lookup."""
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)
    token = jwt.encode(claims, "not-used", algorithm="HS256")

    with patch("ansible_base.authentication.authenticator_plugins.oauth_bearer.CachedJWKClient") as jwk_client:
        assert plugin.authenticate(token=token) is None

    jwk_client.assert_not_called()


@pytest.mark.django_db
def test_oauth_bearer_plugin_skips_jwks_for_opaque_tokens(oauth_bearer_authenticator):
    """A non-JWT Bearer credential is left for an API plugin that supports it."""
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)

    with patch("ansible_base.authentication.authenticator_plugins.oauth_bearer.CachedJWKClient") as jwk_client:
        assert plugin.authenticate(token="opaque-token") is None

    jwk_client.assert_not_called()


@pytest.mark.django_db
def test_oauth_bearer_plugin_propagates_unexpected_signing_key_lookup_failure(oauth_bearer_authenticator):
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)
    with (
        patch("ansible_base.authentication.authenticator_plugins.oauth_bearer.CachedJWKClient") as jwk_client,
        patch(
            "ansible_base.authentication.authenticator_plugins.oauth_bearer.decode",
            return_value=_routing_claims(oauth_bearer_authenticator.configuration),
        ),
    ):
        jwk_client.return_value.get_signing_key_from_jwt.side_effect = RuntimeError("unreachable")
        with pytest.raises(RuntimeError, match="unreachable"):
            plugin.authenticate(token="token")


@pytest.mark.django_db
def test_oauth_bearer_plugin_rejects_invalid_jwt_claims(oauth_bearer_authenticator):
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)
    with (
        patch("ansible_base.authentication.authenticator_plugins.oauth_bearer.CachedJWKClient") as jwk_client,
        patch(
            "ansible_base.authentication.authenticator_plugins.oauth_bearer.decode",
            side_effect=[_routing_claims(oauth_bearer_authenticator.configuration), jwt.InvalidIssuerError("invalid issuer")],
        ),
    ):
        jwk_client.return_value.get_signing_key_from_jwt.return_value = Mock(key="public-key")
        with pytest.raises(BearerTokenValidationError, match="Invalid Bearer token"):
            plugin.authenticate(token="token")


@pytest.mark.django_db
def test_oauth_bearer_plugin_classifies_expired_tokens(oauth_bearer_authenticator):
    """Expired JWTs communicate a safe failure category to the Bearer dispatcher."""
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)
    with (
        patch("ansible_base.authentication.authenticator_plugins.oauth_bearer.CachedJWKClient") as jwk_client,
        patch(
            "ansible_base.authentication.authenticator_plugins.oauth_bearer.decode",
            side_effect=[_routing_claims(oauth_bearer_authenticator.configuration), jwt.ExpiredSignatureError("expired")],
        ),
    ):
        jwk_client.return_value.get_signing_key_from_jwt.return_value = Mock(key="public-key")
        with pytest.raises(BearerTokenValidationError) as exc_info:
            plugin.authenticate(token="token")

    assert exc_info.value.reason == "expired"


@pytest.mark.django_db
def test_oauth_bearer_plugin_classifies_unavailable_jwks_provider(oauth_bearer_authenticator):
    """An unavailable JWKS endpoint has a safe client-visible failure category."""
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)
    with (
        patch("ansible_base.authentication.authenticator_plugins.oauth_bearer.CachedJWKClient") as jwk_client,
        patch(
            "ansible_base.authentication.authenticator_plugins.oauth_bearer.decode",
            return_value=_routing_claims(oauth_bearer_authenticator.configuration),
        ),
    ):
        jwk_client.return_value.get_signing_key_from_jwt.side_effect = jwt.PyJWKClientConnectionError("unavailable")
        with pytest.raises(BearerTokenValidationError) as exc_info:
            plugin.authenticate(token="token")

    assert exc_info.value.reason == "provider_unavailable"


@pytest.mark.django_db
def test_oauth_bearer_plugin_propagates_unexpected_identity_provisioning_errors(oauth_bearer_authenticator):
    """Provisioning defects bubble to the dispatcher, which records unexpected plugin exceptions."""
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)
    claims = {**_routing_claims(oauth_bearer_authenticator.configuration), "email": "user@example.com"}
    with (
        patch("ansible_base.authentication.authenticator_plugins.oauth_bearer.CachedJWKClient") as jwk_client,
        patch(
            "ansible_base.authentication.authenticator_plugins.oauth_bearer.decode",
            side_effect=[_routing_claims(oauth_bearer_authenticator.configuration), claims],
        ),
        patch(
            "ansible_base.authentication.authenticator_plugins.oauth_bearer.get_or_create_authenticator_user",
            side_effect=RuntimeError("provisioning failure"),
        ),
    ):
        jwk_client.return_value.get_signing_key_from_jwt.return_value = Mock(key="public-key")
        with pytest.raises(RuntimeError, match="provisioning failure"):
            plugin.authenticate(token="token")


@pytest.mark.django_db
def test_oauth_bearer_plugin_retries_once_after_invalid_signature(oauth_bearer_authenticator):
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)
    initial_key = Mock(key="old-key")
    refreshed_key = Mock(key="new-key")
    claims = {"sub": "subject", "groups": []}
    with (
        patch("ansible_base.authentication.authenticator_plugins.oauth_bearer.CachedJWKClient") as jwk_client,
        patch(
            "ansible_base.authentication.authenticator_plugins.oauth_bearer.decode",
            side_effect=[_routing_claims(oauth_bearer_authenticator.configuration), jwt.InvalidSignatureError("old key"), claims],
        ) as decode_token,
        patch(
            "ansible_base.authentication.authenticator_plugins.oauth_bearer.get_or_create_authenticator_user",
            return_value=(Mock(is_active=False), Mock(), False),
        ),
    ):
        jwk_client.return_value.get_signing_key_from_jwt.return_value = initial_key
        jwk_client.return_value.refresh_signing_key_from_jwt.return_value = refreshed_key
        with pytest.raises(BearerTokenValidationError, match="Invalid Bearer token"):
            plugin.authenticate(token="token")

    jwk_client.return_value.refresh_signing_key_from_jwt.assert_called_once_with("token")
    assert decode_token.call_args_list[2].kwargs["key"] == refreshed_key.key


@pytest.mark.django_db
def test_oauth_bearer_plugin_skips_retry_when_refreshed_key_is_unchanged(oauth_bearer_authenticator):
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)
    key_data = {"kid": "unchanged"}
    signing_key = Mock(key="old-key", _jwk_data=key_data)
    refreshed_key = Mock(key="same-key", _jwk_data=key_data)
    with (
        patch("ansible_base.authentication.authenticator_plugins.oauth_bearer.CachedJWKClient") as jwk_client,
        patch(
            "ansible_base.authentication.authenticator_plugins.oauth_bearer.decode",
            side_effect=[_routing_claims(oauth_bearer_authenticator.configuration), jwt.InvalidSignatureError("bad signature")],
        ) as decode_token,
    ):
        jwk_client.return_value.get_signing_key_from_jwt.return_value = signing_key
        jwk_client.return_value.refresh_signing_key_from_jwt.return_value = refreshed_key
        with pytest.raises(BearerTokenValidationError, match="Invalid Bearer token"):
            plugin.authenticate(token="token")

    assert decode_token.call_count == 2


@pytest.mark.django_db
def test_oauth_bearer_plugin_rejects_a_matching_token_without_a_jwks_uri(oauth_bearer_authenticator):
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)
    plugin.database_instance.configuration["JWKS_URI"] = ""

    with patch(
        "ansible_base.authentication.authenticator_plugins.oauth_bearer.decode",
        return_value=_routing_claims(plugin.database_instance.configuration),
    ):
        with pytest.raises(BearerTokenValidationError):
            plugin.authenticate(token="token")


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("exception", "reason"),
    [
        (jwt.ExpiredSignatureError(), "expired"),
        (jwt.PyJWKClientConnectionError(), "provider_unavailable"),
        (jwt.PyJWKClientError(), "invalid"),
    ],
)
def test_oauth_bearer_plugin_translates_key_refresh_failures(oauth_bearer_authenticator, exception, reason):
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)
    signing_key = Mock(_jwk_data={"kid": "old"})
    jwk_client = Mock()
    jwk_client.refresh_signing_key_from_jwt.side_effect = exception

    with pytest.raises(BearerTokenValidationError) as exc_info:
        plugin._validated_claims_after_key_refresh("token", signing_key, jwk_client, plugin.database_instance.configuration)

    assert exc_info.value.reason == reason


@pytest.mark.django_db
def test_oauth_bearer_plugin_treats_non_list_groups_as_empty(oauth_bearer_authenticator):
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)
    user = Mock(is_active=True)
    claims = {"email": "user@example.com", "sub": "subject", "groups": "operators"}

    with (
        patch(
            "ansible_base.authentication.authenticator_plugins.oauth_bearer.get_or_create_authenticator_user",
            return_value=(user, Mock(), False),
        ),
        patch("ansible_base.authentication.authenticator_plugins.oauth_bearer.is_system_user", return_value=False),
        patch("ansible_base.authentication.authenticator_plugins.oauth_bearer.update_user_claims", return_value=user) as update_claims,
    ):
        assert plugin._user_from_claims(claims, plugin.database_instance.configuration) is user

    assert update_claims.call_args.args[2] == []


@pytest.mark.django_db
def test_oauth_bearer_plugin_rejects_wrong_signing_key(oauth_bearer_authenticator):
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)
    signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode(_claims(oauth_bearer_authenticator.configuration), signing_key, algorithm="RS256")

    result, get_or_create = _authenticate_signed_token(plugin, token, wrong_key.public_key())

    assert result is None
    get_or_create.assert_not_called()


@pytest.mark.django_db
def test_oauth_bearer_plugin_rejects_unsupported_algorithm(oauth_bearer_authenticator):
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)
    token = jwt.encode(_claims(oauth_bearer_authenticator.configuration), "shared-secret", algorithm="HS256")

    result, get_or_create = _authenticate_signed_token(plugin, token, "shared-secret")

    assert result is None
    get_or_create.assert_not_called()


@pytest.mark.django_db
def test_oauth_bearer_plugin_accepts_es256_when_configured(oauth_bearer_authenticator):
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)
    plugin.database_instance.configuration["ALLOWED_ALGORITHMS"] = ["ES256"]
    signing_key = ec.generate_private_key(ec.SECP256R1())
    token = jwt.encode(_claims(plugin.database_instance.configuration), signing_key, algorithm="ES256")

    result, get_or_create = _authenticate_signed_token(plugin, token, signing_key.public_key())

    assert result is None
    get_or_create.assert_called_once()


@pytest.mark.django_db
def test_oauth_bearer_plugin_accepts_audience_list_containing_configured_audience(oauth_bearer_authenticator):
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)
    signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode(
        _claims(plugin.database_instance.configuration, aud=["other-client", plugin.database_instance.configuration["AUDIENCE"]]),
        signing_key,
        algorithm="RS256",
    )

    result, get_or_create = _authenticate_signed_token(plugin, token, signing_key.public_key())

    assert result is None
    get_or_create.assert_called_once()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "tolerance_seconds,expired_seconds,expected_provisioning",
    [(30, 15, True), (30, 31, False), (0, 1, False)],
)
def test_oauth_bearer_plugin_uses_configured_clock_skew_tolerance(oauth_bearer_authenticator, tolerance_seconds, expired_seconds, expected_provisioning):
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)
    plugin.database_instance.configuration["JWT_CLOCK_SKEW_TOLERANCE_SECONDS"] = tolerance_seconds
    signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode(
        _claims(plugin.database_instance.configuration, exp=datetime.now(timezone.utc) - timedelta(seconds=expired_seconds)),
        signing_key,
        algorithm="RS256",
    )

    _result, get_or_create = _authenticate_signed_token(plugin, token, signing_key.public_key())

    assert get_or_create.called is expected_provisioning


@pytest.mark.django_db
def test_oauth_bearer_plugin_requires_expiration_claim(oauth_bearer_authenticator):
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode(
        {
            "iss": oauth_bearer_authenticator.configuration["ISSUER_URL"],
            "aud": oauth_bearer_authenticator.configuration["AUDIENCE"],
            "sub": "subject",
        },
        private_key,
        algorithm="RS256",
    )
    with patch("ansible_base.authentication.authenticator_plugins.oauth_bearer.CachedJWKClient") as jwk_client:
        jwk_client.return_value.get_signing_key_from_jwt.return_value = Mock(key=private_key.public_key())
        with pytest.raises(BearerTokenValidationError, match="Invalid Bearer token"):
            plugin.authenticate(token=token)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "claims,user",
    [
        ({"groups": []}, None),
        ({"sub": "subject", "groups": []}, Mock(is_active=False)),
        ({"sub": "subject", "groups": []}, Mock(is_active=True)),
    ],
)
def test_oauth_bearer_plugin_rejects_unusable_identity(oauth_bearer_authenticator, claims, user):
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)
    with (
        patch("ansible_base.authentication.authenticator_plugins.oauth_bearer.CachedJWKClient") as jwk_client,
        patch(
            "ansible_base.authentication.authenticator_plugins.oauth_bearer.decode",
            side_effect=[_routing_claims(oauth_bearer_authenticator.configuration), claims],
        ),
        patch(
            "ansible_base.authentication.authenticator_plugins.oauth_bearer.get_or_create_authenticator_user",
            return_value=(user, Mock(), False),
        ),
        patch(
            "ansible_base.authentication.authenticator_plugins.oauth_bearer.is_system_user",
            return_value=True,
        ),
    ):
        jwk_client.return_value.get_signing_key_from_jwt.return_value = Mock(key="public-key")
        with pytest.raises(BearerTokenValidationError, match="Invalid Bearer token"):
            plugin.authenticate(token="token")
