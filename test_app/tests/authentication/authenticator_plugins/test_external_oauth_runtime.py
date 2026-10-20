from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric import rsa

from ansible_base.authentication.authenticator_plugins.external_oauth import AuthenticatorPlugin


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


def _authenticate_signed_token(plugin, token, public_key):
    with patch(
        "ansible_base.authentication.authenticator_plugins.external_oauth.CachedJWKClient"
    ) as jwk_client, patch(
        "ansible_base.authentication.authenticator_plugins.external_oauth.get_or_create_authenticator_user",
        return_value=(Mock(is_active=False), Mock(), False),
    ) as get_or_create:
        jwk_client.return_value.get_signing_key_from_jwt.return_value = Mock(key=public_key)
        result = plugin.authenticate(token=token)
    return result, get_or_create


@pytest.mark.django_db
def test_external_oauth_plugin_validates_token_and_updates_claims(external_oauth_authenticator):
    plugin = AuthenticatorPlugin(database_instance=external_oauth_authenticator)
    token = "signed-token"
    signing_key = Mock(key="public-key")
    user = Mock(is_active=True, username="external-user")
    claims = {"email": "user@example.com", "sub": "subject", "groups": ["operators", 3]}

    with patch(
        "ansible_base.authentication.authenticator_plugins.external_oauth.CachedJWKClient"
    ) as jwk_client, patch(
        "ansible_base.authentication.authenticator_plugins.external_oauth.decode",
        return_value=claims,
    ) as decode_token, patch(
        "ansible_base.authentication.authenticator_plugins.external_oauth.get_or_create_authenticator_user",
        return_value=(user, Mock(), True),
    ) as get_or_create, patch(
        "ansible_base.authentication.authenticator_plugins.external_oauth.is_system_user",
        return_value=False,
    ), patch(
        "ansible_base.authentication.authenticator_plugins.external_oauth.update_user_claims",
        return_value=user,
    ) as update_claims:
        jwk_client.return_value.get_signing_key_from_jwt.return_value = signing_key
        assert plugin.authenticate(token=token) == user

    jwk_client.assert_called_once_with(
        external_oauth_authenticator.configuration["JWKS_URI"],
        lifespan=external_oauth_authenticator.configuration["JWKS_CACHE_TIMEOUT"],
        timeout=external_oauth_authenticator.configuration["JWKS_URL_TIMEOUT"],
        ssl_context=None,
    )
    decode_token.assert_called_once_with(
        token,
        key=signing_key.key,
        algorithms=external_oauth_authenticator.configuration["ALLOWED_ALGORITHMS"],
        audience=external_oauth_authenticator.configuration["AUDIENCE"],
        issuer=external_oauth_authenticator.configuration["ISSUER_URL"],
        options={"require": ["exp"]},
        leeway=0,
    )
    get_or_create.assert_called_once_with(
        uid="user@example.com",
        email="user@example.com",
        authenticator=external_oauth_authenticator,
        user_details={"email": "user@example.com"},
        extra_data=claims,
    )
    update_claims.assert_called_once_with(user, external_oauth_authenticator, ["operators"], attrs=claims)


@pytest.mark.django_db
@pytest.mark.parametrize(
    "token,database_instance",
    [(None, True), ("token", False)],
)
def test_external_oauth_plugin_requires_token_and_database_instance(external_oauth_authenticator, token, database_instance):
    plugin = AuthenticatorPlugin(database_instance=external_oauth_authenticator if database_instance else None)
    assert plugin.authenticate(token=token) is None


@pytest.mark.django_db
def test_external_oauth_plugin_rejects_signing_key_lookup_failure(external_oauth_authenticator):
    plugin = AuthenticatorPlugin(database_instance=external_oauth_authenticator)
    with patch(
        "ansible_base.authentication.authenticator_plugins.external_oauth.CachedJWKClient"
    ) as jwk_client:
        jwk_client.return_value.get_signing_key_from_jwt.side_effect = RuntimeError("unreachable")
        assert plugin.authenticate(token="token") is None


@pytest.mark.django_db
def test_external_oauth_plugin_rejects_invalid_jwt_claims(external_oauth_authenticator):
    plugin = AuthenticatorPlugin(database_instance=external_oauth_authenticator)
    with patch(
        "ansible_base.authentication.authenticator_plugins.external_oauth.CachedJWKClient"
    ) as jwk_client, patch(
        "ansible_base.authentication.authenticator_plugins.external_oauth.decode",
        side_effect=ValueError("invalid issuer"),
    ):
        jwk_client.return_value.get_signing_key_from_jwt.return_value = Mock(key="public-key")
        assert plugin.authenticate(token="token") is None


@pytest.mark.django_db
def test_external_oauth_plugin_retries_once_after_invalid_signature(external_oauth_authenticator):
    plugin = AuthenticatorPlugin(database_instance=external_oauth_authenticator)
    initial_key = Mock(key="old-key")
    refreshed_key = Mock(key="new-key")
    claims = {"sub": "subject", "groups": []}
    with patch(
        "ansible_base.authentication.authenticator_plugins.external_oauth.CachedJWKClient"
    ) as jwk_client, patch(
        "ansible_base.authentication.authenticator_plugins.external_oauth.decode",
        side_effect=[jwt.InvalidSignatureError("old key"), claims],
    ) as decode_token, patch(
        "ansible_base.authentication.authenticator_plugins.external_oauth.get_or_create_authenticator_user",
        return_value=(Mock(is_active=False), Mock(), False),
    ):
        jwk_client.return_value.get_signing_key_from_jwt.return_value = initial_key
        jwk_client.return_value.refresh_signing_key_from_jwt.return_value = refreshed_key
        assert plugin.authenticate(token="token") is None

    jwk_client.return_value.refresh_signing_key_from_jwt.assert_called_once_with("token")
    assert decode_token.call_args_list[1].kwargs["key"] == refreshed_key.key


@pytest.mark.django_db
def test_external_oauth_plugin_skips_retry_when_refreshed_key_is_unchanged(external_oauth_authenticator):
    plugin = AuthenticatorPlugin(database_instance=external_oauth_authenticator)
    key_data = {"kid": "unchanged"}
    signing_key = Mock(key="old-key", _jwk_data=key_data)
    refreshed_key = Mock(key="same-key", _jwk_data=key_data)
    with patch(
        "ansible_base.authentication.authenticator_plugins.external_oauth.CachedJWKClient"
    ) as jwk_client, patch(
        "ansible_base.authentication.authenticator_plugins.external_oauth.decode",
        side_effect=jwt.InvalidSignatureError("bad signature"),
    ) as decode_token:
        jwk_client.return_value.get_signing_key_from_jwt.return_value = signing_key
        jwk_client.return_value.refresh_signing_key_from_jwt.return_value = refreshed_key
        assert plugin.authenticate(token="token") is None

    decode_token.assert_called_once()


@pytest.mark.django_db
def test_external_oauth_plugin_rejects_wrong_signing_key(external_oauth_authenticator):
    plugin = AuthenticatorPlugin(database_instance=external_oauth_authenticator)
    signing_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    wrong_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode(_claims(external_oauth_authenticator.configuration), signing_key, algorithm="RS256")

    result, get_or_create = _authenticate_signed_token(plugin, token, wrong_key.public_key())

    assert result is None
    get_or_create.assert_not_called()


@pytest.mark.django_db
def test_external_oauth_plugin_rejects_unsupported_algorithm(external_oauth_authenticator):
    plugin = AuthenticatorPlugin(database_instance=external_oauth_authenticator)
    token = jwt.encode(_claims(external_oauth_authenticator.configuration), "shared-secret", algorithm="HS256")

    result, get_or_create = _authenticate_signed_token(plugin, token, "shared-secret")

    assert result is None
    get_or_create.assert_not_called()


@pytest.mark.django_db
def test_external_oauth_plugin_accepts_es256_when_configured(external_oauth_authenticator):
    plugin = AuthenticatorPlugin(database_instance=external_oauth_authenticator)
    plugin.database_instance.configuration["ALLOWED_ALGORITHMS"] = ["ES256"]
    signing_key = ec.generate_private_key(ec.SECP256R1())
    token = jwt.encode(_claims(plugin.database_instance.configuration), signing_key, algorithm="ES256")

    result, get_or_create = _authenticate_signed_token(plugin, token, signing_key.public_key())

    assert result is None
    get_or_create.assert_called_once()


@pytest.mark.django_db
def test_external_oauth_plugin_accepts_audience_list_containing_configured_audience(external_oauth_authenticator):
    plugin = AuthenticatorPlugin(database_instance=external_oauth_authenticator)
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
def test_external_oauth_plugin_uses_configured_clock_skew_tolerance(
    external_oauth_authenticator, tolerance_seconds, expired_seconds, expected_provisioning
):
    plugin = AuthenticatorPlugin(database_instance=external_oauth_authenticator)
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
def test_external_oauth_plugin_requires_expiration_claim(external_oauth_authenticator):
    plugin = AuthenticatorPlugin(database_instance=external_oauth_authenticator)
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    token = jwt.encode(
        {
            "iss": external_oauth_authenticator.configuration["ISSUER_URL"],
            "aud": external_oauth_authenticator.configuration["AUDIENCE"],
            "sub": "subject",
        },
        private_key,
        algorithm="RS256",
    )
    with patch(
        "ansible_base.authentication.authenticator_plugins.external_oauth.CachedJWKClient"
    ) as jwk_client:
        jwk_client.return_value.get_signing_key_from_jwt.return_value = Mock(key=private_key.public_key())
        assert plugin.authenticate(token=token) is None


@pytest.mark.django_db
@pytest.mark.parametrize(
    "claims,user",
    [
        ({"groups": []}, None),
        ({"sub": "subject", "groups": []}, Mock(is_active=False)),
        ({"sub": "subject", "groups": []}, Mock(is_active=True)),
    ],
)
def test_external_oauth_plugin_rejects_unusable_identity(external_oauth_authenticator, claims, user):
    plugin = AuthenticatorPlugin(database_instance=external_oauth_authenticator)
    with patch(
        "ansible_base.authentication.authenticator_plugins.external_oauth.CachedJWKClient"
    ) as jwk_client, patch(
        "ansible_base.authentication.authenticator_plugins.external_oauth.decode",
        return_value=claims,
    ), patch(
        "ansible_base.authentication.authenticator_plugins.external_oauth.get_or_create_authenticator_user",
        return_value=(user, Mock(), False),
    ), patch(
        "ansible_base.authentication.authenticator_plugins.external_oauth.is_system_user",
        return_value=True,
    ):
        jwk_client.return_value.get_signing_key_from_jwt.return_value = Mock(key="public-key")
        assert plugin.authenticate(token="token") is None
