from unittest.mock import Mock, patch

import jwt
import pytest
from django.test import RequestFactory
from rest_framework.exceptions import AuthenticationFailed

from ansible_base.authentication.bearer_authentication import BearerAuthentication
from ansible_base.authentication.models import Authenticator


def _request(token=None, scheme="Bearer"):
    headers = {} if token is None else {"HTTP_AUTHORIZATION": f"{scheme} {token}"}
    return RequestFactory().get("/", **headers)


def _token(issuer, audience):
    return jwt.encode({"iss": issuer, "aud": audience}, "not-used", algorithm="HS256")


@pytest.mark.django_db
@pytest.mark.parametrize("auth_request", [_request(), _request("token", scheme="Basic")])
def test_bearer_authentication_ignores_missing_or_non_bearer_authorization(auth_request):
    assert BearerAuthentication().authenticate(auth_request) is None


@pytest.mark.django_db
def test_bearer_authentication_rejects_an_empty_bearer_token():
    with pytest.raises(AuthenticationFailed, match="Invalid Bearer token"):
        BearerAuthentication().authenticate(_request(""))


@pytest.mark.django_db
@pytest.mark.parametrize(
    "claims",
    [
        {"aud": "api://aap-example"},
        {"iss": "https://login.example.com/tenant/v2.0"},
        {"iss": ["not-an-issuer"], "aud": "api://aap-example"},
        {"iss": "https://login.example.com/tenant/v2.0", "aud": 42},
        {"iss": "https://login.example.com/tenant/v2.0", "aud": ["api://aap-example", 42]},
    ],
)
def test_bearer_authentication_rejects_invalid_unverified_claim_shapes(claims):
    with patch("ansible_base.authentication.bearer_authentication.decode", return_value=claims), patch(
        "ansible_base.authentication.bearer_authentication.LoggedOAuth2Authentication.authenticate",
        return_value=None,
    ):
        with pytest.raises(AuthenticationFailed, match="Invalid Bearer token"):
            BearerAuthentication().authenticate(_request("token"))


@pytest.mark.django_db
def test_bearer_authentication_rejects_a_malformed_token_when_local_oauth_rejects_it():
    with patch(
        "ansible_base.authentication.bearer_authentication.LoggedOAuth2Authentication.authenticate",
        return_value=None,
    ):
        with pytest.raises(AuthenticationFailed, match="Invalid Bearer token"):
            BearerAuthentication().authenticate(_request("not.a.jwt"))


@pytest.mark.django_db
def test_bearer_authentication_rejects_token_without_matching_provider_when_local_oauth_rejects_it(external_oauth_authenticator):
    token = _token("https://another.example.com/issuer", external_oauth_authenticator.configuration["AUDIENCE"])
    with patch(
        "ansible_base.authentication.bearer_authentication.LoggedOAuth2Authentication.authenticate",
        return_value=None,
    ):
        with pytest.raises(AuthenticationFailed, match="Invalid Bearer token"):
            BearerAuthentication().authenticate(_request(token))


@pytest.mark.django_db
def test_bearer_authentication_uses_only_matching_enabled_api_authenticator(external_oauth_authenticator):
    token = _token(
        external_oauth_authenticator.configuration["ISSUER_URL"],
        external_oauth_authenticator.configuration["AUDIENCE"],
    )
    plugin = Mock()
    plugin.authenticate.return_value = None
    plugin_class = Mock(return_value=plugin)

    with patch(
        "ansible_base.authentication.bearer_authentication.get_authenticator_class",
        return_value=plugin_class,
    ) as get_plugin_class, patch(
        "ansible_base.authentication.bearer_authentication.LoggedOAuth2Authentication.authenticate",
        return_value=None,
    ):
        with pytest.raises(AuthenticationFailed, match="Invalid Bearer token"):
            BearerAuthentication().authenticate(_request(token))

    get_plugin_class.assert_called_once_with(external_oauth_authenticator.type)
    plugin_class.assert_called_once_with(database_instance=external_oauth_authenticator)
    plugin.authenticate.assert_called_once()


@pytest.mark.django_db
def test_bearer_authentication_accepts_a_matching_audience_in_a_list(external_oauth_authenticator):
    token = _token(
        external_oauth_authenticator.configuration["ISSUER_URL"],
        ["another-client", external_oauth_authenticator.configuration["AUDIENCE"]],
    )
    plugin = Mock()
    user = Mock(username="external-user")
    plugin.authenticate.return_value = user

    with patch(
        "ansible_base.authentication.bearer_authentication.get_authenticator_class",
        return_value=Mock(return_value=plugin),
    ), patch("ansible_base.authentication.bearer_authentication.LoggedOAuth2Authentication.authenticate") as local_authenticate:
        assert BearerAuthentication().authenticate(_request(token)) == (user, token)

    local_authenticate.assert_not_called()


@pytest.mark.django_db
def test_bearer_authentication_audits_external_oauth_success(external_oauth_authenticator):
    token = _token(
        external_oauth_authenticator.configuration["ISSUER_URL"],
        external_oauth_authenticator.configuration["AUDIENCE"],
    )
    user = Mock(username="external-user")
    plugin = Mock()
    plugin.authenticate.return_value = user
    with patch(
        "ansible_base.authentication.bearer_authentication.get_authenticator_class",
        return_value=Mock(return_value=plugin),
    ), patch("ansible_base.authentication.bearer_authentication.log_auth_event") as log_auth_event:
        assert BearerAuthentication().authenticate(_request(token)) == (user, token)

    log_auth_event.assert_called_once_with(
        f"User {user.username} authenticated with external OAuth authenticator {external_oauth_authenticator.name}"
    )


@pytest.mark.django_db
def test_bearer_authentication_uses_local_oauth_after_external_candidates_decline(external_oauth_authenticator):
    token = _token(
        external_oauth_authenticator.configuration["ISSUER_URL"],
        external_oauth_authenticator.configuration["AUDIENCE"],
    )
    plugin = Mock()
    plugin.authenticate.return_value = None
    local_user = Mock(username="local-user")
    local_token = Mock()

    with patch(
        "ansible_base.authentication.bearer_authentication.get_authenticator_class",
        return_value=Mock(return_value=plugin),
    ), patch(
        "ansible_base.authentication.bearer_authentication.LoggedOAuth2Authentication.authenticate",
        return_value=(local_user, local_token),
    ) as local_authenticate:
        assert BearerAuthentication().authenticate(_request(token)) == (local_user, local_token)

    local_authenticate.assert_called_once()


@pytest.mark.django_db
def test_bearer_authentication_preserves_legacy_local_oauth_token_scheme():
    local_user = Mock(username="local-user")
    local_token = Mock()

    with patch.object(BearerAuthentication, "_matching_external_authenticators") as external_authenticators, patch(
        "ansible_base.authentication.bearer_authentication.LoggedOAuth2Authentication.authenticate",
        return_value=(local_user, local_token),
    ):
        assert BearerAuthentication().authenticate(_request("token", scheme="Token")) == (local_user, local_token)

    external_authenticators.assert_not_called()


@pytest.mark.django_db
def test_bearer_authentication_continues_after_external_plugin_failure(external_oauth_authenticator):
    second = Authenticator.objects.create(
        name="Second external OAuth authenticator",
        enabled=True,
        type=external_oauth_authenticator.type,
        configuration=external_oauth_authenticator.configuration,
        order=external_oauth_authenticator.order + 1,
    )
    token = _token(
        external_oauth_authenticator.configuration["ISSUER_URL"],
        external_oauth_authenticator.configuration["AUDIENCE"],
    )
    rejected_plugin = Mock()
    rejected_plugin.authenticate.side_effect = RuntimeError("bad plugin")
    user = Mock(username="external-user")
    accepted_plugin = Mock()
    accepted_plugin.authenticate.return_value = user
    plugin_class = Mock(side_effect=[rejected_plugin, accepted_plugin])

    with patch(
        "ansible_base.authentication.bearer_authentication.get_authenticator_class",
        return_value=plugin_class,
    ):
        assert BearerAuthentication().authenticate(_request(token)) == (user, token)

    rejected_plugin.authenticate.assert_called_once()
    accepted_plugin.authenticate.assert_called_once()
    second.delete()


def test_bearer_authentication_returns_the_local_oauth_challenge():
    request = _request("token")
    with patch(
        "ansible_base.authentication.bearer_authentication.LoggedOAuth2Authentication.authenticate_header",
        return_value='Bearer realm="api"',
    ):
        assert BearerAuthentication().authenticate_header(request) == 'Bearer realm="api"'
