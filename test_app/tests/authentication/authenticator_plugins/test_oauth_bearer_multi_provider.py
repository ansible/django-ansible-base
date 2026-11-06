from collections import OrderedDict
from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import jwt
import pytest

from ansible_base.authentication.authenticator_plugins.oauth_bearer import AuthenticatorPlugin
from ansible_base.authentication.bearer_authentication import (
    BearerAuthentication,
    BearerAuthenticationFailed,
    BearerAuthenticationResult,
    BearerTokenValidationError,
    ScopedBearerToken,
    get_api_authentication_backends,
)
from ansible_base.authentication.models import Authenticator
from ansible_base.lib.testing.util import delete_authenticator
from ansible_base.lib.utils.response import get_relative_url

PLUGIN = "ansible_base.authentication.authenticator_plugins.oauth_bearer"


def _token(configuration, **overrides):
    claims = {
        "iss": configuration["ISSUER_URL"],
        "aud": configuration["AUDIENCE"],
        "sub": "subject",
        "email": "multi@example.com",
        "scope": "read",
        "exp": int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp()),
    }
    claims.update(overrides)
    return jwt.encode(claims, "routing-only", algorithm="HS256")


def _authenticate(plugin, token):
    with ExitStack() as stack:
        stack.enter_context(patch(f"{PLUGIN}.CachedJWKClient"))
        stack.enter_context(
            patch(
                f"{PLUGIN}.decode",
                side_effect=lambda candidate, **_kwargs: jwt.decode(candidate, options={"verify_signature": False}),
            )
        )
        stack.enter_context(patch(f"{PLUGIN}.get_or_create_authenticator_user", return_value=(Mock(username="multi-user"), Mock(), True)))
        stack.enter_context(patch(f"{PLUGIN}.update_user_claims", side_effect=lambda user, *_args, **_kwargs: user))
        return plugin.authenticate(token=token)


@pytest.fixture
def second_provider(oauth_bearer_configuration):
    configuration = {**oauth_bearer_configuration, "AUDIENCE": "api://other-audience"}
    authenticator = Authenticator.objects.create(
        name="Second OAuth Bearer Authenticator",
        enabled=True,
        type="ansible_base.authentication.authenticator_plugins.oauth_bearer",
        configuration=configuration,
    )
    yield authenticator
    delete_authenticator(authenticator)


@pytest.mark.django_db
def test_same_issuer_different_audience_providers_are_disambiguated(oauth_bearer_authenticator, second_provider):
    """Two providers sharing an issuer are told apart by audience, and an unknown audience matches neither (TC-6 items 5 and 7)."""
    first = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)
    second = AuthenticatorPlugin(database_instance=second_provider)

    token_for_second = _token(second_provider.configuration)
    assert _authenticate(first, token_for_second) is None
    assert _authenticate(second, token_for_second) is not None

    token_for_none = _token(second_provider.configuration, aud="api://unknown-audience")
    assert _authenticate(first, token_for_none) is None
    assert _authenticate(second, token_for_none) is None


@pytest.mark.django_db
def test_unknown_audience_returns_a_generic_401(unauthenticated_api_client, second_provider):
    """A token whose audience matches no provider is a generic 401 that names no organization (TC-6 item 7)."""
    token = _token(second_provider.configuration, aud="api://unknown-audience")

    get_api_authentication_backends.cache_clear()
    try:
        with patch(f"{PLUGIN}.CachedJWKClient") as jwk_client:
            response = unauthenticated_api_client.get(get_relative_url("user-me"), headers={"Authorization": f"Bearer {token}"})
    finally:
        get_api_authentication_backends.cache_clear()

    jwk_client.assert_not_called()
    assert response.status_code == 401
    assert response.content.decode() == '{"detail":"Invalid Bearer token."}'


@pytest.mark.django_db
def test_first_accepting_provider_wins_deterministically():
    """When several providers accept a token, order decides the user on every attempt (TC-6 item 6)."""
    first = Mock()
    first.authenticate.return_value = BearerAuthenticationResult(user=Mock(username="first"), auth=ScopedBearerToken(scopes=frozenset()))
    second = Mock()
    second.authenticate.return_value = BearerAuthenticationResult(user=Mock(username="second"), auth=ScopedBearerToken(scopes=frozenset()))

    with (
        patch.object(BearerAuthentication, "_api_authentication_backends", return_value=OrderedDict([(1, first), (2, second)])),
        patch.object(BearerAuthentication, "_authenticate_local_oauth") as local_oauth,
    ):
        for _ in range(3):
            user, _ = BearerAuthentication().authenticate(Mock(headers={"Authorization": "Bearer external-token"}))
            assert user.username == "first"

    second.authenticate.assert_not_called()
    local_oauth.assert_not_called()


@pytest.mark.django_db
def test_first_failure_wins_deterministically_across_providers():
    """With several rejecting providers the earliest ordered failure is reported on every attempt (TC-6 item 9)."""
    first = Mock()
    first.authenticate.side_effect = BearerTokenValidationError("expired")
    second = Mock()
    second.authenticate.side_effect = BearerTokenValidationError("provider_unavailable")

    with (
        patch.object(BearerAuthentication, "_api_authentication_backends", return_value=OrderedDict([(1, first), (2, second)])),
        patch.object(BearerAuthentication, "_authenticate_local_oauth", return_value=None),
    ):
        details = set()
        for _ in range(3):
            with pytest.raises(BearerAuthenticationFailed) as failure:
                BearerAuthentication().authenticate(Mock(headers={"Authorization": "Bearer external-token"}))
            details.add(str(failure.value.detail))

    assert details == {"Bearer token has expired."}
