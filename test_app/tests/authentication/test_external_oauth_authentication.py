from unittest.mock import Mock, patch

import jwt
import pytest
from django.test import RequestFactory

from ansible_base.authentication.external_oauth_authentication import ExternalOAuthAuthentication
from ansible_base.authentication.models import Authenticator


def _request(token=None, scheme="Bearer"):
    headers = {} if token is None else {"HTTP_AUTHORIZATION": f"{scheme} {token}"}
    return RequestFactory().get("/", **headers)


def _token(issuer, audience):
    return jwt.encode({"iss": issuer, "aud": audience}, "not-used", algorithm="HS256")


@pytest.mark.django_db
@pytest.mark.parametrize(
    "auth_request",
    [
        _request(),
        _request("token", scheme="Basic"),
        RequestFactory().get("/", HTTP_AUTHORIZATION="Bearer "),
    ],
)
def test_external_oauth_authentication_ignores_missing_or_invalid_authorization(auth_request):
    assert ExternalOAuthAuthentication().authenticate(auth_request) is None


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
def test_external_oauth_authentication_rejects_invalid_unverified_claim_shapes(claims):
    with patch(
        "ansible_base.authentication.external_oauth_authentication.decode",
        return_value=claims,
    ):
        assert ExternalOAuthAuthentication().authenticate(_request("token")) is None


@pytest.mark.django_db
def test_external_oauth_authentication_rejects_malformed_token():
    assert ExternalOAuthAuthentication().authenticate(_request("not.a.jwt")) is None


@pytest.mark.django_db
def test_external_oauth_authentication_rejects_token_without_matching_provider(external_oauth_authenticator):
    token = _token("https://another.example.com/issuer", external_oauth_authenticator.configuration["AUDIENCE"])
    assert ExternalOAuthAuthentication().authenticate(_request(token)) is None


@pytest.mark.django_db
def test_external_oauth_authentication_uses_only_matching_enabled_api_authenticator(external_oauth_authenticator):
    token = _token(
        external_oauth_authenticator.configuration["ISSUER_URL"],
        external_oauth_authenticator.configuration["AUDIENCE"],
    )
    plugin = Mock()
    plugin.authenticate.return_value = None
    plugin_class = Mock(return_value=plugin)
    request = _request(token)

    with patch(
        "ansible_base.authentication.external_oauth_authentication.get_authenticator_class",
        return_value=plugin_class,
    ) as get_plugin_class:
        assert ExternalOAuthAuthentication().authenticate(request) is None

    get_plugin_class.assert_called_once_with(external_oauth_authenticator.type)
    plugin_class.assert_called_once_with(database_instance=external_oauth_authenticator)
    plugin.authenticate.assert_called_once_with(request, token=token)


@pytest.mark.django_db
def test_external_oauth_authentication_accepts_a_matching_audience_in_a_list(external_oauth_authenticator):
    token = _token(
        external_oauth_authenticator.configuration["ISSUER_URL"],
        ["another-client", external_oauth_authenticator.configuration["AUDIENCE"]],
    )
    plugin = Mock()
    user = Mock(username="external-user")
    plugin.authenticate.return_value = user

    with patch(
        "ansible_base.authentication.external_oauth_authentication.get_authenticator_class",
        return_value=Mock(return_value=plugin),
    ):
        assert ExternalOAuthAuthentication().authenticate(_request(token)) == (user, token)


@pytest.mark.django_db
def test_external_oauth_authentication_audits_success(external_oauth_authenticator):
    token = _token(
        external_oauth_authenticator.configuration["ISSUER_URL"],
        external_oauth_authenticator.configuration["AUDIENCE"],
    )
    user = Mock(username="external-user")
    plugin = Mock()
    plugin.authenticate.return_value = user
    with patch(
        "ansible_base.authentication.external_oauth_authentication.get_authenticator_class",
        return_value=Mock(return_value=plugin),
    ), patch("ansible_base.authentication.external_oauth_authentication.log_auth_event") as log_auth_event:
        assert ExternalOAuthAuthentication().authenticate(_request(token)) == (user, token)

    log_auth_event.assert_called_once_with(
        f"User {user.username} authenticated with external OAuth authenticator {external_oauth_authenticator.name}"
    )


@pytest.mark.django_db
def test_external_oauth_authentication_skips_unloadable_plugin(external_oauth_authenticator):
    token = _token(
        external_oauth_authenticator.configuration["ISSUER_URL"],
        external_oauth_authenticator.configuration["AUDIENCE"],
    )
    with patch(
        "ansible_base.authentication.external_oauth_authentication.get_authenticator_class",
        side_effect=ImportError("unavailable"),
    ):
        assert ExternalOAuthAuthentication().authenticate(_request(token)) is None


@pytest.mark.django_db
def test_external_oauth_authentication_continues_after_plugin_failure(external_oauth_authenticator):
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
        "ansible_base.authentication.external_oauth_authentication.get_authenticator_class",
        return_value=plugin_class,
    ):
        assert ExternalOAuthAuthentication().authenticate(_request(token)) == (user, token)

    rejected_plugin.authenticate.assert_called_once()
    accepted_plugin.authenticate.assert_called_once()
    second.delete()
