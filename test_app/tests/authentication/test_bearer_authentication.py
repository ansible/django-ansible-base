from collections import OrderedDict
from unittest.mock import Mock, patch

import pytest
from django.test import RequestFactory
from rest_framework.exceptions import AuthenticationFailed

from ansible_base.authentication.bearer_authentication import BearerAuthentication, get_api_authentication_backends
from ansible_base.authentication.models import Authenticator


def _request(token: str | None = None, scheme: str = "Bearer"):
    """Build a request that optionally has an Authorization credential."""
    headers = {} if token is None else {"HTTP_AUTHORIZATION": f"{scheme} {token}"}
    return RequestFactory().get("/", **headers)


@pytest.fixture(autouse=True)
def clear_api_authenticator_cache():
    """Keep the process-local API-authenticator cache isolated between tests."""
    get_api_authentication_backends.cache_clear()
    yield
    get_api_authentication_backends.cache_clear()


@pytest.mark.django_db
@pytest.mark.parametrize("auth_request", [_request(), _request("token", scheme="Basic")])
def test_bearer_authentication_ignores_missing_or_non_bearer_authorization(auth_request):
    """Credentials belonging to another authentication scheme are not claimed."""
    assert BearerAuthentication().authenticate(auth_request) is None


@pytest.mark.django_db
def test_bearer_authentication_rejects_an_empty_bearer_token():
    """A declared Bearer scheme with no credential is invalid."""
    with pytest.raises(AuthenticationFailed, match="Invalid Bearer token"):
        BearerAuthentication().authenticate(_request(""))


@pytest.mark.django_db
def test_bearer_authentication_passes_opaque_tokens_to_api_authenticators():
    """The generic dispatcher does not parse or otherwise constrain token format."""
    plugin = Mock()
    plugin.authenticate.return_value = None

    with (
        patch.object(
            BearerAuthentication,
            "_api_authentication_backends",
            return_value=OrderedDict([(17, plugin)]),
        ),
        patch.object(BearerAuthentication, "_authenticate_local_oauth", return_value=None),
    ):
        request = _request("opaque-token")
        with pytest.raises(AuthenticationFailed, match="Invalid Bearer token"):
            BearerAuthentication().authenticate(request)

    plugin.authenticate.assert_called_once_with(request, token="opaque-token")


@pytest.mark.django_db
def test_bearer_authentication_returns_and_audits_api_authenticator_success():
    """The first plugin that authenticates a token wins and is audited."""
    plugin = Mock()
    user = Mock(username="external-user")
    plugin.authenticate.return_value = user

    with (
        patch.object(
            BearerAuthentication,
            "_api_authentication_backends",
            return_value=OrderedDict([(17, plugin)]),
        ),
        patch("ansible_base.authentication.bearer_authentication.log_auth_event") as log_auth_event,
        patch.object(BearerAuthentication, "_authenticate_local_oauth") as local_authenticate,
    ):
        assert BearerAuthentication().authenticate(_request("opaque-token")) == (user, "opaque-token")

    local_authenticate.assert_not_called()
    log_auth_event.assert_called_once_with('User external-user authenticated with API authenticator with ID "17"')


@pytest.mark.django_db
def test_bearer_authentication_uses_local_oauth_after_api_authenticators_decline():
    """A local OAuth2 token remains valid if no configured API plugin owns it."""
    plugin = Mock()
    plugin.authenticate.return_value = None
    local_user = Mock(username="local-user")
    local_token = Mock()

    with (
        patch.object(
            BearerAuthentication,
            "_api_authentication_backends",
            return_value=OrderedDict([(17, plugin)]),
        ),
        patch.object(BearerAuthentication, "_authenticate_local_oauth", return_value=(local_user, local_token)) as local_authenticate,
    ):
        assert BearerAuthentication().authenticate(_request("opaque-token")) == (local_user, local_token)

    local_authenticate.assert_called_once()


@pytest.mark.django_db
def test_bearer_authentication_preserves_legacy_local_oauth_token_scheme():
    """The legacy Token scheme remains reserved for the local OAuth2 backend."""
    local_user = Mock(username="local-user")
    local_token = Mock()

    with (
        patch.object(BearerAuthentication, "_api_authentication_backends") as api_authenticators,
        patch.object(BearerAuthentication, "_authenticate_local_oauth", return_value=(local_user, local_token)),
    ):
        assert BearerAuthentication().authenticate(_request("token", scheme="Token")) == (local_user, local_token)

    api_authenticators.assert_not_called()


@pytest.mark.django_db
def test_bearer_authentication_continues_after_api_plugin_failure():
    """One faulty plugin does not prevent a later API authenticator from succeeding."""
    rejected_plugin = Mock()
    rejected_plugin.authenticate.side_effect = RuntimeError("bad plugin")
    accepted_plugin = Mock()
    user = Mock(username="external-user")
    accepted_plugin.authenticate.return_value = user

    with patch.object(
        BearerAuthentication,
        "_api_authentication_backends",
        return_value=OrderedDict([(17, rejected_plugin), (42, accepted_plugin)]),
    ):
        assert BearerAuthentication().authenticate(_request("opaque-token")) == (user, "opaque-token")

    rejected_plugin.authenticate.assert_called_once()
    accepted_plugin.authenticate.assert_called_once()


@pytest.mark.django_db
def test_bearer_authentication_rejects_token_when_all_handlers_decline():
    """A claimed Bearer credential receives a 401 when no handler can authenticate it."""
    with (
        patch.object(BearerAuthentication, "_api_authentication_backends", return_value=OrderedDict()),
        patch.object(BearerAuthentication, "_authenticate_local_oauth", return_value=None),
    ):
        with pytest.raises(AuthenticationFailed, match="Invalid Bearer token"):
            BearerAuthentication().authenticate(_request("opaque-token"))


@pytest.mark.django_db
def test_api_authentication_backends_cache_and_refresh_configuration(external_oauth_authenticator):
    """API plugins are rebuilt only when the API-authenticator timestamp changes."""
    plugin = Mock()
    initial_modified = external_oauth_authenticator.modified

    with patch(
        "ansible_base.authentication.bearer_authentication.get_authenticator_plugin",
        return_value=plugin,
    ) as get_plugin:
        cached = get_api_authentication_backends(initial_modified)
        assert cached == OrderedDict([(external_oauth_authenticator.id, plugin)])
        assert get_api_authentication_backends(initial_modified) is cached
        get_plugin.assert_called_once_with(external_oauth_authenticator.type)
        plugin.update_if_needed.assert_called_once_with(external_oauth_authenticator)

        external_oauth_authenticator.name = "Updated external OAuth authenticator"
        external_oauth_authenticator.save()
        get_api_authentication_backends(external_oauth_authenticator.modified)

    assert get_plugin.call_count == 2


@pytest.mark.django_db
def test_api_authentication_cache_version_includes_disabled_authenticators(external_oauth_authenticator):
    """Enabling a previously disabled API authenticator invalidates a cached dispatcher list."""
    disabled = Authenticator.objects.create(
        name="Disabled API authenticator",
        enabled=False,
        type=external_oauth_authenticator.type,
        configuration=external_oauth_authenticator.configuration,
        category="api_auth",
        order=external_oauth_authenticator.order + 1,
    )
    with patch("ansible_base.authentication.bearer_authentication.get_api_authentication_backends") as get_backends:
        BearerAuthentication()._api_authentication_backends()

    assert get_backends.call_args.args[0] == disabled.modified


def test_bearer_authentication_returns_the_local_oauth_challenge():
    """Use the established local OAuth2 challenge for all rejected Bearer credentials."""
    request = _request("token")
    with (
        patch.object(BearerAuthentication, "_oauth2_provider_installed", return_value=True),
        patch(
            "ansible_base.oauth2_provider.authentication.LoggedOAuth2Authentication.authenticate_header",
            return_value='Bearer realm="api"',
        ),
    ):
        assert BearerAuthentication().authenticate_header(request) == 'Bearer realm="api"'


def test_bearer_authentication_returns_standard_challenge_without_oauth2_provider():
    """Authentication-only applications expose a standard Bearer challenge."""
    with patch.object(BearerAuthentication, "_oauth2_provider_installed", return_value=False):
        assert BearerAuthentication().authenticate_header(_request("token")) == "Bearer"
