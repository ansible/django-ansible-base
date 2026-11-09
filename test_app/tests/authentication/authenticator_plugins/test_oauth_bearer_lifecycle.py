from contextlib import ExitStack
from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import pytest

from ansible_base.authentication.bearer_authentication import get_api_authentication_backends
from ansible_base.authentication.models import Authenticator
from ansible_base.lib.testing.util import delete_authenticator
from ansible_base.lib.utils.response import get_relative_url

PLUGIN = "ansible_base.authentication.authenticator_plugins.oauth_bearer"


def _claims(configuration, email="external@example.com"):
    return {
        "iss": configuration["ISSUER_URL"],
        "aud": configuration["AUDIENCE"],
        "sub": "subject",
        "email": email,
        "scope": "read",
        "exp": int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp()),
    }


def _external_login(client, authenticator, email="external@example.com"):
    """Log in with an external token through the real dispatcher and cache versioning."""
    claims = _claims(authenticator.configuration, email)
    get_api_authentication_backends.cache_clear()
    try:
        with ExitStack() as stack:
            jwk_client = stack.enter_context(patch(f"{PLUGIN}.CachedJWKClient"))
            stack.enter_context(patch(f"{PLUGIN}.decode", side_effect=lambda _token, **_kwargs: claims))
            jwk_client.return_value.get_signing_key_from_jwt.return_value = Mock(key="public-key")
            return client.get(get_relative_url("user-me"), headers={"Authorization": "Bearer external-token"})
    finally:
        get_api_authentication_backends.cache_clear()


def _local_login(client, plaintext_token):
    return client.get(get_relative_url("user-me"), headers={"Authorization": f"Bearer {plaintext_token}"})


@pytest.fixture
def second_provider(oauth_bearer_configuration):
    authenticator = Authenticator.objects.create(
        name="Second OAuth Bearer Authenticator",
        enabled=True,
        type="ansible_base.authentication.authenticator_plugins.oauth_bearer",
        configuration={**oauth_bearer_configuration, "AUDIENCE": "api://other-audience"},
    )
    yield authenticator
    delete_authenticator(authenticator)


@pytest.mark.django_db
def test_disabling_one_provider_leaves_the_other_working(oauth_bearer_authenticator, second_provider, unauthenticated_api_client):
    """Disabling a provider removes only that provider; another one keeps authenticating (TC-12 item 6)."""
    oauth_bearer_authenticator.enabled = False
    oauth_bearer_authenticator.save()

    assert _external_login(unauthenticated_api_client, oauth_bearer_authenticator).status_code == 401
    assert _external_login(unauthenticated_api_client, second_provider).status_code == 200


@pytest.mark.django_db
def test_a_reenabled_provider_authenticates_again(oauth_bearer_authenticator, unauthenticated_api_client):
    """Re-enabling a provider restores authentication without recreating it (TC-12 item 8)."""
    assert _external_login(unauthenticated_api_client, oauth_bearer_authenticator).status_code == 200

    oauth_bearer_authenticator.enabled = False
    oauth_bearer_authenticator.save()
    assert _external_login(unauthenticated_api_client, oauth_bearer_authenticator).status_code == 401

    oauth_bearer_authenticator.enabled = True
    oauth_bearer_authenticator.save()
    assert _external_login(unauthenticated_api_client, oauth_bearer_authenticator).status_code == 200


@pytest.mark.django_db
def test_local_oauth_still_works_while_the_external_provider_is_disabled(oauth_bearer_authenticator, oauth2_admin_access_token, unauthenticated_api_client):
    """The local OAuth2 backend is independent of external-provider state (TC-11 item 6)."""
    oauth_bearer_authenticator.enabled = False
    oauth_bearer_authenticator.save()

    response = _local_login(unauthenticated_api_client, oauth2_admin_access_token[1])

    assert response.status_code == 200
    assert response.data["username"] == oauth2_admin_access_token[0].user.username


@pytest.mark.django_db
def test_reenabled_external_provider_and_local_oauth_coexist(oauth_bearer_authenticator, oauth2_admin_access_token, unauthenticated_api_client):
    """After re-enabling, external and local tokens both authenticate (TC-11 item 7)."""
    oauth_bearer_authenticator.enabled = False
    oauth_bearer_authenticator.save()
    oauth_bearer_authenticator.enabled = True
    oauth_bearer_authenticator.save()

    assert _external_login(unauthenticated_api_client, oauth_bearer_authenticator).status_code == 200
    assert _local_login(unauthenticated_api_client, oauth2_admin_access_token[1]).status_code == 200
