from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest

from ansible_base.authentication.authenticator_plugins.oauth_bearer import AuthenticatorPlugin
from ansible_base.authentication.bearer_authentication import get_api_authentication_backends
from ansible_base.authentication.models import AuthenticatorUser
from ansible_base.lib.utils.response import get_relative_url

PLUGIN = "ansible_base.authentication.authenticator_plugins.oauth_bearer"


def _claims(configuration, **overrides):
    claims = {
        "iss": configuration["ISSUER_URL"],
        "aud": configuration["AUDIENCE"],
        "sub": "subject",
        "email": "returning@example.com",
        "scope": "read",
        "exp": int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp()),
    }
    claims.update(overrides)
    return claims


def _authenticate(authenticator, claims):
    plugin = AuthenticatorPlugin(database_instance=authenticator)
    with ExitStack() as stack:
        jwk_client = stack.enter_context(patch(f"{PLUGIN}.CachedJWKClient"))
        stack.enter_context(patch(f"{PLUGIN}.decode", side_effect=[claims, claims]))
        jwk_client.return_value.get_signing_key_from_jwt.return_value = Mock(key="public-key")
        return plugin.authenticate(token="external-token")


@pytest.mark.django_db
def test_returning_user_is_matched_without_a_duplicate(oauth_bearer_authenticator):
    """Authenticating twice with the same identity reuses the provisioned user (TC-3 item 9, TC-8 item 3)."""
    claims = _claims(oauth_bearer_authenticator.configuration)

    first = _authenticate(oauth_bearer_authenticator, claims)
    second = _authenticate(oauth_bearer_authenticator, claims)

    assert first.user.pk == second.user.pk
    assert AuthenticatorUser.objects.filter(provider=oauth_bearer_authenticator, uid=claims["email"]).count() == 1


@pytest.mark.django_db
def test_valid_identity_without_permission_is_forbidden(oauth_bearer_authenticator, unauthenticated_api_client, animal):
    """A read-scoped external identity is authenticated but not authorized to write, so it gets 403 (TC-10 item 4)."""
    claims = _claims(oauth_bearer_authenticator.configuration)

    get_api_authentication_backends.cache_clear()
    try:
        with ExitStack() as stack:
            jwk_client = stack.enter_context(patch(f"{PLUGIN}.CachedJWKClient"))
            stack.enter_context(patch(f"{PLUGIN}.decode", side_effect=[claims, claims]))
            jwk_client.return_value.get_signing_key_from_jwt.return_value = Mock(key="public-key")
            response = unauthenticated_api_client.post(
                get_relative_url("animal-list"),
                data={"name": "Forbidden", "owner": animal.owner.pk},
                headers={"Authorization": "Bearer external-token"},
            )
    finally:
        get_api_authentication_backends.cache_clear()

    assert response.status_code == 403
    # A 403 is an authorization decision, not an authentication challenge.
    assert "WWW-Authenticate" not in response.headers
