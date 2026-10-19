from unittest.mock import Mock, patch

import pytest

from ansible_base.authentication.authenticator_plugins.external_oauth import AuthenticatorPlugin


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
