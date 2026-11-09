from datetime import datetime, timedelta, timezone
from unittest.mock import Mock, patch

import jwt
import pytest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType

from ansible_base.activitystream.models import Entry
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
        "email": "external-user@example.com",
        "scope": "read",
        "exp": int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp()),
    }
    claims.update(overrides)
    return claims


def _authenticate(authenticator, claims):
    plugin = AuthenticatorPlugin(database_instance=authenticator)
    with (
        patch(f"{PLUGIN}.CachedJWKClient") as jwk_client,
        patch(f"{PLUGIN}.decode", side_effect=[claims, claims]),
    ):
        jwk_client.return_value.get_signing_key_from_jwt.return_value = Mock(key="public-key")
        return plugin.authenticate(token="external-token")


@pytest.mark.django_db
def test_external_login_provisions_by_email_without_activity_stream(oauth_bearer_authenticator, unauthenticated_api_client):
    """A user absent from AAP is provisioned by email, non-elevated, with no activity-stream record (TC-1 items 2, 3, 5 and 19)."""
    claims = _claims(oauth_bearer_authenticator.configuration)

    get_api_authentication_backends.cache_clear()
    try:
        with (
            patch(f"{PLUGIN}.CachedJWKClient") as jwk_client,
            patch(f"{PLUGIN}.decode", side_effect=[claims, claims]),
        ):
            jwk_client.return_value.get_signing_key_from_jwt.return_value = Mock(key="public-key")
            response = unauthenticated_api_client.get(
                get_relative_url("user-me"),
                headers={"Authorization": "Bearer external-token"},
            )
    finally:
        get_api_authentication_backends.cache_clear()

    assert response.status_code == 200
    assert response.data["username"] == claims["email"]
    assert response.data["email"] == claims["email"]
    assert response.data["is_superuser"] is False

    authenticator_user = AuthenticatorUser.objects.get(uid=claims["email"], provider=oauth_bearer_authenticator)
    assert authenticator_user.user.username == claims["email"]
    assert authenticator_user.user.is_superuser is False
    assert authenticator_user.user.is_staff is False
    # The local user is audited; the AuthenticatorUser link itself is not.
    user_entries = Entry.objects.filter(
        content_type=ContentType.objects.get_for_model(get_user_model()),
        object_id=str(authenticator_user.user.pk),
    )
    # Later updates (last_login) follow the create; the provision itself must be recorded.
    assert user_entries.filter(operation="create").exists()
    assert "authenticatoruser" not in set(Entry.objects.values_list("content_type__model", flat=True))


@pytest.mark.django_db
def test_admin_roles_claim_is_ignored(oauth_bearer_authenticator):
    """An upstream roles claim grants nothing; permissions come from local maps and RBAC only (TC-1 item 8)."""
    claims = _claims(oauth_bearer_authenticator.configuration, roles=["admin"], scope="read write")

    result = _authenticate(oauth_bearer_authenticator, claims)

    assert result.user.is_superuser is False
    assert result.user.is_staff is False
    assert result.user.groups.count() == 0
    assert result.auth.scopes == frozenset({"read", "write"})


@pytest.mark.django_db
@pytest.mark.parametrize(
    "audience",
    [
        pytest.param("api://aap-example' OR '1'='1", id="quote-or"),
        pytest.param("api://aap-example'; DROP TABLE authenticator; --", id="stacked-drop"),
        pytest.param(["api://aap-other", "' OR 1=1 --"], id="list-with-injection"),
        pytest.param('api://aap-example" OR "1"="1', id="double-quote-or"),
    ],
)
def test_audience_injection_payloads_never_route_to_a_provider(oauth_bearer_authenticator, audience):
    """Injection text in the audience is an ordinary non-match; no query runs and no key is fetched (TC-1 N2)."""
    token = jwt.encode({"iss": oauth_bearer_authenticator.configuration["ISSUER_URL"], "aud": audience}, "routing-only", algorithm="HS256")
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)

    with patch(f"{PLUGIN}.CachedJWKClient") as jwk_client:
        assert plugin.authenticate(token=token) is None

    jwk_client.assert_not_called()


@pytest.mark.django_db
@pytest.mark.parametrize(
    "payload",
    [
        pytest.param("eyJhbGciOiJSUzI1NiJ9", id="header-only"),
        pytest.param("eyJhbGciOiJSUzI1NiJ9.bm90LWpzb24.signature", id="undecodable-payload"),
        pytest.param("eyJhbGciOiJSUzI1NiJ9..signature", id="empty-payload"),
        pytest.param("....", id="empty-segments"),
    ],
)
def test_unusable_payloads_are_declined_without_a_key_lookup(oauth_bearer_authenticator, payload):
    """A token whose payload cannot yield routing claims is declined before any key lookup (TC-1 N4 and N5)."""
    plugin = AuthenticatorPlugin(database_instance=oauth_bearer_authenticator)

    with patch(f"{PLUGIN}.CachedJWKClient") as jwk_client:
        assert plugin.authenticate(token=payload) is None

    jwk_client.assert_not_called()
